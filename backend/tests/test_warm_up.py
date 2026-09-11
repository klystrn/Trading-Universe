"""A cold-started deployment serves the HUD and reports progress before the
first scan lands, and answers 503 on every other API route until it does."""

from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture
def warming_client(tmp_path, monkeypatch):
    """An app whose bootstrap is held open until the test releases it."""
    monkeypatch.setenv("TU_DATABASE_URL", f"sqlite:///{tmp_path}/warm.sqlite")
    monkeypatch.setenv("TU_DATA_MODE", "DEMO")
    monkeypatch.setenv("TU_BOOTSTRAP_BACKGROUND", "true")

    from fastapi.testclient import TestClient

    from trading_universe.db.session import reset_engine
    from trading_universe.services.platform import Platform, reset_platform
    from trading_universe.settings import reload_settings

    reload_settings()
    reset_engine()
    reset_platform()

    gate = threading.Event()
    abandon = threading.Event()
    real_bootstrap = Platform.bootstrap

    def held_bootstrap(self, warm_tickers=None):
        self.bootstrap_stage = "held by test"
        gate.wait(timeout=30)
        if abandon.is_set():
            # The test never released the gate: skip the real scan so teardown
            # does not pay for a bootstrap nobody will look at.
            return {}
        return real_bootstrap(self, warm_tickers=warm_tickers)

    monkeypatch.setattr(Platform, "bootstrap", held_bootstrap)

    from trading_universe.api.app import create_app

    with TestClient(create_app()) as client:
        yield client, gate
        abandon.set()
        gate.set()
    reset_platform()


def _wait_until_ready(client, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/system/status").json()
        if body["bootstrap"]["ready"]:
            return body
        time.sleep(0.2)
    raise AssertionError("bootstrap never finished")


class TestWarmUp:
    def test_status_answers_and_names_the_stage_while_warming(self, warming_client):
        client, _gate = warming_client
        body = client.get("/api/system/status").json()
        assert body["bootstrap"]["ready"] is False
        assert body["bootstrap"]["stage"] == "held by test"
        assert body["bootstrap"]["error"] is None

    def test_other_routes_answer_503_while_warming(self, warming_client):
        client, _gate = warming_client
        for path in ("/api/signals", "/api/portfolio", "/api/universe/briefing"):
            response = client.get(path)
            assert response.status_code == 503, path
            assert response.headers["retry-after"] == "3"
            assert response.json()["detail"] == "warming up"
            assert response.json()["stage"] == "held by test"

    def test_static_frontend_is_not_blocked(self, warming_client):
        client, _gate = warming_client
        # No frontend build in the test tree, so "/" is the JSON landing page;
        # what matters is that the warm-up guard leaves it alone.
        assert client.get("/").status_code == 200

    def test_routes_open_once_the_scan_lands(self, warming_client):
        client, gate = warming_client
        assert client.get("/api/signals").status_code == 503
        gate.set()
        body = _wait_until_ready(client)
        assert body["bootstrap"]["stage"] == "ready"
        assert body["scanner"] == "RUNNING"
        signals = client.get("/api/signals")
        assert signals.status_code == 200
        assert signals.json()["count"] > 0
