"""
Tests for the demo traffic generation endpoints.

Redis interactions are mocked to keep tests fast and isolated.
We also avoid actually firing background threads by patching threading.Thread
where it matters.
"""

import os
import tempfile
import importlib
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(monkeypatch):
    """Flask test client with a fresh DB and mocked Redis."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    monkeypatch.setenv("PULSE_DB_PATH", path)

    # Import demo first and patch its Redis client BEFORE app imports demo
    import demo as demo_module
    importlib.reload(demo_module)

    # Replace the Redis client with a MagicMock so all Redis calls succeed by default
    mock_redis = MagicMock()
    mock_redis.exists.return_value = False
    mock_redis.get.return_value = None
    mock_redis.ttl.return_value = 0
    mock_redis.incr.return_value = 1
    mock_redis.setex.return_value = True
    mock_redis.decr.return_value = 0
    mock_redis.delete.return_value = 1
    mock_redis.keys.return_value = []
    demo_module._r = mock_redis

    import db as db_module
    importlib.reload(db_module)

    import app as app_module
    importlib.reload(app_module)
    # The reload of app re-imported demo, so re-patch demo_module's _r
    import sys
    sys.modules['demo']._r = mock_redis
    demo_module = sys.modules['demo']

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        c._mock_redis = mock_redis  # so individual tests can inspect/configure it
        yield c

    if os.path.exists(path):
        os.unlink(path)


# --- /demo/burst ---

@patch("demo.threading.Thread")
def test_burst_returns_202_with_default_count(mock_thread, client):
    response = client.post("/demo/burst", json={})
    assert response.status_code == 202
    data = response.get_json()
    assert data["started"] is True
    assert data["kind"] == "burst"
    assert data["count"] == 20  # BURST_DEFAULT
    assert "demo_id" in data
    mock_thread.assert_called_once()


@patch("demo.threading.Thread")
def test_burst_accepts_custom_count(mock_thread, client):
    response = client.post("/demo/burst", json={"count": 50})
    assert response.get_json()["count"] == 50


@patch("demo.threading.Thread")
def test_burst_clamps_count_above_max(mock_thread, client):
    response = client.post("/demo/burst", json={"count": 99999})
    assert response.get_json()["count"] == 100  # BURST_MAX


@patch("demo.threading.Thread")
def test_burst_clamps_count_below_min(mock_thread, client):
    response = client.post("/demo/burst", json={"count": 0})
    assert response.get_json()["count"] == 1  # BURST_MIN


# --- /demo/sustained ---

@patch("demo.threading.Thread")
def test_sustained_returns_estimate(mock_thread, client):
    response = client.post("/demo/sustained", json={"duration_seconds": 30, "rps": 3})
    data = response.get_json()
    assert data["duration_seconds"] == 30
    assert data["rps"] == 3
    assert data["total_estimate"] == 90


@patch("demo.threading.Thread")
def test_sustained_clamps_rps(mock_thread, client):
    response = client.post("/demo/sustained", json={"rps": 100})
    assert response.get_json()["rps"] == 5  # SUSTAINED_RPS_MAX


# --- /demo/errors and /demo/slow ---

@patch("demo.threading.Thread")
def test_errors_default(mock_thread, client):
    response = client.post("/demo/errors", json={})
    assert response.get_json()["count"] == 5  # ERRORS_DEFAULT


@patch("demo.threading.Thread")
def test_slow_default(mock_thread, client):
    response = client.post("/demo/slow", json={})
    assert response.get_json()["delay_seconds"] == 2  # SLOW_DELAY_DEFAULT


# --- Cooldown ---

@patch("demo.threading.Thread")
def test_cooldown_blocks_subsequent_call(mock_thread, client):
    # First call succeeds; mock Redis exists=False on first check, True on second
    client._mock_redis.exists.side_effect = [False, True]
    client._mock_redis.ttl.return_value = 42

    resp1 = client.post("/demo/burst", json={})
    assert resp1.status_code == 202

    resp2 = client.post("/demo/burst", json={})
    assert resp2.status_code == 429
    data = resp2.get_json()
    assert data["started"] is False
    assert data["retry_after"] == 42


# --- Concurrency cap ---

@patch("demo.threading.Thread")
def test_concurrency_cap_blocks_when_at_limit(mock_thread, client):
    client._mock_redis.exists.return_value = False
    client._mock_redis.get.return_value = "5"  # already 5 running, == limit

    response = client.post("/demo/burst", json={})
    assert response.status_code == 429
    assert "concurrent" in response.get_json()["error"]


# --- Admin surface bypass ---

@patch("demo.threading.Thread")
def test_admin_surface_skips_cooldown(mock_thread, client):
    # Cooldown would normally block, but admin header bypasses
    client._mock_redis.exists.return_value = True
    client._mock_redis.ttl.return_value = 30

    response = client.post(
        "/demo/burst",
        json={},
        headers={"X-Admin-Surface": "1"},
    )
    assert response.status_code == 202


@patch("demo.threading.Thread")
def test_admin_surface_uses_higher_concurrency_limit(mock_thread, client):
    # Public would be blocked at 5; admin allowed up to 20
    client._mock_redis.exists.return_value = False
    client._mock_redis.get.return_value = "10"  # at public limit but under admin

    response = client.post(
        "/demo/burst",
        json={},
        headers={"X-Admin-Surface": "1"},
    )
    assert response.status_code == 202


# --- Stop endpoint ---

def test_stop_sets_redis_flag(client):
    response = client.post("/demo/stop/abc123")
    assert response.status_code == 200
    assert response.get_json()["stopped"] is True
    client._mock_redis.setex.assert_any_call("demo:stop:abc123", 60, "1")


# --- Active demos ---

def test_active_returns_empty_when_no_demos(client):
    client._mock_redis.keys.return_value = []
    response = client.get("/demo/active")
    assert response.get_json() == {"active": [], "count": 0}


def test_active_returns_running_demos(client):
    client._mock_redis.keys.return_value = ["demo:active:xyz789"]
    client._mock_redis.get.return_value = '{"kind": "sustained", "started_at": 1000, "params": {"duration_seconds": 30}, "ip": "1.2.3.4"}'

    response = client.get("/demo/active")
    data = response.get_json()
    assert data["count"] == 1
    assert data["active"][0]["kind"] == "sustained"
    assert data["active"][0]["demo_id"] == "xyz789"


# --- Helper endpoints ---

def test_force_error_returns_500(client):
    response = client.get("/demo/_force_error")
    assert response.status_code == 500


def test_simulate_slow_clamps_to_max(client):
    # Default 2s, max 5s; passing 99 should clamp to 5
    response = client.get("/demo/_simulate_slow?seconds=99")
    assert response.status_code == 200
    # Don't actually wait 5s — just verify the response shape
    assert response.get_json()["slept_seconds"] == 5


# --- Full-spectrum endpoint ---

@patch("demo.threading.Thread")
def test_full_spectrum_default_level(mock_thread, client):
    response = client.post("/demo/full-spectrum", json={})
    assert response.status_code == 202
    data = response.get_json()
    assert data["started"] is True
    assert data["kind"] == "full-spectrum"
    assert data["level"] == 3  # FULLSPECTRUM_LEVEL_DEFAULT
    assert data["duration_seconds"] == 60  # FULLSPECTRUM_DURATION_DEFAULT
    assert "profile" in data


@patch("demo.threading.Thread")
def test_full_spectrum_custom_level_and_duration(mock_thread, client):
    response = client.post("/demo/full-spectrum", json={"level": 5, "duration_seconds": 120})
    data = response.get_json()
    assert data["level"] == 5
    assert data["duration_seconds"] == 120
    # Level 5 profile should have higher rps than level 1
    assert data["profile"]["rps"] == 10


@patch("demo.threading.Thread")
def test_full_spectrum_clamps_level_above_max(mock_thread, client):
    response = client.post("/demo/full-spectrum", json={"level": 99})
    assert response.get_json()["level"] == 5


@patch("demo.threading.Thread")
def test_full_spectrum_clamps_duration_below_min(mock_thread, client):
    response = client.post("/demo/full-spectrum", json={"duration_seconds": 5})
    assert response.get_json()["duration_seconds"] == 30


@patch("demo.threading.Thread")
def test_full_spectrum_respects_cooldown(mock_thread, client):
    client._mock_redis.exists.return_value = True
    client._mock_redis.ttl.return_value = 30

    response = client.post("/demo/full-spectrum", json={})
    assert response.status_code == 429