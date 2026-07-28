# hyperliquid_fetcher.py
"""
HyperliquidFetcher: polls Hyperliquid /info POST endpoints to retrieve
funding rate and open interest for configured symbols and updates EnrichmentStore.
Instrumented with Prometheus metrics and StatusStore updates.
"""
import asyncio
import logging
import os
import time
from typing import List, Dict, Optional

import aiohttp

from enrichment import EnrichmentStore
from metrics import api_request_latency_seconds, funding_fetch_success, funding_fetch_failure, oi_fetch_success, oi_fetch_failure, set_stale_seconds
from status import StatusStore

LOG = logging.getLogger("hyperliquid_fetcher")
LOG.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
LOG.addHandler(handler)


class HyperliquidFetcher:
    def __init__(
        self,
        store: EnrichmentStore,
        symbols: List[str],
        status_store: StatusStore,
        base_url: str = None,
        funding_path: str = None,
        oi_path: str = None,
        poll_interval: float = 5.0,
        timeout: float = 5.0,
        retries: int = 3,
        api_key: Optional[str] = None,
    ):
        self.store = store
        self.symbols = [s.upper() for s in symbols]
        self.status_store = status_store
        self.base_url = base_url or os.getenv("HYPERLIQUID_BASE_URL", "https://api.hyperliquid.xyz")
        self.funding_path = funding_path or os.getenv("HYPERLIQUID_FUNDING_PATH", "/info")
        self.oi_path = oi_path or os.getenv("HYPERLIQUID_OI_PATH", "/info")
        self.poll_interval = float(os.getenv("HYPERLIQUID_POLL_INTERVAL", str(poll_interval)))
        self.timeout = float(os.getenv("HYPERLIQUID_TIMEOUT", str(timeout)))
        self.retries = int(os.getenv("HYPERLIQUID_RETRIES", str(retries)))
        self.api_key = api_key or os.getenv("HYPERLIQUID_API_KEY", None)

        self._session: Optional[aiohttp.ClientSession] = None
        self._stop = asyncio.Event()

    async def start(self):
        if self._session is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(headers=headers)

        tasks = []
        for s in self.symbols:
            tasks.append(asyncio.create_task(self._poll_symbol_loop(s)))
        await asyncio.gather(*tasks)

    async def stop(self):
        self._stop.set()
        if self._session:
            await self._session.close()

    async def _post_json(self, url: str, payload: dict) -> Dict:
        backoff = 0.5
        last_exc = None
        start = time.time()
        for attempt in range(1, self.retries + 1):
            try:
                async with self._session.post(url, json=payload, timeout=self.timeout) as resp:
                    resp.raise_for_status()
                    js = await resp.json()
                    latency = time.time() - start
                    api_request_latency_seconds.labels(service='hyperliquid').observe(latency)
                    return js
            except Exception as exc:
                last_exc = exc
                LOG.warning("POST failed (%s) to %s attempt=%d/%d: %s", type(exc).__name__, url, attempt, self.retries, exc)
                await asyncio.sleep(backoff)
                backoff = min(10.0, backoff * 2)
        LOG.error("All retries failed for url %s; last_exc=%s", url, last_exc)
        raise last_exc

    async def _fetch_for_symbol(self, symbol: str) -> Dict:
        fund_url = f"{self.base_url}{self.funding_path}"
        oi_url = f"{self.base_url}{self.oi_path}"

        # If using /info POST endpoint, prepare payloads
        if self.funding_path == "/info":
            fund_payload = {"type": "fundingHistory", "coin": symbol, "limit": 1}
            fund_res = await self._post_json(fund_url, fund_payload)
        else:
            async with self._session.get(fund_url.format(symbol=symbol), timeout=self.timeout) as r:
                r.raise_for_status()
                fund_res = await r.json()

        if self.oi_path == "/info":
            oi_payload = {"type": "perpMarketContext", "coin": symbol}
            oi_res = await self._post_json(oi_url, oi_payload)
        else:
            async with self._session.get(oi_url.format(symbol=symbol), timeout=self.timeout) as r:
                r.raise_for_status()
                oi_res = await r.json()

        funding = None
        open_interest = None

        # map common keys
        try:
            if isinstance(fund_res, dict):
                if "funding_rate" in fund_res:
                    funding = fund_res.get("funding_rate")
                elif isinstance(fund_res.get("data"), list) and len(fund_res.get("data")) > 0:
                    entry = fund_res.get("data")[0]
                    funding = entry.get("funding_rate") or entry.get("funding")
                else:
                    funding = fund_res.get("funding_rate") or fund_res.get("funding")
        except Exception:
            LOG.exception("Error parsing funding response for %s", symbol)

        try:
            if isinstance(oi_res, dict):
                open_interest = oi_res.get("open_interest") or oi_res.get("oi") or oi_res.get("openInterest")
                if open_interest is None and isinstance(oi_res.get("data"), dict):
                    open_interest = oi_res.get("data").get("open_interest")
        except Exception:
            LOG.exception("Error parsing oi response for %s", symbol)

        return {"funding": funding, "open_interest": open_interest, "raw": {"funding": fund_res, "open_interest": oi_res}}

    async def _poll_symbol_loop(self, symbol: str):
        LOG.info("Starting Hyperliquid fetcher for %s (interval=%.1fs)", symbol, self.poll_interval)
        while not self._stop.is_set():
            start = time.time()
            try:
                data = await self._fetch_for_symbol(symbol)
                data["src_ts"] = time.time()
                normalized = {
                    "funding": float(data["funding"]) if data.get("funding") is not None else None,
                    "open_interest": float(data["open_interest"]) if data.get("open_interest") is not None else None,
                    "src_ts": data["src_ts"],
                    "raw": data.get("raw")
                }
                # Update enrichment store
                await self.store.set(symbol, normalized)

                # Metrics: success counters
                if normalized.get("funding") is not None:
                    funding_fetch_success.labels(symbol=symbol).inc()
                else:
                    funding_fetch_failure.labels(symbol=symbol).inc()

                if normalized.get("open_interest") is not None:
                    oi_fetch_success.labels(symbol=symbol).inc()
                else:
                    oi_fetch_failure.labels(symbol=symbol).inc()

                # Update status store
                await self.status_store.set_enrichment(symbol, normalized["src_ts"])

                # Reset stale gauge for symbol
                set_stale_seconds(symbol, 0.0)

                LOG.debug("Updated enrichment for %s: funding=%s oi=%s", symbol, normalized["funding"], normalized["open_interest"])
            except Exception as exc:
                LOG.exception("Exception while fetching enrichment for %s: %s", symbol, exc)
                # Metrics: failure
                funding_fetch_failure.labels(symbol=symbol).inc()
                oi_fetch_failure.labels(symbol=symbol).inc()
                await self.status_store.set_fetcher_error(symbol, time.time())
            elapsed = time.time() - start
            to_sleep = max(0.0, self.poll_interval - elapsed)
            await asyncio.sleep(to_sleep)
