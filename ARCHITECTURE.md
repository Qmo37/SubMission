# Smart Subtitle Architecture

`smart_subtitle` is a high-precision subtitle alignment and translation pipeline. Unlike naive audio-to-text alignment tools that blindly bind to Voice Activity Detection (VAD) timestamps, this architecture relies on a **Subtitle-Led Iteration** pattern combined with **Offset Consensus Voting** to generate mathematically perfect timelines immune to commercial breaks, LLM hallucinations, and audio gaps.

---

## 1. System Components

The project is structured as a monolithic repository that bundles a high-performance Python processing engine with an embedded interactive React web interface.

### 1.1 Python Core Engine (`src/smart_subtitle/`)
- Utilizes `faster-whisper` for word-level speech boundaries.
- Uses local LLMs (via Ollama/Llama-3-Taiwan) for baseline text translation and Gap Filling semantics.
- Computes highly optimized 1D Sliding-Window Offset distance clusters to calculate non-linear video cuts.
- Evaluates Smooth Time Distance curves constrained by Chronological Monotonicity to perfectly map translated strings to audio waveforms.

### 1.2 Web UI Dashboard (`src/smart_subtitle/ui/`)
To effectively tweak complex pipeline configurations (like Sliding Window widths and text-matching thresholds) and visualize physical offset mappings, a web interface is bundled directly into the CLI.
- **Backend**: `FastAPI` wraps the core engine into REST API routes, exposing the `/api/align/anchors` and `/api/config` endpoints. It relies on `uvicorn` to dynamically serve the React build.
- **Frontend**: A custom React multi-track visualizer managed by Vite. Key features include:
  - **Dynamic Layout**: A glassmorphism-themed layout integrating a top-level file picker bar, video player, configuration sidebar, and bottom timeline.
  - **Timeline Management**: Renders `<div className="timeline-block">` DOM arrays bound to a synchronized HTML5 `<video>` cursor, allowing users to physically drag subtitle blocks with mathematically constrained chronological collision detection. Features sticky track-toggles for isolating specific audio/subtitle representations.
  - **Pipeline Control**: Embedded Stage Selectors and live progress indication for triggering specific engine stages (e.g., Audio Extraction, Anchor Mapping) directly from the browser.

---

## 2. Pipeline Execution Stages

The core engine sequentially routes through 7 strict computational stages. Each stage is heavily cached (hashed by specific dependency inputs and UI parameters) to enable sub-second re-renders inside the Web UI.

### Stage 1: Extraction & Preprocessing (`AudioExtractionStage`)
Extracts a normalized 16kHz MONO `.wav` stream from the video (`ffmpeg`). If the user inputs a bilingual `.srt` file containing both translated and native tracks sequentially, the preprocessor aggressively chops the file over the median indices into two cleanly separated single-language files.

### Stage 2: Transcription (`TranscriptionStage`)
Executes `faster-whisper`. Critically, it requests `word_timestamps=True` and enforces `condition_on_previous_text=False` to prevent the LLM from hallucinating audio across massive silent gaps. This generates structurally pure waveform fragments.

### Stage 3: Reference Translation (`ReferenceTranslationStage`)
Foreign source language Whisper segments are batch-translated to the Target Baseline Language (e.g., Traditional Chinese) using `Llama-3-Taiwan`. The underlying prompts strictly prioritize localized **Taiwanese Mandarin** phrasing and vocabulary. This provides the semantic bridge between the raw audio and whatever human-edited `.srt` files the user provides.

4. **Dynamic Anchor Mapping (`AnchorMapperStage`)**
*Replaces legacy tools like `alass`.* 
It scans the primary `.srt` and the translated Whisper nodes to construct a non-linear Temporal Displacement Map.
1. **Candidate Match Generation**: Creates an N x M matrix matching subtitle strings to translated Whisper segments (if semantic similarity `> 0.3`). Calculates the exact timestamp offset `delta` for every pair.
2. **Offset Consensus Voting**: Sliding clusters group string matches by timestamp offsets. We strictly enforce a **Rule of 3**—meaning a cluster must contain at least 3 unique, sequential, high-confidence human translation matches to form an anchor block.
3. **Linear Time Interpolation**: The resulting Anchor Map evaluates time using linear interpolation between fixed anchor points, ensuring smooth temporal offset transitions and mathematically neutralizing audio gaps and commercial breaks.

### Stage 5: Fine Alignment (`FineAlignmentStage` -> `TextMatcher`)
Matches individual human-edited lines to discrete Whisper audio segments, strictly enforcing chronological ordering to prevent greedy temporal warping.

**The Scoring Engine (`TextMatcher`)**:
1. **Chronological Monotonicity Guardrails**: Prevents lines from snapping to false-positive text chunks outside their chronological sequence. A line *must* begin sequentially after the start constraints of the previous matched item.
2. **Time Distance Penalty**: Uses a continuous sliding curve measuring the absolute distance between actual spoken audio and the dynamically anchored expected subtitle time. If distance exceeds `2.0s`, it institutes a hard clamp, completely throwing out the match unless literal string certainty approaches `>0.6`.
3. **Semantic Gap Penalty (Pacing)**: Computes the human-authored conversational gap between the current sentence and the previous sentence. Punishes candidate matches that would violate the intended pacing.

### Stage 6: The Subtitle-Led Merge (`MergeStage`)
Instead of iterating blindly over the Whisper audio (which would drop lines wherever Voice Activity Detection failed), the iterator drives across the highest-ranked Subtitle File (*The Primary Backbone*).

- **For Matched Lines**: Adopts the exact Whisper spoken starting boundary (ensuring millimeter precise audio-sync) but rigorously preserves the *Original Human Duration* by adding it to the start boundary. This automatically fixes Whisper's "Trailing Silence Hanging" bug.
- **For Missing Lines**: Queries the `AnchorMap` generated in Stage 4. Interpolates the precise dynamically shifted timestamp and safely drops the missed line into the synchronized video timeline.
- **Global Timeline Delay**: Applies a strict, configurable positive shift (default `0.4s`) to all finalized subtitles to ensure comfortable reading-start reactivity for the viewing audience.

### Stage 7: LLM Contextual Gap Filling (`GapFillingStage`)
Identifies spans of valid translated Whisper audio that have zero corresponding lines inside any human-authored Subtitle track. The pipeline groups the orphan audio chunk with its immediate surrounding context lines and prompts the local LLM to structurally repair the timeline void and generate matching text.
