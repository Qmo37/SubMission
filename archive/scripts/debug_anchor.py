import logging
from pathlib import Path
from smart_subtitle.core.config import Config
from smart_subtitle.core.pipeline import SubtitleAlignmentPipeline
from smart_subtitle.stages.anchor_mapper import AnchorMapperStage, AnchorMapperInput

logging.basicConfig(level=logging.INFO)

config = Config.from_defaults()
pipeline = SubtitleAlignmentPipeline(config)

audio_path = Path("tests/video1/snippet.mkv")
subs = [Path("tests/video1/trditional_big_time.srt")]

# Run the raw steps to get translation
input_data = pipeline.audio_extraction.run(audio_path)
ref = pipeline.transcription.run(input_data)
ref_translated = pipeline.reference_translation.run(ref)

from smart_subtitle.subtitle.io import load_subtitle
sub_file = load_subtitle(Path("tests/video1/trditional_big_time.srt"), 0)

# compare
from smart_subtitle.subtitle.normalizer import TextNormalizer
normalizer = TextNormalizer()
print(f"Total whisper segments: {len(ref_translated.segments)}")
for idx, seg in enumerate(ref_translated.segments[:5]):
    print(f"[{idx}] Text: {seg.text} | Trans: {seg.translation}")

valid_whisper = [s for s in ref_translated.segments if s.translation]
print(f"valid_whisper count: {len(valid_whisper)}")

mapper = AnchorMapperStage(config, pipeline.cache)
anchor_maps = mapper.run(input_data=AnchorMapperInput(reference=ref_translated, subtitles=[sub_file]))
anchor_map = anchor_maps[sub_file.path]
print(f"Found {len(anchor_map.anchors)} anchors:")
for i, a in enumerate(anchor_map.anchors):
    print(f"Anchor {i}: subtitle_idx={a.subtitle_start_idx}, whisper_id={a.whisper_start_id}, offset={a.offset:.2f}, conf={a.confidence:.2f}")

for i in range(min(15, len(sub_file.lines))):
    sub = sub_file.lines[i]
    print(f"\nSub {i}: {sub.text}")
    for j in range(min(10, len(valid_whisper))):
        w = valid_whisper[j]
        sim = normalizer.similarity(sub.text, w.translation)
        print(f"  Whisp {j}: {w.translation} | Sim: {sim:.2f}")
