"""Deterministic photo fixtures, generated with ImageMagick and ExifTool at test time."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import _common as C  # noqa: E402

SKY = "rgb(155,195,232)"
GROUND = "rgb(74,108,58)"
DUST = [(300, 200), (800, 300), (600, 150)]  # dark dust dots on dusty.jpg (x, y px)


def _im(*args: str) -> None:
    subprocess.run(["convert", *args], check=True, capture_output=True, timeout=120)


def make_blown(path: Path, w: int = 1200, h: int = 800) -> Path:
    """Landscape with a pure-white (clipped) band at the top of the sky."""
    top = round(h * 0.175)
    sky = round(h * 0.2)
    _im("-size", f"{w}x{top}", "xc:white",
        "(", "-size", f"{w}x{sky}", "gradient:white-rgb(200,220,245)", ")",
        "(", "-size", f"{w}x{h - top - sky}", "gradient:rgb(120,160,90)-rgb(40,70,30)", ")",
        "-append", "-quality", "92", str(path))
    return path


def make_dark(path: Path) -> Path:
    _im("-size", "1000x700", "gradient:rgb(60,45,30)-rgb(10,8,5)", "-quality", "92", str(path))
    return path


def make_dark_cold(path: Path) -> Path:
    """Dim, slightly blue interior: dark, cool walls with a sofa and a window-ish panel."""
    _im("-size", "1200x800", "gradient:rgb(50,52,60)-rgb(20,22,28)", "-fill", "rgb(70,60,50)",
        "-draw", "rectangle 150,450 520,750", "-fill", "rgb(90,90,100)", "-draw", "rectangle 700,200 1000,520",
        "-quality", "92", str(path))
    return path


def make_tilted(path: Path, angle: float = 5) -> Path:
    """Sky over ground with a level horizon, rotated `angle` degrees clockwise, centre-cropped to 1200x800."""
    _im("-size", "1800x600", f"xc:{SKY}", "(", "-size", "1800x600", f"xc:{GROUND}", ")", "-append",
        "-background", GROUND, "-rotate", f"{angle}", "-gravity", "center", "-crop", "1200x800+0+0", "+repage",
        "-quality", "92", str(path))
    return path


def make_dusty(path: Path) -> Path:
    draw = " ".join(f"circle {x},{y} {x + 6},{y}" for x, y in DUST)
    _im("-size", "1200x800", "gradient:rgb(150,190,235)-rgb(205,225,245)", "-fill", "rgb(48,48,52)",
        "-draw", draw, "-quality", "95", str(path))
    return path


def make_small(path: Path, colour: str, w: int = 360, h: int = 240) -> Path:
    _im("-size", f"{w}x{h}", f"gradient:{colour}-rgb(30,40,30)", "-quality", "90", str(path))
    return path


def add_exif(path: Path) -> Path:
    subprocess.run(["exiftool", "-overwrite_original", "-Make=Canon", "-Model=Canon EOS R6",
                    "-LensModel=RF24-105mm F4 L IS USM", "-ISO=200", "-ExposureTime=1/250", "-FNumber=8",
                    "-FocalLength=50", "-DateTimeOriginal=2024:06:01 18:30:00", str(path)],
                   check=True, capture_output=True, timeout=60)
    return path


@pytest.fixture(scope="session")
def fx(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("fx")
    make_blown(d / "blown.jpg")
    make_dark(d / "dark.jpg")
    make_dark_cold(d / "cold_room.jpg")
    make_tilted(d / "tilted.jpg")
    make_dusty(d / "dusty.jpg")
    shutil.copyfile(d / "blown.jpg", d / "exif.jpg")
    add_exif(d / "exif.jpg")
    _im("-size", "640x480", "gradient:rgb(250,180,90)-rgb(40,30,60)", str(d / "sunset.png"))
    (d / "fake.jpg").write_text("this is not an image at all")
    (d / "notes.txt").write_text("hello")
    return d


@pytest.fixture(scope="session")
def raw_dng(tmp_path_factory) -> Path:
    """A synthetic camera raw (DNG) written by the engine itself."""
    d = tmp_path_factory.mktemp("raw")
    subprocess.run(["lightcraft-cli", "synth-merge", "hdr", "-o", str(d)], check=True, capture_output=True,
                   timeout=300)
    dngs = sorted(d.glob("*.dng"))
    assert dngs, "synthetic DNG generation failed"
    return dngs[0]


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def out(env, name: str) -> Path:
    for o in env.outputs:
        if o.name == name:
            return Path(o.path)
    raise AssertionError(f"{name} not in outputs: {[o.name for o in env.outputs]}")


def rgb(p: Path, max_edge: int | None = None):
    return C.load_rgb(p, max_edge)
