#!/usr/bin/env bash
set -euo pipefail

# start-replit.sh
# Installs requirements and launches the Python app (health server + fetchers) in a Replit environment.
# NOTE: Replit may have network and process limitations. This script runs the app directly without Docker.

# Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Copy example env if not present
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Please edit .env with real POSTGRES_DSN/REDIS_URL/HYPERLIQUID settings if required"
fi

# Run the app (main_runner starts health server on METRICS_PORT = 8000 by default)
python main_runner.py
