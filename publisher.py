# publisher.py
"""
Publisher: consumes ingestion queue, merges enrichment, publishes to Redis and persists to Postgres.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from typing import List, Dict, Any, Optional

import asyncpg
import aioredis

LOG = logging.getLogger("publisher")
LOG.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
LOG.addHandler(handler)


class Publisher:
    def __init__(
        self,
        queue: asyncio.Queue,
        redis_url: str,
        pg_dsn: str,
        batch_size: int = 50,
        batch_interval: float = 1.0,
        enrichment_store: Optional[Any] = None,
    ):
        self.queue = queue
        self.redis_url = redis_url
        self.pg_dsn = pg_dsn
        self.batch_size = batch_size
        self.batch_interval = batch_interval

        self._redis = None
        self._pg_pool = None
        self._stop = asyncio.Event()
        self.enrichment_store = enrichment_store

    async def start(self):
        await self._connect_redis()
        await self._connect_postgres()

    async def _connect_redis(self):
        backoff = 1.0
        while True:
            try:
                self._redis = await aioredis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
                LOG.info("Connected to Redis at %s", self.redis_url)
                return
            except Exception as e:
                LOG.warning("Redis connect failed: %s; retrying in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    async def _connect_postgres(self):
        backoff = 1.0
        while True:
            try:
                self._pg_pool = await asyncpg.create_pool(dsn=self.pg_dsn, min_size=1, max_size=10)
                LOG.info("Connected to Postgres")
                return
            except Exception as e:
                LOG.warning("Postgres connect failed: %s; retrying in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    async def stop(self):
        self._stop.set()
        if self._pg_pool:
            await self._pg_pool.close()
        if self._redis:
            await self._redis.close()

    async def run(self):
        if self._redis is None or self._pg_pool is None:
            await self.start()

        buffer: List[Dict[str, Any]] = []
        last_flush = time.time()

        while not self._stop.is_set():
            try:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.batch_interval)
                    buffer.append(item)
                    self.queue.task_done()
                except asyncio.TimeoutError:
                    item = None

                now = time.time()
                if len(buffer) >= self.batch_size or (now - last_flush) >= self.batch_interval:
                    if buffer:
                        await self._flush(buffer)
                        buffer = []
                    last_flush = now
            except asyncio.CancelledError:
                break
            except Exception as exc:
                LOG.exception("Publisher loop exception: %s", exc)
                await asyncio.sleep(1.0)

        if buffer:
            await self._flush(buffer)

    async def _flush(self, buffer: List[Dict[str, Any]]):
        # publish to redis and persist to postgres
        records = []
        for ev in buffer:
            symbol = ev.get("symbol", "unknown").upper()
            channel = f"raw:binance:{symbol}"
            # merge enrichment
            if self.enrichment_store:
                try:
                    enrichment = await self.enrichment_store.get(symbol)
                    if enrichment:
                        ev.setdefault("enrichment", {})
                        ev["enrichment"]["funding"] = enrichment.get("funding")
                        ev["enrichment"]["open_interest"] = enrichment.get("open_interest")
                        ev["enrichment"]["enrichment_ts"] = enrichment.get("src_ts")
                except Exception:
                    LOG.exception("Failed to get enrichment for %s", symbol)
            try:
                payload = json.dumps(ev, default=str)
            except Exception:
                payload = json.dumps({"symbol": symbol, "ts": ev.get("ts"), "payload_repr": str(ev)})
            try:
                await self._redis.publish(channel, payload)
            except Exception:
                LOG.exception("Failed to publish to Redis; attempting reconnect")
                await self._connect_redis()
                try:
                    await self._redis.publish(channel, payload)
                except Exception:
                    LOG.exception("Redis publish retry failed for channel %s", channel)
            rec_id = str(uuid.uuid4())
            source = ev.get("source", "binance_futures")
            received_at = ev.get("ts", time.time())
            records.append((rec_id, source, symbol, json.dumps(ev, default=str), received_at))

        insert_sql = """
            INSERT INTO raw_events (id, source, symbol, data, received_at)
            VALUES ($1, $2, $3, $4::jsonb, to_timestamp($5))
            ON CONFLICT DO NOTHING
        """
        if not self._pg_pool:
            LOG.error("No Postgres pool available; skipping DB persist")
            return
        try:
            async with self._pg_pool.acquire() as conn:
                async with conn.transaction():
                    for rec in records:
                        await conn.execute(insert_sql, *rec)
            LOG.info("Flushed %d events to Postgres and published to Redis", len(records))
        except Exception as e:
            LOG.exception("Failed to persist batch to Postgres: %s", e)
            try:
                await self._connect_postgres()
            except Exception:
                LOG.exception("Reconnect attempt failed")
