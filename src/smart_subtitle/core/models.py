"""Data models for smart_subtitle pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TimeSpan(BaseModel):
    """Time interval in seconds with millisecond precision."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2

    def shift(self, offset: float) -> TimeSpan:
        return TimeSpan(start=self.start + offset, end=self.end + offset)

    def overlap(self, other: TimeSpan) -> float:
        """Return overlap duration in seconds (0 if no overlap)."""
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return max(0.0, end - start)

    def overlap_ratio(self, other: TimeSpan) -> float:
        """Return overlap as a fraction of the shorter span's duration."""
        o = self.overlap(other)
        if o == 0:
            return 0.0
        shorter = min(self.duration, other.duration)
        if shorter <= 0:
            return 0.0
        return o / shorter

    def contains(self, time: float) -> bool:
        return self.start <= time <= self.end

    def expand(self, margin: float) -> TimeSpan:
        return TimeSpan(start=max(0, self.start - margin), end=self.end + margin)


class Word(BaseModel):
    """Word-level timing information."""

    word: str
    timespan: TimeSpan
    confidence: float | None = None


class Segment(BaseModel):
    """A single speech segment with text and timing."""

    id: int
    text: str
    timespan: TimeSpan
    confidence: float | None = None
    language: str | None = None
    words: list[Word] | None = None
    translation: str | None = None  # Reference translation (Stage 3)


class ReferenceTranscript(BaseModel):
    """Whisper transcription result (ground truth timeline)."""

    segments: list[Segment]
    language: str
    model: str
    audio_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubtitleLine(BaseModel):
    """Single subtitle line from input file."""

    index: int
    text: str
    timespan: TimeSpan
    style: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubtitleSource(str, Enum):
    """Type of subtitle source."""

    OFFICIAL = "official"
    FANSUB = "fansub"
    AUTO = "auto"


class SubtitleFile(BaseModel):
    """Input subtitle file representation."""

    path: str
    lines: list[SubtitleLine]
    language: str  # e.g. "zh-cn", "zh-tw"
    encoding: str = "utf-8"
    format: str  # "srt", "ass", etc.
    quality_rank: int = 0  # Lower = higher quality (0 = best)
    source_type: SubtitleSource = SubtitleSource.FANSUB


class MatchQuality(str, Enum):
    """Quality of subtitle-to-whisper match."""

    EXACT = "exact"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNMATCHED = "unmatched"


class SubtitleMatch(BaseModel):
    """Matched pair of subtitle line and Whisper segment."""

    subtitle_line: SubtitleLine
    whisper_segment: Segment
    text_similarity: float  # 0.0 to 1.0
    time_similarity: float  # 0.0 to 1.0
    combined_score: float
    quality: MatchQuality
    final_timespan: TimeSpan
    source_file: str  # Which subtitle file this came from


class AnchorBlock(BaseModel):
    """A high-confidence sync point between subtitle and audio."""

    subtitle_timespan: TimeSpan
    whisper_timespan: TimeSpan
    offset: float  # whisper_time - subtitle_time
    confidence: float
    subtitle_start_idx: int
    subtitle_end_idx: int
    whisper_start_id: int
    whisper_end_id: int

class AnchorMap(BaseModel):
    """Dynamic terrain map of temporal offsets for a subtitle file."""

    subtitle_path: str
    anchors: list[AnchorBlock]
    
    def get_offset(self, time: float) -> float:
        """Get the localized offset for a given subtitle timestamp using linear interpolation."""
        if not self.anchors:
            return 0.0
            
        if len(self.anchors) == 1:
            return self.anchors[0].offset
            
        sorted_anchors = sorted(self.anchors, key=lambda a: a.subtitle_timespan.mid)
        
        # Clamp to edges
        if time <= sorted_anchors[0].subtitle_timespan.mid:
            return sorted_anchors[0].offset
        if time >= sorted_anchors[-1].subtitle_timespan.mid:
            return sorted_anchors[-1].offset
            
        # Linear Interpolation between the wrapping anchors
        for i in range(len(sorted_anchors) - 1):
            a1 = sorted_anchors[i]
            a2 = sorted_anchors[i+1]
            t1 = a1.subtitle_timespan.mid
            t2 = a2.subtitle_timespan.mid
            
            if t1 <= time <= t2:
                range_span = t2 - t1
                if range_span <= 0:
                    return a1.offset
                progress = (time - t1) / range_span
                return a1.offset + progress * (a2.offset - a1.offset)
                
        return 0.0


class AlignedSubtitleCollection(BaseModel):
    """Collection of aligned subtitles from one source."""

    subtitle_file: SubtitleFile
    anchor_map: AnchorMap
    matches: list[SubtitleMatch]
    unmatched_subtitles: list[SubtitleLine]
    unmatched_whisper_ids: list[int]


class Gap(BaseModel):
    """Gap in subtitle coverage."""

    timespan: TimeSpan
    whisper_segments: list[Segment]
    context_before: list[Segment] = Field(default_factory=list)
    context_after: list[Segment] = Field(default_factory=list)
    filled: bool = False
    filled_text: str | None = None


class MergedSubtitle(BaseModel):
    """Merged result from multiple subtitle sources."""

    segments: list[Segment]
    gaps: list[Gap]
    sources_used: dict[str, int] = Field(default_factory=dict)  # source -> count
    coverage: float = 0.0  # Percentage of speech timeline covered


class CompleteSubtitle(BaseModel):
    """Final output with all gaps filled."""

    segments: list[Segment]
    filled_gaps: list[Gap]
    total_coverage: float
    metadata: dict[str, Any] = Field(default_factory=dict)
