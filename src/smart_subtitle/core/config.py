"""Configuration management for smart_subtitle."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class CacheConfig(BaseModel):
    enabled: bool = True
    directory: str = "~/.cache/smart_subtitle"
    max_size_gb: float = 10.0

    @property
    def resolved_directory(self) -> Path:
        return Path(self.directory).expanduser()


class VADConfig(BaseModel):
    enabled: bool = True
    threshold: float = 0.5


class ChunkingConfig(BaseModel):
    chunk_duration: int = 600  # seconds
    overlap: int = 5  # seconds


class TranscriptionConfig(BaseModel):
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "default"
    language: str | None = None  # auto-detect if None
    batch_size: int = 16
    cpu_threads: int = 10        # threads per worker
    num_workers: int = 1         # concurrent transcription workers
    word_timestamps: bool = True
    condition_on_previous_text: bool = False
    vad: VADConfig = Field(default_factory=VADConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)


class TranslationConfig(BaseModel):
    provider: str = "ollama"  # openai, ollama, lm-studio
    base_url: str = "http://localhost:11434/v1"
    api_key: str | None = None
    model: str = "hf.co/chienweichang/Llama-3-Taiwan-8B-Instruct-GGUF:Q4_K_M"
    target_language: str = "zh-tw"
    batch_size: int = 40
    batch_overlap: int = 5
    temperature: float = 0.3
    max_tokens: int = 4096
    glossary_path: str | None = None

    def get_api_key(self) -> str:
        """Resolve API key from config or environment."""
        if self.api_key:
            return self.api_key
        env_key = os.environ.get("SMART_SUBTITLE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        return env_key or "not-needed"


class FineAlignmentConfig(BaseModel):
    text_weight: float = 0.5
    time_weight: float = 0.5
    start_offset: float = -0.1   # Visual offset before the first spoken word
    time_tolerance: float = 5.0  # seconds
    min_match_score: float = 0.3
    gap_penalty_weight: float = 0.2
    high_confidence_override: float = 0.9


class AnchorMapperConfig(BaseModel):
    window_size: int = 60
    step_size: int = 30
    min_sim_threshold: float = 0.5
    cluster_tolerance: float = 2.0
    min_cluster_score: float = 2.0
    min_unique_lines: int = 3


class AlignmentConfig(BaseModel):
    anchor_mapper: AnchorMapperConfig = Field(default_factory=AnchorMapperConfig)
    fine_alignment: FineAlignmentConfig = Field(default_factory=FineAlignmentConfig)
    global_delay: float = 0.4
    bilingual_cross_match_strategy: str = "lexical"  # 'lexical', 'timestamp', or 'none'


class OutputConfig(BaseModel):
    format: str = "srt"  # srt, ass
    language: str = "zh-tw"
    encoding: str = "utf-8"


class GapFillingConfig(BaseModel):
    enabled: bool = True
    min_gap_duration: float = 1.0  # seconds
    context_window: int = 3  # segments before/after


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    codec: str = "pcm_s16le"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str | None = None


class Config(BaseModel):
    """Main configuration model."""

    cache: CacheConfig = Field(default_factory=CacheConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    gap_filling: GapFillingConfig = Field(default_factory=GapFillingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_file(cls, path: Path) -> Config:
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    @classmethod
    def from_defaults(cls) -> Config:
        """Load default configuration."""
        default_path = Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"
        if default_path.exists():
            return cls.from_file(default_path)
        return cls()

    def merge_overrides(self, overrides: dict[str, Any]) -> Config:
        """Create new config with overrides applied."""
        data = self.model_dump()
        _deep_merge(data, overrides)
        return Config(**data)


def _deep_merge(base: dict, overrides: dict) -> None:
    """Recursively merge overrides into base dict."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
