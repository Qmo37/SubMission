"""Text similarity matching for fine alignment."""

from __future__ import annotations

from smart_subtitle.core.models import (
    MatchQuality,
    Segment,
    SubtitleLine,
    SubtitleMatch,
    TimeSpan,
)
from smart_subtitle.subtitle.normalizer import TextNormalizer


class TextMatcher:
    """Match subtitle lines to Whisper segments using text similarity."""

    def __init__(
        self,
        text_weight: float = 0.5,
        time_weight: float = 0.5,
        start_offset: float = -0.1,
        time_tolerance: float = 5.0,
        min_match_score: float = 0.3,
        gap_penalty_weight: float = 0.2,
        high_confidence_override: float = 0.9,
    ):
        self.text_weight = text_weight
        self.time_weight = time_weight
        self.start_offset = start_offset
        self.time_tolerance = time_tolerance
        self.min_match_score = min_match_score
        self.gap_penalty_weight = gap_penalty_weight
        self.high_confidence_override = high_confidence_override
        self.normalizer = TextNormalizer()

    def find_best_match(
        self,
        subtitle_line: SubtitleLine,
        candidates: list[Segment],
        used_ids: set[int],
        source_file: str,
        previous_match: SubtitleMatch | None = None,
    ) -> SubtitleMatch | None:
        """Find the best matching Whisper segment for a subtitle line.

        Compares the subtitle's Chinese text against each candidate segment's
        .translation field (the reference Chinese translation from Stage 3).
        """
        available = [
            seg for seg in candidates
            if seg.id not in used_ids
            and self._within_tolerance(subtitle_line.timespan, seg.timespan)
        ]

        if not available:
            return None

        best: SubtitleMatch | None = None
        best_score = -1.0

        if previous_match:
            available = [s for s in available if s.timespan.start >= previous_match.whisper_segment.timespan.start]
            
        for seg in available:
            # Text similarity: compare subtitle Chinese vs reference translation Chinese
            ref_text = seg.translation or ""
            if ref_text:
                text_sim = self.normalizer.similarity(subtitle_line.text, ref_text)
            else:
                text_sim = 0.0

            # Time similarity: distance degrades smoothly instead of failing completely when not overlapping
            time_distance = min(
                abs(subtitle_line.timespan.start - seg.timespan.start),
                abs(subtitle_line.timespan.end - seg.timespan.end)
            )
            time_sim = max(0.0, 1.0 - (time_distance / self.time_tolerance))
            
            # Prevent greedy jumping across time for weak text matches
            if time_distance > 2.0 and text_sim < 0.6:
                continue
            
            # Semantic Gap Penalty
            gap_penalty = 0.0
            if previous_match and text_sim < self.high_confidence_override:
                # How much time elapsed between the LAST line starting and THIS line starting in the original file?
                expected_pacing = subtitle_line.timespan.start - previous_match.subtitle_line.timespan.start
                
                # How much time elapsed between the LAST whisper segment starting and THIS candidate starting?
                actual_pacing = seg.timespan.start - previous_match.whisper_segment.timespan.start
                
                # Calculate pacing deviation
                pacing_diff = abs(expected_pacing - actual_pacing)
                
                # Apply penalty (cap it at 0.3 so we don't completely discard lines just because of pacing)
                gap_penalty = min(0.3, pacing_diff * self.gap_penalty_weight)

            # Combined score
            combined = (self.text_weight * text_sim) + (self.time_weight * time_sim) - gap_penalty

            if combined > best_score:
                best_score = combined
                final_timespan = self._blend_timespans(subtitle_line.timespan, seg.timespan)
                quality = self._assess_quality(text_sim, time_sim)

                best = SubtitleMatch(
                    subtitle_line=subtitle_line,
                    whisper_segment=seg,
                    text_similarity=text_sim,
                    time_similarity=time_sim,
                    combined_score=combined,
                    quality=quality,
                    final_timespan=final_timespan,
                    source_file=source_file,
                )

        if best and (best.combined_score >= self.min_match_score and (best.text_similarity >= 0.25 or best.time_similarity >= 0.8)):
            return best
        return None

    def _within_tolerance(self, sub_ts: TimeSpan, seg_ts: TimeSpan) -> bool:
        """Check if two timespans are close enough to be candidates."""
        # Either they overlap, or their midpoints are within tolerance
        if sub_ts.overlap(seg_ts) > 0:
            return True
        gap = min(abs(sub_ts.start - seg_ts.end), abs(seg_ts.start - sub_ts.end))
        return gap <= self.time_tolerance

    def _blend_timespans(self, sub_ts: TimeSpan, whisper_ts: TimeSpan) -> TimeSpan:
        """Blend timestamps using a hybrid approach.
        
        The dynamic Offset Consensus algorithm already perfectly shifted the subtitle's
        timeline to match the temporal audio terrain. We just return it directly so
        we preserve the absolute original duration and pacing exactly.
        """
        # The AnchorMapperStage already applied local_offset to sub_ts
        final_start = sub_ts.start
        final_end = sub_ts.end
        
        # Boundary checks
        final_start = max(0.0, final_start)
        final_end = max(final_start + 0.1, final_end)
        
        return TimeSpan(start=final_start, end=final_end)

    @staticmethod
    def _assess_quality(text_sim: float, time_sim: float) -> MatchQuality:
        avg = (text_sim + time_sim) / 2
        if avg >= 0.85:
            return MatchQuality.EXACT
        elif avg >= 0.65:
            return MatchQuality.GOOD
        elif avg >= 0.45:
            return MatchQuality.FAIR
        elif avg >= 0.25:
            return MatchQuality.POOR
        return MatchQuality.UNMATCHED
