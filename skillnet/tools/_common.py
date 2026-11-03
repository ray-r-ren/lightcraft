"""Shared helpers: drive the LightCraft engine, measure images, handle look files.

Every edit runs on a private copy of the user's photo in a temporary work folder, so the
original file is never written to (LightCraft can write XMP sidecars next to the files it
imports; with a copy those land in the work folder, never beside the user's file).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from skillnet_sdk import ToolContext, ToolError

ENGINE = "lightcraft-cli"

RAW_EXTS = {
    ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".rw2", ".orf",
    ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".kdc", ".mef", ".mos", ".mrw", ".raw", ".rwl",
}
RASTER_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".jxl", ".avif", ".psd"}
PHOTO_EXTS = sorted(RAW_EXTS | RASTER_EXTS)
# Accepted by the argument check only so the tools can answer with a clear "not supported" error.
REFUSED_EXTS = {".heic", ".heif", ".hif"}
ACCEPT_EXTS = sorted(RAW_EXTS | RASTER_EXTS | REFUSED_EXTS)
LOOK_KIND = "pro-photo-darkroom-look"

# Aspect words users say → [w, h] used as given (taller than wide = portrait).
ASPECTS = {
    "1:1": [1, 1], "4:5": [4, 5], "5:4": [5, 4], "5:7": [5, 7], "7:5": [7, 5], "2:3": [2, 3], "3:2": [3, 2],
    "4:3": [4, 3], "3:4": [3, 4], "16:9": [16, 9], "9:16": [9, 16], "16:10": [16, 10], "10:16": [10, 16],
}


# ----------------------------------------------------------------------------------------------
# work folders and inputs

def work_dir(prefix: str = "pdr-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def stage_photo(src: Path, wd: Path, index: int = 0) -> Path:
    """Copy the user's photo into the work folder (the engine only ever sees the copy)."""
    ext = src.suffix.lower()
    if ext in REFUSED_EXTS:
        raise ToolError(
            "unsupported_format",
            f"{src.name} is a HEIC/HEIF photo; this skill does not support HEIC, so this photo was not edited and no edited "
            "copy of it was made.",
            "Tell the user plainly that HEIC photos are not supported, so no edited file was produced, and ask "
            "them for a JPEG copy (iPhone: share or export the photo as JPEG, or set Settings → Camera → Formats "
            "→ Most Compatible for new shots). Once they upload the JPEG, start again with inspect_photo.",
        )
    if ext not in RAW_EXTS and ext not in RASTER_EXTS:
        raise ToolError(
            "unsupported_format",
            f"{src.name} is not a supported photo type ({ext or 'no extension'}).",
            "Pass a JPEG, PNG, TIFF, WebP, JPEG XL, AVIF, PSD, DNG or camera raw file (CR2/CR3/NEF/ARW/RAF/"
            "RW2/ORF/PEF…). HEIC is not supported: ask the user to export it as JPEG first.",
        )
    stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in src.stem)[:80] or "photo"
    dst = wd / f"in{index:03d}" / f"{stem}{ext}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------------
# engine

@dataclass
class ChainResult:
    results: list[dict[str, Any]]

    def get(self, command: str, nth: int = 0) -> Any:
        seen = [r for r in self.results if r.get("command") == command]
        return seen[nth].get("result") if len(seen) > nth else None


