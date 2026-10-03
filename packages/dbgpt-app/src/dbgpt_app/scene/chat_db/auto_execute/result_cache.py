"""Bounded, opt-in SQL result cache for database chat."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional


class SqlResultCache:
    """Small TTL/LRU cache that is disabled unless explicitly enabled.

    The scope is part of the key so deployments with row-level policies can
    isolate results per user.  Callers should still apply access policy before
    reading or populating the cache.
    """

    def __init__(self, ttl_seconds: float = 60.0, max_entries: int = 128):
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[tuple[str, str, str], tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()

    @classmethod
    def from_env(cls) -> "SqlResultCache":
        enabled = os.getenv("DBGPT_SQL_RESULT_CACHE", "false").casefold() == "true"
        if not enabled:
            return cls(ttl_seconds=0, max_entries=1)
        return cls(
            ttl_seconds=float(os.getenv("DBGPT_SQL_RESULT_CACHE_TTL", "60")),
            max_entries=int(os.getenv("DBGPT_SQL_RESULT_CACHE_MAX_ENTRIES", "128")),
        )

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    @staticmethod
    def _copy(value: Any) -> Any:
        if hasattr(value, "copy"):
            try:
                return value.copy(deep=True)
            except TypeError:
                return value.copy()
        return copy.deepcopy(value)

    def get(self, db_name: str, sql: str, scope: str = "") -> Optional[Any]:
        if not self.enabled:
            return None
        key = (str(scope), str(db_name), str(sql))
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            created, value = item
            if now - created > self.ttl_seconds:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return self._copy(value)

    def set(self, db_name: str, sql: str, value: Any, scope: str = "") -> None:
        if not self.enabled:
            return
        key = (str(scope), str(db_name), str(sql))
        with self._lock:
            self._items[key] = (time.monotonic(), self._copy(value))
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
