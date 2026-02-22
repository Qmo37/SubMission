"""Pipeline orchestrator connecting all 7 stages."""

from __future__ import annotations

from pathlib import Path

from smart_subtitle.cache.manager import CacheManager
from smart_subtitle.core.config import Config
from smart_subtitle.core.models import (
    CompleteSubtitle,
    SubtitleFile,
    SubtitleSource,
)
from smart_subtitle.stages.audio_extraction import AudioExtractionStage
from smart_subtitle.stages.fine_alignment import FineAlignmentInput, FineAlignmentStage
from smart_subtitle.stages.gap_filling import GapFillingInput, GapFillingStage
from smart_subtitle.stages.anchor_mapper import (
    AnchorMapperInput,
    AnchorMapperStage,
)
from smart_subtitle.stages.merge import MergeInput, MergeStage
from smart_subtitle.stages.reference_translation import ReferenceTranslationStage
from smart_subtitle.stages.transcription import TranscriptionStage
from smart_subtitle.subtitle.io import load_subtitle, write_subtitle
from smart_subtitle.subtitle.preprocessor import preprocess_subtitle, cross_map_subtitles
from smart_subtitle.utils.logger import get_logger


class SubtitleAlignmentPipeline:
    """Main pipeline orchestrator."""

    def __init__(self, config: Config):
        self.config = config
        self.cache = CacheManager(
            cache_dir=config.cache.resolved_directory,
            enabled=config.cache.enabled,
            max_size_gb=config.cache.max_size_gb,
        )
        self.logger = get_logger("Pipeline", config.logging.level)

        # Initialize stages
        self.audio_extraction = AudioExtractionStage(config, self.cache)
        self.transcription = TranscriptionStage(config, self.cache)
        self.reference_translation = ReferenceTranslationStage(config, self.cache)
        self.anchor_mapper = AnchorMapperStage(config, self.cache)
        self.fine_alignment = FineAlignmentStage(config, self.cache)
        self.merge = MergeStage(config, self.cache)
        self.gap_filling = GapFillingStage(config, self.cache)

    def run(
        self,
        video_path: Path,
        subtitle_paths: list[Path],
        output_path: Path,
        quality_ranks: list[int] | None = None,
        fill_gaps: bool = True,
        force_stages: list[str] | None = None,
    ) -> CompleteSubtitle:
        """Execute the full 7-stage pipeline.

        Args:
            video_path: Path to video file
            subtitle_paths: Paths to subtitle files
            output_path: Where to write the final subtitle
            quality_ranks: Quality rank per subtitle (0=best). Defaults to input order.
            fill_gaps: Whether to run Stage 7 (LLM gap filling)
            force_stages: Stage names to force re-run (skip cache)
        """
        force = set(force_stages or [])

        # Stage 1: Audio Extraction
        self.logger.info("=" * 60)
        self.logger.info("Stage 1/7: Audio Extraction")
        audio_path = self.audio_extraction.run(video_path, force="audio_extraction" in force)

        # Stage 2: Transcription
        self.logger.info("=" * 60)
        self.logger.info("Stage 2/7: Transcription")
        reference = self.transcription.run(audio_path, force="transcription" in force)

        # Stage 3: Reference Translation
        self.logger.info("=" * 60)
        self.logger.info("Stage 3/7: Reference Translation")
        reference = self.reference_translation.run(reference, force="translation" in force)

        # Load and preprocess subtitle files
        if quality_ranks is None:
            quality_ranks = list(range(len(subtitle_paths)))

        work_dir = self.cache.cache_dir / "preprocessed_subs"
        
        processed_paths = []
        processed_ranks = []
        subtitles = []
        primary_processed_path = None
        secondary_processed_path = None
        
        for path, rank in zip(subtitle_paths, quality_ranks):
            result = preprocess_subtitle(path, output_dir=work_dir)
            
            if rank == 0:
                primary_processed_path = result.primary_path
            else:
                secondary_processed_path = result.primary_path
                
            processed_paths.append(result.primary_path)
            processed_ranks.append(rank)
            
            if result.is_bilingual and result.secondary_path:
                processed_paths.append(result.secondary_path)
                processed_ranks.append(rank + 5)
                
        # Subtitle Cross-Mapping (Optional)
        # If we have both a primary and secondary track (e.g., zh-cn and zh-tw),
        # swap the raw text from the secondary onto the primary timings before alignment.
        strategy = self.config.alignment.bilingual_cross_match_strategy
        if strategy == "lexical" and primary_processed_path and secondary_processed_path:
            mapped_path = work_dir / f"cross_mapped_{primary_processed_path.name}"
            cross_map_subtitles(
                primary_path=primary_processed_path,
                secondary_path=secondary_processed_path,
                output_path=mapped_path
            )
            # Update the primary path to point to the cross-mapped file
            for i, p in enumerate(processed_paths):
                if p == primary_processed_path:
                    processed_paths[i] = mapped_path
                    break

        for path, rank in zip(processed_paths, processed_ranks):
            sub = load_subtitle(path, quality_rank=rank)
            self.logger.info(
                "Loaded subtitle: %s (%d lines, language=%s, rank=%d)",
                path.name,
                len(sub.lines),
                sub.language,
                rank,
            )
            subtitles.append(sub)

        # Stage 4: Dynamic Anchor Mapping
        self.logger.info("=" * 60)
        self.logger.info("Stage 4/7: Dynamic Anchor Mapping")
        anchor_maps = self.anchor_mapper.run(
            AnchorMapperInput(
                reference=reference,
                subtitles=subtitles,
            ),
            force="anchor_mapping" in force,
        )

        # Stage 5: Fine Alignment
        self.logger.info("=" * 60)
        self.logger.info("Stage 5/7: Fine Alignment")
        aligned_collections = self.fine_alignment.run(
            FineAlignmentInput(
                reference=reference,
                subtitles=subtitles,
                anchor_maps=anchor_maps,
            ),
            force="fine_alignment" in force,
        )

        # Stage 6: Merge
        self.logger.info("=" * 60)
        self.logger.info("Stage 6/7: Merge")
        merged = self.merge.run(
            MergeInput(
                reference=reference,
                aligned_collections=aligned_collections,
            ),
            force="merge" in force,
        )

        # Stage 7: Gap Filling
        if fill_gaps and self.config.gap_filling.enabled and merged.gaps:
            self.logger.info("=" * 60)
            self.logger.info("Stage 7/7: Gap Filling")
            complete = self.gap_filling.run(
                GapFillingInput(
                    merged=merged,
                    source_language=reference.language,
                ),
                force="gap_filling" in force,
            )
        else:
            if merged.gaps:
                self.logger.info("Skipping gap filling (%d gaps remain)", len(merged.gaps))
            complete = CompleteSubtitle(
                segments=merged.segments,
                filled_gaps=[],
                total_coverage=merged.coverage,
            )

        # Write output
        self.logger.info("=" * 60)
        output_format = self.config.output.format
        write_subtitle(complete, output_path, format=output_format)
        self.logger.info("Output written to: %s", output_path)
        self.logger.info(
            "Final: %d segments, %.1f%% coverage",
            len(complete.segments),
            complete.total_coverage,
        )

        return complete
