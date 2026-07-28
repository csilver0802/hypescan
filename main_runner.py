# main_runner.py
"""
Start ingestor + hyperliquid fetcher + publisher + health server
"""
import asyncio
import os
import logging
import time
from binance_ingestor import BinanceL2Ingestor
from publisher import Publisher
from enrichment import EnrichmentStore
from hyperliquid_fetcher import HyperliquidFetcher
from status import StatusStore
from health_server import HealthServer
import metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger("main")

async def stale_updater(status_store: StatusStore, poll_interval: float = 5.0):
    """Background task that updates stale_data_gauge for each known symbol.
    stale_data_gauge is set to seconds since last enrichment update.
    """
    from metrics import stale_data_gauge, application_uptime_seconds
    while True:
        snap = await status_store.snapshot()
        now = time.time()
        for sym, ts in snap['last_enrichment_update'].items():
            age = now - ts if ts else float('inf')
            try:
                stale_data_gauge.labels(symbol=sym).set(age)
            except Exception:
                pass
        # update uptime gauge
        try:
            application_uptime_seconds.set(now - snap['start_time'])
        except Exception:
            pass
        await asyncio.sleep(poll_interval)

async def main():
    q = asyncio.Queue(maxsize=20000)
    symbol = os.getenv("SYMBOL", "BTCUSDT")
    depth_limit = int(os.getenv("DEPTH_LIMIT", "200"))

    enrichment_store = EnrichmentStore()
    status_store = StatusStore()

    symbols_env = os.getenv("HYPERLIQUID_SYMBOLS", symbol)
    hl_symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]

    hyper = HyperliquidFetcher(
        store=enrichment_store,
        symbols=hl_symbols,
        status_store=status_store,
        base_url=os.getenv("HYPERLIQUID_BASE_URL", None),
        funding_path=os.getenv("HYPERLIQUID_FUNDING_PATH", None),
        oi_path=os.getenv("HYPERLIQUID_OI_PATH", None),
        poll_interval=float(os.getenv("HYPERLIQUID_POLL_INTERVAL", "5")),
        timeout=float(os.getenv("HYPERLIQUID_TIMEOUT", "5")),
        retries=int(os.getenv("HYPERLIQUID_RETRIES", "3")),
    )

    ingestor = BinanceL2Ingestor(symbol=symbol, out_q=q, depth_limit=depth_limit)
    publisher = Publisher(
        queue=q,
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        pg_dsn=os.getenv("POSTGRES_DSN", "postgresql://postgres:postgres@postgres:5432/liquidation"),
        batch_size=int(os.getenv("PUBLISH_BATCH_SIZE", "50")),
        batch_interval=float(os.getenv("PUBLISH_BATCH_INTERVAL", "1.0")),
        enrichment_store=enrichment_store,
        status_store=status_store,
    )

    # Health server
    health = HealthServer(status_store=status_store, pg_dsn=os.getenv('POSTGRES_DSN'), redis_url=os.getenv('REDIS_URL'))

    await publisher.start()

    tasks = [
        asyncio.create_task(ingestor.run()),
        asyncio.create_task(publisher.run()),
        asyncio.create_task(hyper.start()),
    ]

    # start health server
    await health.start(host='0.0.0.0', port=int(os.getenv('METRICS_PORT', '8000')))
    LOG.info("Health server started on port %s", os.getenv('METRICS_PORT', '8000'))

    # start stale updater
    stale_task = asyncio.create_task(stale_updater(status_store, poll_interval=5.0))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        LOG.info("Shutting down main")
    finally:
        await ingestor.stop()
        await hyper.stop()
        await publisher.stop()
        stale_task.cancel()
        await health.stop()

if __name__ == "__main__":
    asyncio.run(main())
