"""Stage 5: Fine-grained alignment matching individual lines to segments."""

from __future__ import annotations

from dataclasses import dataclass

from smart_subtitle.alignment.text_matcher import TextMatcher
from smart_subtitle.core.models import (
    AlignedSubtitleCollection,
    AnchorMap,
    ReferenceTranscript,
    SubtitleFile,
    SubtitleMatch,
    SubtitleLine,
    TimeSpan,
)

from .base import PipelineStage


@dataclass
class FineAlignmentInput:
    reference: ReferenceTranscript  # With translations from Stage 3
    subtitles: list[SubtitleFile]
    anchor_maps: dict[str, AnchorMap]


class FineAlignmentStage(PipelineStage[FineAlignmentInput, list[AlignedSubtitleCollection]]):
    """Match individual subtitle lines to Whisper segments.

    After applying global offset, each subtitle line is matched to the best
    Whisper segment using a combination of time overlap and text similarity
    (comparing the subtitle's Chinese text to the reference translation).
    """

    @property
    def stage_name(self) -> str:
        return "Fine Alignment"

    def _process(self, input_data: FineAlignmentInput) -> list[AlignedSubtitleCollection]:
        cfg = self.config.alignment.fine_alignment
        matcher = TextMatcher(
            text_weight=cfg.text_weight,
            time_weight=cfg.time_weight,
            start_offset=cfg.start_offset,
            time_tolerance=cfg.time_tolerance,
            min_match_score=cfg.min_match_score,
            gap_penalty_weight=cfg.gap_penalty_weight,
            high_confidence_override=cfg.high_confidence_override,
        )

        collections = []
        segments = input_data.reference.segments

        for sub in input_data.subtitles:
            anchor_map = input_data.anchor_maps[sub.path]

            # Apply dynamic offset to all subtitle lines
            shifted_lines = []
            for line in sub.lines:
                local_offset = anchor_map.get_offset(line.timespan.mid)
                shifted_lines.append(
                    SubtitleLine(
                        index=line.index,
                        text=line.text,
                        timespan=line.timespan.shift(local_offset),
                        style=line.style,
                        metadata=line.metadata,
                    )
                )

            matches = []
            used_segment_ids: set[int] = set()
            last_successful_match: SubtitleMatch | None = None

            for line in shifted_lines:
                match = matcher.find_best_match(
                    subtitle_line=line,
                    candidates=segments,
                    used_ids=used_segment_ids,
                    source_file=sub.path,
                    previous_match=last_successful_match,
                )
                if match:
                    matches.append(match)
                    used_segment_ids.add(match.whisper_segment.id)
                    last_successful_match = match

            unmatched_subs = [
                line
                for line in shifted_lines
                if not any(m.subtitle_line.index == line.index for m in matches)
            ]
            unmatched_whisper_ids = [seg.id for seg in segments if seg.id not in used_segment_ids]

            self.logger.info(
                "  %s: %d matched, %d unmatched subs, %d unmatched whisper segments",
                sub.path,
                len(matches),
                len(unmatched_subs),
                len(unmatched_whisper_ids),
            )

            collections.append(
                AlignedSubtitleCollection(
                    subtitle_file=sub,
                    anchor_map=anchor_map,
                    matches=matches,
                    unmatched_subtitles=unmatched_subs,
                    unmatched_whisper_ids=unmatched_whisper_ids,
                )
            )

        return collections
