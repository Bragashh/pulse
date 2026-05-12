"""
Alert webhook receiver.

Alertmanager POSTs alert events here. We:
  1. Store them in memory (newest 50) so the admin UI can show them.
  2. Forward to Discord with a properly-formatted embed payload.

Discord webhook URL is read from env var DISCORD_WEBHOOK_URL.
"""

import os
import threading
import time
from collections import deque

import requests
from flask import Blueprint, jsonify, request

alerts = Blueprint("alerts", __name__)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# In-memory store of recent alerts. Last 50.
# Each entry: {"alertname", "severity", "summary", "description", "status", "received_at"}
_recent_alerts = deque(maxlen=50)
_lock = threading.Lock()

# Discord color codes
SEVERITY_COLORS = {
    "critical": 0xEF4444,   # red
    "warning": 0xF59E0B,    # amber
    "info": 0x3B82F6,       # blue
}
RESOLVED_COLOR = 0x10B981   # green


def _post_to_discord(alert: dict) -> None:
    """POST a single alert as a Discord embed. Non-blocking failure."""
    if not DISCORD_WEBHOOK_URL:
        return

    status = alert.get("status", "firing")
    severity = alert.get("labels", {}).get("severity", "info")
    annotations = alert.get("annotations", {})
    summary = annotations.get("summary", "Alert")
    description = annotations.get("description", "")
    alertname = alert.get("labels", {}).get("alertname", "Unknown")

    if status == "resolved":
        title = f"✅ Resolved — {alertname}"
        color = RESOLVED_COLOR
    else:
        emoji = "🚨" if severity == "critical" else "⚠️"
        title = f"{emoji} {alertname}"
        color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["info"])

    payload = {
        "username": "Pulse Alerts",
        "embeds": [{
            "title": title,
            "description": f"**{summary}**\n{description}",
            "color": color,
            "fields": [
                {"name": "Severity", "value": severity, "inline": True},
                {"name": "Status", "value": status, "inline": True},
            ],
            "footer": {"text": "Pulse v1.5.1 monitoring"},
        }],
    }

    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except requests.exceptions.RequestException:
        pass


@alerts.route("/api/alerts/webhook", methods=["POST"])
def receive_alert():
    """Receive a webhook from Alertmanager and forward each alert to Discord."""
    data = request.get_json(silent=True) or {}
    incoming = data.get("alerts", [])

    for alert in incoming:
        # Store in memory
        with _lock:
            _recent_alerts.append({
                "alertname": alert.get("labels", {}).get("alertname", "Unknown"),
                "severity": alert.get("labels", {}).get("severity", "info"),
                "summary": alert.get("annotations", {}).get("summary", ""),
                "description": alert.get("annotations", {}).get("description", ""),
                "status": alert.get("status", "firing"),
                "received_at": int(time.time()),
            })

        # Forward to Discord (fire-and-forget)
        threading.Thread(target=_post_to_discord, args=(alert,), daemon=True).start()

    return jsonify({"received": len(incoming)}), 200


@alerts.route("/api/alerts/active", methods=["GET"])
def list_active_alerts():
    """Return recent alerts for the admin UI. Newest first."""
    with _lock:
        items = list(_recent_alerts)
    items.reverse()
    return jsonify({"alerts": items, "count": len(items)})