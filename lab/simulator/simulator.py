"""Carga abierta: agenda normal truncada, tareas independientes y CSV incremental."""
import argparse
import asyncio
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
import uuid

import httpx
import numpy as np

FIELDS = ["request_id", "scheduled_at", "sent_at", "scheduled_min", "sent_min",
          "schedule_lag_ms", "operation", "intended_event", "expected_status",
          "status_code", "client_latency_ms", "category", "customer_tier",
          "scenario", "transport_error"]
CATEGORIES = ("electronics", "books", "clothing")
TIERS = ("standard", "premium")


def validate(config):
    if type(config["n_requests"]) is not int or config["n_requests"] <= 0:
        raise ValueError("n_requests debe ser entero positivo")
    for key in ("mu_min", "sigma_min", "invalid_share"):
        if not np.isfinite(config[key]):
            raise ValueError(f"{key} debe ser finito")
    if config["sigma_min"] <= 0 or not 0 <= config["mu_min"] <= 60:
        raise ValueError("Se requiere sigma_min > 0 y 0 <= mu_min <= 60")
    if not 0 <= config["invalid_share"] <= 1:
        raise ValueError("invalid_share debe estar entre 0 y 1")
    for scenario in config.get("scenarios", []):
        if (scenario["effect"] != "double_errors" or scenario["category"] not in CATEGORIES
                or not 0 <= scenario["start_min"] < scenario["end_min"] <= 60):
            raise ValueError("Escenario no soportado o intervalo inválido")


def make_plan(config):
    validate(config)
    rng = np.random.default_rng(config["seed"])
    samples = []
    # Rechazar fuera de rango; no recortar (clip acumularía masa en 0 y 60).
    while len(samples) < config["n_requests"]:
        batch = rng.normal(config["mu_min"], config["sigma_min"], config["n_requests"])
        samples.extend(batch[(batch >= 0) & (batch <= 60)].tolist())
    plan = []
    for minute in sorted(samples[:config["n_requests"]]):
        category, tier = str(rng.choice(CATEGORIES)), str(rng.choice(TIERS))
        share, scenario_names = config["invalid_share"], []
        for scenario in config.get("scenarios", []):
            if (scenario["start_min"] <= minute < scenario["end_min"]
                    and category == scenario["category"]):
                share = min(1, share * 2)
                scenario_names.append("double_errors")
        invalid = rng.random() < share
        event = str(rng.choice(("invalid_payload", "missing_id", "impossible_sequence"))) if invalid else "valid"
        plan.append({"scheduled_min": minute, "category": category,
                     "customer_tier": tier, "amount": round(float(rng.uniform(10, 500)), 2),
                     "event": event, "operation": str(rng.choice(("create", "get", "cancel"))),
                     "scenario": ",".join(scenario_names)})
    return plan


