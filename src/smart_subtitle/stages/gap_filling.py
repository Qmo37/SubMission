"""Stage 7: Fill gaps using LLM translation with context awareness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smart_subtitle.cache.manager import CacheManager
from smart_subtitle.core.models import (
    CompleteSubtitle,
    Gap,
    MergedSubtitle,
    Segment,
)
from smart_subtitle.translation.client import LLMClient
from smart_subtitle.translation.glossary import Glossary
from smart_subtitle.translation.prompts import build_gap_filling_prompt

from .base import PipelineStage


@dataclass
class GapFillingInput:
    merged: MergedSubtitle
    source_language: str


class GapFillingStage(PipelineStage[GapFillingInput, CompleteSubtitle]):
    """Fill gaps in subtitle coverage using LLM translation.

    For each gap:
    1. Build context from surrounding translated segments
    2. Include Whisper's original foreign-language text as a hint
    3. Ask LLM to generate appropriate Traditional Chinese translation
    """

    @property
    def stage_name(self) -> str:
        return "Gap Filling"

    def _process(self, input_data: GapFillingInput) -> CompleteSubtitle:
        merged = input_data.merged
        source_language = input_data.source_language

        if not merged.gaps:
            self.logger.info("No gaps to fill")
            return CompleteSubtitle(
                segments=merged.segments,
                filled_gaps=[],
                total_coverage=merged.coverage,
            )

        cfg = self.config.translation
        client = LLMClient(cfg)

        # Load glossary
        glossary = None
        if cfg.glossary_path:
            glossary_path = Path(cfg.glossary_path)
            if glossary_path.exists():
                glossary = Glossary.from_file(glossary_path)
        glossary_dict = glossary.to_dict() if glossary and not glossary.is_empty() else None

        filled_gaps = []
        segments_by_id = {s.id: s for s in merged.segments}

        for i, gap in enumerate(merged.gaps):
            self.logger.info(
                "Filling gap %d/%d: %.1fs - %.1fs (%.1fs)",
                i + 1,
                len(merged.gaps),
                gap.timespan.start,
                gap.timespan.end,
                gap.timespan.duration,
            )

            # Build context
            context_before = [
                f"[{s.timespan.start:.1f}s] {s.translation}"
                for s in gap.context_before
                if s.translation
            ]
            context_after = [
                f"[{s.timespan.start:.1f}s] {s.translation}"
                for s in gap.context_after
                if s.translation
            ]

            # Combine Whisper text for the gap
            whisper_text = " ".join(s.text for s in gap.whisper_segments)

            system_prompt, user_prompt = build_gap_filling_prompt(
                whisper_text=whisper_text,
                source_language=source_language,
                duration=gap.timespan.duration,
                context_before=context_before,
                context_after=context_after,
                glossary=glossary_dict,
            )

            try:
                filled_text = client.chat(system_prompt, user_prompt)

                # Update gap
                gap.filled = True
                gap.filled_text = filled_text
                filled_gaps.append(gap)

                # Update the segments in the gap with the filled text
                # If there's one segment, assign all text to it
                # If multiple, try to distribute proportionally
                gap_seg_ids = [s.id for s in gap.whisper_segments]
                if len(gap_seg_ids) == 1:
                    seg = segments_by_id[gap_seg_ids[0]]
                    segments_by_id[seg.id] = seg.model_copy(update={"translation": filled_text})
                else:
                    # Split text roughly evenly across segments
                    chars = list(filled_text)
                    n_segs = len(gap_seg_ids)
                    chars_per_seg = max(1, len(chars) // n_segs)
                    for j, seg_id in enumerate(gap_seg_ids):
                        start_idx = j * chars_per_seg
                        if j == n_segs - 1:
                            part = "".join(chars[start_idx:])
                        else:
                            part = "".join(chars[start_idx : start_idx + chars_per_seg])
                        seg = segments_by_id[seg_id]
                        segments_by_id[seg.id] = seg.model_copy(update={"translation": part})

                self.logger.info("  Filled: %s", filled_text[:50])
            except Exception as e:
                self.logger.warning("  Failed to fill gap %d: %s", i + 1, e)

        # Rebuild segment list in order
        final_segments = [segments_by_id[s.id] for s in merged.segments]

        # Recalculate coverage
        total_duration = sum(s.timespan.duration for s in final_segments)
        covered = sum(s.timespan.duration for s in final_segments if s.translation)
        total_coverage = (covered / total_duration * 100) if total_duration > 0 else 0

        self.logger.info(
            "Gap filling complete: %d/%d gaps filled, coverage: %.1f%%",
            len(filled_gaps),
            len(merged.gaps),
            total_coverage,
        )

        return CompleteSubtitle(
            segments=final_segments,
            filled_gaps=filled_gaps,
            total_coverage=total_coverage,
        )
