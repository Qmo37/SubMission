"""CLI interface for smart-subtitle."""

from __future__ import annotations

from pathlib import Path

import click

from smart_subtitle.core.config import Config
from smart_subtitle.core.pipeline import SubtitleAlignmentPipeline


@click.group()
@click.option("--config", "config_path", type=click.Path(exists=True), help="Config YAML file")
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
@click.pass_context
def cli(ctx, config_path, log_level):
    """Smart Subtitle - Align and enhance subtitles using Whisper and LLM."""
    ctx.ensure_object(dict)

    if config_path:
        cfg = Config.from_file(Path(config_path))
    else:
        cfg = Config.from_defaults()

    if log_level:
        cfg = cfg.merge_overrides({"logging": {"level": log_level}})

    ctx.obj["config"] = cfg


@cli.command()
@click.argument("video", type=click.Path(exists=True))
@click.argument("subtitles", nargs=-1, type=click.Path(exists=True), required=True)
@click.option("-o", "--output", type=click.Path(), required=True, help="Output subtitle file")
@click.option("--quality-rank", multiple=True, type=int, help="Quality rank per subtitle (0=best)")
@click.option("--source-lang", help="Source language code (auto-detected if omitted)")
@click.option("--glossary", type=click.Path(exists=True), help="Glossary YAML file")
@click.option("--no-fill-gaps", is_flag=True, help="Skip LLM gap filling")
@click.option("--force", multiple=True, help="Force re-run stages (e.g., --force transcription)")
@click.option("--output-format", type=click.Choice(["srt", "ass"]), help="Output format override")
@click.pass_context
def align(
    ctx,
    video,
    subtitles,
    output,
    quality_rank,
    source_lang,
    glossary,
    no_fill_gaps,
    force,
    output_format,
):
    """Align subtitles to video and produce Traditional Chinese output.

    Examples:

        smart-subtitle align movie.mp4 sub_cn.srt sub_tw.ass -o output.srt

        smart-subtitle align movie.mp4 sub_cn.srt sub_tw.ass \\
          --quality-rank 1 --quality-rank 0 -o output.srt
    """
    cfg: Config = ctx.obj["config"]

    # Apply overrides
    overrides = {}
    if source_lang:
        overrides.setdefault("transcription", {})["language"] = source_lang
    if glossary:
        overrides.setdefault("translation", {})["glossary_path"] = glossary
    if output_format:
        overrides.setdefault("output", {})["format"] = output_format
    if overrides:
        cfg = cfg.merge_overrides(overrides)

    # Validate quality ranks
    ranks = list(quality_rank) if quality_rank else None
    if ranks and len(ranks) != len(subtitles):
        raise click.BadParameter(
            f"--quality-rank count ({len(ranks)}) must match subtitle count ({len(subtitles)})"
        )

    pipeline = SubtitleAlignmentPipeline(cfg)

    try:
        result = pipeline.run(
            video_path=Path(video),
            subtitle_paths=[Path(s) for s in subtitles],
            output_path=Path(output),
            quality_ranks=ranks,
            fill_gaps=not no_fill_gaps,
            force_stages=list(force) if force else None,
        )

        click.echo(f"Output written to: {output}")
        click.echo(f"Segments: {len(result.segments)}")
        click.echo(f"Coverage: {result.total_coverage:.1f}%")
        if result.filled_gaps:
            click.echo(f"Gaps filled: {len(result.filled_gaps)}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("video", type=click.Path(exists=True))
@click.option("-o", "--output", type=click.Path(), help="Output subtitle file")
@click.option("--model", help="Whisper model override (e.g., large-v3, medium)")
@click.option("--source-lang", help="Source language code")
@click.option("--translate-to", help="Translate to language (e.g., zh-tw)")
@click.option("--glossary", type=click.Path(exists=True), help="Glossary for translation")
@click.pass_context
def transcribe(ctx, video, output, model, source_lang, translate_to, glossary):
    """Transcribe video audio using Whisper (optionally translate).

    Examples:

        smart-subtitle transcribe movie.mp4 -o whisper.srt
        smart-subtitle transcribe movie.mp4 -o translated.srt --translate-to zh-tw
    """
    cfg: Config = ctx.obj["config"]

    overrides = {}
    if model:
        overrides.setdefault("transcription", {})["model"] = model
    if source_lang:
        overrides.setdefault("transcription", {})["language"] = source_lang
    if glossary:
        overrides.setdefault("translation", {})["glossary_path"] = glossary
    if overrides:
        cfg = cfg.merge_overrides(overrides)

    from smart_subtitle.cache.manager import CacheManager
    from smart_subtitle.stages.audio_extraction import AudioExtractionStage
    from smart_subtitle.stages.transcription import TranscriptionStage
    from smart_subtitle.subtitle.io import write_segments_as_subtitle

    cache = CacheManager(cfg.cache.resolved_directory, cfg.cache.enabled, cfg.cache.max_size_gb)

    # Extract audio
    audio_stage = AudioExtractionStage(cfg, cache)
    audio_path = audio_stage.run(Path(video))

    # Transcribe
    trans_stage = TranscriptionStage(cfg, cache)
    transcript = trans_stage.run(audio_path)

    click.echo(f"Transcribed {len(transcript.segments)} segments (language: {transcript.language})")

    # Optionally translate
    if translate_to:
        from smart_subtitle.stages.reference_translation import ReferenceTranslationStage

        ref_stage = ReferenceTranslationStage(cfg, cache)
        transcript = ref_stage.run(transcript)

        translated_count = sum(1 for s in transcript.segments if s.translation)
        click.echo(f"Translated {translated_count} segments to {translate_to}")

    # Write output
    if output:
        use_translation = bool(translate_to)
        write_segments_as_subtitle(
            transcript.segments,
            Path(output),
            format=Path(output).suffix.lstrip(".") or "srt",
            use_translation=use_translation,
        )
        click.echo(f"Saved to: {output}")


@cli.command("clear-cache")
@click.pass_context
def clear_cache(ctx):
    """Clear all cached data."""
    cfg: Config = ctx.obj["config"]
    from smart_subtitle.cache.manager import CacheManager

    cache = CacheManager(cfg.cache.resolved_directory)
    cache.clear()
    click.echo("Cache cleared")


@cli.command("ui")
@click.option("--port", default=8080, help="Port to run the Web UI on")
@click.option("--host", default="127.0.0.1", help="Host IP to bind the Web UI to")
def run_ui(port: int, host: str):
    """Launch the interactive Subtitle Editor Web UI."""
    try:
        import uvicorn
        from smart_subtitle.ui.app import app
        click.echo(f"Starting Smart Subtitle Web UI at http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
    except ImportError:
        click.echo("Error: FastAPI/Uvicorn not installed. Please install with 'pip install fastapi uvicorn' first.")

def main():
    cli()


if __name__ == "__main__":
    main()
