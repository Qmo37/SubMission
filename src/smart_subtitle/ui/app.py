"""FastAPI backend for Smart Subtitle Web UI."""

import logging
import mimetypes
import os
import threading
import tempfile
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from smart_subtitle.core.config import Config

app = FastAPI(title="Smart Subtitle Editor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve paths
CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"
UI_DIST = Path(__file__).parent / "dist"

# Job store: job_id -> { status, stage, detail, progress, result, error, latest_stage }
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ── Log handler that feeds job progress ────────────────────────────────────


class JobLogHandler(logging.Handler):
    """Captures smart_subtitle.* log messages into the job's 'detail' field."""

    def __init__(self, job_id: str):
        super().__init__(level=logging.INFO)
        self.job_id = job_id

    def emit(self, record):
        msg = self.format(record)
        _set_job(self.job_id, detail=msg)


# ── Pydantic request/response models ──────────────────────────────────────


class AnchorMapperParams(BaseModel):
    window_size: int | None = None
    step_size: int | None = None
    min_sim_threshold: float | None = None
    cluster_tolerance: float | None = None
    min_cluster_score: float | None = None


class TranscriptionParams(BaseModel):
    model: str | None = None


class FineAlignmentParams(BaseModel):
    text_weight: float | None = None
    time_weight: float | None = None
    start_offset: float | None = None
    time_tolerance: float | None = None
    min_match_score: float | None = None
    gap_penalty_weight: float | None = None
    high_confidence_override: float | None = None


class ConfigUpdateRequest(BaseModel):
    anchor_mapper: AnchorMapperParams | None = None
    fine_alignment: FineAlignmentParams | None = None
    transcription: TranscriptionParams | None = None


class AlignRequest(BaseModel):
    video_path: str
    subtitle_paths: list[str]
    quality_ranks: list[int] | None = None


# ── Helper ─────────────────────────────────────────────────────────────────


def _load_config() -> Config:
    if CONFIG_PATH.exists():
        return Config.from_file(CONFIG_PATH)
    return Config.from_defaults()


def _save_config(cfg: Config) -> None:
    data = cfg.model_dump()
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def _set_job(job_id: str, **kwargs):
    with _jobs_lock:
        if job_id not in _jobs:
            _jobs[job_id] = {}
        _jobs[job_id].update(kwargs)


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return _jobs.get(job_id, {}).copy() if job_id in _jobs else None


# ── API routes ─────────────────────────────────────────────────────────────


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/config")
def get_config():
    """Return alignment config parameters."""
    cfg = _load_config()
    return {
        "anchor_mapper": cfg.alignment.anchor_mapper.model_dump(),
        "fine_alignment": cfg.alignment.fine_alignment.model_dump(),
        "transcription": cfg.transcription.model_dump(),
        "alignment_global": {
            "bilingual_cross_match_strategy": cfg.alignment.bilingual_cross_match_strategy,
            "global_delay": cfg.alignment.global_delay
        }
    }

@app.put("/api/config")
def update_config(body: ConfigUpdateRequest):
    """Update alignment config parameters and persist to default.yaml."""
    cfg = _load_config()

    overrides: dict = {}
    if body.anchor_mapper:
        am = {k: v for k, v in body.anchor_mapper.model_dump().items() if v is not None}
        if am:
            overrides.setdefault("alignment", {})["anchor_mapper"] = am
    if body.fine_alignment:
        fa = {k: v for k, v in body.fine_alignment.model_dump().items() if v is not None}
        if fa:
            overrides.setdefault("alignment", {})["fine_alignment"] = fa
    if body.transcription:
        tr = {k: v for k, v in body.transcription.model_dump().items() if v is not None}
        if tr:
            overrides.setdefault("transcription", {}).update(tr)
    
    # Check for raw dictionary payload for alignment global config overrides
    if hasattr(body, "alignment_global") and body.alignment_global:
        overrides.setdefault("alignment", {}).update(body.alignment_global)
    # Support direct dict access if fastapi parses it generically
    elif isinstance(body, dict) and "alignment_global" in body:
        overrides.setdefault("alignment", {}).update(body["alignment_global"])

    if overrides:
        cfg = cfg.merge_overrides(overrides)
        _save_config(cfg)

    return {
        "anchor_mapper": cfg.alignment.anchor_mapper.model_dump(),
        "fine_alignment": cfg.alignment.fine_alignment.model_dump(),
        "transcription": cfg.transcription.model_dump(),
        "alignment_global": {
            "bilingual_cross_match_strategy": cfg.alignment.bilingual_cross_match_strategy,
            "global_delay": cfg.alignment.global_delay
        }
    }


# ── File browser API ──────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".flv", ".wmv", ".ts", ".m4v"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}

FILTER_PRESETS = {
    "video": VIDEO_EXTENSIONS,
    "subtitle": SUBTITLE_EXTENSIONS,
}


@app.get("/api/browse")
def browse_filesystem(dir: str | None = None, filter: str | None = None):
    """Browse local filesystem for file selection.

    Query params:
        dir: Directory to list (defaults to user home)
        filter: 'video' or 'subtitle' to restrict file types shown
    """
    home = Path.home()
    target = Path(dir) if dir else home

    # Security: resolve symlinks and ensure we stay under home
    try:
        resolved = target.resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {resolved}")

    # Allow browsing under home, /media, /mnt, /tmp, and the project directory
    allowed_roots = [home.resolve(), Path("/media").resolve(), Path("/mnt").resolve(),
                     Path("/tmp").resolve(), Path(__file__).parent.parent.parent.parent.resolve()]
    if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: outside allowed directories")

    allowed_exts = FILTER_PRESETS.get(filter) if filter else None

    entries = []
    try:
        for item in sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith("."):
                continue
            is_dir = item.is_dir()
            if not is_dir and allowed_exts and item.suffix.lower() not in allowed_exts:
                continue
            size_mb = None
            if not is_dir:
                try:
                    size_mb = round(item.stat().st_size / (1024 * 1024), 1)
                except OSError:
                    pass
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": is_dir,
                "size_mb": size_mb,
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied reading directory")

    parent_dir = str(resolved.parent) if resolved != home else None

    return {
        "current_dir": str(resolved),
        "parent_dir": parent_dir,
        "entries": entries,
    }


# ── Video streaming with Range support ────────────────────────────────────


@app.get("/api/video")
async def stream_video(path: str, request: Request):
    """Stream video with Range header support for seeking."""
    video_path = Path(path)
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail=f"Video not found: {path}")

    file_size = video_path.stat().st_size
    content_type = mimetypes.guess_type(str(video_path))[0] or "video/mp4"

    range_header = request.headers.get("range")

    if range_header:
        # Parse Range: bytes=start-end
        range_spec = range_header.replace("bytes=", "")
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        content_length = end - start + 1

        def iter_file():
            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk_size = min(65536, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iter_file(),
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": content_type,
            },
        )
    else:
        def iter_full():
            with open(video_path, "rb") as f:
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    yield data

        return StreamingResponse(
            iter_full(),
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Type": content_type,
            },
        )


