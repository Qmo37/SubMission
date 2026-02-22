"""Dynamic Anchor Mapping Stage."""

import logging
from pathlib import Path

from smart_subtitle.core.config import AlignmentConfig
from smart_subtitle.core.models import (
    AnchorBlock,
    AnchorMap,
    ReferenceTranscript,
    SubtitleFile,
    TimeSpan,
)
from smart_subtitle.subtitle.normalizer import TextNormalizer


from smart_subtitle.cache.manager import CacheManager
from .base import PipelineStage

class AnchorMapperInput:
    def __init__(
        self,
        reference: ReferenceTranscript,
        subtitles: list[SubtitleFile],
    ):
        self.reference = reference
        self.subtitles = subtitles


class AnchorMapperStage(PipelineStage[AnchorMapperInput, dict[str, AnchorMap]]):
    """Finds high-confidence semantic sync sequences to map temporal offsets."""

    @property
    def stage_name(self) -> str:
        return "Dynamic Anchor Mapping"
        
    def _cache_key(self, input_data: AnchorMapperInput) -> str | None:
        parts = [input_data.reference.audio_hash]
        for sub in input_data.subtitles:
            parts.append(CacheManager.hash_file(Path(sub.path)))
            
        am_cfg = self.config.alignment.anchor_mapper
        params_hash = CacheManager.hash_string(
            f"window={am_cfg.window_size},"
            f"step={am_cfg.step_size},"
            f"sim={am_cfg.min_sim_threshold},"
            f"tol={am_cfg.cluster_tolerance},"
            f"score={am_cfg.min_cluster_score},"
            f"uni={am_cfg.min_unique_lines}"
        )
        parts.append(params_hash)
        
        combined = "|".join(parts)
        return f"anchor_map_{CacheManager.hash_string(combined)}"
        
    def _serialize(self, output: dict[str, AnchorMap]) -> dict:
        return {k: v.model_dump() for k, v in output.items()}

    def _deserialize(self, data: dict) -> dict[str, AnchorMap]:
        return {k: AnchorMap(**v) for k, v in data.items()}

    def _process(self, input_data: AnchorMapperInput) -> dict[str, AnchorMap]:
        results = {}
        for sub_file in input_data.subtitles:
            self.logger.info("  Mapping dynamic anchors for %s", sub_file.path)
            map_result = self._map_anchors(input_data.reference, sub_file)
            results[sub_file.path] = map_result
        return results

    def _map_anchors(self, reference: ReferenceTranscript, subtitle_file: SubtitleFile) -> AnchorMap:
        normalizer = TextNormalizer()
        anchors: list[AnchorBlock] = []
        
        # Use translated segments if available, otherwise fallback to native whisper text
        valid_whisper = reference.segments
        if not valid_whisper or not subtitle_file.lines:
            return AnchorMap(subtitle_path=subtitle_file.path, anchors=[])
            
        cfg = self.config.alignment.anchor_mapper
        
        # 1. Generate all candidate matches
        candidates = []
        self.logger.info("Generating candidate matches...")
        for i, sub in enumerate(subtitle_file.lines):
            for j, w in enumerate(valid_whisper):
                w_text = w.translation or w.text
                sim = normalizer.similarity(sub.text, w_text)
                if sim > cfg.min_sim_threshold:
                    offset = w.timespan.start - sub.timespan.start
                    candidates.append({
                        'sub_idx': i,
                        'w_idx': j,
                        'offset': offset,
                        'sim': sim,
                        'sub': sub,
                        'w': w,
                    })

        if not candidates:
            return AnchorMap(subtitle_path=subtitle_file.path, anchors=[])

        self.logger.info(f"Generated {len(candidates)} candidates.")
        
        # 2. Sliding window over subtitles
        window_size = cfg.window_size
        step_size = cfg.step_size
        
        for window_start in range(0, len(subtitle_file.lines), step_size):
            window_end = window_start + window_size
            
            # Get candidates in this window
            window_candidates = [c for c in candidates if window_start <= c['sub_idx'] < window_end]
            if not window_candidates:
                continue
                
            # 3. Cluster offsets using a simple 1D clustering
            clusters = []
            for c in window_candidates:
                placed = False
                for cluster in clusters:
                    if abs(cluster['center'] - c['offset']) <= cfg.cluster_tolerance:
                        cluster['items'].append(c)
                        # Recalculate center
                        cluster['center'] = sum(x['offset'] * x['sim'] for x in cluster['items']) / sum(x['sim'] for x in cluster['items'])
                        cluster['score'] += c['sim']
                        placed = True
                        break
                if not placed:
                    clusters.append({
                        'center': c['offset'],
                        'items': [c],
                        'score': c['sim']
                    })
            
            if not clusters:
                continue
                
            best_cluster = max(clusters, key=lambda cl: cl['score'])
            
            # 4. Check if the cluster is strong enough
            unique_sub_indices = len(set(x['sub_idx'] for x in best_cluster['items']))
            
            if best_cluster['score'] > cfg.min_cluster_score and unique_sub_indices >= cfg.min_unique_lines:
                items = sorted(best_cluster['items'], key=lambda x: x['sub_idx'])
                
                mid_sub_idx = window_start + (window_size // 2)
                mid_sub_idx = min(mid_sub_idx, len(subtitle_file.lines) - 1)
                mid_sub = subtitle_file.lines[mid_sub_idx]
                
                offset = best_cluster['center']
                
                block = AnchorBlock(
                    subtitle_timespan=mid_sub.timespan,
                    whisper_timespan=mid_sub.timespan.shift(offset),
                    offset=offset,
                    confidence=min(1.0, best_cluster['score'] / 5.0),
                    subtitle_start_idx=items[0]['sub_idx'],
                    subtitle_end_idx=items[-1]['sub_idx'],
                    whisper_start_id=items[0]['w_idx'],
                    whisper_end_id=items[-1]['w_idx'],
                )
                
                # Deduplicate anchors
                if anchors:
                    last_anchor = anchors[-1]
                    time_diff = abs(last_anchor.subtitle_timespan.start - block.subtitle_timespan.start)
                    offset_diff = abs(last_anchor.offset - block.offset)
                    if time_diff < 30.0 and offset_diff < 1.0:
                        continue
                
                anchors.append(block)
                self.logger.debug(f"Found window anchor: sub_time={block.subtitle_timespan.start:.1f}s, offset={offset:.2f}s, score={best_cluster['score']:.2f}")

        self.logger.info("  -> Found %d dynamic anchor blocks", len(anchors))
        
        return AnchorMap(
            subtitle_path=subtitle_file.path,
            anchors=anchors
        )
