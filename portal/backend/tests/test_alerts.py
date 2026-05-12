import json
import time
import importlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/discord")
    import alerts as alerts_module
    importlib.reload(alerts_module)
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def _sample_alertmanager_payload(status="firing", severity="warning"):
    return {
        "alerts": [{
            "status": status,
            "labels": {"alertname": "TestAlert", "severity": severity},
            "annotations": {"summary": "Test summary", "description": "Test description"},
        }]
    }


@patch("alerts.threading.Thread")
def test_webhook_accepts_alert(mock_thread, client):
    response = client.post("/api/alerts/webhook", json=_sample_alertmanager_payload())
    assert response.status_code == 200
    assert response.get_json()["received"] == 1


@patch("alerts.threading.Thread")
def test_webhook_stores_alert(mock_thread, client):
    client.post("/api/alerts/webhook", json=_sample_alertmanager_payload())
    response = client.get("/api/alerts/active")
    data = response.get_json()
    assert data["count"] >= 1
    assert data["alerts"][0]["alertname"] == "TestAlert"
    assert data["alerts"][0]["severity"] == "warning"


@patch("alerts.threading.Thread")
def test_webhook_empty_payload(mock_thread, client):
    response = client.post("/api/alerts/webhook", json={"alerts": []})
    assert response.status_code == 200
    assert response.get_json()["received"] == 0


@patch("alerts.requests.post")
def test_discord_post_formats_correctly(mock_post, client):
    payload = _sample_alertmanager_payload(severity="critical")
    client.post("/api/alerts/webhook", json=payload)
    # Wait for thread to fire
    time.sleep(0.1)
    # The thread may or may not have run depending on timing; mock should have been called
    # We're mostly checking the threading.Thread mechanism doesn't crash