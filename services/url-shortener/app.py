"""
URL shortener service.

Two main endpoints:
  POST /shorten        - body {"url": "https://..."} returns {"short": "abc1234", "url": "..."}
  GET  /<code>          - 302 redirect to the long URL or 404 if not found

Also exposes /health and /prometheus-metrics for monitoring.

Storage: Redis. Key format: short:<code> -> <long_url>
Configuration: REDIS_HOST, REDIS_PORT env vars.
"""

import os
import secrets
import string
import time
from functools import wraps

import redis
from flask import Flask, jsonify, request, redirect, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST


# --- Configuration ---

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Rate limiting: per-IP cap on shorten requests per day.
# Real limiter (flask-limiter with Redis backend) is overkill here; we use
# a Redis counter ourselves so it stays simple and the counter is shared
# across replicas if we ever scale out.
SHORTEN_RATE_LIMIT_PER_DAY = int(os.environ.get("SHORTEN_RATE_LIMIT_PER_DAY", "50"))


# --- Setup ---

app = Flask(__name__)
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# --- Prometheus metrics ---

shorten_requests = Counter(
    "shortener_shorten_requests_total",
    "Total POST /shorten requests, by outcome",
    ["outcome"],   # success, rate_limited, invalid_url, redis_unavailable
)
redirect_requests = Counter(
    "shortener_redirect_requests_total",
    "Total GET /<code> requests, by outcome",
    ["outcome"],   # success, not_found, redis_unavailable
)
request_duration = Histogram(
    "shortener_http_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
)


def track_duration(endpoint_name):
    """Decorator that records request duration as a histogram."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                request_duration.labels(endpoint=endpoint_name).observe(time.time() - start)
        return wrapper
    return decorator


# --- Short code generation ---

SHORT_CODE_LENGTH = 7
SHORT_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_short_code() -> str:
    return ''.join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


# --- Rate limiting helper ---

def check_rate_limit(client_ip: str) -> bool:
    """
    Returns True if the IP is under the daily limit and the request is allowed.
    Returns False if the limit is exceeded.

    Uses Redis INCR with EXPIRE to count requests per IP per UTC day.
    """
    today = time.strftime("%Y-%m-%d", time.gmtime())
    key = f"ratelimit:shorten:{client_ip}:{today}"
    try:
        count = r.incr(key)
        if count == 1:
            # First request of the day for this IP — set expiry to 25h (rolls over)
            r.expire(key, 25 * 60 * 60)
        return count <= SHORTEN_RATE_LIMIT_PER_DAY
    except redis.exceptions.RedisError:
        # If Redis is down, fall open (allow the request rather than block all traffic)
        return True


# --- Routes ---

@app.route('/health')
@track_duration('health')
def health():
    """Health check — also verifies Redis is reachable."""
    try:
        r.ping()
        return jsonify({"status": "ok", "redis": "connected"})
    except redis.exceptions.ConnectionError:
        return jsonify({"status": "degraded", "redis": "unreachable"}), 503


@app.route('/')
def index():
    return jsonify({
        "service": "url-shortener",
        "endpoints": {
            "POST /shorten": "body {url} -> {short, url}",
            "GET /<code>": "302 redirect to long URL"
        }
    })


@app.route('/shorten', methods=['POST'])
@track_duration('shorten')
def shorten():
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

    # Rate limit
    if not check_rate_limit(client_ip):
        shorten_requests.labels(outcome="rate_limited").inc()
        return jsonify({
            "error": f"rate limit exceeded ({SHORTEN_RATE_LIMIT_PER_DAY} per day per IP)"
        }), 429

    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()

    if not url:
        shorten_requests.labels(outcome="invalid_url").inc()
        return jsonify({"error": "url is required"}), 400

    if not (url.startswith('http://') or url.startswith('https://')):
        shorten_requests.labels(outcome="invalid_url").inc()
        return jsonify({"error": "url must start with http:// or https://"}), 400

    # Generate a unique code (retry rare collisions)
    try:
        for _ in range(5):
            code = generate_short_code()
            if not r.exists(f"short:{code}"):
                r.set(f"short:{code}", url)
                shorten_requests.labels(outcome="success").inc()
                return jsonify({"short": code, "url": url}), 201
        shorten_requests.labels(outcome="invalid_url").inc()
        return jsonify({"error": "could not generate a unique code"}), 500
    except redis.exceptions.RedisError:
        shorten_requests.labels(outcome="redis_unavailable").inc()
        return jsonify({"error": "storage unavailable"}), 503


@app.route('/<code>')
@track_duration('redirect')
def redirect_short(code):
    try:
        long_url = r.get(f"short:{code}")
    except redis.exceptions.RedisError:
        redirect_requests.labels(outcome="redis_unavailable").inc()
        return jsonify({"error": "storage unavailable"}), 503

    if long_url is None:
        redirect_requests.labels(outcome="not_found").inc()
        return jsonify({"error": "short code not found"}), 404

    redirect_requests.labels(outcome="success").inc()
    return redirect(long_url, code=302)


@app.route('/prometheus-metrics')
def prometheus_metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)