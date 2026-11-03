"""inspect_photo and list_looks."""

from __future__ import annotations

import json
import subprocess
from typing import Annotated, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool, untrusted)

from . import _common as C


class InspectIn(ToolInput):
    photo: Annotated[InputFile, FileConstraints(extensions=C.ACCEPT_EXTS)] = Field(
        description="The photo to look at: JPEG, PNG, TIFF, WebP, JPEG XL, AVIF, DNG or a camera raw "
                    "(CR2/CR3/NEF/ARW/RAF/RW2/ORF/PEF…). A file id from upload_file or an https URL.")


class Suggestion(ToolOutput):
    control: str = Field(description="A slider id for grade_photo's adjustments, or 'warmth' (grade_photo's own "
                                     "warmth argument).")
    value: float
    why: str


class InspectOut(ToolOutput):
    format: str
    width: int
    height: int
    is_raw: bool
    preview_only: str | None = Field(default=None, description="Set when only the raw's embedded JPEG preview "
                                                                  "could be read (reason).")
    camera: str | None
    lens: str | None
    iso: float | None
    shutter: str | None
    aperture: float | None
    focal_mm: float | None
    capture_time: str | None
    has_edit_sidecar: bool = Field(description="True when the file carries embedded Lightroom/Camera Raw "
                                               "(XMP crs) edit settings.")
    mean_luminance: float = Field(description="0 (black) .. 1 (white); ~0.4-0.5 is a typical well-exposed photo.")
    clipped_highlights_pct: float = Field(description="% of pixels with a colour channel at maximum.")
    clipped_shadows_pct: float = Field(description="% of pixels that are pure black.")
    contrast_std: float
    mean_saturation: float
    warmth: float = Field(description="Mean red minus blue over the whole frame: below about -0.015 reads cool/"
                                      "cold, above +0.015 warm. Compare with grade_photo's before/after warmth.")
    cast: str = Field(description="warm, cool, green, magenta, neutral or unknown (from near-grey mid-tones).")
    cast_strength: float
    suggestions: list[Suggestion]


def _exif(path) -> dict:
    try:
        out = subprocess.run(["exiftool", "-j", "-Make", "-Model", "-LensModel", "-LensID", "-ISO",
                              "-ExposureTime", "-FNumber", "-FocalLength#", "-DateTimeOriginal", "-CreateDate",
                              "-XMP-crs:all", str(path)], capture_output=True, timeout=60).stdout
        return json.loads(out)[0]
    except Exception:  # noqa: BLE001 - metadata is optional
        return {}


@tool(kind="inspect", title="Inspect a photo before editing", timeout_s=180,
      examples=[{"arguments": {"photo": "beach.jpg"}}])
