"""Preprocessing for special subtitle formats (bilingual SRT, embedded ASS tags, etc.)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from smart_subtitle.subtitle.normalizer import TextNormalizer

logger = logging.getLogger("smart_subtitle.subtitle.preprocessor")

# Regex for ASS override tags: {\...}
ASS_TAG_RE = re.compile(r"\{[^}]*\}")

# Regex for SRT timestamp line
SRT_TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


@dataclass
class SplitResult:
    """Result of splitting a bilingual SRT file."""

    primary_path: Path  # The main track (Chinese translation)
    secondary_path: Path | None = None  # The secondary track (Japanese original)
    primary_language: str = "zh-cn"
    secondary_language: str = "ja"
    is_bilingual: bool = False
    total_entries: int = 0
    primary_entries: int = 0
    secondary_entries: int = 0


@dataclass
class SrtEntry:
    """A single SRT subtitle entry."""

    index: int
    start_time: str  # Raw timestamp string
    end_time: str
    text: str
    start_ms: int = 0  # Parsed millisecond value

    def clean_text(self) -> str:
        """Remove ASS override tags and clean up."""
        text = ASS_TAG_RE.sub("", self.text)
        text = re.sub(r"\\[nN]", "\n", text)  # ASS line breaks
        return text.strip()


# Regex for a single timestamp
SINGLE_TS_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")

def _parse_timestamp_ms(ts: str) -> int:
    """Parse an SRT timestamp string to milliseconds."""
    m = SINGLE_TS_RE.match(ts.strip())
    if not m:
        return 0
    h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return ((h * 3600 + mi * 60 + s) * 1000) + ms


def _format_timestamp(ms: int) -> str:
    """Format milliseconds as SRT timestamp."""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_entries(content: str) -> list[SrtEntry]:
    """Parse raw SRT file content into structured entries."""
    entries = []
    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # Split on blank lines to get blocks
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # First line should be the index
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # Second line should be the timestamp
        ts_match = SRT_TIMESTAMP_RE.search(lines[1])
        if not ts_match:
            continue

        # Rest is the subtitle text
        text = "\n".join(lines[2:]).strip()
        if not text:
            continue

        # Parse full timestamp line for start_time and end_time
        ts_parts = lines[1].strip().split("-->")
        start_time = ts_parts[0].strip()
        end_time = ts_parts[1].strip() if len(ts_parts) > 1 else start_time

        start_ms = _parse_timestamp_ms(start_time)

        entries.append(SrtEntry(
            index=index,
            start_time=start_time,
            end_time=end_time,
            text=text,
            start_ms=start_ms,
        ))

    return entries


def _detect_bilingual_split(entries: list[SrtEntry]) -> int | None:
    """Detect the split point in a bilingual SRT where timestamps reset.

    In bilingual SRTs, the first half contains one language (e.g., Japanese)
    and the second half contains another (e.g., Chinese), with timestamps
    restarting from the beginning for the second language.

    Returns the index in the entries list where the second language begins,
    or None if no split is detected.
    """
    if len(entries) < 10:
        return None

    # Look for a big timestamp jump backward (reset) in the middle portion
    # We search in the 30-70% range of the file to avoid false positives
    # from small timing adjustments near the edges
    search_start = len(entries) // 4
    search_end = len(entries) * 3 // 4

    for i in range(search_start, search_end):
        prev_ms = entries[i - 1].start_ms
        curr_ms = entries[i].start_ms

        # A reset is a large backward jump (e.g., from 01:10:00 back to 00:00:19)
        if prev_ms > 60000 and curr_ms < prev_ms * 0.1:
            print(f"Potential split at index {i}: {prev_ms} -> {curr_ms}", flush=True)
            # Verify: the entries after the split should roughly cover the same
            # time range as entries before the split
            first_half_end = entries[i - 1].start_ms
            second_half_entries = entries[i:]
            if second_half_entries:
                second_half_end = second_half_entries[-1].start_ms
                # Both halves should cover a similar time range (within 50%)
                if first_half_end > 0:
                    ratio = second_half_end / first_half_end
                    print(f"Ratio calculation: {second_half_end} / {first_half_end} = {ratio}", flush=True)
                    if 0.5 < ratio < 2.0:
                        logger.info(
                            "Detected bilingual split at entry %d/%d "
                            "(first half ends at %s, second starts at %s)",
                            i, len(entries),
                            _format_timestamp(prev_ms),
                            _format_timestamp(curr_ms),
                        )
                        return i

    return None


def _detect_language(text: str) -> str:
    """Simple heuristic to detect if text is CJK Chinese vs Japanese."""
    # Check for Japanese-specific characters (hiragana/katakana)
    hiragana = sum(1 for c in text if "\u3040" <= c <= "\u309f")
    katakana = sum(1 for c in text if "\u30a0" <= c <= "\u30ff")
    # Check for Chinese characters (CJK unified)
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")

    jp_chars = hiragana + katakana
    if jp_chars > 0 and jp_chars > cjk * 0.1:
        return "ja"

    # Check for Simplified vs Traditional
    trad_chars = set("與學從國這裡說對點還個們機開關過經歷認為處樣體頭發電話點書語實現報導經濟環境價錢讓識記號選擇")
    simp_chars = set("与学从国这里说对点还个们机开关过经历认为处样体头发电话点书语实现报导经济环境价钱让识记号选择")

    trad = sum(1 for c in text if c in trad_chars)
    simp = sum(1 for c in text if c in simp_chars)

    if trad > simp * 1.5:
        return "zh-tw"
    elif simp > trad * 1.5:
        return "zh-cn"
    return "zh"


def _write_clean_srt(entries: list[SrtEntry], output_path: Path) -> None:
    """Write cleaned SRT entries to a file with ASS tags stripped."""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, entry in enumerate(entries, 1):
            clean = entry.clean_text()
            if not clean:
                continue
            f.write(f"{i}\n")
            f.write(f"{entry.start_time} --> {entry.end_time}\n")
            f.write(f"{clean}\n")
            f.write("\n")


def preprocess_subtitle(
    input_path: Path,
    output_dir: Path | None = None,
) -> SplitResult:
    """Preprocess a subtitle file, handling bilingual SRTs and ASS tags.

    If a bilingual SRT is detected, splits it into separate files for each language.
    Always strips ASS override tags from the output.

    Args:
        input_path: Path to the original subtitle file
        output_dir: Directory for preprocessed output files. Defaults to same dir as input.

    Returns:
        SplitResult with paths to the preprocessed file(s)
    """
    if output_dir is None:
        output_dir = input_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read and parse the file
    content = input_path.read_text(encoding="utf-8", errors="replace")
    entries = _parse_srt_entries(content)

    if not entries:
        logger.warning("No subtitle entries found in %s", input_path)
        return SplitResult(primary_path=input_path, total_entries=0)

    logger.info("Parsed %d entries from %s", len(entries), input_path.name)

    # Check for bilingual split
    split_point = _detect_bilingual_split(entries)

    if split_point is not None:
        first_half = entries[:split_point]
        second_half = entries[split_point:]

        # Detect languages of each half
        first_text = " ".join(e.clean_text() for e in first_half[:50])
        second_text = " ".join(e.clean_text() for e in second_half[:50])
        first_lang = _detect_language(first_text)
        second_lang = _detect_language(second_text)

        logger.info(
            "Bilingual split: %d entries (%s) + %d entries (%s)",
            len(first_half), first_lang,
            len(second_half), second_lang,
        )

        # Determine which half is the Chinese translation (primary for our pipeline)
        if "zh" in second_lang:
            cn_half, jp_half = second_half, first_half
            cn_lang, jp_lang = second_lang, first_lang
        elif "zh" in first_lang:
            cn_half, jp_half = first_half, second_half
            cn_lang, jp_lang = first_lang, second_lang
        else:
            # Neither is clearly Chinese — just use the second half as primary
            cn_half, jp_half = second_half, first_half
            cn_lang, jp_lang = second_lang, first_lang

        stem = input_path.stem

        # Write Chinese translation
        cn_path = output_dir / f"{stem}_chinese.srt"
        _write_clean_srt(cn_half, cn_path)

        # Write Japanese original
        jp_path = output_dir / f"{stem}_japanese.srt"
        _write_clean_srt(jp_half, jp_path)

        logger.info(
            "Split bilingual SRT: Chinese -> %s (%d entries), Japanese -> %s (%d entries)",
            cn_path.name, len(cn_half), jp_path.name, len(jp_half),
        )

        return SplitResult(
            primary_path=cn_path,
            secondary_path=jp_path,
            primary_language=cn_lang,
            secondary_language=jp_lang,
            is_bilingual=True,
            total_entries=len(entries),
            primary_entries=len(cn_half),
            secondary_entries=len(jp_half),
        )
    else:
        # Not bilingual — just clean ASS tags
        clean_text = " ".join(e.clean_text() for e in entries[:50])
        lang = _detect_language(clean_text)

        # Check if ASS tags are present and need stripping
        has_ass_tags = any(ASS_TAG_RE.search(e.text) for e in entries[:20])

        if has_ass_tags:
            clean_path = output_dir / f"{input_path.stem}_clean.srt"
            _write_clean_srt(entries, clean_path)
            logger.info(
                "Stripped ASS tags: %s -> %s (%d entries)",
                input_path.name, clean_path.name, len(entries),
            )
            return SplitResult(
                primary_path=clean_path,
                primary_language=lang,
                total_entries=len(entries),
                primary_entries=len(entries),
            )
        else:
            # File is already clean
            return SplitResult(
                primary_path=input_path,
                primary_language=lang,
                total_entries=len(entries),
                primary_entries=len(entries),
            )

def cross_map_subtitles(primary_path: Path, secondary_path: Path, output_path: Path) -> Path:
    """Inject text from secondary subtitle into the timings of the primary subtitle.
    
    Used to pull high-quality localizations (e.g. Taiwanese Mandarin) into a
    subtitle track that has perfectly synced timings but poor localization (e.g. Simplified OTT).
    """
    logger.info("Cross-mapping text from %s onto timings of %s", secondary_path.name, primary_path.name)
    
    # Read and parse both files
    prim_content = primary_path.read_text(encoding="utf-8", errors="replace")
    sec_content = secondary_path.read_text(encoding="utf-8", errors="replace")
    
    prim_entries = _parse_srt_entries(prim_content)
    sec_entries = _parse_srt_entries(sec_content)
    
    if not prim_entries or not sec_entries:
        logger.warning("Subtitle cross-mapping failed: missing entries")
        return primary_path

    normalizer = TextNormalizer()
    mapped_count = 0
    
    # 5-minute sliding window (300,000 ms) in case of massive commercial break offsets
    TIME_WINDOW_MS = 300000 
    
    for p_entry in prim_entries:
        best_match = None
        best_score = 0.0
        
        # Search for lexical matches within the sliding window
        for s_entry in sec_entries:
            time_diff = abs(p_entry.start_ms - s_entry.start_ms)
            if time_diff > TIME_WINDOW_MS:
                continue
                
            sim = normalizer.similarity(p_entry.text, s_entry.text)
            if sim > best_score:
                best_score = sim
                best_match = s_entry
                
        # Only inject the text if it strongly correlates
        if best_match and best_score > 0.65:
            p_entry.text = best_match.clean_text()
            mapped_count += 1
            
    _write_clean_srt(prim_entries, output_path)
    logger.info("Cross-mapped %d/%d lines into %s", mapped_count, len(prim_entries), output_path.name)
    
    return output_path
