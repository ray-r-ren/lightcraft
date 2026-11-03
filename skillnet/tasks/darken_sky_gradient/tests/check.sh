#!/bin/bash
set -euo pipefail
cd /task
python3 - <<'PYCHECK'
import sys
sys.path.insert(0, "/task")
from imgcheck import *
ref = load('/task/truth/original.jpg', 800)
cands = candidates()
if not cands:
    fail('no output image found')
good = []
for p in cands:
    a = load(p, 800)
    if a.shape != ref.shape:
        print(p.name, 'skipped: different size/shape', a.shape, ref.shape); continue
    h = a.shape[0]
    yt, yt0 = float(luma(a[: int(h * 0.15)]).mean()), float(luma(ref[: int(h * 0.15)]).mean())
    yb, yb0 = float(luma(a[int(h * 0.7):]).mean()), float(luma(ref[int(h * 0.7):]).mean())
    print(p.name, 'top %.3f -> %.3f, bottom %.3f -> %.3f' % (yt0, yt, yb0, yb))
    if yt < yt0 - 0.06 and abs(yb - yb0) <= 0.03:
        good.append(p)
if not good:
    fail('no output where the top is clearly darker and the bottom unchanged')
print('PASS', good[0].name)
PYCHECK
