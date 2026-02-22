"""Stage 3: Reference translation of Whisper output to Traditional Chinese."""

from __future__ import annotations

from pathlib import Path

from smart_subtitle.cache.manager import CacheManager
from smart_subtitle.core.models import ReferenceTranscript
from smart_subtitle.translation.batch import translate_segments
from smart_subtitle.translation.glossary import Glossary

from .base import PipelineStage


class ReferenceTranslationStage(PipelineStage[ReferenceTranscript, ReferenceTranscript]):
    """Translate Whisper's foreign-language transcription to Traditional Chinese (Taiwan).

    This reference translation is used for:
    - Fine alignment (comparing Chinese subtitle lines to Chinese reference)
    - Gap filling (as a fallback translation)

    It is NOT the final output — user-provided subtitles take priority.
    """

    @property
    def stage_name(self) -> str:
        return "Reference Translation"

    def _cache_key(self, transcript: ReferenceTranscript) -> str | None:
        # Cache by transcript content hash + LLM model
        text_hash = CacheManager.hash_string(
            "|".join(s.text for s in transcript.segments)
        )
        model = self.config.translation.model
        return f"reftrans_{text_hash}_{CacheManager.hash_string(model)}"

    def _serialize(self, output: ReferenceTranscript) -> dict:
        return output.model_dump()

    def _deserialize(self, data: dict) -> ReferenceTranscript:
        return ReferenceTranscript(**data)

    def _process(self, transcript: ReferenceTranscript) -> ReferenceTranscript:
        cfg = self.config.translation

        # Load glossary if configured
        glossary = None
        if cfg.glossary_path:
            glossary_path = Path(cfg.glossary_path)
            if glossary_path.exists():
                glossary = Glossary.from_file(glossary_path)
                self.logger.info("Loaded glossary with %d entries", len(glossary.entries))

        # Skip translation if source is already Chinese
        if transcript.language.startswith("zh"):
            self.logger.info("Source is already Chinese, skipping reference translation")
            # Just copy text to translation field
            segments = [
                seg.model_copy(update={"translation": seg.text})
                for seg in transcript.segments
            ]
            return transcript.model_copy(update={"segments": segments})

        self.logger.info(
            "Translating %d segments from %s to Traditional Chinese (Taiwan)",
            len(transcript.segments), transcript.language,
        )

        translated_segments = translate_segments(
            segments=transcript.segments,
            source_language=transcript.language,
            config=cfg,
            glossary=glossary,
        )

        return transcript.model_copy(update={"segments": translated_segments})
