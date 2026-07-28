# README.md

HypeScan - Hyperliquid + Binance ingestion (proof-of-concept)

This branch adds Hyperliquid funding/open-interest fetchers, Redis publish and Postgres persistence, and a docker-compose deployment.

Quickstart
1. Copy .env.example to .env and adjust values.
2. Ensure Docker is installed.
3. Initialize Postgres schema:
   docker compose up -d postgres
   docker exec -i $(docker ps -qf "ancestor=postgres:15-alpine") psql -U postgres -d liquidation -f /app/create_tables.sql || \
   psql postgresql://postgres:postgres@localhost:5432/liquidation -f create_tables.sql
4. Build and run all services:
   docker compose up --build -d
5. Tail logs:
   docker compose logs -f app

Notes
- Hyperliquid endpoints are live (https://api.hyperliquid.xyz). No dummy data is used.
- If Hyperliquid requires auth, set HYPERLIQUID_API_KEY in your .env.