def run_chain(ctx: ToolContext, photo: Path, commands: list[dict[str, Any]], wd: Path,
              timeout_s: float | None = None) -> ChainResult:
    """Import one photo (a private copy) and run LightCraft commands on it, in order."""
    script = wd / f"script-{abs(hash((str(photo), len(commands)))) % 10**8}.jsonl"
    script.write_text("".join(json.dumps({"command": c["command"], "params": c.get("params", {})}) + "\n"
                              for c in commands))
    proc = ctx.run([ENGINE, "run", "--import", str(photo), "--script", str(script)], engine="lightcraft",
                   timeout_s=timeout_s, check=False)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    results = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if "import failed" in err or "unrecognized file format" in err:
        ctx.mark_untrusted("lightcraft output")
        raise ToolError(
            "unreadable_photo",
            f"{photo.name} could not be read as a photo (unrecognised or damaged file).",
            "Check the file opens in an image viewer; if it is HEIC or a damaged download, ask the user for a "
            "JPEG/TIFF/raw export of it.",
        )
    failed = [r for r in results if not r.get("ok")]
    if failed:
        ctx.mark_untrusted("lightcraft output")
        f = failed[0]
        raise ToolError(
            "engine_rejected",
            f"The photo engine refused `{f.get('command')}`: {str(f.get('error'))[:300]}",
            "Check the values against list_looks (controls and preset ids) and try again with corrected values.",
        )
    if proc.returncode != 0:
        ctx.mark_untrusted("lightcraft output")
        tail = " ".join(l for l in err.splitlines() if "WARN" not in l)[-300:]
        raise ToolError("engine_failed", f"The photo engine failed: {tail or 'exit ' + str(proc.returncode)}",
                        "Check the photo opens elsewhere; if it does, try a smaller preview_size or report this.")
    return ChainResult(results)


@lru_cache(maxsize=1)
def controls() -> dict[str, dict[str, Any]]:
    import subprocess
    out = subprocess.run([ENGINE, "controls", "--json"], capture_output=True, timeout=60, check=True).stdout
    return {c["id"]: c for c in json.loads(out)}


@lru_cache(maxsize=1)
def presets_and_profiles() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import subprocess
    out = subprocess.run([ENGINE, "run", "--demo", "presets.list", "profiles.list"], capture_output=True,
                         timeout=120, check=True).stdout.decode()
    res = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
    presets = [{"id": p["id"], "name": p["name"], "group": p.get("group", "")} for p in res[0]["result"]]
    profiles = [{"id": p["id"], "name": p["name"], "group": p.get("group", "")} for p in res[1]["result"]]
    return presets, profiles


def check_preset(preset: str | None) -> None:
    if preset is None:
        return
    ids = {p["id"] for p in presets_and_profiles()[0]}
    if preset not in ids:
        raise ToolError("unknown_preset", f"There is no look called '{preset}'.",
                        "Call list_looks (what='looks', optionally with search) and pass one of the returned "
                        "preset ids, e.g. 'lc.golden-hour'.")


def validate_adjustments(adj: dict[str, float] | None) -> tuple[dict[str, float], list[str], list[str]]:
    """Return (accepted values, rejected ids, clamped notes)."""
    if not adj:
        return {}, [], []
    table = controls()
    ok: dict[str, float] = {}
    rejected: list[str] = []
    notes: list[str] = []
    for k, v in adj.items():
        c = table.get(k)
        if c is None:
            rejected.append(k)
            continue
        val = float(v)
        lo, hi = float(c["min"]), float(c["max"])
        if val < lo or val > hi:
            notes.append(f"{k}={val:g} is outside {lo:g}..{hi:g}; clamped to {min(max(val, lo), hi):g}")
            val = min(max(val, lo), hi)
        ok[k] = val
    return ok, rejected, notes


# ----------------------------------------------------------------------------------------------
# look files

def read_look(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ToolError("invalid_look_file", "The look file is not valid JSON.",
                        "Pass the look.json returned by grade_photo, adjust_area or retouch_photo.") from None
    if isinstance(doc, dict) and doc.get("kind") == LOOK_KIND and isinstance(doc.get("settings"), dict):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("light"), dict):  # bare develop settings
        return {"kind": LOOK_KIND, "version": 1, "source_sha256": None, "settings": doc}
    raise ToolError("invalid_look_file", "The look file is not a Pro Photo Darkroom look.",
                    "Pass the look.json returned by grade_photo, adjust_area or retouch_photo.")


PHOTO_SPECIFIC = ("spots", "red_eye", "crop", "orientation", "geometry")


