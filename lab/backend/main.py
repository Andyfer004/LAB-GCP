"""API de pedidos. Persistencia en Firestore; entrada HTTP: handle."""
import json
import math
import os
import random
import re
import time
import uuid
from functools import lru_cache

import functions_framework
from google.cloud import firestore

CATEGORIES = {"electronics", "books", "clothing"}
TIERS = {"standard", "premium"}
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.02"))
EXTRA_LATENCY_MS = float(os.getenv("EXTRA_LATENCY_MS", "0"))
if not math.isfinite(FAILURE_RATE) or not 0 <= FAILURE_RATE <= 1:
    raise ValueError("FAILURE_RATE debe estar entre 0 y 1")
if not math.isfinite(EXTRA_LATENCY_MS) or EXTRA_LATENCY_MS < 0:
    raise ValueError("EXTRA_LATENCY_MS debe ser >= 0")


class ApiError(Exception):
    def __init__(self, status, kind):
        self.status, self.kind = status, kind


@lru_cache(maxsize=1)
def database():
    return firestore.Client(database=os.getenv("FIRESTORE_DATABASE", "orders-lab"))


def create_order(data):
    order_id = str(uuid.uuid4())
    order = {**data, "id": order_id, "status": "created"}
    database().collection("orders").document(order_id).create(order)
    return order


def get_order(order_id):
    snapshot = database().collection("orders").document(order_id).get()
    if not snapshot.exists:
        raise ApiError(404, "order_not_found")
    return snapshot.to_dict()


def cancel_order(order_id):
    ref = database().collection("orders").document(order_id)

    @firestore.transactional
    def cancel(transaction):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            raise ApiError(404, "order_not_found")
        order = snapshot.to_dict()
        if order["status"] != "created":
            raise ApiError(409, "already_cancelled")
        transaction.update(ref, {"status": "cancelled"})
        return {**order, "status": "cancelled"}

    return cancel(database().transaction())


@functions_framework.http
def handle(request):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    endpoint, status, error_type = "unknown", 500, "internal_error"
    # Cabeceras solo como contexto de solicitudes sin recurso (p. ej. un 404).
    category = request.headers.get("X-Category", "unknown")
    tier = request.headers.get("X-Customer-Tier", "unknown")
    attrs = {"category": category if category in CATEGORIES else "unknown",
             "customer_tier": tier if tier in TIERS else "unknown", "amount": 0}
    body = {"error": error_type}
    try:
        path = request.path.rstrip("/") or "/"
        match = re.fullmatch(r"/orders/([0-9a-f-]{36})(/cancel)?", path)
        if path == "/orders" and request.method == "POST":
            endpoint = "POST /orders"
        elif match and not match[2] and request.method == "GET":
            endpoint = "GET /orders/{id}"
        elif match and match[2] and request.method == "POST":
            endpoint = "POST /orders/{id}/cancel"
        else:
            raise ApiError(404, "route_not_found")

        if endpoint == "POST /orders":
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ApiError(400, "invalid_payload")
            attrs.update({k: data[k] for k in attrs if k in data
                          and isinstance(data[k], (str, int, float))})
            amount = data.get("amount")
            if (not isinstance(data.get("category"), str)
                    or data["category"] not in CATEGORIES
                    or not isinstance(data.get("customer_tier"), str)
                    or data["customer_tier"] not in TIERS
                    or isinstance(amount, bool) or not isinstance(amount, (float, int))
                    or not 0 < amount <= 1_000_000):
                raise ApiError(400, "invalid_payload")
        else:
            order = get_order(match[1])
            attrs.update({k: order[k] for k in attrs})

        # La latencia se aplica incluso a solicitudes inválidas (en finally).
        # Las fallas se inyectan antes de mutar, para no ocultar escrituras exitosas.
        if random.random() < FAILURE_RATE:
            raise ApiError(500, "simulated_failure")
        if endpoint == "POST /orders":
            body, status = create_order(attrs), 201
        elif endpoint == "GET /orders/{id}":
            body, status = order, 200
        else:
            body, status = cancel_order(match[1]), 200
        error_type = None
    except ApiError as exc:
        status, error_type = exc.status, exc.kind
        body = {"error": error_type}
    except Exception:
        status, error_type = 500, "internal_error"
        body = {"error": error_type}
    finally:
        time.sleep(EXTRA_LATENCY_MS / 1000)
        outcome = "server_error" if status >= 500 else "client_error" if status >= 400 else "success"
        # Mantener atributos de logs acotados, aun para JSON malformado semánticamente.
        safe_attrs = {
            "category": attrs["category"] if isinstance(attrs["category"], str) and attrs["category"] in CATEGORIES else "unknown",
            "customer_tier": attrs["customer_tier"] if isinstance(attrs["customer_tier"], str) and attrs["customer_tier"] in TIERS else "unknown",
            "amount": attrs["amount"] if type(attrs["amount"]) in (int, float) and -1_000_000 <= attrs["amount"] <= 1_000_000 else 0,
        }
        print(json.dumps({
            "severity": "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO",
            "message": "request_completed", "request_id": request_id,
            "endpoint": endpoint, "status_code": status, "outcome": outcome,
            "error_type": error_type, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            **safe_attrs,
        }, allow_nan=False), flush=True)
    return json.dumps({**body, "request_id": request_id}), status, {
        "Content-Type": "application/json", "X-Request-ID": request_id,
    }
