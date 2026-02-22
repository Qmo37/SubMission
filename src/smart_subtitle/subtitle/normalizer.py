"""Text normalization for Chinese subtitle comparison."""

from __future__ import annotations

import re

from opencc import OpenCC
from rapidfuzz import fuzz


class TextNormalizer:
    """Normalize Chinese text for cross-variant comparison."""

    def __init__(self):
        self._t2s = OpenCC("t2s")   # Traditional -> Simplified (for comparison)
        self._s2tw = OpenCC("s2tw")  # Simplified -> Traditional (Taiwan, for output)

    def to_simplified(self, text: str) -> str:
        """Convert any Chinese variant to Simplified for comparison."""
        return self._t2s.convert(text)

    def to_traditional_tw(self, text: str) -> str:
        """Convert any Chinese to Traditional Chinese (Taiwan) for output."""
        return self._s2tw.convert(text)

    def normalize_for_comparison(self, text: str) -> str:
        """Full normalization pipeline for text comparison."""
        text = self._remove_formatting(text)
        text = self.to_simplified(text)
        text = self._normalize_punctuation(text)
        text = re.sub(r"\s+", " ", text).strip()
        text = text.lower()
        return text

    def similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity score (0.0-1.0) between two Chinese texts.

        Both texts are normalized to Simplified Chinese before comparison.
        """
        norm1 = self.normalize_for_comparison(text1)
        norm2 = self.normalize_for_comparison(text2)
        if not norm1 or not norm2:
            return 0.0
        score = fuzz.token_sort_ratio(norm1, norm2)
        return score / 100.0

    def partial_similarity(self, text1: str, text2: str) -> float:
        """Partial match — useful when one text is a substring of the other."""
        norm1 = self.normalize_for_comparison(text1)
        norm2 = self.normalize_for_comparison(text2)
        if not norm1 or not norm2:
            return 0.0
        score = fuzz.partial_ratio(norm1, norm2)
        return score / 100.0

    @staticmethod
    def _remove_formatting(text: str) -> str:
        """Remove ASS override tags, HTML tags, etc."""
        text = re.sub(r"\{[^}]*\}", "", text)  # ASS tags
        text = re.sub(r"<[^>]*>", "", text)     # HTML tags
        text = re.sub(r"\\[nN]", " ", text)     # ASS line breaks
        return text

    @staticmethod
    def _normalize_punctuation(text: str) -> str:
        """Normalize Chinese punctuation to ASCII equivalents."""
        replacements = {
            "\u3001": ",",   # 、
            "\uff0c": ",",   # ，
            "\u3002": ".",   # 。
            "\uff01": "!",   # ！
            "\uff1f": "?",   # ？
            "\uff1a": ":",   # ：
            "\uff1b": ";",   # ；
            "\u201c": '"',   # "
            "\u201d": '"',   # "
            "\u2018": "'",   # '
            "\u2019": "'",   # '
            "\uff08": "(",   # （
            "\uff09": ")",   # ）
            "\u3010": "[",   # 【
            "\u3011": "]",   # 】
            "\u2014": "-",   # —
            "\u2026": "...", # …
            "\u300a": "<",   # 《
            "\u300b": ">",   # 》
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text
