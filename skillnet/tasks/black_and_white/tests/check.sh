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
    if abs(a.shape[0] / a.shape[1] - ref.shape[0] / ref.shape[1]) > 0.02:
        print(p.name, 'skipped: different shape'); continue
    sat, sd, sd0 = saturation(a), float(luma(a).std()), float(luma(ref).std())
    print(p.name, 'saturation %.4f, contrast %.3f (was %.3f)' % (sat, sd, sd0))
    if sat < 0.03 and sd >= sd0 * 0.9:
        good.append(p)
if not good:
    fail('no black-and-white output that keeps or raises contrast')
print('PASS', good[0].name)
PYCHECK
