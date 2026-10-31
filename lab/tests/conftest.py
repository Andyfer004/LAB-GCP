from pathlib import Path
import sys

import flask
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import main as api


class Snapshot:
    def __init__(self, value):
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return dict(self.value)


class Reference:
    def __init__(self, data, key):
        self.data, self.key = data, key

    def create(self, value):
        assert self.key not in self.data
        self.data[self.key] = dict(value)

    def get(self, transaction=None):
        return Snapshot(self.data.get(self.key))


class MemoryDatabase:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        assert name == "orders"
        return self

    def document(self, key):
        return Reference(self.data, key)

    def transaction(self):
        return self

    def update(self, ref, values):
        self.data[ref.key].update(values)


@pytest.fixture
def client(monkeypatch):
    memory = MemoryDatabase()
    monkeypatch.setattr(api, "database", lambda: memory)
    # Doble de prueba: la atomicidad/reintentos del SDK se verifican al desplegar.
    monkeypatch.setattr(api.firestore, "transactional", lambda fn: fn)
    monkeypatch.setattr(api, "FAILURE_RATE", 0)
    monkeypatch.setattr(api, "EXTRA_LATENCY_MS", 0)
    app = flask.Flask(__name__)
    def view(path):
        return api.handle(flask.request)
    app.add_url_rule("/", defaults={"path": ""}, view_func=view, methods=["GET", "POST"])
    app.add_url_rule("/<path:path>", view_func=view, methods=["GET", "POST"])
    return app.test_client()
