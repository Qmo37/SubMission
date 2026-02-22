"""Stage 2: Speech transcription using faster-whisper with Silero VAD."""

from __future__ import annotations

import subprocess
from pathlib import Path

from smart_subtitle.cache.manager import CacheManager
from smart_subtitle.core.config import Config
from smart_subtitle.core.exceptions import TranscriptionError
from smart_subtitle.core.models import ReferenceTranscript, Segment, TimeSpan

from .base import PipelineStage


class TranscriptionStage(PipelineStage[Path, ReferenceTranscript]):
    """Transcribe audio using faster-whisper with VAD and chunking."""

    @property
    def stage_name(self) -> str:
        return "Transcription"

    def _cache_key(self, audio_path: Path) -> str | None:
        audio_hash = CacheManager.hash_file(audio_path)
        model = self.config.transcription.model
        lang = self.config.transcription.language or "auto"
        return f"whisper_{audio_hash}_{model}_{lang}"

    def _serialize(self, output: ReferenceTranscript) -> dict:
        return output.model_dump()

    def _deserialize(self, data: dict) -> ReferenceTranscript:
        return ReferenceTranscript(**data)

    def _process(self, audio_path: Path) -> ReferenceTranscript:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise TranscriptionError(
                "faster-whisper not installed. Install with: pip install faster-whisper"
            )

        cfg = self.config.transcription
        audio_hash = CacheManager.hash_file(audio_path)
        audio_duration = self._get_duration(audio_path)
        chunk_cfg = cfg.chunking

        # Decide whether to chunk
        if chunk_cfg.chunk_duration > 0 and audio_duration > chunk_cfg.chunk_duration:
            return self._transcribe_chunked(audio_path, audio_hash, audio_duration)

        return self._transcribe_single(audio_path, audio_hash)

    def _transcribe_single(self, audio_path: Path, audio_hash: str) -> ReferenceTranscript:
        from faster_whisper import WhisperModel

        cfg = self.config.transcription
        device = cfg.device if cfg.device != "auto" else None

        self.logger.info("Loading Whisper model: %s (threads=%d, workers=%d)", 
                         cfg.model, cfg.cpu_threads, cfg.num_workers)
        
        model = WhisperModel(
            cfg.model,
            device=device or "auto",
            compute_type=cfg.compute_type,
            cpu_threads=cfg.cpu_threads,
            num_workers=cfg.num_workers,
        )

        self.logger.info("Transcribing %s", audio_path.name)
        kwargs = {
            "vad_filter": cfg.vad.enabled,
            "word_timestamps": cfg.word_timestamps,
            "condition_on_previous_text": cfg.condition_on_previous_text,
        }
        if cfg.vad.enabled:
            kwargs["vad_parameters"] = {"threshold": cfg.vad.threshold}
        if cfg.language:
            kwargs["language"] = cfg.language

        segments_gen, info = model.transcribe(str(audio_path), **kwargs)

        segments = []
        for idx, seg in enumerate(segments_gen):
            if seg.words:
                start = seg.words[0].start
                end = seg.words[-1].end
            else:
                start = seg.start
                end = seg.end

            segments.append(Segment(
                id=idx,
                text=seg.text.strip(),
                timespan=TimeSpan(start=start, end=end),
                confidence=seg.avg_logprob,
                language=info.language,
            ))
            if (idx + 1) % 50 == 0:
                self.logger.info("  Transcribed %d segments so far (latest: %.1fs)", idx + 1, end)

        self.logger.info(
            "Transcribed %d segments, detected language: %s", len(segments), info.language
        )

        return ReferenceTranscript(
            segments=segments,
            language=info.language,
            model=cfg.model,
            audio_hash=audio_hash,
        )

    def _transcribe_chunked(
        self, audio_path: Path, audio_hash: str, total_duration: float
    ) -> ReferenceTranscript:
        """Transcribe long audio in chunks with overlap."""
        from faster_whisper import WhisperModel

        cfg = self.config.transcription
        chunk_dur = cfg.chunking.chunk_duration
        overlap = cfg.chunking.overlap
        device = cfg.device if cfg.device != "auto" else None

        self.logger.info("Loading Whisper model: %s (threads=%d, workers=%d)", 
                         cfg.model, cfg.cpu_threads, cfg.num_workers)
        
        model = WhisperModel(
            cfg.model,
            device=device or "auto",
            compute_type=cfg.compute_type,
            cpu_threads=cfg.cpu_threads,
            num_workers=cfg.num_workers,
        )

        all_segments: list[Segment] = []
        segment_id = 0
        chunk_start = 0.0

        while chunk_start < total_duration:
            chunk_end = min(chunk_start + chunk_dur, total_duration)
            self.logger.info(
                "Transcribing chunk: %.1fs - %.1fs / %.1fs",
                chunk_start, chunk_end, total_duration,
            )

            # Extract chunk audio
            chunk_path = self._extract_chunk(audio_path, chunk_start, chunk_end)

            kwargs = {
                "vad_filter": cfg.vad.enabled,
                "word_timestamps": cfg.word_timestamps,
                "condition_on_previous_text": cfg.condition_on_previous_text,
            }
            if cfg.vad.enabled:
                kwargs["vad_parameters"] = {"threshold": cfg.vad.threshold}
            if cfg.language:
                kwargs["language"] = cfg.language

            segments_gen, info = model.transcribe(str(chunk_path), **kwargs)

            chunk_seg_count = 0
            for seg in segments_gen:
                if seg.words:
                    start = seg.words[0].start
                    end = seg.words[-1].end
                else:
                    start = seg.start
                    end = seg.end

                # Adjust timestamps to global time
                global_start = start + chunk_start
                global_end = end + chunk_start

                # Skip segments in overlap region that were already captured
                if all_segments and global_start < all_segments[-1].timespan.end - 0.5:
                    continue

                all_segments.append(Segment(
                    id=segment_id,
                    text=seg.text.strip(),
                    timespan=TimeSpan(start=global_start, end=global_end),
                    confidence=seg.avg_logprob,
                    language=info.language,
                ))
                segment_id += 1
                chunk_seg_count += 1
                if chunk_seg_count % 50 == 0:
                    self.logger.info(
                        "  Chunk %.0fs-%.0fs: %d segments so far (at %.1fs)",
                        chunk_start, chunk_end, chunk_seg_count, global_end,
                    )

            # Clean up chunk file
            chunk_path.unlink(missing_ok=True)

            if chunk_end >= total_duration:
                break

            # Next chunk starts before current chunk ends (overlap)
            chunk_start = chunk_end - overlap

        detected_lang = info.language if all_segments else "unknown"
        self.logger.info("Transcribed %d segments total across all chunks", len(all_segments))

        return ReferenceTranscript(
            segments=all_segments,
            language=detected_lang,
            model=cfg.model,
            audio_hash=audio_hash,
        )

    def _extract_chunk(self, audio_path: Path, start: float, end: float) -> Path:
        """Extract a time-bounded chunk from audio file."""
        chunk_dir = self.config.cache.resolved_directory / "chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_path = chunk_dir / f"chunk_{start:.0f}_{end:.0f}.wav"

        cmd = [
            "ffmpeg",
            "-i", str(audio_path),
            "-ss", str(start),
            "-to", str(end),
            "-acodec", self.config.audio.codec,
            "-ar", str(self.config.audio.sample_rate),
            "-ac", str(self.config.audio.channels),
            "-y",
            str(chunk_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return chunk_path

    def _get_duration(self, audio_path: Path) -> float:
        """Get audio duration in seconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            self.logger.warning("Could not determine audio duration, processing as single file")
            return 0.0
