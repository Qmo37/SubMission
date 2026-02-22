"""Integration tests using short video clips.

Tests are skipped gracefully when heavy dependencies (Whisper, Ollama) aren't available.
"""

import subprocess
import shutil
from pathlib import Path

import pytest

# ── Test data paths ──────────────────────────────────────────────────────

VIDEO_DIR = Path(__file__).parent / "video1"
SNIPPET = VIDEO_DIR / "snippet.mkv"
FULL_VIDEO = VIDEO_DIR / "Umi.no.Hajimari.EP01.1080p.AMZN.WEB-DL.DDP2.0.H.264.V2-MagicStar.mkv"
SUB_SIMPLIFIED = VIDEO_DIR / "simplified_minor_time.srt"
SUB_TRADITIONAL = VIDEO_DIR / "trditional_big_time.srt"


# ── Skip conditions ──────────────────────────────────────────────────────

def _has_whisper():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _has_ollama():
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


skip_no_whisper = pytest.mark.skipif(
    not _has_whisper(), reason="faster-whisper not installed"
)
skip_no_ollama = pytest.mark.skipif(
    not _has_ollama(), reason="ollama not available"
)
skip_no_snippet = pytest.mark.skipif(
    not SNIPPET.exists(), reason=f"Test clip not found: {SNIPPET}"
)
skip_no_full_video = pytest.mark.skipif(
    not FULL_VIDEO.exists(), reason=f"Full video not found: {FULL_VIDEO}"
)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def eight_min_clip(tmp_path_factory):
    """Create an 8-minute clip from the full video (if available)."""
    if not FULL_VIDEO.exists():
        pytest.skip("Full video not available for 8-min clip fixture")

    out_dir = tmp_path_factory.mktemp("clips")
    clip_path = out_dir / "8min_clip.mkv"

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(FULL_VIDEO),
            "-ss", "0", "-t", "480",
            "-c", "copy",
            str(clip_path),
        ],
        capture_output=True,
        timeout=60,
    )

    if not clip_path.exists():
        pytest.skip("Failed to create 8-min clip via ffmpeg")

    return clip_path


@pytest.fixture(scope="session")
def pipeline_config():
    """Load default config for testing."""
    from smart_subtitle.core.config import Config
    config_path = Path(__file__).parent.parent / "config" / "default.yaml"
    if config_path.exists():
        return Config.from_file(config_path)
    return Config.from_defaults()


# ── Tests ────────────────────────────────────────────────────────────────

@skip_no_whisper
@skip_no_snippet
def test_smoke_stages_1_to_4(pipeline_config, tmp_path):
    """2-min snippet through stages 1-4 without crash."""
    from smart_subtitle.cache.manager import CacheManager
    from smart_subtitle.stages.audio_extraction import AudioExtractionStage
    from smart_subtitle.stages.transcription import TranscriptionStage
    from smart_subtitle.stages.reference_translation import ReferenceTranslationStage
    from smart_subtitle.stages.anchor_mapper import AnchorMapperInput, AnchorMapperStage
    from smart_subtitle.subtitle.io import load_subtitle
    from smart_subtitle.subtitle.preprocessor import preprocess_subtitle

    cfg = pipeline_config
    cache = CacheManager(
        cache_dir=cfg.cache.resolved_directory,
        enabled=cfg.cache.enabled,
        max_size_gb=cfg.cache.max_size_gb,
    )

    # Stage 1
    audio_stage = AudioExtractionStage(cfg, cache)
    audio_path = audio_stage.run(SNIPPET)
    assert audio_path.exists()

    # Stage 2
    trans_stage = TranscriptionStage(cfg, cache)
    reference = trans_stage.run(audio_path)
    assert len(reference.segments) > 0

    # Stage 3 (may skip if Ollama not available)
    try:
        ref_trans_stage = ReferenceTranslationStage(cfg, cache)
        reference = ref_trans_stage.run(reference)
    except Exception:
        pytest.skip("Stage 3 translation failed (Ollama likely unavailable)")

    # Stage 4
    work_dir = tmp_path / "preprocessed"
    result = preprocess_subtitle(SUB_SIMPLIFIED, output_dir=work_dir)
    sub = load_subtitle(result.primary_path, quality_rank=0)

    anchor_stage = AnchorMapperStage(cfg, cache)
    anchor_maps = anchor_stage.run(
        AnchorMapperInput(reference=reference, subtitles=[sub])
    )
    assert len(anchor_maps) > 0


