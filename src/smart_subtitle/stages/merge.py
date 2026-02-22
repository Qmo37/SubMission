"""Stage 6: Merge aligned subtitle sources and detect gaps."""

from __future__ import annotations

from dataclasses import dataclass

from smart_subtitle.core.models import (
    AlignedSubtitleCollection,
    Gap,
    MergedSubtitle,
    ReferenceTranscript,
    Segment,
    TimeSpan,
)
from smart_subtitle.subtitle.normalizer import TextNormalizer

from .base import PipelineStage


@dataclass
class MergeInput:
    reference: ReferenceTranscript  # With translations from Stage 3
    aligned_collections: list[AlignedSubtitleCollection]


class MergeStage(PipelineStage[MergeInput, MergedSubtitle]):
    """Merge multiple aligned subtitle sources into a single timeline.

    For each Whisper segment:
    1. Pick the best translation by quality rank from matched subtitle sources
    2. Convert to Traditional Chinese (Taiwan) via OpenCC s2tw
    3. Fall back to Stage 3's LLM reference translation if no match

    Then detect gaps — Whisper segments with speech but no translation.
    """

    @property
    def stage_name(self) -> str:
        return "Merge"

    def _process(self, input_data: MergeInput) -> MergedSubtitle:
        normalizer = TextNormalizer()
        reference = input_data.reference
        collections = sorted(input_data.aligned_collections, key=lambda c: c.subtitle_file.quality_rank)
        
        primary_collection = collections[0] if collections else None

        # Build lookup: whisper_segment_id -> list of (match, subtitle_file)
        # Sorted by quality rank (lower = better)
        matches_by_segment: dict[int, list[tuple]] = {}
        for collection in collections:
            for match in collection.matches:
                seg_id = match.whisper_segment.id
                if seg_id not in matches_by_segment:
                    matches_by_segment[seg_id] = []
                matches_by_segment[seg_id].append((match, collection.subtitle_file))

        output_segments = []
        sources_used: dict[str, int] = {}
        highest_assigned_id = 0
        
        max_whisper = max((s.timespan.end for s in reference.segments), default=float('inf'))
        # Using 0.0 to max_whisper + 10s to bounds-check lines for snippet clips
        max_valid = max_whisper + 10.0

        if primary_collection:
            primary_matches = {m.subtitle_line.index: m for m in primary_collection.matches}
            anchor_map = primary_collection.anchor_map
            
            for sub_line in primary_collection.subtitle_file.lines:
                # Calculate shifted time dynamically based on nearest Anchor block
                local_offset = anchor_map.get_offset(sub_line.timespan.mid)
                shifted_start = sub_line.timespan.start + local_offset
                shifted_end = sub_line.timespan.end + local_offset
                
                # Exclude lines that fall completely outside the valid audio chunk (for snippets)
                if shifted_end < 0.0 or shifted_start > max_valid:
                    continue
                    
                highest_assigned_id += 1
                
                text_to_use = sub_line.text
                timespan_to_use = TimeSpan(start=shifted_start, end=shifted_end)
                confidence = 0.0
                
                # If this line mapped to a Whisper segment, use Whisper timing & best translation
                if sub_line.index in primary_matches:
                    match = primary_matches[sub_line.index]
                    whisper_id = match.whisper_segment.id
                    timespan_to_use = match.final_timespan
                    confidence = match.whisper_segment.confidence
                    
                    if whisper_id in matches_by_segment:
                        segment_matches = matches_by_segment[whisper_id]
                        # Priority: 0 if Traditional Chinese ("zh-tw", "zh-hk"), else 1.
                        # Since Python's sort is stable, it preserves the original quality_rank sorting for ties.
                        best_match, best_source = sorted(
                            segment_matches,
                            key=lambda x: 0 if x[1].language in ("zh-tw", "zh-hk") else 1
                        )[0]
                        
                        text_to_use = best_match.subtitle_line.text
                        source_name = best_source.path
                        sources_used[source_name] = sources_used.get(source_name, 0) + 1
                    else:
                        source_name = primary_collection.subtitle_file.path
                        sources_used[source_name] = sources_used.get(source_name, 0) + 1
                else:
                    # Unmatched line, use shifted timing and its own text
                    source_name = primary_collection.subtitle_file.path
                    sources_used[source_name] = sources_used.get(source_name, 0) + 1
                    
                text_tw = normalizer.to_traditional_tw(text_to_use)
                
                output_segments.append(
                    Segment(
                        id=highest_assigned_id,
                        text=text_tw,
                        timespan=timespan_to_use,
                        confidence=confidence,
                        language=primary_collection.subtitle_file.language,
                        translation=text_tw
                    )
                )

        # Append Whisper segments that were completely missed by the primary subtitle track
        gap_segments = []
        if primary_collection:
            primary_matched_whisper_ids = {m.whisper_segment.id for m in primary_collection.matches}
            for seg in reference.segments:
                if seg.id not in primary_matched_whisper_ids:
                    gap_segments.append(seg)
        else:
            gap_segments = list(reference.segments)
            
        for seg in gap_segments:
            if seg.translation:
                # Reject Whisper hallucinations / massive segments
                if seg.timespan.duration > 20.0:
                    continue

                # Reject gap segments that extensively overlap with mapped primary subtitles
                is_overlap = False
                for out_seg in output_segments:
                    overlap_start = max(seg.timespan.start, out_seg.timespan.start)
                    overlap_end = min(seg.timespan.end, out_seg.timespan.end)
                    if overlap_end - overlap_start > 1.0:
                        is_overlap = True
                        break
                
                if is_overlap:
                    continue

                highest_assigned_id += 1
                text_tw = normalizer.to_traditional_tw(seg.translation)
                sources_used["reference_translation"] = sources_used.get("reference_translation", 0) + 1
                output_segments.append(
                    Segment(
                        id=highest_assigned_id,
                        text=seg.text,
                        timespan=seg.timespan,
                        confidence=seg.confidence,
                        language=seg.language,
                        translation=text_tw
                    )
                )

        # Sort all combined segments by time
        output_segments.sort(key=lambda s: s.timespan.start)

        # Apply Global Delay
        global_delay = self.config.alignment.global_delay
        if global_delay != 0.0:
            for seg in output_segments:
                seg.timespan = seg.timespan.shift(global_delay)

        # Build gaps from consecutive unmatched segments
        gaps = self._build_gaps(gap_segments, output_segments)

        # Calculate coverage
        total_speech_duration = sum(s.timespan.duration for s in reference.segments)
        covered_duration = sum(s.timespan.duration for s in output_segments if s.translation)
        coverage = (
            (covered_duration / total_speech_duration * 100) if total_speech_duration > 0 else 0
        )

        self.logger.info(
            "Merge complete: %d segments, %d gaps, %.1f%% coverage",
            len(output_segments),
            len(gaps),
            coverage,
        )
        for source, count in sources_used.items():
            self.logger.info("  Source %s: %d segments", source, count)

        return MergedSubtitle(
            segments=output_segments,
            gaps=gaps,
            sources_used=sources_used,
            coverage=coverage,
        )

    def _build_gaps(self, gap_segments: list[Segment], all_segments: list[Segment]) -> list[Gap]:
        """Group consecutive gap segments and build Gap objects with context."""
        if not gap_segments:
            return []

        gap_ids = {s.id for s in gap_segments}
        min_duration = self.config.gap_filling.min_gap_duration
        context_window = self.config.gap_filling.context_window

        gaps = []
        current_gap_segs: list[Segment] = []

        for seg in gap_segments:
            if current_gap_segs and seg.timespan.start - current_gap_segs[-1].timespan.end > 1.0:
                # Break in gap — finalize current gap
                gap = self._finalize_gap(current_gap_segs, all_segments, context_window)
                if gap and gap.timespan.duration >= min_duration:
                    gaps.append(gap)
                current_gap_segs = []
            current_gap_segs.append(seg)

        # Final gap
        if current_gap_segs:
            gap = self._finalize_gap(current_gap_segs, all_segments, context_window)
            if gap and gap.timespan.duration >= min_duration:
                gaps.append(gap)

        return gaps

    def _finalize_gap(
        self,
        gap_segs: list[Segment],
        all_segments: list[Segment],
        context_window: int,
    ) -> Gap:
        """Create a Gap object with surrounding context."""
        timespan = TimeSpan(
            start=gap_segs[0].timespan.start,
            end=gap_segs[-1].timespan.end,
        )

        # Find context segments (those with translations)
        translated = [s for s in all_segments if s.translation]
        before = [s for s in translated if s.timespan.end <= timespan.start][-context_window:]
        after = [s for s in translated if s.timespan.start >= timespan.end][:context_window]

        return Gap(
            timespan=timespan,
            whisper_segments=gap_segs,
            context_before=before,
            context_after=after,
        )
