"""Abstract base class for pipeline stages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from smart_subtitle.cache.manager import CacheManager
from smart_subtitle.core.config import Config
from smart_subtitle.utils.logger import get_logger

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class PipelineStage(ABC, Generic[InputT, OutputT]):
    """Abstract base class for pipeline stages with built-in caching."""

    def __init__(self, config: Config, cache: CacheManager):
        self.config = config
        self.cache = cache
        self.logger = get_logger(self.__class__.__name__, config.logging.level)

    @property
    @abstractmethod
    def stage_name(self) -> str:
        """Human-readable stage name."""

    @abstractmethod
    def _process(self, input_data: InputT) -> OutputT:
        """Core processing logic."""

    def _cache_key(self, input_data: InputT) -> str | None:
        """Generate cache key for input. Return None to skip caching."""
        return None

    def _serialize(self, output: OutputT) -> Any:
        """Serialize output for caching. Default: use as-is (must be picklable)."""
        return output

    def _deserialize(self, data: Any) -> OutputT:
        """Deserialize cached output."""
        return data

    def run(self, input_data: InputT, force: bool = False) -> OutputT:
        """Execute stage with caching support."""
        self.logger.info("Starting stage: %s", self.stage_name)

        # Check cache
        cache_key = self._cache_key(input_data)
        if cache_key and not force:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self.logger.info("Cache hit for %s", self.stage_name)
                return self._deserialize(cached)

        # Process
        output = self._process(input_data)

        # Store in cache
        if cache_key:
            self.cache.set(cache_key, self._serialize(output))

        self.logger.info("Completed stage: %s", self.stage_name)
        return output
