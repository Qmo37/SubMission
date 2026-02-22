# Proposal: Dynamic Anchor-Based Alignment Architecture

Your intuition is spot on. A single global offset (like what `alass` currently calculates) completely breaks down if the subtitle file was timed for a TV broadcast (with commercial breaks) but the video is a Web-DL (no commercial breaks). The offset might be +2 seconds for the first 10 minutes, and then suddenly shift to -40 seconds after a commercial cut.

The architecture you just described—using the fan subtitle as the untouchable core structure, and using Whisper purely as a **Dynamic Anchor Map**—is the holy grail of robust subtitle alignment.

Here is a formalized breakdown of how we can build this pipeline.

## The Core Concept: The Anchor Map

Instead of forcing Whisper segments to become the subtitles, we will use Whisper to build a "terrain map" of the video. We drop "anchors" wherever the subtitle file perfectly matches the audio, and use those anchors to warp the rest of the subtitle file into place.

### The New Pipeline Flow

#### 1. Independent Generation (No Change)
- Run Whisper to get word-level audio timestamps.
- Translate Whisper segments to a baseline language using the local LLM, strictly enforcing **Traditional Chinese (Taiwan Mandarin)** phrasing.

#### 2. Semantic Anchoring (New Stage)
We scan both the Primary Subtitle file and the translated Whisper transcript to find **Unquestionable Matches**.
- **The Rule of 3**: We look for sequences where 3 (or more) consecutive lines in the Subtitle file have a very high semantic similarity (e.g., > 0.85) to 3 consecutive lines in the Whisper transcript.
- When we find this sequence, we lock it in as an **Anchor Block**.
- We record the temporal offset for this specific block: `Offset = Whisper_Time - Original_Subtitle_Time`.

#### 3. Building the Dynamic Offset Interpolator (New Stage)
Once we scan the whole video, we will have a sparse map of anchors.
*Example:*
- **Anchor A (0m - 10m)**: Offset is `+1.5s`
- *(Commercial break happens in the TV broadcast text, but not the video)*
- **Anchor B (12m - 25m)**: Offset is `-118.0s`
- **Anchor C (28m - 40m)**: Offset is `-240.0s`

We build a function that takes *any* original subtitle timestamp and evaluates its exact localized offset using **Linear Interpolation** between the nearest valid Anchor Blocks, creating a mathematically smooth mapping across the entire timeline.

#### 4. The Subtitle-Led Execution (Refined Merge Stage)
We iterate through every single line in the Primary Subtitle file exactly once:
- **Condition A (It is an Anchor Line)**: The line belongs to an Anchor Block. We give it the hyper-accurate, word-level timestamps from its corresponding Whisper segment.
- **Condition B (It is an Unmatched Line)**: Whisper missed the audio, or the translation was too blurry to match. We look at the Dynamic Interpolator to see what the offset *should* be at this specific minute of the video, apply that offset to the original human timestamp, and inject the line.

## Why this is vastly superior:

1. **Immunity to Video Cuts**: It effortlessly handles different video releases (TV vs Web-DL, Director's Cuts with extra scenes). The mathematical offset simply "jumps" to the correct value after a commercial break based on the next localized Anchor Block.
2. **Zero Dropped Lines**: As you noted, the first few lines of an episode (which Whisper often misses if they are spoken during a noisy opening theme song) will just grab the offset from the first valid Anchor Block found a minute later, allowing them to be placed perfectly.
3. **No More Forced Fallbacks**: We no longer need to rely on external C++ tools like `alass` to do a naive audio-to-audio global shift. We are aligning purely on intelligent, contextual *semantics*, which makes the tool entirely self-contained in Python.

## Implementation Steps needed to achieve this:

To pivot to this architecture, we would need to:
1. Deprecate the `GlobalAlignmentStage` (remove the `alass` dependency).
2. Rewrite `TextMatcher` to evaluate *sequences* of lines rather than isolated segments to establish the high-confidence Anchor Blocks.
3. Implement a `DynamicOffsetMapper` class that intelligently groups these anchors and returns the correct localized offset for any given point in time.
4. Update the `MergeStage` to pull from this dynamic mapper when injecting missing lines.

What do you think of this formalized structure? This would be a completely bespoke, state-of-the-art alignment engine.
