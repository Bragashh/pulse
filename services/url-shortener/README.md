# URL shortener

Tiny Flask service that creates short URL codes backed by Redis.
Part of Pulse v1.5.1 — provides a second service alongside the main Pulse backend
for monitoring/observability demonstrations.

## Endpoints

- `GET /health` — health check, returns 200 with Redis status (503 if Redis down)
- `POST /shorten` — body `{"url": "https://..."}` returns `{"short": "abc1234", "url": "..."}`
- `GET /<code>` — 302 redirect to the long URL, or 404 if not found
- `GET /prometheus-metrics` — Prometheus scrape endpoint

## Configuration

Environment variables:

- `REDIS_HOST` (default: `localhost`)
- `REDIS_PORT` (default: `6379`)
- `SHORTEN_RATE_LIMIT_PER_DAY` (default: `50`) — per-IP daily cap on shorten requests

## Abuse prevention

- Per-IP daily rate limit (configurable)
- Rate limit failures recorded as a labeled Prometheus metric so spikes are visible
- If Redis is unreachable during rate limit check, fails open (allows request) to avoid blocking all traffic during an outage