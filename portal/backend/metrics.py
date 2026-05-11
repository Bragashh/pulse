"""
Prometheus metrics for Pulse v1.5.1.

Defines the metric objects and provides a decorator that auto-records
request count and duration for Flask routes.

Metrics are exposed at /prometheus-metrics in the Prometheus text format,
which Prometheus scrapes periodically.
"""

import time
from functools import wraps
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST


# --- Metric definitions ---

# Counter: ever-increasing total. Use rate() in PromQL to get "requests per second".
request_count = Counter(
    "pulse_http_requests_total",
    "Total number of HTTP requests handled",
    ["endpoint", "status_code"],
)

# Histogram: bucketed observations. Lets us compute percentiles (p50, p95, p99).
request_duration = Histogram(
    "pulse_http_request_duration_seconds",
    "Time spent processing each HTTP request",
    ["endpoint"],
)

# Gauges: values that can go up and down. Set explicitly, not incremented.
monitored_services_count = Gauge(
    "pulse_monitored_services",
    "Number of services currently being monitored",
)

cpu_percent = Gauge("pulse_cpu_percent", "Current CPU usage percentage")
memory_percent = Gauge("pulse_memory_percent", "Current memory usage percentage")
disk_percent = Gauge("pulse_disk_percent", "Current disk usage percentage")


# --- Decorator that auto-records metrics for a Flask route ---

def track_request(endpoint_name):
    """
    Wrap a Flask route to record request count and duration.

    Usage:
        @app.route('/health')
        @track_request('health')
        def health(): ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            status_code = "500"  # default if exception bubbles
            try:
                response = func(*args, **kwargs)
                # Flask handlers return either a body or a (body, status) tuple
                if isinstance(response, tuple) and len(response) >= 2:
                    status_code = str(response[1])
                else:
                    status_code = "200"
                return response
            finally:
                duration = time.time() - start
                request_count.labels(endpoint=endpoint_name, status_code=status_code).inc()
                request_duration.labels(endpoint=endpoint_name).observe(duration)
        return wrapper
    return decorator


# --- Exposition format helper ---

def metrics_response():
    """Return the metrics in Prometheus text format and the right content type."""
    return generate_latest(), CONTENT_TYPE_LATEST