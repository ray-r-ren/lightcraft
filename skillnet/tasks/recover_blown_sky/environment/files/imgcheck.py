"""Measure photos for task checks (ImageMagick decodes, numpy measures). Independent of the skill's code."""
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

IMG = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".avif", ".jxl"}
SKIP = ("before_after", "overlay", "preview", "contact", "mask")


def load(path, width=None):
    args = ["convert", str(path) + "[0]", "-auto-orient", "-colorspace", "sRGB", "-depth", "8"]
    if width:
        args += ["-resize", f"{width}x"]
    raw = subprocess.run(args + ["ppm:-"], check=True, capture_output=True, timeout=120).stdout
    parts = raw.split(maxsplit=4)
    w, h = int(parts[1]), int(parts[2])
    return np.frombuffer(parts[4][: w * h * 3], np.uint8).reshape(h, w, 3).astype(np.float32) / 255.0


def size(path):
    out = subprocess.run(["identify", "-format", "%w %h", str(path) + "[0]"], check=True, capture_output=True,
                         text=True, timeout=60).stdout.split()
    return int(out[0]), int(out[1])


def luma(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def clipped_pct(a):
    return float((a.max(axis=2) >= 254 / 255).mean() * 100)


def saturation(a):
    mx, mn = a.max(axis=2), a.min(axis=2)
    return float(np.where(mx > 0.02, (mx - mn) / np.maximum(mx, 1e-6), 0).mean())


def horizon_rows(a):
    g = luma(a)
    h, w = g.shape
    return [int(np.argmax(np.abs(np.diff(g[:, int(w * f)])))) for f in (0.15, 0.85)]


def candidates(root="/task/outputs", skip=SKIP):
    """Every result image under root, including inside zips; evidence images (before/after etc.) skipped."""
    root = Path(root)
    found = []
    if not root.exists():
        return found
    tmp = Path(tempfile.mkdtemp())
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() == ".zip":
            d = tmp / p.stem
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if ".." in n or n.startswith("/"):
                        continue
                    z.extract(n, d)
    for base in (root, tmp):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix.lower() in IMG and not any(s in p.name.lower() for s in skip):
                found.append(p)
    return found


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)
