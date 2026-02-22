"""File-based cache manager for smart_subtitle."""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("smart_subtitle.cache")


class CacheManager:
    """Manage caching of expensive pipeline stage results."""

    def __init__(self, cache_dir: str | Path, enabled: bool = True, max_size_gb: float = 10.0):
        self.cache_dir = Path(cache_dir).expanduser()
        self.enabled = enabled
        self.max_size_gb = max_size_gb
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Any | None:
        """Retrieve a cached value by key."""
        if not self.enabled:
            return None
        cache_file = self._path(key)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning("Cache read failed for %s: %s", key, e)
            return None

    def set(self, key: str, value: Any) -> None:
        """Store a value in cache."""
        if not self.enabled:
            return
        cache_file = self._path(key)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "wb") as f:
                pickle.dump(value, f, protocol=pickle.HIGHEST_PROTOCOL)
            self._cleanup_if_needed()
        except Exception as e:
            logger.warning("Cache write failed for %s: %s", key, e)

    def invalidate(self, key: str) -> None:
        """Remove a cached entry."""
        cache_file = self._path(key)
        if cache_file.exists():
            cache_file.unlink()

    def clear(self) -> None:
        """Clear entire cache."""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cache cleared")

    def has(self, key: str) -> bool:
        """Check if a key exists in cache."""
        return self.enabled and self._path(key).exists()

    def _path(self, key: str) -> Path:
        """Convert cache key to file path. Uses first 2 chars as subdirectory."""
        return self.cache_dir / key[:2] / f"{key}.pkl"

    def _cleanup_if_needed(self) -> None:
        """Remove oldest files if cache exceeds size limit."""
        max_bytes = int(self.max_size_gb * 1024 * 1024 * 1024)
        files = sorted(self.cache_dir.rglob("*.pkl"), key=lambda f: f.stat().st_mtime)
        total_size = sum(f.stat().st_size for f in files)
        if total_size <= max_bytes:
            return
        for f in files:
            size = f.stat().st_size
            f.unlink()
            total_size -= size
            logger.debug("Evicted cache file: %s", f.name)
            if total_size <= max_bytes * 0.8:
                break

    @staticmethod
    def hash_file(path: Path) -> str:
        """Generate SHA-256 hash of a file's contents."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def hash_string(data: str) -> str:
        """Generate SHA-256 hash of a string."""
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def hash_dict(data: dict) -> str:
        """Generate SHA-256 hash of a dict (via sorted JSON)."""
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode()).hexdigest()
