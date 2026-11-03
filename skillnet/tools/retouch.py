"""retouch_photo: crop, straighten, spots, red eye, detail and optics."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from skillnet_sdk import OutputFile, ToolContext, ToolError, ToolInput, ToolOutput, ToolResult, tool

from . import _common as C
from .grade import LookFile, PhotoFile

Point = tuple[float, float]


class SpotIn(ToolInput):
    x: float = Field(ge=0, le=1, description="Spot centre, fraction of the width from the left.")
    y: float = Field(ge=0, le=1, description="Spot centre, fraction of the height from the top.")
    radius: float = Field(default=0.015, gt=0, le=0.2, description="Spot radius, fraction of the long edge.")
    mode: Literal["heal", "clone", "remove"] = Field(default="heal", description="heal = blend texture from a "
                                                                                 "nearby patch (dust, blemish); "
                                                                                 "clone = copy it exactly; remove "
                                                                                 "= content-aware remove.")


class EyeIn(ToolInput):
    x: float = Field(ge=0, le=1, description="Eye centre x (fraction of width).")
    y: float = Field(ge=0, le=1, description="Eye centre y (fraction of height).")
    radius: float = Field(default=0.02, gt=0, le=0.2, description="Eye radius, fraction of the long edge.")


class RetouchIn(ToolInput):
    photo: PhotoFile = Field(description="The photo (file id or https URL); never modified.")
    aspect: Literal["original", "free", "1:1", "4:5", "5:4", "5:7", "7:5", "2:3", "3:2", "4:3", "3:4", "16:9",
                    "9:16", "16:10", "10:16"] | None = Field(
        default=None, description="Crop to this width:height ratio, as given (4:5 and 9:16 are portrait, 16:9 "
                                  "landscape). 'Instagram portrait' = 4:5, 'square' = 1:1, 'widescreen' = 16:9. "
                                  "The largest centred crop of that shape is used unless crop_box is given.")
    crop_box: tuple[float, float, float, float] | None = Field(
        default=None, description="Explicit crop [x, y, width, height] as fractions 0-1 of the (straightened) "
                                  "frame, from the top-left.")
    straighten: Literal["auto", "level", "vertical", "full"] | None = Field(
        default=None, description="auto = level a tilted horizon by rotating; level = upright to horizontal lines; "
                                  "vertical = fix converging verticals (buildings); full = level + vertical "
                                  "perspective.")
    angle: float | None = Field(default=None, ge=-45, le=45,
                                description="Rotate by this many degrees (positive = clockwise) to straighten.")
    spots: list[SpotIn] = Field(default_factory=list, max_length=200,
                                description="Dust spots or blemishes to heal, each at x, y with a radius.")
    auto_dust: bool = Field(default=False, description="Find small dark sensor-dust spots on smooth areas (sky) "
                                                       "and heal them automatically.")
    red_eye: list[EyeIn] = Field(default_factory=list, max_length=20, description="Eyes to fix red-eye in.")
    sharpen: float | None = Field(default=None, ge=0, le=150, description="Sharpening amount 0-150 (40 is a "
                                                                          "typical value).")
    noise_reduction: float | None = Field(default=None, ge=0, le=100, description="Luminance noise reduction "
                                                                                  "0-100 (also sets colour noise "
                                                                                  "reduction to at least 25).")
    lens_corrections: bool = Field(default=False, description="Enable lens profile corrections (distortion, "
                                                              "vignetting) and chromatic-aberration removal when "
                                                              "the photo has lens data.")
    look_file: LookFile | None = Field(default=None, description="look.json from an earlier call to build on.")
    preview_size: int = Field(default=2048, ge=256, le=8192, description="Long edge of the returned image, px.")

    @model_validator(mode="after")
    def _check(self):  # noqa: ANN202
        if self.crop_box is not None:
            x, y, w, h = self.crop_box
            if w <= 0.02 or h <= 0.02 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
                raise ValueError("crop_box must be [x, y, width, height] inside 0..1 with a positive size")
        if self.straighten == "auto" and self.angle is not None:
            raise ValueError("give either straighten='auto' or an angle, not both")
        return self


class RetouchOut(ToolOutput):
    width: int = Field(description="Width of the returned preview, px.")
    height: int
    full_width: int = Field(description="Width of the full-size result after crop, px (estimated from the crop).")
    full_height: int
    aspect_ratio: float = Field(description="Width / height of the result.")
    rotation_deg: float
    upright: str
    spots_healed: int
    dust_found: int
    red_eyes_fixed: int
    applied: dict[str, float]


@tool(kind="repair", title="Crop, straighten and clean up a photo", timeout_s=400,
      examples=[{"arguments": {"photo": "beach.jpg", "aspect": "4:5", "straighten": "auto"}},
                {"arguments": {"photo": "sky.jpg", "spots": [{"x": 0.31, "y": 0.22, "radius": 0.01}]}}])
def retouch_photo(args: RetouchIn, ctx: ToolContext) -> ToolResult[RetouchOut]:
    """Use for 'crop to 4:5 / square / 16:9', 'straighten the horizon', 'fix converging lines', 'remove dust spots or \
blemishes', 'fix red eye', 'sharpen', 'reduce noise', 'fix lens distortion'. Applies crop/aspect, rotation or \
automatic straighten/upright, non-generative spot healing at given points (or automatic dust finding), red-eye, \
sharpening, noise reduction and lens corrections, on top of an optional look_file. Returns the retouched image, a \
before/after and an updated look.json. Use after grade_photo, before export_photos; the original is never \
modified."""
    if not any([args.aspect, args.crop_box, args.straighten, args.angle is not None, args.spots, args.auto_dust,
                args.red_eye, args.sharpen is not None, args.noise_reduction is not None, args.lens_corrections]):
        raise ToolError("nothing_to_do", "No retouch operation was requested.",
                        "Pass at least one of aspect, crop_box, straighten, angle, spots, auto_dust, red_eye, "
                        "sharpen, noise_reduction or lens_corrections.")
    look = C.read_look(args.look_file)
    wd = C.work_dir()
    photo = C.stage_photo(args.photo, wd)
    sha = C.sha256_file(photo)
    lcmds, notes = C.look_commands(look, sha)
    before = wd / "before.jpg"
    out = ctx.output_path("retouched.jpg")
    cmds = list(lcmds) + [{"command": "photo.inspect"}, C.export_cmd(before, args.preview_size, 90)]
    hist = list((look or {}).get("history") or [])
    if args.lens_corrections:
        cmds.append({"command": "develop.merge", "params": {"settings": {"optics": {"lens_profile": True,
                                                                                    "remove_ca": True}}}})
        hist.append("lens corrections")
    if args.straighten in ("level", "vertical", "full"):
        cmds.append({"command": "geometry.upright", "params": {"mode": args.straighten}})
        hist.append(f"upright {args.straighten}")
    if args.straighten == "auto":
        cmds.append({"command": "crop.autoStraighten"})
        hist.append("auto straighten")
    if args.angle is not None:
        cmds.append({"command": "crop.straighten", "params": {"angle": args.angle}})
        hist.append(f"rotate {args.angle:g}°")
    if args.aspect:
        asp = args.aspect if args.aspect in ("original", "free") else C.ASPECTS[args.aspect]
        cmds.append({"command": "crop.aspect", "params": {"aspect": asp}})
        hist.append(f"aspect {args.aspect}")
    if args.crop_box:
        x, y, w, h = args.crop_box
        cmds.append({"command": "crop.set", "params": {"rect": [x, y, min(1.0, x + w), min(1.0, y + h)]}})
        hist.append("crop box")
    for s in args.spots:
        cmds.append({"command": "spot.add", "params": {"mode": s.mode, "points": [[s.x, s.y]], "size": s.radius}})
    if args.spots:
        hist.append(f"{len(args.spots)} spots")
    if args.auto_dust:
        cmds.append({"command": "spot.findDust", "params": {"sensitivity": 50}})
        hist.append("auto dust")
    for e in args.red_eye:
        cmds.append({"command": "redeye.add", "params": {"center": [e.x, e.y], "rx": e.radius, "ry": e.radius}})
    vals = {}
    if args.sharpen is not None:
        vals["detail.sharpenAmount"] = args.sharpen
    if args.noise_reduction is not None:
        vals["detail.nrLuminance"] = args.noise_reduction
        vals["detail.nrColor"] = max(25.0, args.noise_reduction / 2)
    if vals:
        cmds.append({"command": "develop.set", "params": {"values": vals}})
        hist.append("detail " + ", ".join(f"{k}={v:g}" for k, v in vals.items()))
    cmds += [C.export_cmd(out, args.preview_size, 92), {"command": "develop.get"}]
    ctx.progress(20, "rendering")
    res = C.run_chain(ctx, photo, cmds, wd)
    settings = res.get("develop.get") or {}
    info = res.get("photo.inspect") or {}
    dust = res.get("spot.findDust") or {}
    ctx.progress(80, "writing evidence")
    w, h = C.image_size(out)
    crop = settings.get("crop") or {}
    geo = crop.get("geometry") or {}
    rect = geo.get("rect") or {"x0": 0, "x1": 1, "y0": 0, "y1": 1}
    fw0, fh0 = int(info.get("width") or 0), int(info.get("height") or 0)
    full_w = round(fw0 * (rect["x1"] - rect["x0"])) if fw0 else w
    full_h = round(fh0 * (rect["y1"] - rect["y0"])) if fh0 else h
    ba = ctx.output_path("before_after.jpg")
    C.side_by_side(before, out, ba)
    look_path = ctx.output_path("look.json")
    C.write_look(look_path, settings, sha, args.photo.name, hist)
    upright = str((settings.get("geometry") or {}).get("upright", "off"))
    uncertain = list(notes)
    dust_found = int(dust.get("added") or len(dust.get("spots") or [])) if isinstance(dust, dict) else 0
    if args.auto_dust and dust_found == 0:
        uncertain.append("Automatic dust finding found no spots; pass spots with x, y if you can see some.")
    if args.straighten == "auto" and abs(float(geo.get("angle") or 0)) < 0.05:
        uncertain.append("Auto straighten found no tilt to correct (no clear horizon or plumb lines); pass an "
                         "angle instead if the photo looks tilted.")
    if args.straighten in ("level", "vertical", "full") and not (settings.get("geometry") or {}).get(
            "upright_transform"):
        uncertain.append(f"Upright '{args.straighten}' found no usable lines; the perspective was left unchanged.")
    if args.lens_corrections and not info.get("meta", {}).get("lens"):
        uncertain.append("The photo carries no lens data, so lens-profile corrections may have had no effect.")
    if args.red_eye:
        uncertain.append("Red-eye pupils are detected inside each given circle; check the eyes in the result.")
    n_spots = len(settings.get("spots") or [])
    data = RetouchOut(width=w, height=h, full_width=full_w, full_height=full_h, aspect_ratio=round(w / h, 4),
                      rotation_deg=round(float(geo.get("angle") or 0), 3), upright=upright, spots_healed=n_spots,
                      dust_found=dust_found, red_eyes_fixed=len(settings.get("red_eye") or []),
                      applied=C.changed_settings(settings))
    parts = [f"{full_w}×{full_h} (ratio {data.aspect_ratio})"]
    if data.rotation_deg:
        parts.append(f"rotated {data.rotation_deg}°")
    if upright != "off":
        parts.append(f"upright {upright}")
    if n_spots:
        parts.append(f"{n_spots} spots healed")
    if data.red_eyes_fixed:
        parts.append(f"{data.red_eyes_fixed} red eyes fixed")
    if vals:
        parts.append("detail " + ", ".join(f"{k.split('.')[1]} {v:g}" for k, v in vals.items()))
    return ToolResult(
        data=data, summary="Retouched: " + ", ".join(parts), uncertain=uncertain,
        outputs=[OutputFile(out, f"Retouched photo, {args.preview_size}px long edge"),
                 OutputFile(ba, "Before (left) and after (right)"),
                 OutputFile(look_path, "Updated look: pass as look_file to the next edit or export_photos")],
        next_step="Show before_after.jpg; pass look.json to export_photos for the full-size file.")
