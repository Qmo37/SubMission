"""Prompt templates for translation and gap filling."""

from __future__ import annotations

TRANSLATION_SYSTEM = """You are an expert subtitle translator. You translate subtitles exclusively into 繁體中文（台灣用語） (Traditional Chinese, Taiwan Mandarin).

CRITICAL RULES FOR WORD USAGE:
- You MUST prioritize Taiwanese Mandarin vocabulary, idioms, and phrasing (e.g., using "影片" instead of "視頻", "螢幕" instead of "屏幕", "計程車" instead of "出租車").
- Ensure the tone is natural for a Taiwanese audience. Use localized slang and casual grammar structures appropriate for Taiwan.

Formatting Rules:
- Translate each numbered line and preserve the line numbers exactly.
- Keep the same number of output lines as input lines.
- Do NOT merge or split lines.
- Do NOT add explanations or notes.
- Preserve the emotional tone and character voice.
{glossary_section}"""

TRANSLATION_USER = """Translate the following {source_language} subtitle lines to 繁體中文（台灣用語）.

{lines}"""

GLOSSARY_SECTION = """
Glossary (use these translations consistently):
{entries}"""


GAP_FILLING_SYSTEM = """You are an expert Chinese subtitle writer. You write natural 繁體中文（台灣用語） (Traditional Chinese, Taiwan Mandarin) subtitle text.

CRITICAL RULES FOR WORD USAGE:
- You MUST prioritize Taiwanese Mandarin vocabulary, idioms, and phrasing.
- Ensure the tone is natural for a Taiwanese audience.

Formatting Rules:
- Write ONLY the subtitle text, no timestamps or labels.
- Match the tone and style of the surrounding dialogue.
- Keep it concise and natural for subtitle reading speed (~2-4 characters per second).
{glossary_section}"""

GAP_FILLING_USER = """A subtitle is missing for a {duration:.1f}-second segment. Generate the appropriate Traditional Chinese subtitle.

Context BEFORE the gap:
{context_before}

Original speech (may be inaccurate): "{whisper_text}"
Source language: {source_language}

Context AFTER the gap:
{context_after}

Write ONLY the Traditional Chinese subtitle text for this gap."""


def build_translation_prompt(
    lines: list[tuple[int, str]],
    source_language: str,
    glossary: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Build system and user prompts for batch translation.

    Args:
        lines: List of (line_number, text) tuples
        source_language: Source language name (e.g., "English", "Japanese")
        glossary: Optional dict of term -> translation mappings

    Returns:
        (system_prompt, user_prompt)
    """
    glossary_section = ""
    if glossary:
        entries = "\n".join(f"- {k}: {v}" for k, v in glossary.items())
        glossary_section = GLOSSARY_SECTION.format(entries=entries)

    system = TRANSLATION_SYSTEM.format(glossary_section=glossary_section)
    formatted_lines = "\n".join(f"[{num}] {text}" for num, text in lines)
    user = TRANSLATION_USER.format(
        source_language=source_language,
        lines=formatted_lines,
    )
    return system, user


def build_gap_filling_prompt(
    whisper_text: str,
    source_language: str,
    duration: float,
    context_before: list[str],
    context_after: list[str],
    glossary: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Build system and user prompts for gap filling.

    Returns:
        (system_prompt, user_prompt)
    """
    glossary_section = ""
    if glossary:
        entries = "\n".join(f"- {k}: {v}" for k, v in glossary.items())
        glossary_section = GLOSSARY_SECTION.format(entries=entries)

    system = GAP_FILLING_SYSTEM.format(glossary_section=glossary_section)

    before_text = "\n".join(context_before) if context_before else "(none)"
    after_text = "\n".join(context_after) if context_after else "(none)"

    user = GAP_FILLING_USER.format(
        duration=duration,
        context_before=before_text,
        whisper_text=whisper_text,
        source_language=source_language,
        context_after=after_text,
    )
    return system, user
