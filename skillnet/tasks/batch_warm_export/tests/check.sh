#!/bin/bash
set -euo pipefail
cd /task
python3 - <<'PYCHECK'
import sys
sys.path.insert(0, "/task")
from imgcheck import *
import glob, os
stems = ['field_01', 'street_02', 'tower_03', 'lamp_04']
cands = candidates()
found = {}
for p in cands:
    for s in stems:
        if p.stem.startswith(s) and p.suffix.lower() in ('.jpg', '.jpeg') and s not in found:
            found[s] = p
missing = [s for s in stems if s not in found]
if missing:
    fail('missing exported JPEGs for %s (found %s)' % (missing, [p.name for p in cands]))
warmer = 0
for s, p in found.items():
    w, h = size(p)
    if abs(max(w, h) - 1600) > 2:
        fail('%s long edge is %d, expected 1600' % (p.name, max(w, h)))
    a, r = load(p, 600), load('/task/truth/%s.jpg' % s, 600)
    d_out, d_in = float((a[..., 0] - a[..., 2]).mean()), float((r[..., 0] - r[..., 2]).mean())
    print(p.name, '%dx%d warmth (R-B) %.3f -> %.3f' % (w, h, d_in, d_out))
    warmer += d_out > d_in + 0.01
if warmer < 3:
    fail('photos were not made warmer (%d of 4)' % warmer)
pdfs = [p for p in glob.glob('/task/outputs/**/*.pdf', recursive=True)]
if not pdfs:
    fail('no contact sheet PDF')
import pypdf
n = len(pypdf.PdfReader(pdfs[0]).pages)
if n < 1:
    fail('contact sheet has no pages')
print('PASS: 4 JPEGs at 1600 px, warmer, contact sheet with %d page(s)' % n)
PYCHECK
