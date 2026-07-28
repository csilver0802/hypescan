# status.py
"""
In-memory status store for health endpoint and coordination.
"""
import asyncio
import time
from typing import Dict, Optional

class StatusStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.start_time = time.time()
        self.last_liquidation_event: Optional[float] = None
        self.last_enrichment_update: Dict[str, float] = {}  # symbol -> ts
        self.fetcher_status: Dict[str, Dict] = {}  # symbol -> {ok:bool, last_ok:ts, last_error:ts}
        self.db_connected: Optional[bool] = None
        self.redis_connected: Optional[bool] = None

    async def set_last_liquidation_event(self, ts: float):
        async with self._lock:
            self.last_liquidation_event = ts

    async def set_enrichment(self, symbol: str, ts: float):
        async with self._lock:
            self.last_enrichment_update[symbol.upper()] = ts
            self.fetcher_status.setdefault(symbol.upper(), {})['last_ok'] = ts
            self.fetcher_status[symbol.upper()]['ok'] = True

    async def set_fetcher_error(self, symbol: str, ts: float):
        async with self._lock:
            self.fetcher_status.setdefault(symbol.upper(), {})['last_error'] = ts
            self.fetcher_status[symbol.upper()]['ok'] = False

    async def set_db_connected(self, ok: bool):
        async with self._lock:
            self.db_connected = ok

    async def set_redis_connected(self, ok: bool):
        async with self._lock:
            self.redis_connected = ok

    async def snapshot(self):
        async with self._lock:
            return {
                'start_time': self.start_time,
                'last_liquidation_event': self.last_liquidation_event,
                'last_enrichment_update': dict(self.last_enrichment_update),
                'fetcher_status': dict(self.fetcher_status),
                'db_connected': self.db_connected,
                'redis_connected': self.redis_connected,
            }