def inspect_photo(args: InspectIn, ctx: ToolContext) -> ToolResult[InspectOut]:
    """Start here with any photo the user wants improved, graded or retouched. Reads the format (JPEG, PNG, TIFF, \
WebP, DNG and camera raws), size, camera/lens/ISO/shutter/aperture, embedded Lightroom edits, and measures \
brightness, clipped highlights/shadows and colour cast. Returns a 1024 px preview and suggested starting sliders \
for grade_photo. Read-only: the original is never changed."""
    wd = C.work_dir()
    photo = C.stage_photo(args.photo, wd)
    ctx.progress(10, "decoding the photo")
    preview = ctx.output_path("preview.jpg")
    res = C.run_chain(ctx, photo, [{"command": "photo.inspect"},
                                   C.export_cmd(preview, 1024, 88)], wd)
    info = res.get("photo.inspect") or {}
    meta = info.get("meta") or {}
    ex = _exif(photo)
    ctx.progress(70, "measuring exposure")
    arr = C.load_rgb(preview)
    st = C.stats(arr)
    cast, strength = C.colour_cast(arr)
    is_raw = info.get("kind") == "raw" or photo.suffix.lower() in C.RAW_EXTS

    sug: list[Suggestion] = []
    if st["clipped_highlights_pct"] > 1.0:
        v = -min(90.0, 30 + st["clipped_highlights_pct"] * 3)
        sug.append(Suggestion(control="light.highlights", value=round(v), why=f"{st['clipped_highlights_pct']}% "
                              "of pixels are clipped white; pull highlights to recover detail"))
        sug.append(Suggestion(control="light.whites", value=-25, why="lower the white point to keep bright areas "
                              "below clipping"))
    if st["mean_luminance"] < 0.3:
        sug.append(Suggestion(control="light.exposure", value=round(min(2.0, (0.42 - st["mean_luminance"]) * 5), 2),
                              why=f"the photo is dark (mean brightness {st['mean_luminance']})"))
    elif st["mean_luminance"] > 0.65:
        sug.append(Suggestion(control="light.exposure", value=-round(min(1.5, (st["mean_luminance"] - 0.5) * 4), 2),
                              why=f"the photo is bright (mean brightness {st['mean_luminance']})"))
    if st["clipped_shadows_pct"] > 3.0:
        sug.append(Suggestion(control="light.shadows", value=35, why=f"{st['clipped_shadows_pct']}% of pixels are "
                              "pure black; lift shadows"))
    if st["contrast_std"] < 0.12:
        sug.append(Suggestion(control="light.contrast", value=20, why="flat tonal range (low contrast)"))
        sug.append(Suggestion(control="effects.dehaze", value=15, why="hazy/flat look"))
    if (cast == "cool" and strength > 0.03) or (st["warmth"] < -0.015 and cast != "warm"):
        sug.append(Suggestion(control="warmth", value=30,
                              why=f"cool/cold colour (frame warmth {st['warmth']}, cast {cast}); pass as "
                                  "grade_photo's warmth argument, which works on JPEGs and raws alike"))
    elif cast == "warm" and strength > 0.06:
        sug.append(Suggestion(control="warmth", value=-30,
                              why=f"warm cast (strength {strength}); pass as grade_photo's warmth argument"))
    if cast in ("green", "magenta") and strength > 0.05:
        sug.append(Suggestion(control="wb.tint", value=15 if cast == "green" else -15, why=f"{cast} cast"))
    if st["mean_saturation"] < 0.12 and cast != "neutral":
        sug.append(Suggestion(control="color.vibrance", value=20, why="muted colours"))

    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    if not w or not h:
        w, h = C.image_size(preview)
    has_crs = any(k for k in ex if k not in ("SourceFile",) and k not in (
        "Make", "Model", "LensModel", "LensID", "ISO", "ExposureTime", "FNumber", "FocalLength", "DateTimeOriginal",
        "CreateDate"))
    make, model = str(ex.get("Make") or ""), str(ex.get("Model") or "")
    camera = meta.get("camera") or (model if model.lower().startswith(make.lower()) else f"{make} {model}").strip()
    if camera and make and camera.lower().startswith(f"{make.lower()} {make.lower()} "):
        camera = camera[len(make) + 1:]
    camera = camera or None
    lens = meta.get("lens") or ex.get("LensModel") or ex.get("LensID") or None
    uncertain = ["The colour cast is estimated from near-grey mid-tone pixels; strongly coloured light (sunset, "
                 "stage lights) also reads as a cast, so judge it on the preview before correcting."]
    if cast == "unknown":
        uncertain.append("Too few near-neutral pixels to estimate a colour cast.")
    if info.get("preview_only"):
        uncertain.append(f"Only the raw's embedded preview could be decoded ({info['preview_only']}); edits will "
                         "work on that smaller JPEG, not the full raw data.")
    data = InspectOut(
        format=str(info.get("format") or photo.suffix.lstrip(".").upper()), width=w, height=h, is_raw=is_raw,
        preview_only=info.get("preview_only"),
        camera=untrusted(camera, source=args.photo.name) if camera else None,
        lens=untrusted(lens, source=args.photo.name) if lens else None,
        iso=meta.get("iso") or ex.get("ISO"), shutter=meta.get("shutter") or (str(ex["ExposureTime"])
                                                                              if ex.get("ExposureTime") else None),
        aperture=meta.get("aperture") or ex.get("FNumber"), focal_mm=meta.get("focal_mm") or ex.get("FocalLength"),
        capture_time=ex.get("DateTimeOriginal") or ex.get("CreateDate"), has_edit_sidecar=has_crs,
        cast=cast, cast_strength=strength, suggestions=sug, **st)
    summary = (f"{data.format} {w}×{h}{' raw' if is_raw else ''}: brightness {st['mean_luminance']}, "
               f"{st['clipped_highlights_pct']}% highlights / {st['clipped_shadows_pct']}% shadows clipped, "
               f"{cast} cast")
    return ToolResult(data=data, summary=summary, uncertain=uncertain,
                      outputs=[OutputFile(preview, "1024 px preview of the photo as it is now")],
                      next_step="Show the preview, then call grade_photo with a preset from list_looks and/or the "
                                "suggested sliders.")


# ----------------------------------------------------------------------------------------------

Section = Literal["light", "color", "effects", "curve", "grading", "mixer", "bw", "detail", "optics", "geometry",
                  "crop", "mask"]

