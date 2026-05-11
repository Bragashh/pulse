from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import psutil
import requests
import sqlite3
import time
from datetime import datetime, timezone, timedelta
import os

import db
import metrics

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


def github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


app = Flask(__name__)
CORS(app)


# Default services seeded into the database on first call to /uptime if empty.
SEED_SERVICES = [
    {"name": "Google", "url": "https://www.google.com"},
    {"name": "GitHub", "url": "https://github.com"},
    {"name": "Gitea", "url": "https://gitea.dev.bodnarescu.ro"},
]


def seed_services_if_empty():
    """If the database has no services, populate it with the defaults."""
    existing = db.list_monitored_services()
    if existing:
        return
    for service in SEED_SERVICES:
        db.add_monitored_service(service["name"], service["url"])


@app.route('/health')
@metrics.track_request('health')
def health():
    return jsonify({"status": "ok", "service": "pulse-backend"})


@app.route('/')
@metrics.track_request('/')
def index():
    return jsonify({"message": "Pulse API is running"})


@app.route('/metrics')
@metrics.track_request('metrics')
def system_metrics():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Update Prometheus gauges so they reflect current values
    metrics.cpu_percent.set(cpu)
    metrics.memory_percent.set(mem.percent)
    metrics.disk_percent.set(disk.percent)

    return jsonify({
        "cpu": {"percent": cpu},
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "percent": mem.percent
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "percent": disk.percent
        }
    })


@app.route('/uptime')
@metrics.track_request('uptime')
def uptime():
    seed_services_if_empty()
    services = db.list_monitored_services()

    # Update Prometheus gauge
    metrics.monitored_services_count.set(len(services))

    results = []
    for service in services:
        try:
            start = time.time()
            response = requests.get(service["url"], timeout=5)
            latency = round((time.time() - start) * 1000, 2)
            results.append({
                "name": service["name"],
                "url": service["url"],
                "status": "up" if response.status_code == 200 else "degraded",
                "status_code": response.status_code,
                "latency_ms": latency
            })
        except Exception as e:
            results.append({
                "name": service["name"],
                "url": service["url"],
                "status": "down",
                "error": str(e)
            })
    return jsonify({"services": results})


@app.route('/dora')
@metrics.track_request('dora')
def dora():
    headers = github_headers()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    commits_url = "https://api.github.com/repos/Bragashh/pulse/commits?sha=main&per_page=100"
    commits_resp = requests.get(commits_url, headers=headers)
    commits_data = commits_resp.json()

    if isinstance(commits_data, list):
        recent_commits = [
            c for c in commits_data
            if datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00")) > week_ago
        ]
        commits_count = len(recent_commits)
    else:
        commits_count = 0

    runs_url = "https://api.github.com/repos/Bragashh/pulse/actions/runs?per_page=20"
    runs_resp = requests.get(runs_url, headers=headers)
    runs_data = runs_resp.json()
    runs = runs_data.get("workflow_runs", []) if isinstance(runs_data, dict) else []

    total_runs = len(runs)
    failed_runs = len([r for r in runs if r["conclusion"] == "failure"])
    failure_rate = round((failed_runs / total_runs) * 100, 1) if total_runs > 0 else 0

    return jsonify({
        "deployment_frequency": {
            "commits_last_7_days": commits_count,
            "per_day": round(commits_count / 7, 1)
        },
        "change_failure_rate": {
            "total_runs": total_runs,
            "failed_runs": failed_runs,
            "failure_rate_percent": failure_rate
        }
    })


@app.route('/score')
@metrics.track_request('score')
def score():
    total = 100

    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent

    if cpu > 80: total -= 20
    elif cpu > 60: total -= 10

    if mem > 80: total -= 20
    elif mem > 60: total -= 10

    if disk > 80: total -= 20
    elif disk > 60: total -= 10

    for service in db.list_monitored_services():
        try:
            r = requests.get(service["url"], timeout=5)
            if r.status_code != 200:
                total -= 15
        except:
            total -= 15

    runs_url = "https://api.github.com/repos/Bragashh/pulse/actions/runs?per_page=20"
    runs_resp = requests.get(runs_url, headers=github_headers())
    runs_data = runs_resp.json()
    runs = runs_data.get("workflow_runs", []) if isinstance(runs_data, dict) else []
    total_runs = len(runs)
    failed_runs = len([r for r in runs if r["conclusion"] == "failure"])
    if total_runs > 0:
        failure_rate = (failed_runs / total_runs) * 100
        if failure_rate > 20: total -= 20
        elif failure_rate > 10: total -= 10

    return jsonify({
        "score": max(0, total),
        "max": 100,
        "status": "healthy" if total >= 80 else "degraded" if total >= 50 else "critical"
    })


# --- Service management endpoints (CRUD) ---

@app.route('/services', methods=['GET'])
@metrics.track_request('list_services')
def list_services():
    """Return all currently monitored services."""
    seed_services_if_empty()
    services = db.list_monitored_services()
    return jsonify({"services": services})


@app.route('/services', methods=['POST'])
def create_service():
    """Add a new monitored service."""
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not url:
        return jsonify({"error": "url is required"}), 400

    if not (url.startswith('http://') or url.startswith('https://')):
        return jsonify({"error": "url must start with http:// or https://"}), 400

    try:
        service_id = db.add_monitored_service(name, url)
    except sqlite3.IntegrityError:
        return jsonify({"error": f"a service named '{name}' already exists"}), 409

    return jsonify({
        "id": service_id,
        "name": name,
        "url": url,
    }), 201


@app.route('/services/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    """Soft-delete a monitored service."""
    deleted = db.soft_delete_monitored_service(service_id)
    if not deleted:
        return jsonify({"error": "service not found or already deleted"}), 404
    return jsonify({"id": service_id, "deleted": True})


@app.route('/services/<int:service_id>/restore', methods=['POST'])
def restore_service(service_id):
    """Restore a soft-deleted service."""
    restored = db.restore_monitored_service(service_id)
    if not restored:
        return jsonify({"error": "service not found or not deleted"}), 404
    return jsonify({"id": service_id, "restored": True})


@app.route('/prometheus-metrics')
def prometheus_metrics():
    """Endpoint Prometheus scrapes to collect all metrics."""
    body, content_type = metrics.metrics_response()
    return Response(body, mimetype=content_type)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)