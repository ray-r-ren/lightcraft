#!/bin/bash
set -euo pipefail
cd /task
python3 - <<'PYCHECK'
import sys
sys.path.insert(0, "/task")
from imgcheck import *
ref = load('/task/truth/original.jpg', 800)
c0 = clipped_pct(ref)
cands = candidates()
if not cands:
    fail('no output image found')
good = []
for p in cands:
    a = load(p, 800)
    if abs(a.shape[0] / a.shape[1] - ref.shape[0] / ref.shape[1]) > 0.02:
        print(p.name, 'skipped: different shape'); continue
    c, m = clipped_pct(a), float(luma(a).mean())
    print(p.name, 'clipped %.2f%% (was %.2f%%), mean luminance %.3f (was %.3f)' % (c, c0, m, luma(ref).mean()))
    if c < c0 * 0.4 and m > 0.25:
        good.append(p)
if not good:
    fail('no output photo with clearly reduced highlight clipping and a normal brightness')
print('PASS', good[0].name)
PYCHECK
