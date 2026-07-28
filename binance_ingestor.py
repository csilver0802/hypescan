# binance_ingestor.py
"""
Binance L2 ingestion (snapshot + diff) simplified for the project.
Publishes normalized events to an asyncio.Queue.
"""
import asyncio
import aiohttp
import logging
import math
import os
import signal
import time
from typing import Dict, List, Tuple, Optional

LOG = logging.getLogger("binance_ingestor")
LOG.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
LOG.addHandler(handler)


class OrderBook:
    def __init__(self, depth_limit: int = 100):
        self.depth_limit = depth_limit
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_update_id: Optional[int] = None

    @staticmethod
    def _to_price_qty(pair):
        p = float(pair[0])
        q = float(pair[1])
        return p, q

    def apply_snapshot(self, snapshot: Dict):
        self.bids = {}
        self.asks = {}
        for b in snapshot.get("bids", []):
            p, q = self._to_price_qty(b)
            if q > 0:
                self.bids[p] = q
        for a in snapshot.get("asks", []):
            p, q = self._to_price_qty(a)
            if q > 0:
                self.asks[p] = q
        self.last_update_id = int(snapshot.get("lastUpdateId"))
        LOG.debug("Snapshot applied: lastUpdateId=%s bids=%d asks=%d", self.last_update_id, len(self.bids), len(self.asks))

    def apply_diff(self, diff: Dict) -> bool:
        if self.last_update_id is None:
            LOG.warning("No snapshot applied before diff; cannot apply")
            return False

        U = int(diff.get("U"))
        u = int(diff.get("u"))

        if self.last_update_id >= u:
            LOG.debug("Dropping old diff: snapshot_last=%s event_u=%s", self.last_update_id, u)
            return True

        if self.last_update_id < U - 1:
            LOG.warning("Out-of-sync: snapshot_last=%s event_U=%s -> resync needed", self.last_update_id, U)
            return False

        for b in diff.get("b", []):
            price, qty = self._to_price_qty(b)
            if qty == 0.0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty

        for a in diff.get("a", []):
            price, qty = self._to_price_qty(a)
            if qty == 0.0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty

        if len(self.bids) > self.depth_limit:
            top_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[: self.depth_limit]
            self.bids = dict(top_bids)
        if len(self.asks) > self.depth_limit:
            top_asks = sorted(self.asks.items(), key=lambda x: x[0])[: self.depth_limit]
            self.asks = dict(top_asks)

        self.last_update_id = u
        LOG.debug("Applied diff: new_lastUpdateId=%s bids=%d asks=%d", self.last_update_id, len(self.bids), len(self.asks))
        return True

    def top_of_book(self) -> Dict:
        best_bid_price = max(self.bids.keys()) if self.bids else 0.0
        best_ask_price = min(self.asks.keys()) if self.asks else 0.0
        return {
            "best_bid": best_bid_price,
            "best_bid_size": self.bids.get(best_bid_price, 0.0),
            "best_ask": best_ask_price,
            "best_ask_size": self.asks.get(best_ask_price, 0.0)
        }

    def aggregate_depth(self, levels: int = 5) -> Dict:
        top_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:levels]
        top_asks = sorted(self.asks.items(), key=lambda x: x[0])[:levels]
        return {"bids": top_bids, "asks": top_asks}


class BinanceL2Ingestor:
    BASE_REST = "https://fapi.binance.com"
    WS_BASE = "wss://fstream.binance.com/ws"

    def __init__(self, symbol: str, out_q: asyncio.Queue, depth_limit: int = 200):
        self.symbol = symbol.upper()
        self.symbol_lower = symbol.lower()
        self.depth_limit = depth_limit
        self.orderbook = OrderBook(depth_limit=depth_limit)
        self.out_q = out_q
        self.session = aiohttp.ClientSession()
        self._stop = asyncio.Event()
        self._health = {"last_snapshot": None, "last_diff": None, "synced": False, "retries": 0}

    async def fetch_snapshot(self) -> Dict:
        url = f"{self.BASE_REST}/fapi/v1/depth"
        params = {"symbol": self.symbol, "limit": self.depth_limit}
        async with self.session.get(url, params=params, timeout=10) as resp:
            resp.raise_for_status()
            j = await resp.json()
            LOG.info("Fetched REST snapshot for %s lastUpdateId=%s", self.symbol, j.get("lastUpdateId"))
            self._health["last_snapshot"] = time.time()
            return j

    def _ws_url(self) -> str:
        return f"{self.WS_BASE}/{self.symbol_lower}@depth@100ms"

    async def _connect_ws(self):
        url = self._ws_url()
        LOG.info("Connecting WS %s", url)
        return await self.session.ws_connect(url, heartbeat=30, autoping=True)

    async def _publish(self, payload: Dict):
        try:
            await self.out_q.put(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Failed to publish payload")

    async def run(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                snapshot = await self.fetch_snapshot()
                self.orderbook.apply_snapshot(snapshot)
                self._health["synced"] = True
                async with await self._connect_ws() as ws:
                    LOG.info("WS connected for %s", self.symbol)
                    backoff = 1.0
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            if isinstance(data, dict) and "data" in data:
                                payload = data["data"]
                            else:
                                payload = data
                            if "e" in payload and payload.get("e") != "depthUpdate":
                                continue
                            if not all(k in payload for k in ("U", "u", "b", "a")):
                                LOG.debug("Unexpected payload (missing fields): %s", payload)
                                continue
                            ok = self.orderbook.apply_diff(payload)
                            self._health["last_diff"] = time.time()
                            if not ok:
                                LOG.info("Resync required for %s. Fetching new snapshot.", self.symbol)
                                snapshot = await self.fetch_snapshot()
                                self.orderbook.apply_snapshot(snapshot)
                                continue
                            tob = self.orderbook.top_of_book()
                            agg = self.orderbook.aggregate_depth(levels=10)
                            event = {
                                "source": "binance_futures",
                                "symbol": self.symbol,
                                "ts": time.time(),
                                "top_of_book": tob,
                                "agg_depth": {"bids": agg["bids"], "asks": agg["asks"]},
                                "lastUpdateId": self.orderbook.last_update_id,
                                "health": dict(self._health)
                            }
                            await self._publish(event)
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            LOG.warning("WS closed for %s", self.symbol)
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            LOG.error("WS error for %s: %s", self.symbol, msg)
                            break
            except asyncio.CancelledError:
                LOG.info("Run cancelled")
                break
            except Exception as exc:
                LOG.exception("Exception in run loop: %s", exc)
                self._health["synced"] = False
                self._health["retries"] = self._health.get("retries", 0) + 1
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)
                continue

    async def stop(self):
        self._stop.set()
        try:
            await self.session.close()
        except Exception:
            pass


# Example consumer
async def example_consumer(q: asyncio.Queue):
    while True:
        msg = await q.get()
        print("INGESTED:", msg["symbol"], "topbid=", msg["top_of_book"]["best_bid"], "topask=", msg["top_of_book"]["best_ask"])
        q.task_done()


async def _main():
    q = asyncio.Queue()
    ingestor = BinanceL2Ingestor(symbol=os.getenv("SYMBOL", "BTCUSDT"), out_q=q, depth_limit=int(os.getenv("DEPTH_LIMIT", "200")))
    producer_task = asyncio.create_task(ingestor.run())
    consumer_task = asyncio.create_task(example_consumer(q))
    await asyncio.gather(producer_task, consumer_task)

if __name__ == "__main__":
    asyncio.run(_main())