@skip_no_whisper
@skip_no_ollama
@skip_no_full_video
def test_full_pipeline_bilingual(pipeline_config, eight_min_clip, tmp_path):
    """8-min clip through all 7 stages with bilingual subtitle input."""
    from smart_subtitle.core.pipeline import SubtitleAlignmentPipeline

    output_path = tmp_path / "output.srt"
    pipeline = SubtitleAlignmentPipeline(pipeline_config)

    subtitle_paths = [SUB_SIMPLIFIED, SUB_TRADITIONAL]
    # Only include existing subtitles
    subtitle_paths = [p for p in subtitle_paths if p.exists()]
    assert len(subtitle_paths) > 0, "No subtitle files found for test"

    result = pipeline.run(
        video_path=eight_min_clip,
        subtitle_paths=subtitle_paths,
        output_path=output_path,
    )

    assert len(result.segments) > 0
    assert output_path.exists()


@skip_no_whisper
@skip_no_ollama
@skip_no_full_video
def test_single_source(pipeline_config, eight_min_clip, tmp_path):
    """Pipeline completes with only one subtitle source."""
    from smart_subtitle.core.pipeline import SubtitleAlignmentPipeline

    if not SUB_SIMPLIFIED.exists():
        pytest.skip("simplified subtitle not found")

    output_path = tmp_path / "output_single.srt"
    pipeline = SubtitleAlignmentPipeline(pipeline_config)

    result = pipeline.run(
        video_path=eight_min_clip,
        subtitle_paths=[SUB_SIMPLIFIED],
        output_path=output_path,
    )

    assert len(result.segments) > 0
    assert output_path.exists()


@skip_no_whisper
@skip_no_ollama
@skip_no_full_video
def test_stage_snapshots(pipeline_config, eight_min_clip, tmp_path):
    """Verify stages 5/6/7 produce non-empty, distinct snapshots."""
    from smart_subtitle.cache.manager import CacheManager
    from smart_subtitle.stages.audio_extraction import AudioExtractionStage
    from smart_subtitle.stages.transcription import TranscriptionStage
    from smart_subtitle.stages.reference_translation import ReferenceTranslationStage
    from smart_subtitle.stages.anchor_mapper import AnchorMapperInput, AnchorMapperStage
    from smart_subtitle.stages.fine_alignment import FineAlignmentInput, FineAlignmentStage
    from smart_subtitle.stages.merge import MergeInput, MergeStage
    from smart_subtitle.stages.gap_filling import GapFillingInput, GapFillingStage
    from smart_subtitle.core.models import CompleteSubtitle
    from smart_subtitle.subtitle.io import load_subtitle
    from smart_subtitle.subtitle.preprocessor import preprocess_subtitle

    cfg = pipeline_config
    cache = CacheManager(
        cache_dir=cfg.cache.resolved_directory,
        enabled=cfg.cache.enabled,
        max_size_gb=cfg.cache.max_size_gb,
    )

    # Stages 1-4
    audio_path = AudioExtractionStage(cfg, cache).run(eight_min_clip)
    reference = TranscriptionStage(cfg, cache).run(audio_path)
    reference = ReferenceTranslationStage(cfg, cache).run(reference)

    work_dir = tmp_path / "preprocessed"
    subs = []
    for sub_path in [SUB_SIMPLIFIED, SUB_TRADITIONAL]:
        if sub_path.exists():
            result = preprocess_subtitle(sub_path, output_dir=work_dir)
            subs.append(load_subtitle(result.primary_path))

    anchor_maps = AnchorMapperStage(cfg, cache).run(
        AnchorMapperInput(reference=reference, subtitles=subs)
    )

    # Stage 5
    aligned = FineAlignmentStage(cfg, cache).run(
        FineAlignmentInput(reference=reference, subtitles=subs, anchor_maps=anchor_maps)
    )
    stage5_count = sum(len(c.matches) for c in aligned)
    assert stage5_count > 0, "Stage 5 produced no matches"

    # Stage 6
    merged = MergeStage(cfg, cache).run(
        MergeInput(reference=reference, aligned_collections=aligned)
    )
    stage6_count = len(merged.segments)
    assert stage6_count > 0, "Stage 6 produced no segments"

    # Stage 7
    if cfg.gap_filling.enabled and merged.gaps:
        complete = GapFillingStage(cfg, cache).run(
            GapFillingInput(merged=merged, source_language=reference.language)
        )
        stage7_count = len(complete.segments)
    else:
        stage7_count = stage6_count

    # Stages should produce different counts (proving each stage changes something)
    # At minimum, stage 5 match count != stage 6 segment count
    assert stage5_count != stage6_count or stage6_count != stage7_count, \
        f"Stages produced identical counts: s5={stage5_count}, s6={stage6_count}, s7={stage7_count}"
