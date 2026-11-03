#!/bin/bash
set -euo pipefail
cd /task
python3 - <<'PYCHECK'
import sys
sys.path.insert(0, "/task")
from imgcheck import *
ref = load('/task/truth/original.jpg', 800)
m0 = float(luma(ref).mean())
w0 = float((ref[..., 0] - ref[..., 2]).mean())
cands = candidates()
if not cands:
    fail('no output image found')
good = []
for p in cands:
    a = load(p, 800)
    if abs(a.shape[0] / a.shape[1] - ref.shape[0] / ref.shape[1]) > 0.02:
        print(p.name, 'skipped: different shape'); continue
    m = float(luma(a).mean())
    w = float((a[..., 0] - a[..., 2]).mean())
    print(p.name, 'mean luminance %.3f (was %.3f), warmth R-B %.4f (was %.4f)' % (m, m0, w, w0))
    if m >= m0 + 0.06 and w >= w0 + 0.02:
        good.append(p)
if not good:
    fail('no output photo that is clearly brighter (+0.06) and warmer (+0.02 red-blue)')
print('PASS', good[0].name)
PYCHECK
