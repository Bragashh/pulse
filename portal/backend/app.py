from flask import Flask, jsonify
from flask_cors import CORS
import psutil
import requests
import time
from datetime import datetime, timezone, timedelta

import os

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

def github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers

app = Flask(__name__)
CORS(app)

SERVICES = [
    {"name": "Google", "url": "https://www.google.com"},
    {"name": "GitHub", "url": "https://github.com"},
    {"name": "Gitea", "url": "https://gitea.dev.bodnarescu.ro"},
]

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "pulse-backend"})

@app.route('/')
def index():
    return jsonify({"message": "Pulse API is running"})

@app.route('/metrics')
def metrics():
    return jsonify({
        "cpu": {"percent": psutil.cpu_percent(interval=1)},
        "memory": {
            "total": psutil.virtual_memory().total,
            "used": psutil.virtual_memory().used,
            "percent": psutil.virtual_memory().percent
        },
        "disk": {
            "total": psutil.disk_usage('/').total,
            "used": psutil.disk_usage('/').used,
            "percent": psutil.disk_usage('/').percent
        }
    })

@app.route('/uptime')
def uptime():
    results = []
    for service in SERVICES:
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

    for service in SERVICES:
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)