async def run(config, plan, output, time_scale):
    url = config["target_url"].rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ValueError("Configura target_url antes de ejecutar")
    output.mkdir(parents=True, exist_ok=False)
    # Preparación separada: recursos estables para 200, 404 y 409 controlados.
    fixtures, cancelled, pool = {}, {}, {}
    run_id = uuid.uuid4().hex
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(timeout=60, limits=limits) as client:
        with (output / "preparation.csv").open("w", newline="") as prep_file:
            prep_writer = csv.writer(prep_file)
            prep_writer.writerow(["request_id", "sent_at", "operation", "status_code", "client_latency_ms"])

            async def prepare(method, path, payload=None):
                for attempt in range(10):
                    rid, begin = f"prep-{run_id}-{uuid.uuid4().hex}", time.perf_counter()
                    sent = datetime.now(timezone.utc).isoformat()
                    response = await client.request(method, url + path, json=payload,
                                                    headers={"X-Request-ID": rid})
                    prep_writer.writerow([rid, sent, f"{method} {path}", response.status_code,
                                          round((time.perf_counter() - begin) * 1000, 3)])
                    prep_file.flush()
                    if response.status_code < 500:
                        response.raise_for_status()
                        return response.json()
                    await asyncio.sleep(min(2 ** attempt, 8))
                raise RuntimeError("La API sigue fallando durante la preparación")

            for category in CATEGORIES:
                for tier in TIERS:
                    key = (category, tier)
                    payload = {"category": category, "customer_tier": tier, "amount": 50}
                    fixtures[key] = (await prepare("POST", "/orders", payload))["id"]
                    cancelled[key] = (await prepare("POST", "/orders", payload))["id"]
                    await prepare("POST", f"/orders/{cancelled[key]}/cancel")
                    pool[key] = []

        started_at, started = datetime.now(timezone.utc), time.perf_counter()
        (output / "run.json").write_text(json.dumps({
            "run_id": run_id, "started_at": started_at.isoformat(), "config": config,
            "time_scale": time_scale, "scheduled_requests": len(plan),
            "note": "preparation.csv queda fuera de las 6000 solicitudes y de la hora medida",
        }, indent=2) + "\n")
        print(f"Inicio UTC: {started_at.isoformat()} | solicitudes: {len(plan)} | duración: {3600*time_scale}s", flush=True)
        with (output / "requests.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            counts = {}
            completed = 0

            async def send(index, item):
                nonlocal completed
                scheduled_s = item["scheduled_min"] * 60 * time_scale
                await asyncio.sleep(max(0, started + scheduled_s - time.perf_counter()))
                key, event, operation = (item["category"], item["customer_tier"]), item["event"], item["operation"]
                payload = {k: item[k] for k in ("category", "customer_tier", "amount")}
                reserved = None
                if event == "invalid_payload":
                    method, path, expected = "POST", "/orders", 400
                    payload["amount"] = -1
                    operation = "create"
                elif event == "missing_id":
                    method, path, expected = "GET", f"/orders/{uuid.uuid4()}", 404
                    operation = "get"
                elif event == "impossible_sequence":
                    method, path, expected = "POST", f"/orders/{cancelled[key]}/cancel", 409
                    operation = "cancel"
                elif operation == "get":
                    method, path, expected = "GET", f"/orders/{fixtures[key]}", 200
                elif operation == "cancel" and pool[key]:
                    reserved = pool[key].pop()
                    method, path, expected = "POST", f"/orders/{reserved}/cancel", 200
                else:
                    # Sin pedido cancelable disponible, crear uno; jamás inventar un ID válido.
                    method, path, expected, operation = "POST", "/orders", 201, "create"
                rid = f"{run_id}-{index:06d}"
                sent_at, begin = datetime.now(timezone.utc), time.perf_counter()
                code, transport = None, ""
                try:
                    response = await client.request(method, url + path,
                        json=payload if operation == "create" else None,
                        headers={"X-Request-ID": rid, "X-Category": key[0], "X-Customer-Tier": key[1]})
                    code = response.status_code
                    if event == "valid" and operation == "create" and code == 201:
                        pool[key].append(response.json()["id"])
                    elif reserved and code == 500 and response.json().get("error") == "simulated_failure":
                        pool[key].append(reserved)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    transport = type(exc).__name__
                latency_ms = (time.perf_counter() - begin) * 1000
                writer.writerow({
                    "request_id": rid,
                    "scheduled_at": (started_at + timedelta(seconds=scheduled_s)).isoformat(),
                    "sent_at": sent_at.isoformat(), "scheduled_min": round(item["scheduled_min"], 6),
                    "sent_min": round((begin - started) / (60 * time_scale), 6),
                    "schedule_lag_ms": round(max(0, begin - started - scheduled_s) * 1000, 3),
                    "operation": operation, "intended_event": event, "expected_status": expected,
                    "status_code": code, "client_latency_ms": round(latency_ms, 3),
                    "category": key[0], "customer_tier": key[1], "scenario": item["scenario"],
                    "transport_error": transport,
                })
                file.flush()
                counts[str(code)] = counts.get(str(code), 0) + 1
                completed += 1
                if completed % 250 == 0:
                    print(f"Completadas: {completed}/{len(plan)} | estados: {counts}", flush=True)

            # Cada tarea espera su propio instante; no espera la respuesta anterior.
            await asyncio.gather(*(send(i, item) for i, item in enumerate(plan)))
            await asyncio.sleep(max(0, started + 3600 * time_scale - time.perf_counter()))
        summary = {"completed": completed, "status_counts": counts,
                   "finished_at": datetime.now(timezone.utc).isoformat(),
                   "elapsed_seconds": round(time.perf_counter() - started, 3)}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.local.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--time-scale", type=float, default=1,
                        help="Solo pruebas rápidas; usar 1 para la entrega de una hora")
    args = parser.parse_args()
    if not np.isfinite(args.time_scale) or args.time_scale <= 0:
        parser.error("time-scale debe ser positivo y finito")
    config = json.loads(args.config.read_text())
    plan = make_plan(config)
    if args.dry_run:
        print(json.dumps({"n_requests": len(plan), "first_min": plan[0]["scheduled_min"],
                          "last_min": plan[-1]["scheduled_min"],
                          "invalid": sum(x["event"] != "valid" for x in plan),
                          "scenario_requests": sum(bool(x["scenario"]) for x in plan)}, indent=2))
        return
    output = args.output or Path(__file__).with_name("results") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    asyncio.run(run(config, plan, output, args.time_scale))


if __name__ == "__main__":
    main()
