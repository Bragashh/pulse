"""
Tests for the Flask app endpoints.

Like test_db.py, each test gets a fresh DB via monkeypatch + reload.
External HTTP calls (to Google, GitHub, etc.) are mocked.
"""

import os
import tempfile
import importlib
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(monkeypatch):
    """Yield a Flask test client with a fresh DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    monkeypatch.setenv("PULSE_DB_PATH", path)

    import db as db_module
    importlib.reload(db_module)

    import app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c

    if os.path.exists(path):
        os.unlink(path)


# --- /health and / ---

def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_index_returns_message(client):
    response = client.get("/")
    assert response.get_json()["message"] == "Pulse API is running"


# --- /metrics ---

def test_metrics_returns_expected_fields(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.get_json()
    assert "cpu" in data
    assert "memory" in data
    assert "disk" in data
    assert "percent" in data["cpu"]


# --- /services CRUD ---

def test_list_services_seeds_on_first_call(client):
    """First call to /services seeds the default 3 services."""
    response = client.get("/services")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["services"]) == 3
    names = {s["name"] for s in data["services"]}
    assert names == {"Google", "GitHub", "Gitea"}


def test_create_service_returns_201(client):
    client.get("/services")  # seed first
    response = client.post("/services", json={
        "name": "Cloudflare",
        "url": "https://www.cloudflare.com",
    })
    assert response.status_code == 201
    assert response.get_json()["name"] == "Cloudflare"


def test_create_service_rejects_missing_name(client):
    response = client.post("/services", json={"url": "https://example.com"})
    assert response.status_code == 400


def test_create_service_rejects_missing_url(client):
    response = client.post("/services", json={"name": "MyService"})
    assert response.status_code == 400


def test_create_service_rejects_bad_url(client):
    response = client.post("/services", json={"name": "X", "url": "not-a-url"})
    assert response.status_code == 400


def test_create_service_rejects_duplicate(client):
    client.get("/services")  # seed
    response = client.post("/services", json={
        "name": "Google",
        "url": "https://example.com",
    })
    assert response.status_code == 409


def test_delete_service_removes_it(client):
    client.get("/services")  # seed (creates ids 1-3)
    response = client.delete("/services/1")
    assert response.status_code == 200

    # Verify it's gone
    list_response = client.get("/services")
    assert len(list_response.get_json()["services"]) == 2


def test_delete_nonexistent_returns_404(client):
    response = client.delete("/services/99999")
    assert response.status_code == 404


def test_restore_service(client):
    client.get("/services")  # seed
    client.delete("/services/1")
    response = client.post("/services/1/restore")
    assert response.status_code == 200


# --- /uptime ---

@patch("app.requests.get")
def test_uptime_returns_services_with_status(mock_get, client):
    """Uptime hits each service and reports status."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_get.return_value = mock_response

    response = client.get("/uptime")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["services"]) == 3
    assert all(s["status"] == "up" for s in data["services"])


@patch("app.requests.get")
def test_uptime_marks_down_on_exception(mock_get, client):
    """If a request fails, the service is marked down."""
    mock_get.side_effect = Exception("connection failed")

    response = client.get("/uptime")
    data = response.get_json()
    assert all(s["status"] == "down" for s in data["services"])