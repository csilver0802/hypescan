# README.md

HypeScan - Hyperliquid + Binance ingestion (instrumented)

This branch adds Hyperliquid funding/open-interest fetchers, Redis publish and Postgres persistence, Prometheus metrics, and a health endpoint. Services are dockerized and can be deployed so you can access health and metrics remotely.

Frontend / Backend ports
- This project is backend-only for now (ingestors, fetchers, publisher, metrics). The "frontend" is the metrics/health UI exposed by the backend.
- Backend (health + metrics) port: METRICS_PORT (default 8000) — exposed to host in docker-compose.
- There is no separate frontend port in this phase; once you add a React frontend we will expose it on a separate port.

Deployment (Docker Compose)
1. Copy .env.example to .env and edit values. Make sure HYPERLIQUID_BASE_URL is set to https://api.hyperliquid.xyz and HYPERLIQUID_SYMBOLS list uses coin identifiers (e.g., BTC,ETH,SOL).

2. Initialize Postgres schema (run once):
   docker compose up -d postgres
   # run migration from host (requires psql):
   psql postgresql://postgres:postgres@localhost:5432/liquidation -f create_tables.sql

3. Build and start all services (rebuild app image):
   docker compose up --build -d

4. Verify services started:
   docker compose ps
   docker compose logs -f app

Accessing the app from Android phone (browser)
- Ensure the host machine (where Docker runs) is reachable from your Android device (same LAN or public IP).
- Open in your mobile browser:
  http://<HOST_IP>:8000/health   -> JSON health
  http://<HOST_IP>:8000/metrics  -> Prometheus metrics

Exact command to start the application (single command):
- docker compose up --build -d

Notes
- The app exposes only health and metrics endpoints. For web UI access consider adding a React frontend that connects to this backend or use Prometheus/Grafana to visualize metrics.
- Make sure firewall rules allow incoming connections to port 8000.
- For production, put a reverse proxy (NGINX) or load balancer in front and enable TLS.
