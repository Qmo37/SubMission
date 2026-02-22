"""Subtitle file I/O using pysubs2."""

from __future__ import annotations

from pathlib import Path

import pysubs2

from smart_subtitle.core.models import (
    CompleteSubtitle,
    Segment,
    SubtitleFile,
    SubtitleLine,
    SubtitleSource,
    TimeSpan,
)


def load_subtitle(
    path: Path,
    quality_rank: int = 0,
    language: str = "auto",
    source_type: SubtitleSource = SubtitleSource.FANSUB,
) -> SubtitleFile:
    """Load a subtitle file and convert to our model."""
    subs = pysubs2.load(str(path))
    fmt = path.suffix.lstrip(".").lower()
    if fmt in ("ssa",):
        fmt = "ass"

    lines = []
    for idx, event in enumerate(subs.events):
        if event.is_comment:
            continue
        # pysubs2 uses milliseconds
        start = event.start / 1000.0
        end = event.end / 1000.0
        text = event.plaintext.strip()
        if not text:
            continue
        lines.append(SubtitleLine(
            index=idx,
            text=text,
            timespan=TimeSpan(start=start, end=end),
            style=event.style if hasattr(event, "style") else None,
        ))

    # Auto-detect language by looking at character ranges
    if language == "auto":
        language = _detect_chinese_variant(lines)

    return SubtitleFile(
        path=str(path),
        lines=lines,
        language=language,
        format=fmt,
        quality_rank=quality_rank,
        source_type=source_type,
    )


def write_subtitle(subtitle: CompleteSubtitle, path: Path, format: str = "srt") -> None:
    """Write a CompleteSubtitle to a file."""
    subs = pysubs2.SSAFile()

    for seg in subtitle.segments:
        text = seg.translation if seg.translation else seg.text
        if not text:
            continue
        event = pysubs2.SSAEvent(
            start=int(seg.timespan.start * 1000),
            end=int(seg.timespan.end * 1000),
            text=text,
        )
        subs.events.append(event)

    subs.sort()
    subs.save(str(path), format_=format)


def write_segments_as_subtitle(
    segments: list[Segment], path: Path, format: str = "srt", use_translation: bool = True
) -> None:
    """Write a list of Segments directly to a subtitle file."""
    subs = pysubs2.SSAFile()

    for seg in segments:
        text = (seg.translation if use_translation and seg.translation else seg.text)
        if not text:
            continue
        event = pysubs2.SSAEvent(
            start=int(seg.timespan.start * 1000),
            end=int(seg.timespan.end * 1000),
            text=text,
        )
        subs.events.append(event)

    subs.sort()
    subs.save(str(path), format_=format)


def _detect_chinese_variant(lines: list[SubtitleLine]) -> str:
    """Heuristic to detect if text is Simplified or Traditional Chinese."""
    # Common Traditional-only characters
    traditional_chars = set("與學從國這裡說對點還個們機開關過經歷認為處樣體頭發電話點書話語實現報導經濟環境價錢讓識記號選擇")
    # Common Simplified-only characters
    simplified_chars = set("与学从国这里说对点还个们机开关过经历认为处样体头发电话点书话语实现报导经济环境价钱让识记号选择")

    trad_count = 0
    simp_count = 0
    for line in lines[:100]:  # Sample first 100 lines
        for ch in line.text:
            if ch in traditional_chars:
                trad_count += 1
            elif ch in simplified_chars:
                simp_count += 1

    if trad_count > simp_count * 1.5:
        return "zh-tw"
    elif simp_count > trad_count * 1.5:
        return "zh-cn"
    return "zh"
