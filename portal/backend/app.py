from flask import Flask, jsonify
from flask_cors import CORS
import psutil
import requests
import time

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
    headers = {"Accept": "application/vnd.github+json"}
    
    # Deployment frequency - commits to main in last 7 days
    commits_url = "https://api.github.com/repos/Bragashh/pulse/commits?sha=main&per_page=100"
    commits_resp = requests.get(commits_url, headers=headers)
    commits = commits_resp.json()
    
    from datetime import datetime, timezone, timedelta
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_commits = [
        c for c in commits
        if datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00")) > week_ago
    ]
    
    # Change failure rate - failed vs successful workflow runs
    runs_url = "https://api.github.com/repos/Bragashh/pulse/actions/runs?per_page=20"
    runs_resp = requests.get(runs_url, headers=headers)
    runs = runs_resp.json().get("workflow_runs", [])
    
    total_runs = len(runs)
    failed_runs = len([r for r in runs if r["conclusion"] == "failure"])
    failure_rate = round((failed_runs / total_runs) * 100, 1) if total_runs > 0 else 0
    
    return jsonify({
        "deployment_frequency": {
            "commits_last_7_days": len(recent_commits),
            "per_day": round(len(recent_commits) / 7, 1)
        },
        "change_failure_rate": {
            "total_runs": total_runs,
            "failed_runs": failed_runs,
            "failure_rate_percent": failure_rate
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)