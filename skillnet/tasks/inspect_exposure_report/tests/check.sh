#!/bin/bash
set -euo pipefail
cd /task
python3 - <<'PYCHECK'
import re, sys
from pathlib import Path
p = Path('/task/answer.txt')
if not p.exists():
    print('FAIL: no answer'); sys.exit(1)
text = p.read_text(errors='replace').lower()
lines = text.splitlines()
cats = {'over': ('overexpos', 'over-expos', 'too bright', 'blown'),
        'under': ('underexpos', 'under-expos', 'too dark'),
        'fine': ('fine', 'ok', 'well exposed', 'well-exposed', 'good', 'correct', 'balanced', 'normal')}
want = {'harbour': 'over', 'forest': 'under', 'market': 'fine'}
def verdict(line):
    line = line.split(':', 1)[1] if ':' in line else line
    best = None
    for cat, words in cats.items():
        for w in words:
            m = re.search(r'\b' + re.escape(w), line)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), cat)
    return best[1] if best else None
for name, cat in want.items():
    ls = [l for l in lines if name in l]
    if not ls:
        print('FAIL: no line about', name); sys.exit(1)
    v = verdict(ls[0])
    if v != cat:
        print('FAIL: verdict for %s is %s, expected %s: %r' % (name, v, cat, ls[0])); sys.exit(1)
    print('OK', ls[0].strip())
if not re.search(r'x-?t4', text):
    print('FAIL: camera model X-T4 not named'); sys.exit(1)
if '3200' not in text:
    print('FAIL: forest ISO 3200 not given'); sys.exit(1)
print('PASS')
PYCHECK
