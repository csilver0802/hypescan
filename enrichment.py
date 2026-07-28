# enrichment.py
"""
EnrichmentStore: async in-memory store for funding & open interest per symbol.
"""
import asyncio
import time
from typing import Dict, Optional


class EnrichmentStore:
    def __init__(self):
        self._store: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    async def set(self, symbol: str, data: Dict):
        async with self._lock:
            self._store[symbol.upper()] = {
                "funding": data.get("funding"),
                "open_interest": data.get("open_interest"),
                "src_ts": data.get("src_ts", time.time()),
                "raw": data.get("raw")
            }

    async def get(self, symbol: str) -> Optional[Dict]:
        async with self._lock:
            return self._store.get(symbol.upper())

    async def get_all(self) -> Dict[str, Dict]:
        async with self._lock:
            return dict(self._store)
