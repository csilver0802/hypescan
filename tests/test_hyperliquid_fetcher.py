# tests/test_hyperliquid_fetcher.py
import asyncio
import pytest
from aioresponses import aioresponses
from enrichment import EnrichmentStore
from hyperliquid_fetcher import HyperliquidFetcher

@pytest.mark.asyncio
async def test_hyperliquid_fetcher_updates_store():
    store = EnrichmentStore()
    base_url = "https://api.test"
    symbol = "BTC"
    funding_path = "/info"
    oi_path = "/info"

    fetcher = HyperliquidFetcher(store=store, symbols=[symbol], base_url=base_url, funding_path=funding_path, oi_path=oi_path, poll_interval=0.1, retries=1, timeout=1)

    fund_url = f"{base_url}{funding_path}"
    oi_url = f"{base_url}{oi_path}"

    with aioresponses() as m:
        # for /info POST, return expected structures
        m.post(fund_url, payload={"data": [{"funding_rate": -0.00012}]})
        m.post(oi_url, payload={"data": {"open_interest": 123456.0}})

        task = asyncio.create_task(fetcher._poll_symbol_loop(symbol))
        await asyncio.sleep(0.25)
        await fetcher.stop()
        task.cancel()

        enrichment = await store.get(symbol)
        assert enrichment is not None
        assert enrichment["funding"] == pytest.approx(-0.00012)
        assert enrichment["open_interest"] == pytest.approx(123456.0)
