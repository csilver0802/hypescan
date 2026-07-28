# tests/test_publisher_enrichment.py
import asyncio
import json
import pytest
from publisher import Publisher
from enrichment import EnrichmentStore

class DummyRedis:
    def __init__(self):
        self.published = []
    async def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1
    async def close(self):
        pass

class DummyPool:
    async def acquire(self):
        class _C:
            async def __aenter__(self_inner): return self
            async def __aexit__(self_inner, *a): pass
        return _C()
    async def close(self): pass
    async def execute(self, *a, **k): pass

@pytest.mark.asyncio
async def test_publisher_merges_enrichment():
    q = asyncio.Queue()
    store = EnrichmentStore()
    await store.set("BTCUSDT", {"funding": -0.00012, "open_interest": 100000.0, "src_ts": 12345.0})

    pub = Publisher(queue=q, redis_url="redis://unused", pg_dsn="postgres://unused", batch_size=1, batch_interval=0.1, enrichment_store=store)
    pub._redis = DummyRedis()
    pub._pg_pool = DummyPool()

    ev = {"source": "binance_futures", "symbol": "BTCUSDT", "ts": 1.0, "top_of_book": {"best_bid": 50000, "best_ask": 50010}}
    await q.put(ev)
    task = asyncio.create_task(pub.run())
    await asyncio.sleep(0.3)
    await pub.stop()
    task.cancel()

    assert len(pub._redis.published) >= 1
    channel, payload = pub._redis.published[0]
    assert channel == "raw:binance:BTCUSDT"
    obj = json.loads(payload)
    assert "enrichment" in obj
    assert obj["enrichment"]["funding"] == pytest.approx(-0.00012)
    assert obj["enrichment"]["open_interest"] == pytest.approx(100000.0)
