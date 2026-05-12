"""
Demo traffic generation endpoints.

Each trigger kicks off background work that generates load on the Pulse backend
itself, producing observable spikes in Prometheus metrics for live demos.

Public-surface protections:
  - Per-IP cooldown (no demo-start more than once per 60s)
  - Global concurrency cap (max 5 demos running site-wide)
  - Bounded input parameters (min/max enforced)

Admin-surface bypass:
  - Requests carrying X-Admin-Surface: 1 (set by nginx admin subdomain only)
    skip cooldown and have an elevated concurrency cap.

All endpoints return immediately; work runs in a thread. Background threads
check a Redis "stop" flag every iteration so the stop button is responsive.
"""

import os
import random
import threading
import time
import uuid

import redis
import requests
from flask import Blueprint, jsonify, request


demo = Blueprint("demo", __name__)


# --- Configuration ---

SELF_URL = os.environ.get("PULSE_SELF_URL", "http://localhost:5000")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

PUBLIC_CONCURRENCY_LIMIT = 5
ADMIN_CONCURRENCY_LIMIT = 20
COOLDOWN_SECONDS = 60

# Bounds for user-supplied parameters
BURST_MIN, BURST_MAX, BURST_DEFAULT = 1, 100, 20
SUSTAINED_DURATION_MIN, SUSTAINED_DURATION_MAX, SUSTAINED_DURATION_DEFAULT = 5, 60, 30
SUSTAINED_RPS_MIN, SUSTAINED_RPS_MAX, SUSTAINED_RPS_DEFAULT = 1, 5, 3
ERRORS_MIN, ERRORS_MAX, ERRORS_DEFAULT = 1, 50, 5
SLOW_DELAY_MIN, SLOW_DELAY_MAX, SLOW_DELAY_DEFAULT = 1, 5, 2


# --- Redis ---

_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def _redis_safe(func, default=None):
    """Run a Redis op, returning default on connection errors so demos work without Redis."""
    try:
        return func()
    except redis.exceptions.RedisError:
        return default


# --- Surface detection ---

def _is_admin_surface() -> bool:
    """nginx admin subdomain sets X-Admin-Surface: 1. Client cannot forge this past nginx."""
    return request.headers.get("X-Admin-Surface") == "1"


