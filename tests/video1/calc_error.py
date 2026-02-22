import re
import math
from datetime import datetime

def parse_srt_time(time_str):
    t = datetime.strptime(time_str.strip(), '%H:%M:%S,%f')
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1000000.0

def load_srt(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    blocks = re.split(r'\n\n+', content.strip())
    subtitles = []
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_line = lines[1]
            text = '\n'.join(lines[2:]).strip()
            
            match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_line)
            if match:
                start = parse_srt_time(match.group(1))
                end = parse_srt_time(match.group(2))
                subtitles.append({
                    'start': start,
                    'end': end,
                    'text': text
                })
    return subtitles

import sys

gt_subs = load_srt('tests/video1/ground_truth_first2mins.srt')
target_file = sys.argv[1] if len(sys.argv) > 1 else 'tests/video1/output_8min_single.srt'
pred_subs = load_srt(target_file)

print(f"Evaluating {target_file} against Ground Truth...")

errors = []
print(f"{'GT ID':<5} | {'GT Start':<10} | {'Pred Start':<10} | {'Error (s)':<10} | {'Text Context'}")
print("-" * 60)

for i, gt in enumerate(gt_subs):
    best_match = None
    best_sim = -1
    
    for pred in pred_subs:
        chars_gt = set(gt['text'])
        chars_pred = set(pred['text'])
        sim = len(chars_gt.intersection(chars_pred)) / max(1, len(chars_gt.union(chars_pred)))
        
        if sim > best_sim:
            best_sim = sim
            best_match = pred
            
    if best_match and best_sim > 0.5:
        error = best_match['start'] - gt['start']
        errors.append(error)
        print(f"{i:<5} | {gt['start']:<10.3f} | {best_match['start']:<10.3f} | {error:<10.3f} | {gt['text'][:20]}")

if errors:
    count = len(errors)
    abs_errors = [abs(e) for e in errors]
    mean_abs_error = sum(abs_errors) / count
    mean_error = sum(errors) / count
    variance = sum((e - mean_error) ** 2 for e in errors) / count
    std_dev = math.sqrt(variance)
    max_abs_error = max(abs_errors)
    
    print("\n--- Metrics ---")
    print(f"Total matched lines   : {count}")
    print(f"Mean Absolute Error   : {mean_abs_error:.3f} seconds")
    print(f"Mean Directional Error: {mean_error:.3f} seconds")
    print(f"Variance             : {variance:.3f} seconds^2")
    print(f"Standard Deviation   : {std_dev:.3f} seconds")
    print(f"Max Absolute Error    : {max_abs_error:.3f} seconds")
else:
    print("No matching lines found to calculate metrics.")
