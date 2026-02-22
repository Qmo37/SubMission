"""Glossary management for translation consistency."""

from __future__ import annotations

from pathlib import Path

import yaml


class Glossary:
    """Manages a term-to-translation mapping for consistent translation."""

    def __init__(self, entries: dict[str, str] | None = None):
        self.entries: dict[str, str] = entries or {}

    @classmethod
    def from_file(cls, path: Path) -> Glossary:
        """Load glossary from a YAML file.

        Expected format:
            glossary:
              "Tony Stark": "乾炒牛河"
              "Jarvis": "賈維斯"

        Or flat format:
            "Tony Stark": "乾炒牛河"
            "Jarvis": "賈維斯"
        """
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if "glossary" in data and isinstance(data["glossary"], dict):
            return cls(data["glossary"])
        if isinstance(data, dict):
            return cls(data)
        return cls()

    def add(self, term: str, translation: str) -> None:
        self.entries[term] = translation

    def get(self, term: str) -> str | None:
        return self.entries.get(term)

    def is_empty(self) -> bool:
        return len(self.entries) == 0

    def to_dict(self) -> dict[str, str]:
        return dict(self.entries)

    def save(self, path: Path) -> None:
        with open(path, "w") as f:
            yaml.dump({"glossary": self.entries}, f, allow_unicode=True, default_flow_style=False)
