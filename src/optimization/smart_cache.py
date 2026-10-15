"""TTL cache with optional Redis and bounded process-local fallback."""

from __future__ import annotations

import hashlib
import copy
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)


class SmartCache:
    """Cache verified responses by query, profile, intent and evidence signature."""

    def __init__(self, redis_client: Any = None, ttl: int = 3600, maxsize: int = 100) -> None:
        self.ttl = ttl
        self.maxsize = maxsize
        self._local: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self.redis = redis_client
        self.hits = 0
        self.misses = 0
        if self.redis is None and os.getenv("CACHE_BACKEND") == "redis":
            try:
                import redis

                self.redis = redis.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", "6379")), socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                )
                self.redis.ping()
            except Exception:
                logger.warning("Redis unavailable; using process-local cache")
                self.redis = None

    @staticmethod
    def key(*parts: Any) -> str:
        """Avoid storing raw personal text as a Redis key."""
        payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
        return "beauty:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any:
        """Get non-expired value; record cache statistics."""
        with self._lock:
            if self.redis is not None:
                try:
                    raw = self.redis.get(key)
                    value = json.loads(raw) if raw else None
                except Exception:
                    logger.warning("Redis read failed; using local cache")
                    expires, value = self._local.get(key, (0, None))
                    if expires <= time.time():
                        value = None
                        self._local.pop(key, None)
            else:
                expires, value = self._local.get(key, (0, None))
                if expires <= time.time():
                    value = None
                    self._local.pop(key, None)
                elif value is not None:
                    self._local.move_to_end(key)
            self.hits += value is not None
            self.misses += value is None
            return copy.deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        """Store value with expiry; local fallback is bounded."""
        with self._lock:
            if self.redis is not None:
                try:
                    self.redis.setex(key, self.ttl, json.dumps(value, ensure_ascii=False))
                except Exception:
                    logger.warning("Redis write failed; using local cache")
            self._local[key] = (time.time() + self.ttl, copy.deepcopy(value))
            self._local.move_to_end(key)
            while len(self._local) > self.maxsize:
                self._local.popitem(last=False)

    def stats(self) -> dict:
        """Return observed hit rate; do not claim target rates before measuring."""
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses,
                "hit_rate": self.hits / total if total else 0}
