"""Smoke tests for the HTTP layer."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gerry.app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "git_sha" in body


def test_index_renders():
    r = client.get("/")
    assert r.status_code == 200
    assert "Gerry" in r.text
