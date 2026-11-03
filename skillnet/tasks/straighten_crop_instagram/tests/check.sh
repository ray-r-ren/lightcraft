#!/bin/bash
set -euo pipefail
cd /task
python3 - <<'PYCHECK'
import sys
sys.path.insert(0, "/task")
from imgcheck import *
cands = candidates()
if not cands:
    fail('no output image found')
good = []
for p in cands:
    w, h = size(p)
    a = load(p, 800)
    rows = horizon_rows(a)
    tilt = abs(rows[0] - rows[1])
    print(p.name, '%dx%d ratio %.4f, horizon rows %s' % (w, h, w / h, rows))
    if abs(w / h - 0.8) <= 0.012 and h >= 800 and tilt <= max(4, a.shape[0] * 0.006):
        good.append(p)
if not good:
    fail('no 4:5 portrait output with a level horizon')
print('PASS', good[0].name)
PYCHECK
