# health_server.py
"""
A small aiohttp-based health and metrics HTTP server.
Exposes:
 - /health  -> JSON health
 - /metrics -> Prometheus metrics

The server can optionally probe Postgres and Redis connections, but in tests we can disable external checks.
"""
import asyncio
import json
import os
import time
from aiohttp import web
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import asyncpg
import aioredis

from status import StatusStore
import metrics

DEFAULT_PORT = int(os.getenv('METRICS_PORT', '8000'))

class HealthServer:
    def __init__(self, status_store: StatusStore, pg_dsn: str = None, redis_url: str = None, probe_external: bool = True):
        self.status_store = status_store
        self.pg_dsn = pg_dsn
        self.redis_url = redis_url
        self.probe_external = probe_external
        self._runner = None
        self._app = web.Application()
        self._app.add_routes([
            web.get('/health', self.handle_health),
            web.get('/metrics', self.handle_metrics),
        ])

    async def handle_metrics(self, request):
        data = generate_latest()
        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)

    async def handle_health(self, request):
        # Snapshot status store
        snap = await self.status_store.snapshot()
        # Optionally probe Postgres/Redis
        db_ok = snap['db_connected']
        redis_ok = snap['redis_connected']
        if self.probe_external:
            # check Postgres
            try:
                if self.pg_dsn:
                    conn = await asyncpg.connect(dsn=self.pg_dsn)
                    await conn.close()
                    db_ok = True
                else:
                    db_ok = False
            except Exception:
                db_ok = False
            # check Redis
            try:
                if self.redis_url:
                    r = await aioredis.from_url(self.redis_url)
                    pong = await r.ping()
                    await r.close()
                    redis_ok = pong is True
                else:
                    redis_ok = False
            except Exception:
                redis_ok = False
            # update status store cached flags
            await self.status_store.set_db_connected(db_ok)
            await self.status_store.set_redis_connected(redis_ok)

        uptime = time.time() - snap['start_time']
        # compute last enrichment ts in human form
        last_enrichment = snap['last_enrichment_update']
        payload = {
            'application': 'hypescan',
            'status': 'ok' if db_ok and redis_ok else 'degraded' if (db_ok or redis_ok) else 'down',
            'db_connected': db_ok,
            'redis_connected': redis_ok,
            'last_liquidation_event_ts': snap['last_liquidation_event'],
            'last_enrichment_update': last_enrichment,
            'fetcher_status': snap['fetcher_status'],
            'uptime_seconds': uptime,
        }
        return web.json_response(payload)

    async def start(self, host='0.0.0.0', port=DEFAULT_PORT):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=host, port=port)
        await site.start()

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
