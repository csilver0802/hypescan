# main_runner.py
"""
Start ingestor + hyperliquid fetcher + publisher
"""
import asyncio
import os
import logging
from binance_ingestor import BinanceL2Ingestor
from publisher import Publisher
from enrichment import EnrichmentStore
from hyperliquid_fetcher import HyperliquidFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger("main")

async def main():
    q = asyncio.Queue(maxsize=20000)
    symbol = os.getenv("SYMBOL", "BTCUSDT")
    depth_limit = int(os.getenv("DEPTH_LIMIT", "200"))

    enrichment_store = EnrichmentStore()

    symbols_env = os.getenv("HYPERLIQUID_SYMBOLS", symbol)
    hl_symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]

    hyper = HyperliquidFetcher(
        store=enrichment_store,
        symbols=hl_symbols,
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
    )

    await publisher.start()
    tasks = [
        asyncio.create_task(ingestor.run()),
        asyncio.create_task(publisher.run()),
        asyncio.create_task(hyper.start()),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        LOG.info("Shutting down main")
    finally:
        await ingestor.stop()
        await hyper.stop()
        await publisher.stop()

if __name__ == "__main__":
    asyncio.run(main())
