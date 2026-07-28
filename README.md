# HypeScan - Quick Mobile Testing Guide (localtunnel)

This branch provides a backend-only prototype that ingests Binance L2 data, fetches funding & open-interest from Hyperliquid, publishes events to Redis and persists to Postgres. It exposes a small HTTP server for health and Prometheus metrics.

This README section explains the fastest way to view the health and metrics endpoints from an Android phone using a secure tunnel (localtunnel). This is for short-term testing only.

-- Quick checklist before starting
1. Docker & Docker Compose installed on the host.
2. Node.js installed (for `npx localtunnel`), or install localtunnel globally via `npm install -g localtunnel`.
3. Ensure you have network access to api.hyperliquid.xyz from the host.

-- Setup & start the app (exact commands)

1) Clone the repo and checkout the instrumentation branch (if you didn't already):

```bash
git clone https://github.com/csilver0802/hypescan.git
cd hypescan
git fetch origin
git checkout feature/hyperliquid-fetchers-docker
```

2) Copy environment template and edit values (do NOT commit .env):

```bash
cp .env.example .env
# Edit .env and set POSTGRES_DSN, REDIS_URL, HYPERLIQUID_SYMBOLS, METRICS_PORT, etc.
# Example: HYPERLIQUID_SYMBOLS=BTC,ETH,SOL
```

3) Initialize Postgres schema (one-time):

Start Postgres container:

```bash
docker compose up -d postgres
```

Apply DB migration (from host, requires psql installed):

```bash
psql postgresql://postgres:postgres@localhost:5432/liquidation -f create_tables.sql
```

If you do not have psql locally, you can exec into the postgres container and run migrations with an appropriate path or use a migration container.

4) Build and start the full stack (single command):

```bash
docker compose up --build -d
```

This will:
- Build the app image
- Start postgres and redis
- Start the app container (runs ingestor, hyperliquid fetchers, publisher, health server, metrics)

5) Verify the app is listening locally on port 8000 (default METRICS_PORT):

```bash
curl http://localhost:8000/health
# You should get a JSON response with application status.
```

-- Create a public tunnel (one-command)

We recommend localtunnel (no account required) for the fastest test.

If you have Node.js installed, run:

```bash
npx localtunnel --port 8000
```

Example output:

```
your url is: https://abcd-1234.loca.lt
```

Notes:
- The URL will be ephemeral and printed to your terminal.
- If you prefer a custom subdomain (not guaranteed), use `npx localtunnel --port 8000 --subdomain mytest123`.
- To stop the tunnel: Ctrl+C in the terminal where you started localtunnel.

-- Exact URL paths to open on your Android phone

Take the public URL printed by localtunnel and append the endpoints:

- Health endpoint:
  https://<PUBLIC_URL>/health

- Prometheus metrics endpoint:
  https://<PUBLIC_URL>/metrics

Example (if localtunnel prints https://abcd-1234.loca.lt):
- https://abcd-1234.loca.lt/health
- https://abcd-1234.loca.lt/metrics

Open the above URL(s) in your Android browser.

-- Verification steps on mobile
1. Open the health URL in your mobile browser. You should see JSON similar to:

```json
{
  "application": "hypescan",
  "status": "ok",
  "db_connected": true,
  "redis_connected": true,
  "last_liquidation_event_ts": 162...,
  "last_enrichment_update": {"BTC": 162...},
  "fetcher_status": {"BTC": {"ok": true, "last_ok": 162...}},
  "uptime_seconds": 123.4
}
```

2. Open the metrics URL and verify Prometheus metrics are present (text output). You should see counters like `liquidation_events_received_total` and `funding_fetch_success_total{symbol="BTC"}`.

-- Security warnings (important)
- localtunnel exposes your local port to the public Internet. Anyone with the URL can access the endpoints.
- Do NOT use this for production or to expose databases. This is strictly for short-term testing.
- Immediately stop the tunnel (Ctrl+C) when you're done.
- If you need password protection for the public URL, use ngrok with basic auth instead (requires signup).

-- Tidy up / stop services

To stop the tunnel: Ctrl+C in the terminal running localtunnel.

To stop the Docker stack:

```bash
docker compose down
```

-- Troubleshooting
- If `curl http://localhost:8000/health` fails, check the app logs first:

```bash
docker compose logs -f app
```

- If the app logs show "Health server started on port 8000" but the curl still fails, ensure the container port is exposed and not blocked by host firewall.

- If localtunnel reports connection errors, verify the host can access the Internet and that localtunnel service isn't blocked.

-- Next steps
After you verify the endpoints from your Android phone, we will proceed to deploy the stack onto a cloud VPS with proper TLS, firewall, and optional reverse-proxy for secure 24/7 access.

If you want, I can also provide a tiny helper script that starts the app and automatically runs localtunnel and prints the public URL.
