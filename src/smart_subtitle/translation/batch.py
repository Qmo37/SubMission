"""Batch translation with context windows for long videos."""

from __future__ import annotations

import logging
import re

from smart_subtitle.core.config import TranslationConfig
from smart_subtitle.core.exceptions import TranslationError
from smart_subtitle.core.models import Segment

from .client import LLMClient
from .glossary import Glossary
from .prompts import build_translation_prompt

logger = logging.getLogger("smart_subtitle.translation")

# Map language codes to display names
LANGUAGE_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ar": "Arabic",
    "zh": "Chinese",
}


def translate_segments(
    segments: list[Segment],
    source_language: str,
    config: TranslationConfig,
    glossary: Glossary | None = None,
    on_progress: callable | None = None,
) -> list[Segment]:
    """Translate all segments in batches, returning segments with .translation set.

    Args:
        segments: Whisper segments with foreign-language text
        source_language: Language code (e.g., "en", "ja")
        config: Translation configuration
        glossary: Optional glossary for consistent terms
        on_progress: Optional callback(batch_idx, total_batches)

    Returns:
        Same segments with .translation field populated
    """
    if not segments:
        return segments

    client = LLMClient(config)
    lang_name = LANGUAGE_NAMES.get(source_language, source_language)
    glossary_dict = glossary.to_dict() if glossary and not glossary.is_empty() else None

    batch_size = config.batch_size
    overlap = config.batch_overlap
    total_batches = _count_batches(len(segments), batch_size, overlap)

    translated = [None] * len(segments)
    batch_idx = 0
    start = 0

    while start < len(segments):
        end = min(start + batch_size, len(segments))
        batch = segments[start:end]

        logger.info("Translating batch %d/%d (segments %d-%d)",
                     batch_idx + 1, total_batches, start, end - 1)

        if on_progress:
            on_progress(batch_idx, total_batches)

        # Build numbered lines for this batch
        lines = [(i + start, seg.text) for i, seg in enumerate(batch)]
        system_prompt, user_prompt = build_translation_prompt(
            lines, lang_name, glossary_dict
        )

        try:
            response = client.chat(system_prompt, user_prompt)
            translations = _parse_numbered_response(response, start, end)

            # Apply translations (don't overwrite already-translated overlap segments)
            for i, seg_idx in enumerate(range(start, end)):
                if translated[seg_idx] is None:
                    translated[seg_idx] = translations.get(seg_idx, "")
        except Exception as e:
            logger.warning("Batch %d translation failed: %s. Segments left untranslated.",
                          batch_idx + 1, e)
            for seg_idx in range(start, end):
                if translated[seg_idx] is None:
                    translated[seg_idx] = ""

        # Advance with overlap
        start = end - overlap if end < len(segments) else end
        batch_idx += 1

    # Apply translations to segments
    result = []
    for seg, trans in zip(segments, translated):
        updated = seg.model_copy(update={"translation": trans or ""})
        result.append(updated)

    translated_count = sum(1 for t in translated if t)
    logger.info("Translation complete: %d/%d segments translated", translated_count, len(segments))
    return result


def _parse_numbered_response(response: str, start: int, end: int) -> dict[int, str]:
    """Parse LLM response with numbered lines like '[0] 翻譯文字'."""
    translations = {}
    # Match lines like [42] some text or 42. some text
    pattern = re.compile(r"^\s*\[?(\d+)\]?\s*[.):：]?\s*(.+)$", re.MULTILINE)
    for match in pattern.finditer(response):
        idx = int(match.group(1))
        text = match.group(2).strip()
        if start <= idx < end and text:
            translations[idx] = text

    # If numbered parsing got nothing, fall back to line-by-line
    if not translations:
        lines = [l.strip() for l in response.strip().splitlines() if l.strip()]
        for i, line in enumerate(lines):
            idx = start + i
            if idx < end:
                # Strip any leading number/bracket artifacts
                clean = re.sub(r"^\s*\[?\d+\]?\s*[.):：]?\s*", "", line).strip()
                translations[idx] = clean or line

    return translations


def _count_batches(total: int, batch_size: int, overlap: int) -> int:
    """Count how many batches are needed."""
    if total <= batch_size:
        return 1
    effective_step = batch_size - overlap
    return 1 + ((total - batch_size + effective_step - 1) // effective_step)
