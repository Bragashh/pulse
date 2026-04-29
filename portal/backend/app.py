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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)