def look_commands(look: dict[str, Any] | None, photo_sha: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Commands that apply a look; photo-specific parts are dropped for a different photo."""
    if not look:
        return [], []
    settings = dict(look["settings"])
    notes: list[str] = []
    settings.pop("orientation", None)
    cmds: list[dict[str, Any]] = []
    same = look.get("source_sha256") == photo_sha
    if not same:
        dropped = []
        if settings.get("spots"):
            dropped.append("spot removals")
        if settings.get("red_eye"):
            dropped.append("red-eye fixes")
        crop = settings.get("crop") or {}
        geo = (crop.get("geometry") or {})
        rect = geo.get("rect") or {}
        if geo.get("angle") or any(abs(rect.get(k, d) - d) > 1e-6 for k, d in
                                   (("x0", 0), ("y0", 0), ("x1", 1), ("y1", 1))):
            dropped.append("crop position/straighten angle")
        for k in ("spots", "red_eye", "crop"):
            settings.pop(k, None)
        g = settings.get("geometry")
        if isinstance(g, dict):
            g = dict(g)
            if g.get("upright") not in (None, "off") or g.get("guides"):
                dropped.append("upright correction (re-run per photo)")
            g["upright"] = "off"
            g["upright_transform"] = None
            g["guides"] = []
            settings["geometry"] = g
        if dropped:
            notes.append("The look came from a different photo: its " + ", ".join(dropped)
                         + " were not applied (they are specific to the original framing).")
        cmds.append({"command": "develop.merge", "params": {"settings": settings, "label": "look"}})
        if crop.get("aspect"):
            cmds.append({"command": "crop.aspect", "params": {"aspect": list(crop["aspect"])}})
    else:
        cmds.append({"command": "develop.merge", "params": {"settings": settings, "label": "look"}})
    return cmds, notes


def write_look(path: Path, settings: dict[str, Any], source_sha: str, source_name: str,
               history: list[str]) -> None:
    doc = {"kind": LOOK_KIND, "version": 1, "source_sha256": source_sha, "source_name": source_name,
           "history": history[-30:], "settings": settings}
    path.write_text(json.dumps(doc, indent=1))


def changed_settings(settings: dict[str, Any]) -> dict[str, float]:
    """Flat control id → value for every slider not at its default (small, for `data`)."""
    flat: dict[str, float] = {}
    key_map = _settings_key_map()
    for cid, c in controls().items():
        path = key_map.get(cid)
        if not path:
            continue
        cur: Any = settings
        for p in path:
            cur = cur.get(p) if isinstance(cur, dict) else None
        if isinstance(cur, (int, float)) and abs(float(cur) - float(c["default"])) > 1e-9:
            flat[cid] = round(float(cur), 3)
    return flat


@lru_cache(maxsize=1)
def _settings_key_map() -> dict[str, tuple[str, ...]]:
    """Map control ids (light.exposure, mixer.red.hue, detail.sharpenAmount) to settings JSON paths."""
    import re

    def snake(s: str) -> str:
        return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), s)

    special = {
        "bw": ("bw_mix",), "detail": ("detail",), "optics": ("optics",), "enhance": ("enhance",),
    }
    out: dict[str, tuple[str, ...]] = {}
    for cid in controls():
        parts = cid.split(".")
        head = special.get(parts[0], (parts[0],))
        rest = tuple(snake(p) for p in parts[1:])
        out[cid] = head + rest
    # irregular names
    out["optics.defringePurple"] = ("optics", "defringe_purple_amount")
    out["optics.defringeGreen"] = ("optics", "defringe_green_amount")
    out["detail.sharpenAmount"] = ("detail", "sharpen_amount")
    out["hdr.maxEv"] = ("hdr", "max_ev")
    out["crop.angle"] = ("crop", "geometry", "angle")
    return out


# ----------------------------------------------------------------------------------------------
# image measurement (on rendered previews)

def load_rgb(path: Path, max_edge: int | None = None) -> np.ndarray:
    """Decode an image (JPEG/PNG/TIFF…) to an HxWx3 float array in 0..1 (sRGB-encoded)."""
    args = ["convert", f"{path}[0]", "-colorspace", "sRGB", "-alpha", "off"]
    if max_edge:
        args += ["-resize", f"{max_edge}x{max_edge}>"]
    args += ["-depth", "8", "ppm:-"]
    import subprocess
    data = subprocess.run(args, capture_output=True, check=True, timeout=120).stdout
    # parse binary PPM header
    fields: list[bytes] = []
    i = 0
    while len(fields) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        fields.append(data[i:j])
        i = j
    i += 1
    w, h = int(fields[1]), int(fields[2])
    arr = np.frombuffer(data, dtype=np.uint8, count=w * h * 3, offset=i).reshape(h, w, 3)
    return arr.astype(np.float32) / 255.0


def save_rgb(arr: np.ndarray, path: Path, quality: int = 90) -> None:
    import subprocess
    a = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    h, w = a.shape[:2]
    header = f"P6\n{w} {h}\n255\n".encode()
    subprocess.run(["convert", "ppm:-", "-quality", str(quality), str(path)], input=header + a.tobytes(),
                   check=True, timeout=120, capture_output=True)


def luma(arr: np.ndarray) -> np.ndarray:
    return arr[..., 0] * 0.2126 + arr[..., 1] * 0.7152 + arr[..., 2] * 0.0722


def stats(arr: np.ndarray) -> dict[str, float]:
    y = luma(arr)
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    hi = float((mx >= 254 / 255).mean() * 100)
    lo = float((mx <= 2 / 255).mean() * 100)
    sat = float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0).mean())
    return {
        "mean_luminance": round(float(y.mean()), 4),
        "clipped_highlights_pct": round(hi, 2),
        "clipped_shadows_pct": round(lo, 2),
        "contrast_std": round(float(y.std()), 4),
        "mean_saturation": round(sat, 4),
        "warmth": round(float((arr[..., 0] - arr[..., 2]).mean()), 4),
    }


def colour_cast(arr: np.ndarray) -> tuple[str, float]:
    """Cast estimate from near-neutral mid-tone pixels (things that should be grey):
    (warm|cool|green|magenta|neutral|unknown, strength 0..1)."""
    y = luma(arr)
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    sel = (y > 0.12) & (y < 0.92) & (sat < 0.3)
    if sel.mean() < 0.02:
        return "unknown", 0.0
    m = arr[sel].mean(axis=0)
    rb = float(m[0] - m[2])
    gm = float(m[1] - (m[0] + m[2]) / 2)
    if max(abs(rb), abs(gm)) < 0.025:
        return "neutral", round(max(abs(rb), abs(gm)), 3)
    if abs(rb) >= abs(gm):
        return ("warm" if rb > 0 else "cool"), round(abs(rb), 3)
    return ("green" if gm > 0 else "magenta"), round(abs(gm), 3)


def kelvin_shift(base: float, warmth: float) -> float:
    """White-balance temperature `warmth` (-100 cool .. +100 warm) away from `base`, in mired steps so the
    same warmth looks alike on raws (Kelvin) and JPEGs (6500 = as shot)."""
    base = min(max(float(base or 6500.0), 2000.0), 50000.0)
    mired = 1e6 / base - 1.0 * float(warmth)
    mired = min(max(mired, 1e6 / 50000.0), 1e6 / 2000.0)
    return float(round(1e6 / mired / 50.0) * 50.0)


def side_by_side(before: Path, after: Path, out: Path, height: int = 720) -> None:
    import subprocess
    subprocess.run([
        "convert", "(", str(before), "-resize", f"x{height}", ")", "(", "-size", f"12x{height}", "xc:white", ")",
        "(", str(after), "-resize", f"x{height}", ")", "+append", "-quality", "88", str(out)],
        check=True, timeout=120, capture_output=True)


def image_size(path: Path) -> tuple[int, int]:
    import subprocess
    out = subprocess.run(["identify", "-format", "%w %h", f"{path}[0]"], capture_output=True, check=True,
                         timeout=60).stdout.decode().split()
    return int(out[0]), int(out[1])


def export_cmd(path: Path, long_edge: int, quality: int = 90, **opts: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"path": str(path), "longEdge": int(long_edge), "quality": int(quality),
                              "conflict": "overwrite"}
    params.update(opts)
    return {"command": "app.export", "params": params}


# ----------------------------------------------------------------------------------------------
# Adobe Camera Raw (crs:) fields for XMP sidecars, the inverse of the engine's own crs reader,
# so Lightroom / Camera Raw pick up the global edits. Masks, spots, red-eye, upright and the
# engine's own colour profiles have no faithful crs equivalent and stay in lc:settings only.

CRS_NS = "http://ns.adobe.com/camera-raw-settings/1.0/"
_CRS_BANDS = [("red", "Red"), ("orange", "Orange"), ("yellow", "Yellow"), ("green", "Green"), ("aqua", "Aqua"),
              ("blue", "Blue"), ("purple", "Purple"), ("magenta", "Magenta")]
_CRS_SIMPLE = [
    ("light.contrast", "Contrast2012"), ("light.highlights", "Highlights2012"), ("light.shadows", "Shadows2012"),
    ("light.whites", "Whites2012"), ("light.blacks", "Blacks2012"), ("effects.texture", "Texture"),
    ("effects.clarity", "Clarity2012"), ("effects.dehaze", "Dehaze"), ("color.vibrance", "Vibrance"),
    ("color.saturation", "Saturation"),
    ("curve.shadows", "ParametricShadows"), ("curve.darks", "ParametricDarks"), ("curve.lights", "ParametricLights"),
    ("curve.highlights", "ParametricHighlights"), ("curve.split_shadows", "ParametricShadowSplit"),
    ("curve.split_mid", "ParametricMidtoneSplit"), ("curve.split_highlights", "ParametricHighlightSplit"),
    ("grading.shadows.hue", "SplitToningShadowHue"), ("grading.shadows.sat", "SplitToningShadowSaturation"),
    ("grading.shadows.lum", "ColorGradeShadowLum"), ("grading.highlights.hue", "SplitToningHighlightHue"),
    ("grading.highlights.sat", "SplitToningHighlightSaturation"), ("grading.highlights.lum", "ColorGradeHighlightLum"),
    ("grading.midtones.hue", "ColorGradeMidtoneHue"), ("grading.midtones.sat", "ColorGradeMidtoneSat"),
    ("grading.midtones.lum", "ColorGradeMidtoneLum"), ("grading.global.hue", "ColorGradeGlobalHue"),
    ("grading.global.sat", "ColorGradeGlobalSat"), ("grading.global.lum", "ColorGradeGlobalLum"),
    ("grading.blending", "ColorGradeBlending"), ("grading.balance", "SplitToningBalance"),
    ("detail.sharpen_amount", "Sharpness"), ("detail.sharpen_radius", "SharpenRadius"),
    ("detail.sharpen_detail", "SharpenDetail"), ("detail.sharpen_masking", "SharpenEdgeMasking"),
    ("detail.nr_luminance", "LuminanceSmoothing"), ("detail.nr_detail", "LuminanceNoiseReductionDetail"),
    ("detail.nr_contrast", "LuminanceNoiseReductionContrast"), ("detail.nr_color", "ColorNoiseReduction"),
    ("detail.nr_color_detail", "ColorNoiseReductionDetail"),
    ("detail.nr_color_smoothness", "ColorNoiseReductionSmoothness"),
    ("vignette.amount", "PostCropVignetteAmount"), ("vignette.midpoint", "PostCropVignetteMidpoint"),
    ("vignette.roundness", "PostCropVignetteRoundness"), ("vignette.feather", "PostCropVignetteFeather"),
    ("vignette.highlights", "PostCropVignetteHighlightContrast"), ("grain.amount", "GrainAmount"),
    ("grain.size", "GrainSize"), ("grain.roughness", "GrainFrequency"),
    ("optics.distortion", "LensManualDistortionAmount"), ("optics.vignetting", "VignetteAmount"),
    ("optics.vignetting_midpoint", "VignetteMidpoint"),
] + [(f"mixer.{b}.{k}", f"{n}Adjustment{c}") for b, c in _CRS_BANDS
     for k, n in (("hue", "Hue"), ("sat", "Saturation"), ("lum", "Luminance"))] + \
    [(f"bw_mix.{b}", f"GrayMixer{c}") for b, c in _CRS_BANDS]
_WB_NAMES = {"asShot": "As Shot", "auto": "Auto", "daylight": "Daylight", "cloudy": "Cloudy", "shade": "Shade",
             "tungsten": "Tungsten", "fluorescent": "Fluorescent", "flash": "Flash", "custom": "Custom"}


def _get(settings: dict, path: str):
    cur: Any = settings
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _crs_num(v: float) -> str:
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def crs_fields(settings: dict, is_raw: bool) -> dict[str, str]:
    """Map engine develop settings to Camera Raw `crs:` properties (global edits only)."""
    f: dict[str, str] = {"Version": "15.0", "ProcessVersion": "11.0", "HasSettings": "True"}
    exp = _get(settings, "light.exposure")
    if isinstance(exp, (int, float)):
        f["Exposure2012"] = ("+" if exp > 0 else "") + f"{exp:.2f}"
    for path, name in _CRS_SIMPLE:
        v = _get(settings, path)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f[name] = _crs_num(float(v))
    f["ConvertToGrayscale"] = "True" if settings.get("treatment") == "bw" else "False"
    wb = settings.get("wb") or {}
    mode = str(wb.get("mode") or "asShot")
    f["WhiteBalance"] = _WB_NAMES.get(mode, "Custom")
    temp, tint = wb.get("temp"), wb.get("tint")
    if mode == "custom" and isinstance(temp, (int, float)) and temp > 0:
        if is_raw:
            f["Temperature"] = str(int(round(temp)))
            f["Tint"] = _crs_num(float(tint or 0))
        else:
            rel = (1e6 / 6500.0 - 1e6 / float(temp)) / 0.8
            f["IncrementalTemperature"] = _crs_num(round(max(-100.0, min(100.0, rel))))
            f["IncrementalTint"] = _crs_num(round(float(tint or 0)))
    optics = settings.get("optics") or {}
    f["LensProfileEnable"] = "1" if optics.get("lens_profile") else "0"
    f["AutoLateralCA"] = "1" if optics.get("remove_ca") else "0"
    geo = (settings.get("crop") or {}).get("geometry") or {}
    rect = geo.get("rect") or {}
    angle = float(geo.get("angle") or 0)
    if rect and (rect.get("x0", 0) > 1e-4 or rect.get("y0", 0) > 1e-4 or rect.get("x1", 1) < 1 - 1e-4
                 or rect.get("y1", 1) < 1 - 1e-4 or abs(angle) > 1e-4):
        f.update({"HasCrop": "True", "CropLeft": f"{rect.get('x0', 0):.6f}", "CropTop": f"{rect.get('y0', 0):.6f}",
                  "CropRight": f"{rect.get('x1', 1):.6f}", "CropBottom": f"{rect.get('y1', 1):.6f}",
                  "CropAngle": _crs_num(angle)})
    else:
        f["HasCrop"] = "False"
    return f


def add_crs_to_xmp(xmp: Path, settings: dict, is_raw: bool) -> list[str]:
    """Insert crs: properties into an engine-written sidecar. Returns the settings that could not be carried."""
    text = xmp.read_text(encoding="utf-8")
    if "camera-raw-settings" in text or "</rdf:Description>" not in text:
        return []
    fields = crs_fields(settings, is_raw)
    els = "".join(f"   <crs:{k}>{v}</crs:{k}>\n" for k, v in fields.items())
    text = text.replace('xmlns:lc="http://ns.lightcraft.app/lc/1.0/"',
                        f'xmlns:lc="http://ns.lightcraft.app/lc/1.0/"\n    xmlns:crs="{CRS_NS}"', 1)
    if f'xmlns:crs="{CRS_NS}"' not in text:
        text = text.replace("<rdf:Description rdf:about=\"\"", f"<rdf:Description rdf:about=\"\" xmlns:crs=\"{CRS_NS}\"", 1)
    text = text.replace("</rdf:Description>", els + "  </rdf:Description>", 1)
    xmp.write_text(text, encoding="utf-8")
    lost = []
    if settings.get("masks"):
        lost.append("masks")
    if settings.get("spots"):
        lost.append("spots")
    if settings.get("red_eye"):
        lost.append("red-eye")
    if str((settings.get("geometry") or {}).get("upright", "off")) != "off":
        lost.append("upright")
    prof = (settings.get("profile") or {}).get("id")
    if prof and prof not in ("lc.color",):
        lost.append(f"profile {prof}")
    return lost