MASK_CONTROLS = [
    ("exposure", -4, 4, 0, "stops"), ("contrast", -100, 100, 0, ""), ("highlights", -100, 100, 0, ""),
    ("shadows", -100, 100, 0, ""), ("whites", -100, 100, 0, ""), ("blacks", -100, 100, 0, ""),
    ("temp", -100, 100, 0, "relative warm(+)/cool(-)"), ("tint", -100, 100, 0, ""), ("texture", -100, 100, 0, ""),
    ("clarity", -100, 100, 0, ""), ("dehaze", -100, 100, 0, ""), ("hue", -100, 100, 0, ""),
    ("saturation", -100, 100, 0, ""), ("sharpness", -100, 100, 0, ""), ("noise", -100, 100, 0, ""),
    ("color_hue", 0, 360, 0, "overlay hue"), ("color_sat", 0, 100, 0, "overlay strength"),
    ("amount", 0, 200, 100, "% of the whole mask effect"),
]

SECTION_PREFIX = {
    "light": ("light.", "profile."), "color": ("wb.", "color.", "calibration."), "effects": ("effects.", "vignette.",
                                                                                                "grain."),
    "curve": ("curve.",), "grading": ("grading.",), "mixer": ("mixer.",), "bw": ("bw.",),
    "detail": ("detail.", "enhance."), "optics": ("optics.",), "geometry": ("geometry.",), "crop": ("crop.",),
}


class LooksIn(ToolInput):
    what: Literal["looks", "controls", "both"] = Field(
        default="looks", description="looks = preset looks and colour profiles; controls = slider ids with ranges "
                                     "for grade_photo/adjust_area; both.")
    section: Section | None = Field(
        default=None, description="Only controls of one panel: light, color (white balance, vibrance), effects "
                                  "(clarity, dehaze, vignette, grain), curve, grading (colour wheels), mixer (HSL), "
                                  "bw, detail (sharpen/noise), optics, geometry, crop, mask (local adjust_area "
                                  "controls).")
    search: str | None = Field(default=None, max_length=60,
                               description="Text to match in ids, names or groups, e.g. 'film', 'b&w', 'warm'.")


class Look(ToolOutput):
    id: str
    name: str
    group: str


class Control(ToolOutput):
    id: str
    label: str
    min: float
    max: float
    default: float


class LooksOut(ToolOutput):
    presets: list[Look]
    profiles: list[Look]
    controls: list[Control]
    total_controls: int


@tool(kind="inspect", title="List looks and adjustment controls", timeout_s=120,
      examples=[{"arguments": {"what": "looks", "search": "film"}},
                {"arguments": {"what": "controls", "section": "light"}}])
def list_looks(args: LooksIn, ctx: ToolContext) -> ToolResult[LooksOut]:
    """Use when choosing a style ('golden hour', 'teal and orange', 'faded film', 'black and white', 'moody') or when \
you need exact slider ids and ranges for grade_photo, adjust_area or retouch_photo. Returns the built-in preset \
looks grouped by style, colour profiles, and develop controls (id, range, default), optionally filtered by panel or \
search text. Call after inspect_photo, before grade_photo."""
    presets, profiles = C.presets_and_profiles()
    q = (args.search or "").strip().lower()

    def match(*fields: str) -> bool:
        return not q or any(q in f.lower() for f in fields)

    out_presets: list[Look] = []
    out_profiles: list[Look] = []
    out_controls: list[Control] = []
    if args.what in ("looks", "both"):
        out_presets = [Look(**p) for p in presets if match(p["id"], p["name"], p["group"])]
        out_profiles = [Look(**p) for p in profiles if match(p["id"], p["name"], p["group"])]
    all_controls = [Control(id=c["id"], label=c["label"], min=c["min"], max=c["max"], default=c["default"])
                    for c in C.controls().values()]
    mask_controls = [Control(id=n, label=(n.replace("_", " ").title() + (f" ({u})" if u else "")), min=lo, max=hi,
                             default=d) for n, lo, hi, d, u in MASK_CONTROLS]
    if args.what in ("controls", "both"):
        if args.section == "mask":
            pool = mask_controls
        elif args.section:
            pool = [c for c in all_controls if c.id.startswith(SECTION_PREFIX[args.section])]
        else:
            pool = all_controls
        out_controls = [c for c in pool if match(c.id, c.label)]
    full = ctx.output_path("controls.json")
    full.write_text(json.dumps({"presets": presets, "profiles": profiles,
                                "controls": [c.model_dump() for c in all_controls],
                                "mask_controls": [c.model_dump() for c in mask_controls]}, indent=1))
    summary = f"{len(out_presets)} looks, {len(out_profiles)} profiles, {len(out_controls)} controls"
    if q:
        summary += f" matching '{args.search}'"
    data = LooksOut(presets=out_presets, profiles=out_profiles, controls=out_controls,
                    total_controls=len(all_controls))
    if not (out_presets or out_profiles or out_controls):
        return ToolResult(data=data, summary=summary, outputs=[OutputFile(full, "Every look and control")],
                          next_step="Nothing matched; call again without search, or with a broader word.")
    return ToolResult(data=data, summary=summary, outputs=[OutputFile(full, "Every look, profile and control")])
