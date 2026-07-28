# metrics.py
"""
Prometheus metrics definitions and helper functions.
"""
from prometheus_client import Counter, Gauge, Histogram, Summary

# Counters
liquidation_events_received = Counter(
    "liquidation_events_received_total",
    "Total number of liquidation events received from exchange ingestors",
)
funding_fetch_success = Counter(
    "funding_fetch_success_total",
    "Number of successful funding rate fetches",
    ['symbol']
)
funding_fetch_failure = Counter(
    "funding_fetch_failure_total",
    "Number of failed funding rate fetches",
    ['symbol']
)
oi_fetch_success = Counter(
    "oi_fetch_success_total",
    "Number of successful open interest fetches",
    ['symbol']
)
oi_fetch_failure = Counter(
    "oi_fetch_failure_total",
    "Number of failed open interest fetches",
    ['symbol']
)
redis_publish_errors = Counter(
    "redis_publish_errors_total",
    "Number of Redis publish errors",
    ['symbol']
)
postgres_write_errors = Counter(
    "postgres_write_errors_total",
    "Number of Postgres write errors",
    ['table']
)

# Histograms / Summaries
api_request_latency_seconds = Histogram(
    "api_request_latency_seconds",
    "API request latency in seconds",
    ['service']
)

# Gauges
stale_data_gauge = Gauge(
    "stale_data_seconds",
    "Seconds since last successful enrichment (funding/OI) per symbol",
    ['symbol']
)
application_uptime_seconds = Gauge(
    "application_uptime_seconds",
    "Seconds since application start"
)

# Simple helper to set stale data
def set_stale_seconds(symbol: str, seconds: float):
    try:
        stale_data_gauge.labels(symbol=symbol).set(seconds)
    except Exception:
        pass
