from flask import Flask, jsonify
from flask_cors import CORS
import psutil

app = Flask(__name__)
CORS(app)

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "pulse-backend"})

@app.route('/')
def index():
    return jsonify({"message": "Pulse API is running"})

@app.route('/metrics')
def metrics():
    return jsonify({
        "cpu": {
            "percent": psutil.cpu_percent(interval=1)
        },
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
    