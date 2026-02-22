"""Stage 1: Audio extraction from video using FFmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from smart_subtitle.cache.manager import CacheManager
from smart_subtitle.core.config import Config
from smart_subtitle.core.exceptions import AudioExtractionError

from .base import PipelineStage


class AudioExtractionStage(PipelineStage[Path, Path]):
    """Extract audio from video file as 16kHz mono WAV."""

    @property
    def stage_name(self) -> str:
        return "Audio Extraction"

    def _cache_key(self, video_path: Path) -> str | None:
        video_hash = CacheManager.hash_file(video_path)
        return f"audio_{video_hash}"

    def _process(self, video_path: Path) -> Path:
        output_dir = self.config.cache.resolved_directory / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)

        video_hash = CacheManager.hash_file(video_path)
        output_path = output_dir / f"{video_hash}.wav"

        if output_path.exists():
            self.logger.info("Audio file already exists: %s", output_path)
            return output_path

        cfg = self.config.audio
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",
            "-acodec", cfg.codec,
            "-ar", str(cfg.sample_rate),
            "-ac", str(cfg.channels),
            "-y",
            str(output_path),
        ]

        self.logger.info("Extracting audio from %s", video_path.name)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise AudioExtractionError(f"FFmpeg failed: {e.stderr}") from e
        except FileNotFoundError:
            raise AudioExtractionError(
                "FFmpeg not found. Install it with: sudo apt install ffmpeg"
            )

        self.logger.info("Audio extracted to %s (%.1f MB)", output_path.name,
                         output_path.stat().st_size / 1024 / 1024)
        return output_path

    def _serialize(self, output: Path) -> str:
        return str(output)

    def _deserialize(self, data: str) -> Path:
        return Path(data)
