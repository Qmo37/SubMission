#!/usr/bin/env python3
"""Quick test of the bilingual SRT preprocessor."""
import re
import sys
import os

# Avoid importing heavy dependencies
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pathlib import Path

print("Testing preprocessor...", flush=True)

from smart_subtitle.subtitle.preprocessor import preprocess_subtitle

# Test 1: Bilingual SRT
print("\n=== Test 1: Bilingual SRT ===", flush=True)
result = preprocess_subtitle(
    Path('tests/video1/simplified_minor_time.srt'),
    output_dir=Path('tests/video1/preprocessed'),
)
print(f"Is bilingual: {result.is_bilingual}", flush=True)
print(f"Total entries: {result.total_entries}", flush=True)
print(f"Primary: {result.primary_path.name} ({result.primary_entries} entries, {result.primary_language})", flush=True)
if result.secondary_path:
    print(f"Secondary: {result.secondary_path.name} ({result.secondary_entries} entries, {result.secondary_language})", flush=True)

# Show first 15 lines of Chinese output
print("\n--- Chinese output (first 15 lines) ---", flush=True)
with open(result.primary_path, encoding='utf-8') as f:
    for i, line in enumerate(f):
        if i >= 15:
            break
        print(line.rstrip(), flush=True)

# Test 2: Traditional SRT
print("\n=== Test 2: Traditional SRT ===", flush=True)
result2 = preprocess_subtitle(
    Path('tests/video1/trditional_big_time.srt'),
    output_dir=Path('tests/video1/preprocessed'),
)
print(f"Is bilingual: {result2.is_bilingual}", flush=True)
print(f"Total entries: {result2.total_entries}", flush=True)
print(f"Primary: {result2.primary_path.name} ({result2.primary_entries} entries, {result2.primary_language})", flush=True)

print("\nDone!", flush=True)
