import asyncio
import csv
import json
from pathlib import Path
import uuid

import httpx
import pytest

from backend import main as api
from simulator import simulator as sim

PAYLOAD = {"category": "electronics", "customer_tier": "premium", "amount": 99.5}


def test_order_lifecycle_and_structured_logs(client, capsys):
    rid = "test-correlation"
    response = client.post("/orders", json=PAYLOAD, headers={"X-Request-ID": rid})
    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == rid
    order_id = response.json["id"]
    assert client.get(f"/orders/{order_id}").json["status"] == "created"
    assert client.post(f"/orders/{order_id}/cancel").status_code == 200
    assert client.get(f"/orders/{order_id}").json["status"] == "cancelled"
    assert client.post(f"/orders/{order_id}/cancel").status_code == 409
    assert client.get(f"/orders/{uuid.uuid4()}").status_code == 404
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(logs) == 6
    assert logs[0]["request_id"] == rid
    required = {"severity", "message", "request_id", "endpoint", "status_code", "outcome", "error_type", "latency_ms", "category", "customer_tier", "amount"}
    assert all(required <= row.keys() for row in logs)
    assert logs[-2]["outcome"] == "client_error"
    assert logs[-2]["error_type"] == "already_cancelled"
    assert logs[0]["category"] == "electronics"


@pytest.mark.parametrize("payload", [None, [], {}, {**PAYLOAD, "amount": -1},
    {**PAYLOAD, "amount": True}, {**PAYLOAD, "amount": "10"},
    {**PAYLOAD, "category": []}, {**PAYLOAD, "customer_tier": {}},
    {**PAYLOAD, "amount": float("nan")}, {**PAYLOAD, "amount": 10**400}])
def test_invalid_payload_returns_400(client, payload):
    assert client.post("/orders", json=payload).status_code == 400


def test_malformed_json_and_unknown_route(client):
    assert client.post("/orders", data="{", content_type="application/json").status_code == 400
    assert client.get("/unknown").status_code == 404


def test_functions_framework_entry_point(capsys):
    import functions_framework
    app = functions_framework.create_app(target="handle", source=str(Path(api.__file__).resolve()))
    response = app.test_client().post("/orders", json={"amount": -1},
                                     headers={"X-Request-ID": "framework-test"})
    assert response.status_code == 400
    assert response.json["request_id"] == "framework-test"
    assert json.loads(capsys.readouterr().out)["message"] == "request_completed"


def test_failure_is_logged_and_does_not_create_order(client, monkeypatch, capsys):
    created = []
    monkeypatch.setattr(api, "create_order", lambda data: created.append(data))
    monkeypatch.setattr(api, "FAILURE_RATE", 1)
    assert client.post("/orders", json=PAYLOAD).status_code == 500
    assert not created
    row = json.loads(capsys.readouterr().out)
    assert row["error_type"] == "simulated_failure"
    assert row["outcome"] == "server_error"


def test_extra_latency_and_unexpected_failure_are_logged(client, monkeypatch, capsys):
    slept = []
    monkeypatch.setattr(api, "EXTRA_LATENCY_MS", 123)
    monkeypatch.setattr(api.time, "sleep", lambda value: slept.append(value))
    def fail(data):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(api, "create_order", fail)
    assert client.post("/orders", json=PAYLOAD).status_code == 500
    assert slept == [0.123]
    assert json.loads(capsys.readouterr().out)["error_type"] == "internal_error"


def config():
    return json.loads((Path(sim.__file__).parent / "config.example.json").read_text())


def test_plan_is_reproducible_and_truncated():
    settings = config()
    first = sim.make_plan(settings)
    assert len(first) == 6000
    assert first == sim.make_plan(settings)
    minutes = [x["scheduled_min"] for x in first]
    assert minutes == sorted(minutes)
    assert all(0 <= minute <= 60 for minute in minutes)
    assert 28 < sum(minutes) / len(minutes) < 32


def test_scenario_doubles_only_target_category():
    settings = {**config(), "invalid_share": 0.5,
                "scenarios": [{"start_min": 0, "end_min": 60,
                               "category": "electronics", "effect": "double_errors"}]}
    plan = sim.make_plan(settings)
    assert all(x["event"] != "valid" for x in plan if x["category"] == "electronics")
    assert any(x["event"] == "valid" for x in plan if x["category"] != "electronics")
    assert all(not x["scenario"] for x in plan if x["category"] != "electronics")


@pytest.mark.parametrize("overrides", [{"n_requests": 0}, {"sigma_min": 0}, {"mu_min": 90},
                                      {"invalid_share": 2}, {"sigma_min": float("nan")}])
def test_invalid_configuration_fails(overrides):
    with pytest.raises(ValueError):
        sim.make_plan({**config(), **overrides})


def test_simulator_http_flow_and_csv(client, monkeypatch, tmp_path):
    active, peak = 0, 0
    async def transport(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        response = client.open(request.url.path, method=request.method,
                               data=request.content, headers=dict(request.headers))
        active -= 1
        return httpx.Response(response.status_code, content=response.data, headers=dict(response.headers))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(sim.httpx, "AsyncClient", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(transport), **kwargs))
    settings = {**config(), "target_url": "https://test.invalid", "n_requests": 120,
                "invalid_share": 0.4}
    output = tmp_path / "run"
    asyncio.run(sim.run(settings, sim.make_plan(settings), output, 0.0003))
    rows = list(csv.DictReader((output / "requests.csv").open()))
    assert len(rows) == 120
    assert len({r["request_id"] for r in rows}) == 120
    assert all(r["status_code"] == r["expected_status"] for r in rows)
    assert all(not r["transport_error"] for r in rows)
    assert {"200", "201", "400", "404", "409"} <= {r["status_code"] for r in rows}
    assert peak > 1  # La carga no espera a que termine la solicitud anterior.
    assert len(list(csv.DictReader((output / "preparation.csv").open()))) == 18
    assert json.loads((output / "summary.json").read_text())["elapsed_seconds"] >= 1.08


def test_transport_failure_keeps_csv_row(client, monkeypatch, tmp_path):
    async def transport(request):
        if not request.headers["X-Request-ID"].startswith("prep-"):
            raise httpx.ConnectError("network down", request=request)
        response = client.open(request.url.path, method=request.method,
                               data=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.data, headers=dict(response.headers))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(sim.httpx, "AsyncClient", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(transport), **kwargs))
    settings = {**config(), "target_url": "https://test.invalid", "n_requests": 3}
    output = tmp_path / "network-failure"
    asyncio.run(sim.run(settings, sim.make_plan(settings), output, 0.00001))
    rows = list(csv.DictReader((output / "requests.csv").open()))
    assert len(rows) == 3
    assert all(row["transport_error"] == "ConnectError" and row["status_code"] == "" for row in rows)
