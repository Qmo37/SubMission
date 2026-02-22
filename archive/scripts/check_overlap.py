import re
from datetime import datetime

def parse_time(t_str):
    t = datetime.strptime(t_str, '%H:%M:%S,%f')
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1000000.0

with open('tests/video1/output.srt', 'r', encoding='utf-8') as f:
    content = f.read()

blocks = re.split(r'\n\n+', content.strip())
for block in blocks:
    lines = block.strip().split('\n')
    if len(lines) >= 3:
        m = re.match(r'(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)', lines[1])
        if m:
            start = parse_time(m.group(1))
            end = parse_time(m.group(2))
            if 53 * 60 <= start <= 58 * 60:
                print(f'{lines[0]}: {lines[1]}')
                for l in lines[2:]:
                    print(f'  {l}')
                print()