def _client_ip() -> str:
    """First IP in X-Forwarded-For, falling back to remote_addr. Used for cooldowns."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


# --- Concurrency + cooldown gates ---

def _check_and_register_demo() -> tuple[bool, str, dict]:
    """
    Verify that the caller is allowed to start a new demo, and reserve a slot if so.

    Returns:
      (ok, demo_id_or_error_message, info_dict)

    ok is True with a fresh UUID on success.
    ok is False with a human-readable error message on rejection.
    """
    admin = _is_admin_surface()
    ip = _client_ip()

    # Cooldown check (public only)
    if not admin:
        cooldown_key = f"demo:cooldown:{ip}"
        if _redis_safe(lambda: _r.exists(cooldown_key)):
            ttl = _redis_safe(lambda: _r.ttl(cooldown_key), default=0)
            return (False, f"demo cooldown active, retry in {ttl}s", {"retry_after": ttl})

    # Concurrency check
    limit = ADMIN_CONCURRENCY_LIMIT if admin else PUBLIC_CONCURRENCY_LIMIT
    current = _redis_safe(lambda: int(_r.get("demo:concurrent") or 0), default=0)
    if current >= limit:
        return (False, f"too many concurrent demos ({current}/{limit}), try again shortly", {"limit": limit})

    # Reserve the slot
    demo_id = uuid.uuid4().hex[:12]
    _redis_safe(lambda: _r.incr("demo:concurrent"))
    if not admin:
        _redis_safe(lambda: _r.setex(f"demo:cooldown:{ip}", COOLDOWN_SECONDS, "1"))

    return (True, demo_id, {"admin": admin})


def _release_demo_slot(demo_id: str) -> None:
    """Cleanup: decrement concurrent counter, remove tracking keys."""
    _redis_safe(lambda: _r.decr("demo:concurrent"))
    _redis_safe(lambda: _r.delete(f"demo:active:{demo_id}"))
    _redis_safe(lambda: _r.delete(f"demo:stop:{demo_id}"))


def _record_active_demo(demo_id: str, kind: str, params: dict) -> None:
    """Record metadata about a running demo. Used by the admin page to display active demos."""
    import json
    payload = {"kind": kind, "started_at": int(time.time()), "params": params, "ip": _client_ip()}
    _redis_safe(lambda: _r.setex(f"demo:active:{demo_id}", 600, json.dumps(payload)))


def _should_stop(demo_id: str) -> bool:
    """Check the Redis stop flag. Background threads check this between iterations."""
    return bool(_redis_safe(lambda: _r.exists(f"demo:stop:{demo_id}")))


# --- Internal helpers ---

def _bounded_int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _fire(method: str, path: str) -> None:
    try:
        if method == "GET":
            requests.get(f"{SELF_URL}{path}", timeout=10)
        else:
            requests.post(f"{SELF_URL}{path}", timeout=10)
    except requests.exceptions.RequestException:
        pass


# --- Background runners ---

def _run_burst(count: int, demo_id: str) -> None:
    """Fire endpoints rapidly. Burst is short-lived; stop button not exposed in UI."""
    endpoints = ["/health", "/metrics", "/services", "/uptime"]
    try:
        for _ in range(count):
            if _should_stop(demo_id):
                return
            _fire("GET", random.choice(endpoints))
    finally:
        _release_demo_slot(demo_id)


def _run_sustained(duration_seconds: int, rps: int, demo_id: str) -> None:
    endpoints = ["/health", "/metrics", "/services"]
    deadline = time.time() + duration_seconds
    interval = 1.0 / max(rps, 1)
    try:
        while time.time() < deadline:
            if _should_stop(demo_id):
                return
            _fire("GET", random.choice(endpoints))
            time.sleep(interval)
    finally:
        _release_demo_slot(demo_id)


def _run_errors(count: int, demo_id: str) -> None:
    try:
        for _ in range(count):
            if _should_stop(demo_id):
                return
            _fire("GET", "/demo/_force_error")
    finally:
        _release_demo_slot(demo_id)


def _run_slow(delay_seconds: int, demo_id: str) -> None:
    """Sleep in 0.5s chunks so the stop flag is checked periodically."""
    try:
        end_time = time.time() + delay_seconds
        while time.time() < end_time:
            if _should_stop(demo_id):
                return
            time.sleep(min(0.5, end_time - time.time()))
        _fire("GET", f"/demo/_simulate_slow?seconds={delay_seconds}")
    finally:
        _release_demo_slot(demo_id)


# --- Public trigger endpoints ---

@demo.route("/demo/burst", methods=["POST"])
def trigger_burst():
    data = request.get_json(silent=True) or {}
    count = _bounded_int(data.get("count"), BURST_DEFAULT, BURST_MIN, BURST_MAX)

    ok, demo_id_or_msg, info = _check_and_register_demo()
    if not ok:
        return jsonify({"started": False, "error": demo_id_or_msg, **info}), 429

    demo_id = demo_id_or_msg
    _record_active_demo(demo_id, "burst", {"count": count})
    threading.Thread(target=_run_burst, args=(count, demo_id), daemon=True).start()
    return jsonify({"started": True, "demo_id": demo_id, "kind": "burst", "count": count, **info}), 202


@demo.route("/demo/sustained", methods=["POST"])
def trigger_sustained():
    data = request.get_json(silent=True) or {}
    duration = _bounded_int(data.get("duration_seconds"), SUSTAINED_DURATION_DEFAULT, SUSTAINED_DURATION_MIN, SUSTAINED_DURATION_MAX)
    rps = _bounded_int(data.get("rps"), SUSTAINED_RPS_DEFAULT, SUSTAINED_RPS_MIN, SUSTAINED_RPS_MAX)

    ok, demo_id_or_msg, info = _check_and_register_demo()
    if not ok:
        return jsonify({"started": False, "error": demo_id_or_msg, **info}), 429

    demo_id = demo_id_or_msg
    params = {"duration_seconds": duration, "rps": rps}
    _record_active_demo(demo_id, "sustained", params)
    threading.Thread(target=_run_sustained, args=(duration, rps, demo_id), daemon=True).start()
    return jsonify({"started": True, "demo_id": demo_id, "kind": "sustained", **params, "total_estimate": duration * rps, **info}), 202


@demo.route("/demo/errors", methods=["POST"])
def trigger_errors():
    data = request.get_json(silent=True) or {}
    count = _bounded_int(data.get("count"), ERRORS_DEFAULT, ERRORS_MIN, ERRORS_MAX)

    ok, demo_id_or_msg, info = _check_and_register_demo()
    if not ok:
        return jsonify({"started": False, "error": demo_id_or_msg, **info}), 429

    demo_id = demo_id_or_msg
    _record_active_demo(demo_id, "errors", {"count": count})
    threading.Thread(target=_run_errors, args=(count, demo_id), daemon=True).start()
    return jsonify({"started": True, "demo_id": demo_id, "kind": "errors", "count": count, **info}), 202


@demo.route("/demo/slow", methods=["POST"])
def trigger_slow():
    data = request.get_json(silent=True) or {}
    delay = _bounded_int(data.get("delay_seconds"), SLOW_DELAY_DEFAULT, SLOW_DELAY_MIN, SLOW_DELAY_MAX)

    ok, demo_id_or_msg, info = _check_and_register_demo()
    if not ok:
        return jsonify({"started": False, "error": demo_id_or_msg, **info}), 429

    demo_id = demo_id_or_msg
    _record_active_demo(demo_id, "slow", {"delay_seconds": delay})
    threading.Thread(target=_run_slow, args=(delay, demo_id), daemon=True).start()
    return jsonify({"started": True, "demo_id": demo_id, "kind": "slow", "delay_seconds": delay, **info}), 202


# --- Stop endpoint ---

@demo.route("/demo/stop/<demo_id>", methods=["POST"])
def stop_demo(demo_id: str):
    """Signal a running demo to stop. The background thread checks this flag each iteration."""
    _redis_safe(lambda: _r.setex(f"demo:stop:{demo_id}", 60, "1"))
    return jsonify({"stopped": True, "demo_id": demo_id})


# --- Active demos endpoint (used by admin page) ---

@demo.route("/demo/active", methods=["GET"])
def list_active_demos():
    """Return all currently active demos with metadata."""
    import json
    keys = _redis_safe(lambda: _r.keys("demo:active:*"), default=[])
    out = []
    for key in keys or []:
        raw = _redis_safe(lambda k=key: _r.get(k))
        if not raw:
            continue
        try:
            payload = json.loads(raw)
            payload["demo_id"] = key.split(":")[-1]
            out.append(payload)
        except json.JSONDecodeError:
            continue
    return jsonify({"active": out, "count": len(out)})


# --- Helper endpoints used by the runners (not public-facing concepts) ---

@demo.route("/demo/_force_error", methods=["GET"])
def force_error():
    return jsonify({"error": "intentional demo error"}), 500


@demo.route("/demo/_simulate_slow", methods=["GET"])
def simulate_slow():
    seconds = _bounded_int(request.args.get("seconds"), SLOW_DELAY_DEFAULT, SLOW_DELAY_MIN, SLOW_DELAY_MAX)
    time.sleep(seconds)
    return jsonify({"slept_seconds": seconds})