# ── Export endpoint ───────────────────────────────────────────────────────


@app.get("/api/export/{job_id}")
def export_subtitle(job_id: str):
    """Export final subtitle as .srt download."""
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.get("result")
    if not result:
        raise HTTPException(status_code=400, detail="Job has no result yet")

    # Determine which stage data to export (latest available)
    stages = result.get("stages", {})
    latest = job.get("latest_stage", 4)

    # Find the best output blocks
    output_blocks = None
    for stage_num in [7, 6, 5]:
        stage_key = str(stage_num)
        if stage_key in stages and stages[stage_key].get("output_blocks"):
            output_blocks = stages[stage_key]["output_blocks"]
            break

    if not output_blocks:
        raise HTTPException(status_code=400, detail="No output stage data available for export")

    import pysubs2
    subs = pysubs2.SSAFile()
    for block in output_blocks:
        text = block.get("text", "")
        if not text:
            continue
        event = pysubs2.SSAEvent(
            start=int(block["start"] * 1000),
            end=int(block["end"] * 1000),
            text=text,
        )
        subs.events.append(event)
    subs.sort()

    tmp = tempfile.NamedTemporaryFile(suffix=".srt", delete=False)
    subs.save(tmp.name, format_="srt")
    tmp.close()

    video_path_str = job.get("video_path", "")
    base_name = Path(video_path_str).stem if video_path_str else "output"
    download_name = f"{base_name}-SmartSubtitle.srt"

    return FileResponse(
        tmp.name,
        media_type="application/x-subrip",
        filename=download_name,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


# ── Two-phase pipeline ────────────────────────────────────────────────────


@app.post("/api/align/anchors")
async def run_anchor_alignment(body: AlignRequest):
    """Start two-phase pipeline. Phase 1 (stages 1-4) returns preview data,
    then phase 2 (stages 5-7) auto-continues in background."""
    video = Path(body.video_path)
    if not video.exists():
        raise HTTPException(status_code=400, detail=f"Video not found: {body.video_path}")

    sub_paths = []
    for p in body.subtitle_paths:
        sp = Path(p)
        if not sp.exists():
            raise HTTPException(status_code=400, detail=f"Subtitle not found: {p}")
        sub_paths.append(sp)

    cfg = _load_config()
    job_id = str(uuid.uuid4())[:8]

    _set_job(
        job_id,
        status="running",
        stage="Initializing...",
        detail="",
        progress=None,
        result=None,
        error=None,
        latest_stage=0,
    )

    def _run_stages():
        handler = JobLogHandler(job_id)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger("smart_subtitle")
        root_logger.addHandler(handler)

        try:
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

            cache = CacheManager(
                cache_dir=cfg.cache.resolved_directory,
                enabled=cfg.cache.enabled,
                max_size_gb=cfg.cache.max_size_gb,
            )

            # ── Phase 1: Stages 1-4 ──

            # Stage 1: Audio Extraction
            _set_job(job_id, stage="Stage 1/7: Extracting audio...", progress=None)
            audio_stage = AudioExtractionStage(cfg, cache)
            audio_path = audio_stage.run(video)

            # Stage 2: Transcription
            _set_job(job_id, stage="Stage 2/7: Transcribing with Whisper...", progress=None)
            trans_stage = TranscriptionStage(cfg, cache)
            reference = trans_stage.run(audio_path)

            _set_job(
                job_id,
                stage="Stage 2/7: Transcription complete",
                progress={"current": len(reference.segments), "total": len(reference.segments), "unit": "segments"},
            )

            # Stage 3: Translation
            total_segs = len(reference.segments)
            _set_job(
                job_id,
                stage=f"Stage 3/7: Translating {total_segs} segments...",
                progress={"current": 0, "total": total_segs, "unit": "segments"},
            )
            ref_trans_stage = ReferenceTranslationStage(cfg, cache)

            original_translate = None
            try:
                from smart_subtitle.translation import batch as batch_mod
                original_translate = batch_mod.translate_segments

                def patched_translate(segments, source_language, config, glossary=None, on_progress=None):
                    def _progress(batch_idx, total_batches):
                        _set_job(
                            job_id,
                            stage=f"Stage 3/7: Translating batch {batch_idx + 1}/{total_batches}...",
                            progress={"current": batch_idx + 1, "total": total_batches, "unit": "batches"},
                        )
                        if on_progress:
                            on_progress(batch_idx, total_batches)

                    return original_translate(
                        segments, source_language, config, glossary, on_progress=_progress,
                    )

                batch_mod.translate_segments = patched_translate
                reference = ref_trans_stage.run(reference)
            finally:
                if original_translate:
                    batch_mod.translate_segments = original_translate

            # Load & preprocess subtitles
            _set_job(job_id, stage="Stage 4/7: Loading subtitles & mapping anchors...", progress=None)
            quality_ranks = body.quality_ranks or list(range(len(sub_paths)))
            work_dir = cache.cache_dir / "preprocessed_subs"

            processed_paths = []
            processed_ranks = []
            for path, rank in zip(sub_paths, quality_ranks):
                result = preprocess_subtitle(path, output_dir=work_dir)
                processed_paths.append(result.primary_path)
                processed_ranks.append(rank)
                if result.is_bilingual and result.secondary_path:
                    processed_paths.append(result.secondary_path)
                    processed_ranks.append(rank + 5)

            subtitles = []
            for path, rank in zip(processed_paths, processed_ranks):
                subtitles.append(load_subtitle(path, quality_rank=rank))

            # Stage 4: Anchor Mapping
            anchor_stage = AnchorMapperStage(cfg, cache)
            anchor_maps = anchor_stage.run(
                AnchorMapperInput(reference=reference, subtitles=subtitles)
            )

            # Build phase 1 response
            whisper_blocks = []
            for seg in reference.segments:
                whisper_blocks.append({
                    "id": f"w-{seg.id}",
                    "type": "whisper",
                    "start": seg.timespan.start,
                    "end": seg.timespan.end,
                    "text": seg.translation or seg.text,
                    "original_text": seg.text,
                })

            subtitle_blocks = {}
            for sub_file in subtitles:
                sub_key = sub_file.path
                sub_block_list = []
                for line in sub_file.lines:
                    sub_block_list.append({
                        "id": f"s-{sub_file.path}-{line.index}",
                        "type": "subtitle",
                        "start": line.timespan.start,
                        "end": line.timespan.end,
                        "text": line.text,
                    })
                subtitle_blocks[sub_key] = sub_block_list

            anchor_blocks_out = []
            for sub_path, amap in anchor_maps.items():
                for i, anchor in enumerate(amap.anchors):
                    anchor_blocks_out.append({
                        "id": f"a-{sub_path}-{i}",
                        "type": "anchor",
                        "start": anchor.whisper_timespan.start,
                        "end": anchor.whisper_timespan.end,
                        "offset": anchor.offset,
                        "confidence": anchor.confidence,
                        "subtitle_start_idx": anchor.subtitle_start_idx,
                        "subtitle_end_idx": anchor.subtitle_end_idx,
                    })

            duration = 0.0
            if reference.segments:
                duration = max(s.timespan.end for s in reference.segments)

            phase1_result = {
                "duration": duration,
                "whisper_blocks": whisper_blocks,
                "subtitle_blocks": subtitle_blocks,
                "anchor_blocks": anchor_blocks_out,
                "stages": {},
            }

            _set_job(job_id, status="complete", stage="Phase 1 complete — stages 5-7 running...",
                     progress=None, result=phase1_result, latest_stage=4)

            # ── Phase 2: Stages 5-7 (auto-continue) ──

            # Stage 5: Fine Alignment
            _set_job(job_id, stage="Stage 5/7: Fine alignment...", detail="")
            fine_stage = FineAlignmentStage(cfg, cache)
            aligned_collections = fine_stage.run(
                FineAlignmentInput(
                    reference=reference,
                    subtitles=subtitles,
                    anchor_maps=anchor_maps,
                )
            )

            # Snapshot stage 5
            stage5_blocks = []
            block_id = 0
            for collection in aligned_collections:
                for match in collection.matches:
                    block_id += 1
                    stage5_blocks.append({
                        "id": f"o5-{block_id}",
                        "start": match.final_timespan.start,
                        "end": match.final_timespan.end,
                        "text": match.subtitle_line.text,
                    })
                # Include unmatched lines with anchor-shifted times
                anchor_map = collection.anchor_map
                for line in collection.unmatched_subtitles:
                    block_id += 1
                    local_offset = anchor_map.get_offset(line.timespan.mid)
                    stage5_blocks.append({
                        "id": f"o5-{block_id}",
                        "start": line.timespan.start + local_offset,
                        "end": line.timespan.end + local_offset,
                        "text": line.text,
                    })
            stage5_blocks.sort(key=lambda b: b["start"])

            with _jobs_lock:
                if job_id in _jobs and _jobs[job_id].get("result"):
                    _jobs[job_id]["result"]["stages"]["5"] = {
                        "output_blocks": stage5_blocks,
                        "label": "Fine Alignment",
                    }
                    _jobs[job_id]["latest_stage"] = 5
                    _jobs[job_id]["stage"] = "Stage 5/7 complete"

            # Stage 6: Merge
            _set_job(job_id, stage="Stage 6/7: Merging...", detail="")
            merge_stage = MergeStage(cfg, cache)
            merged = merge_stage.run(
                MergeInput(
                    reference=reference,
                    aligned_collections=aligned_collections,
                )
            )

            # Snapshot stage 6
            stage6_blocks = []
            for seg in merged.segments:
                stage6_blocks.append({
                    "id": f"o6-{seg.id}",
                    "start": seg.timespan.start,
                    "end": seg.timespan.end,
                    "text": seg.translation or seg.text,
                })

            with _jobs_lock:
                if job_id in _jobs and _jobs[job_id].get("result"):
                    _jobs[job_id]["result"]["stages"]["6"] = {
                        "output_blocks": stage6_blocks,
                        "label": "Merge",
                    }
                    _jobs[job_id]["latest_stage"] = 6
                    _jobs[job_id]["stage"] = "Stage 6/7 complete"

            # Stage 7: Gap Filling
            if cfg.gap_filling.enabled and merged.gaps:
                _set_job(job_id, stage="Stage 7/7: Gap filling...", detail="")
                gap_stage = GapFillingStage(cfg, cache)
                complete = gap_stage.run(
                    GapFillingInput(
                        merged=merged,
                        source_language=reference.language,
                    )
                )

                stage7_blocks = []
                for seg in complete.segments:
                    stage7_blocks.append({
                        "id": f"o7-{seg.id}",
                        "start": seg.timespan.start,
                        "end": seg.timespan.end,
                        "text": seg.translation or seg.text,
                    })
            else:
                complete = CompleteSubtitle(
                    segments=merged.segments,
                    filled_gaps=[],
                    total_coverage=merged.coverage,
                )
                stage7_blocks = stage6_blocks  # Same as stage 6 if no gap filling

            with _jobs_lock:
                if job_id in _jobs and _jobs[job_id].get("result"):
                    _jobs[job_id]["result"]["stages"]["7"] = {
                        "output_blocks": stage7_blocks,
                        "label": "Gap Fill",
                    }
                    _jobs[job_id]["latest_stage"] = 7
                    _jobs[job_id]["stage"] = "Done"

        except Exception as e:
            logging.exception("Alignment job %s failed", job_id)
            _set_job(job_id, status="error", stage="Failed", error=str(e))
        finally:
            root_logger.removeHandler(handler)

    thread = threading.Thread(target=_run_stages, daemon=True)
    thread.start()

    return {"job_id": job_id}


@app.get("/api/align/status/{job_id}")
def get_job_status(job_id: str):
    """Poll for job progress."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── SPA fallback (must be last) ────────────────────────────────────────────


@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    requested_path = UI_DIST / full_path
    if full_path == "" or not requested_path.is_file():
        index_file = UI_DIST / "index.html"
        if not index_file.is_file():
            return {"error": "UI build not found. Run 'npm run build' in the ui directory."}
        return FileResponse(index_file)

    return FileResponse(requested_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("smart_subtitle.ui.app:app", host="127.0.0.1", port=8000, reload=True)
