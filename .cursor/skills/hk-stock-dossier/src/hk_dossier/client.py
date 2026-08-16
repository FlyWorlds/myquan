"""Pandadata client helper — handles authentication, caching, and provides a clean API wrapper."""

import os
import time
import threading
import logging
from typing import Any
from pathlib import Path

import panda_data
from dotenv import load_dotenv

# Load .env from project root (parent of src/)
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

# Default cache TTL: 5 minutes
_DEFAULT_TTL = 300


class PandadataClient:
    """Thin wrapper around panda_data that auto-initializes on first use.

    Features:
      - Lazy authentication (initialized on first API call, thread-safe)
      - In-memory TTL cache to avoid redundant API calls
      - Credentials from env vars or constructor args
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        cache_ttl: int = _DEFAULT_TTL,
    ):
        self._username = username or os.environ.get("DEFAULT_USERNAME")
        self._password = password or os.environ.get("DEFAULT_PASSWORD")
        self._base_url = os.environ.get(
            "JAVA_SERVICE_BASE_URL", "http://pandadata.pandaaiquant.com"
        )
        self._initialized = False
        self._init_lock = threading.Lock()
        # Cache: {cache_key: (timestamp, result)}
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = cache_ttl

    def ensure_init(self):
        """Initialize the Pandadata SDK if not already done (thread-safe)."""
        if self._initialized:
            return
        with self._init_lock:
            # Double-check after acquiring lock
            if self._initialized:
                return
            if not self._username or not self._password:
                raise RuntimeError(
                    "Pandadata credentials not configured. "
                    "Set DEFAULT_USERNAME / DEFAULT_PASSWORD env vars "
                    "or pass username/password to PandadataClient()."
                )
            panda_data.init_token(
                username=self._username,
                password=self._password,
                base_url=self._base_url,
            )
            self._initialized = True
            logger.info("Pandadata SDK initialized")

    def call(self, method: str, **kwargs) -> Any:
        """Call a panda_data.get_* method safely.

        Results are cached with TTL to avoid redundant API calls.

        Usage:
            client.call("get_hk_detail", symbol=["0700.HK"])
        """
        # Build cache key from method + sorted kwargs
        cache_key = self._build_cache_key(method, kwargs)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s", cache_key)
            return cached

        self.ensure_init()
        func = getattr(panda_data, method, None)
        if func is None:
            raise ValueError(f"Unknown Pandadata method: {method}")
        logger.debug("Calling %s with kwargs=%s", method, kwargs)
        try:
            result = func(**kwargs)
            self._set_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error("Pandadata call %s failed: %s", method, e)
            raise

    def clear_cache(self):
        """Clear all cached results."""
        self._cache.clear()
        logger.debug("Cache cleared")

    def _build_cache_key(self, method: str, kwargs: dict) -> str:
        """Build a deterministic cache key from method name and arguments."""
        items = sorted(kwargs.items(), key=lambda x: x[0])
        args_str = ",".join(f"{k}={v}" for k, v in items)
        return f"{method}({args_str})"

    def _get_from_cache(self, key: str) -> Any | None:
        """Get cached result if it exists and hasn't expired."""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            timestamp, result = entry
            if time.time() - timestamp > self._cache_ttl:
                del self._cache[key]
                return None
            return result

    def _set_cache(self, key: str, result: Any):
        """Store result in cache with current timestamp."""
        with self._cache_lock:
            self._cache[key] = (time.time(), result)
