"""grade_photo (global look/tone/colour) and adjust_area (masked local edits)."""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from pydantic import Field, model_validator
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool)

from . import _common as C

PhotoFile = Annotated[InputFile, FileConstraints(extensions=C.PHOTO_EXTS)]
LookFile = Annotated[InputFile, FileConstraints(extensions=[".json"])]


class GradeIn(ToolInput):
    photo: PhotoFile = Field(description="The photo to grade (file id from upload_file or an https URL). Never "
                                         "modified: a new graded copy is written.")
    preset: str | None = Field(default=None, max_length=80,
                               description="A preset look id from list_looks, e.g. 'lc.golden-hour', "
                                           "'lc.teal-orange', 'lc.faded-matte', 'lc.bw-high-contrast'.")
    preset_amount: float = Field(default=100, ge=0, le=200, description="Strength of the preset look, 0-200 %.")
    profile: str | None = Field(default=None, max_length=80,
                                description="Optional colour profile id from list_looks (e.g. 'lc.vivid', "
                                            "'lc.landscape', 'lc.mono').")
    auto_tone: bool = Field(default=False, description="Let the engine set exposure, contrast, highlights, shadows, "
                                                       "whites and blacks automatically (applied before the preset "
                                                       "and sliders).")
    black_and_white: bool = Field(default=False, description="Convert to black & white (with an automatic B&W mix "
                                                             "unless bw.* sliders are given).")
    adjustments: dict[str, float] | None = Field(
        default=None, description="Global sliders as control id → value, applied last, e.g. {\"light.exposure\": "
                                  "0.5, \"light.highlights\": -60, \"color.vibrance\": 20, \"wb.temp\": 5800}. "
                                  "Exposure is in stops (-5..5), most others -100..100; ids and ranges come from "
                                  "list_looks(what='controls').")
    warmth: float | None = Field(
        default=None, ge=-100, le=100,
        description="Make the colour warmer (+) or cooler (-), -100..100: 'warmer', 'cozier', 'less cold', "
                    "'golden' → +30..+60; 'cooler', 'less yellow/orange' → -30..-60. Use this instead of setting "
                    "wb.temp by hand: it works the same on JPEGs and raws, and the tool measures the result and "
                    "strengthens the shift (up to 2 more renders) if the photo did not visibly change warmth, e.g. "
                    "because brightening also strengthened an existing cool tint.")
    look_file: LookFile | None = Field(default=None, description="look.json from an earlier grade_photo / "
                                                                 "adjust_area / retouch_photo call, to build on "
                                                                 "those edits.")
    preview_size: int = Field(default=2048, ge=256, le=8192, description="Long edge in px of the graded image "
                                                                         "returned (full-size files come from "
                                                                         "export_photos).")


class Stats(ToolOutput):
    mean_luminance: float
    clipped_highlights_pct: float
    clipped_shadows_pct: float
    contrast_std: float
    mean_saturation: float
    warmth: float = Field(description="Mean red minus blue: higher = warmer. after - before shows the colour "
                                      "temperature change.")


class GradeOut(ToolOutput):
    applied: dict[str, float] = Field(description="Every slider now away from its default (control id → value).")
    preset: str | None
    profile: str | None
    treatment: str
    before: Stats
    after: Stats
    rejected_controls: list[str]
    white_balance_temp: float | None = Field(default=None, description="wb.temp the graded image uses (6500 = as "
                                                                       "shot on JPEGs, Kelvin on raws).")


def _stats(p) -> Stats:
    return Stats(**C.stats(C.load_rgb(p, 1024)))


@tool(kind="edit", title="Grade a photo (look, tone and colour)", timeout_s=300,
      examples=[{"arguments": {"photo": "beach.jpg", "preset": "lc.golden-hour", "preset_amount": 70,
                               "adjustments": {"light.highlights": -50}}},
                {"arguments": {"photo": "room.jpg", "adjustments": {"light.exposure": 1.2, "light.shadows": 30},
                               "warmth": 40}}])
def grade_photo(args: GradeIn, ctx: ToolContext) -> ToolResult[GradeOut]:
    """After inspect_photo, use to make a photo look better or give it a style: 'brighten it', 'recover the sky', \
'make it warmer', 'film look', 'black and white'. Applies a preset look (0-200 %), auto tone, a colour profile, B&W, \
a measured warmer/cooler shift (warmth) and global sliders (exposure, contrast, highlights, shadows, whites, blacks, white balance, vibrance, clarity, \
dehaze, vignette, grain, colour grading, HSL mixer, tone curve). Returns a NEW graded image, a before/after, \
brightness/clipping/warmth stats before→after and look.json to pass to the next call. The original is never modified."""
    C.check_preset(args.preset)
    vals, rejected, clamp_notes = C.validate_adjustments(args.adjustments)
    if rejected and not (vals or args.preset or args.auto_tone or args.black_and_white or args.profile):
        raise ToolError("unknown_control", f"Unknown slider id(s): {', '.join(rejected[:10])}.",
                        "Call list_looks with what='controls' (and a section such as 'light') and use the exact "
                        "ids, e.g. 'light.exposure', 'color.vibrance', 'wb.temp'.")
    if args.profile:
        ids = {p["id"] for p in C.presets_and_profiles()[1]}
        if args.profile not in ids:
            raise ToolError("unknown_profile", f"There is no profile called '{args.profile}'.",
                            "Call list_looks(what='looks') and pass one of the profile ids, e.g. 'lc.vivid'.")
    look = C.read_look(args.look_file)
    wd = C.work_dir()
    photo = C.stage_photo(args.photo, wd)
    sha = C.sha256_file(photo)
    lcmds, look_notes = C.look_commands(look, sha)
    before = wd / "before.jpg"
    graded = ctx.output_path("graded.jpg")
    cmds = list(lcmds) + [C.export_cmd(before, args.preview_size, 90)]
    history = list((look or {}).get("history") or [])
    if args.auto_tone:
        cmds.append({"command": "develop.auto"})
        history.append("auto tone")
    if args.profile:
        cmds.append({"command": "develop.profile", "params": {"id": args.profile}})
        history.append(f"profile {args.profile}")
    if args.preset:
        cmds.append({"command": "preset.apply", "params": {"id": args.preset, "amount": args.preset_amount}})
        history.append(f"preset {args.preset} {args.preset_amount:g}%")
    if args.black_and_white:
        if any(k.startswith("bw.") for k in vals):
            cmds.append({"command": "develop.treatment", "params": {"bw": True}})
        else:
            cmds.append({"command": "develop.autoBwMix"})
        history.append("black & white")
    pre_cmds = list(cmds)
    if args.warmth is not None:
        if "wb.temp" in vals:
            vals.pop("wb.temp")
            clamp_notes = clamp_notes + ["wb.temp from adjustments was replaced by the warmth shift."]
        probe = [c for c in pre_cmds if c["command"] != "app.export"]
        if vals:
            probe.append({"command": "develop.set", "params": {"values": vals}})
        probe.append({"command": "develop.get"})
        base_settings = C.run_chain(ctx, photo, probe, wd).get("develop.get") or {}
        base_temp = float(((base_settings.get("wb") or {}).get("temp")) or 6500.0)
        history.append(f"warmth {args.warmth:+g}")
    if vals:
        history.append("sliders " + ", ".join(f"{k}={v:g}" for k, v in vals.items()))

    def render(temp: float | None):
        v = dict(vals)
        if temp is not None:
            v["wb.temp"] = temp
        chain = list(pre_cmds)
        if v:
            chain.append({"command": "develop.set", "params": {"values": v}})
        chain += [C.export_cmd(graded, args.preview_size, 92), {"command": "develop.get"}]
        return C.run_chain(ctx, photo, chain, wd)

    ctx.progress(20, "rendering")
    warm_notes: list[str] = []
    if args.warmth is None:
        res = render(None)
        b, a = _stats(before), _stats(graded)
    else:
        target = max(0.01, 0.0008 * abs(args.warmth))
        sign = 1.0 if args.warmth >= 0 else -1.0
        strength = float(args.warmth)
        for attempt in range(1 if args.black_and_white else 3):
            temp = C.kelvin_shift(base_temp, strength)
            res = render(temp)
            b, a = _stats(before), _stats(graded)
            got = sign * (a.warmth - b.warmth)
            if got >= 0.7 * target or temp in (2000.0, 50000.0) or abs(strength) >= 300:
                break
            ctx.progress(40 + 15 * attempt, "colour did not shift enough; strengthening the warmth")
            strength = sign * min(300.0, abs(strength) * min(3.0, max(1.5, target / max(got, 0.003))))
        if sign * (a.warmth - b.warmth) < 0.5 * target:
            warm_notes.append(f"Asked for warmth {args.warmth:+g} but measured warmth only moved {b.warmth}→{a.warmth} "
                              f"(white balance {temp:g}); the colour change may not be visible.")
        elif abs(strength) > abs(args.warmth) + 1e-6:
            warm_notes.append(f"The white-balance shift was strengthened to reach a visible change: warmth "
                              f"{b.warmth}→{a.warmth} with white balance {temp:g}.")
    settings = res.get("develop.get") or {}
    ctx.progress(75, "measuring before/after")
    ba = ctx.output_path("before_after.jpg")
    C.side_by_side(before, graded, ba)
    look_path = ctx.output_path("look.json")
    C.write_look(look_path, settings, sha, args.photo.name, history)

    uncertain = list(look_notes) + clamp_notes + warm_notes
    wb_temp = (settings.get("wb") or {}).get("temp")
    if args.warmth is None and "wb.temp" in vals and abs(a.warmth - b.warmth) < 0.01:
        uncertain.append(f"wb.temp={vals['wb.temp']:g} barely changed the measured warmth ({b.warmth}→{a.warmth}); "
                         "for a visibly warmer or cooler result use the warmth argument instead.")
    if rejected:
        uncertain.append(f"Ignored unknown slider id(s): {', '.join(rejected[:10])} (see list_looks controls).")
    if a.clipped_highlights_pct > b.clipped_highlights_pct + 1.0:
        uncertain.append(f"Highlight clipping rose from {b.clipped_highlights_pct}% to {a.clipped_highlights_pct}%; "
                         "lower light.highlights / light.whites or exposure if detail matters.")
    if a.clipped_shadows_pct > b.clipped_shadows_pct + 2.0:
        uncertain.append(f"Shadow clipping rose from {b.clipped_shadows_pct}% to {a.clipped_shadows_pct}%.")
    treatment = str(settings.get("treatment", "color"))
    prof = (settings.get("profile") or {}).get("id")
    data = GradeOut(applied=C.changed_settings(settings), preset=args.preset, profile=prof, treatment=treatment,
                    before=b, after=a, rejected_controls=rejected,
                    white_balance_temp=float(wb_temp) if isinstance(wb_temp, (int, float)) else None)
    what = ", ".join(history[len((look or {}).get("history") or []):]) or "no changes"
    summary = (f"Graded ({what[:120]}): brightness {b.mean_luminance}→{a.mean_luminance}, highlights clipped "
               f"{b.clipped_highlights_pct}%→{a.clipped_highlights_pct}%, warmth {b.warmth}→{a.warmth}")
    return ToolResult(
        data=data, summary=summary, uncertain=uncertain,
        status="partial" if rejected else "ok",
        outputs=[OutputFile(graded, f"Graded photo, {args.preview_size}px long edge"),
                 OutputFile(ba, "Before (left) and after (right)"),
                 OutputFile(look_path, "Reusable look: pass as look_file to the next edit or to export_photos")],
        next_step="Show before_after.jpg. Pass look.json as look_file to adjust_area / retouch_photo / export_photos "
                  "to keep these edits.")


# ----------------------------------------------------------------------------------------------
# adjust_area

Point = tuple[float, float]
MaskKind = Literal["radial", "linear", "luminance", "color", "sky", "subject", "background"]
LOCAL_KEYS = {"exposure", "contrast", "highlights", "shadows", "whites", "blacks", "temp", "tint", "texture",
              "clarity", "dehaze", "hue", "saturation", "sharpness", "noise", "moire", "defringe", "color_hue",
              "color_sat"}


class Shape(ToolInput):
    kind: MaskKind = Field(description="radial (ellipse), linear (gradient), luminance (tonal range), color "
                                       "(colour picked at `pick`), sky, subject, background (automatic, "
                                       "heuristic).")
    center: Point | None = Field(default=None, description="radial: ellipse centre [x, y], 0-1 from top-left.")
    rx: float | None = Field(default=None, gt=0, le=2, description="radial: horizontal radius, fraction of the "
                                                                    "long edge (e.g. 0.2).")
    ry: float | None = Field(default=None, gt=0, le=2, description="radial: vertical radius, fraction of the long "
                                                                    "edge.")
    angle: float = Field(default=0, ge=-180, le=180, description="radial: rotation in degrees.")
    feather: float = Field(default=50, ge=0, le=100, description="radial: edge softness 0-100.")
    start: Point | None = Field(default=None, description="linear: [x, y] where the effect is full (0-1 coords).")
    end: Point | None = Field(default=None, description="linear: [x, y] where the effect has faded to none.")
    lum_lo: float = Field(default=0.0, ge=0, le=1, description="luminance: lower bound 0 (black)..1 (white).")
    lum_hi: float = Field(default=1.0, ge=0, le=1, description="luminance: upper bound.")
    lum_feather: float = Field(default=0.1, ge=0, le=1, description="luminance: falloff width.")
    pick: Point | None = Field(default=None, description="color: [x, y] of a pixel whose colour to select.")
    refine: float = Field(default=50, ge=0, le=100, description="color: how wide the colour range is (higher = "
                                                                "more similar colours).")

    @model_validator(mode="after")
    def _geometry(self):  # noqa: ANN202
        for p in (self.center, self.start, self.end, self.pick):
            if p is not None and not all(-0.5 <= v <= 1.5 for v in p):
                raise ValueError("points are image fractions: x and y must be between 0 and 1")
        if self.kind == "radial" and (self.center is None or self.rx is None):
            raise ValueError("a radial mask needs center [x, y] and rx (ry defaults to rx)")
        if self.kind == "linear" and (self.start is None or self.end is None):
            raise ValueError("a linear mask needs start [x, y] and end [x, y]")
        if self.kind == "linear" and self.start == self.end:
            raise ValueError("linear start and end must differ")
        if self.kind == "luminance" and self.lum_lo >= self.lum_hi:
            raise ValueError("lum_lo must be below lum_hi")
        if self.kind == "color" and self.pick is None:
            raise ValueError("a color mask needs pick [x, y]")
        return self


class MaskSpec(Shape):
    invert: bool = Field(default=False, description="Apply everywhere EXCEPT the shape.")
    subtract: Shape | None = Field(default=None, description="Optional second shape removed from this mask (e.g. "
                                                             "sky minus a radial over a building).")
    adjustments: dict[str, float] = Field(description="Local sliders: exposure (stops, -4..4), contrast, "
                                                      "highlights, shadows, whites, blacks, temp (+warm/-cool), "
                                                      "tint, texture, clarity, dehaze, hue, saturation, "
                                                      "sharpness, noise (-100..100), color_hue (0-360) + color_sat "
                                                      "(0-100) for a colour overlay.")
    amount: float = Field(default=100, ge=0, le=200, description="Overall strength of this mask's effect, %.")


class AdjustIn(ToolInput):
    photo: PhotoFile = Field(description="The photo (file id or https URL); never modified.")
    masks: list[MaskSpec] = Field(min_length=1, max_length=12, description="One or more masked adjustments.")
    look_file: LookFile | None = Field(default=None, description="look.json from an earlier call to build on.")
    preview_size: int = Field(default=2048, ge=256, le=8192, description="Long edge of the returned image, px.")


class MaskResult(ToolOutput):
    kind: str
    coverage_pct: float = Field(description="% of the frame the mask affects noticeably (measured).")
    adjustments: dict[str, float]
    inside_luminance_before: float
    inside_luminance_after: float
    outside_luminance_before: float
    outside_luminance_after: float


class AdjustOut(ToolOutput):
    masks_applied: list[MaskResult]
    before: Stats
    after: Stats


def _shape_params(s: Shape) -> dict:
    if s.kind == "radial":
        return {"kind": "radial", "center": list(s.center), "rx": s.rx, "ry": s.ry or s.rx, "angle": s.angle,
                "feather": s.feather}
    if s.kind == "linear":
        return {"kind": "linear", "start": list(s.start), "end": list(s.end)}
    if s.kind == "luminance":
        return {"kind": "luminanceRange", "lo": s.lum_lo, "hi": s.lum_hi, "loFeather": s.lum_feather,
                "hiFeather": s.lum_feather}
    if s.kind == "color":
        return {"kind": "colorRange", "refine": s.refine}
    return {"kind": s.kind}


def _mask_cmds(m: MaskSpec, values: dict) -> list[dict]:
    cmds = [{"command": "mask.add", "params": _shape_params(m)}]
    if m.kind == "color":
        cmds.append({"command": "mask.sampleColor", "params": {"x": m.pick[0], "y": m.pick[1]}})
    if m.subtract is not None:
        sp = _shape_params(m.subtract)
        cmds.append({"command": "mask.addComponent", "params": {"op": "subtract", **sp}})
        if m.subtract.kind == "color":
            cmds.append({"command": "mask.sampleColor", "params": {"x": m.subtract.pick[0],
                                                                   "y": m.subtract.pick[1],
                                                                   "component": 1}})
    if m.invert:
        cmds.append({"command": "mask.invert"})
    cmds.append({"command": "mask.adjust", "params": {"values": values}})
    return cmds


@tool(kind="edit", title="Adjust part of a photo (masks)", timeout_s=400,
      examples=[{"arguments": {"photo": "beach.jpg", "masks": [
          {"kind": "linear", "start": [0.5, 0.0], "end": [0.5, 0.45], "adjustments": {"exposure": -0.8,
                                                                                         "highlights": -40}}]}}])
def adjust_area(args: AdjustIn, ctx: ToolContext) -> ToolResult[AdjustOut]:
    """Use when only part of a photo should change: 'darken the sky', 'brighten the face', 'warm the sunset glow', \
'add a vignette spotlight', 'make the greens pop'. Adds masks (radial, linear gradient, luminance range, colour \
range, automatic sky/subject/background; invert or subtract a second shape), each with local exposure, contrast, \
highlights, shadows, temperature, clarity, saturation and more, on top of an optional look_file. Returns the \
edited image, a mask overlay showing where each mask applied (measured), and an updated look.json. Use after \
grade_photo; the original is never modified."""
    plan = []
    for i, m in enumerate(args.masks):
        bad = [k for k in m.adjustments if k not in LOCAL_KEYS]
        if bad:
            raise ToolError("unknown_control", f"Mask {i + 1}: unknown local slider(s) {', '.join(bad[:8])}.",
                            "Use local names without a section prefix: exposure, contrast, highlights, shadows, "
                            "whites, blacks, temp, tint, texture, clarity, dehaze, hue, saturation, sharpness, "
                            "noise, color_hue, color_sat (list_looks section='mask').")
        if not m.adjustments:
            raise ToolError("no_adjustments", f"Mask {i + 1} has no adjustments.",
                            "Give each mask at least one local slider, e.g. {\"exposure\": -0.7}.")
        plan.append({**m.adjustments, "amount": m.amount})
    look = C.read_look(args.look_file)
    wd = C.work_dir()
    photo = C.stage_photo(args.photo, wd)
    sha = C.sha256_file(photo)
    lcmds, notes = C.look_commands(look, sha)
    size = args.preview_size
    probe_size = min(size, 1024)
    before, before_small = wd / "before.jpg", wd / "before_small.png"
    out = ctx.output_path("adjusted.jpg")
    cmds = list(lcmds) + [C.export_cmd(before, size, 90), C.export_cmd(before_small, probe_size, 100)]
    for m, vals in zip(args.masks, plan):
        cmds += _mask_cmds(m, vals)
    after_small = wd / "after_small.png"
    cmds += [C.export_cmd(out, size, 92), C.export_cmd(after_small, probe_size, 100), {"command": "develop.get"}]
    ctx.progress(15, "rendering masks")
    res = C.run_chain(ctx, photo, cmds, wd)
    settings = res.get("develop.get") or {}

    # Measure where each mask acts: render the base with only that mask, its effect replaced by -2 stops.
    base = C.load_rgb(before_small)
    after = C.load_rgb(after_small)
    yb, ya = C.luma(base), C.luma(after)
    weights = []
    for i, m in enumerate(args.masks):
        ctx.progress(30 + 50 * i / len(args.masks), f"measuring mask {i + 1}")
        probe = wd / f"probe{i}.png"
        pc = list(lcmds) + [{"command": "mask.deleteAll"}] + _mask_cmds(m, {"exposure": -2, "amount": 100}) + \
            [C.export_cmd(probe, probe_size, 100)]
        C.run_chain(ctx, photo, pc, wd)
        yp = C.luma(C.load_rgb(probe))
        if yp.shape != yb.shape:
            weights.append(np.zeros_like(yb))
            continue
        drop = np.clip(yb - yp, 0, None)
        expected = np.maximum(yb * 0.6, 0.02)  # -2 stops removes roughly 60-75 % of encoded brightness
        weights.append(np.clip(drop / expected, 0, 1))
    results = []
    overlay = base.copy()
    palette = [(1, 0.15, 0.15), (0.2, 0.5, 1), (0.2, 1, 0.3), (1, 0.85, 0.1), (0.9, 0.2, 1), (0.1, 1, 1)]
    for i, (m, w) in enumerate(zip(args.masks, weights)):
        inside = w > 0.25
        cov = float(inside.mean() * 100)
        out_sel = ~inside

        def mean(y, sel):
            return round(float(y[sel].mean()), 4) if sel.any() else 0.0

        results.append(MaskResult(kind=m.kind, coverage_pct=round(cov, 2), adjustments=dict(m.adjustments),
                                  inside_luminance_before=mean(yb, inside), inside_luminance_after=mean(ya, inside),
                                  outside_luminance_before=mean(yb, out_sel),
                                  outside_luminance_after=mean(ya, out_sel)))
        col = np.array(palette[i % len(palette)], dtype=np.float32)
        a = (w * 0.55)[..., None]
        overlay = overlay * (1 - a) + col * a
    ov_path = ctx.output_path("mask_overlay.jpg")
    C.save_rgb(overlay, ov_path)
    ba = ctx.output_path("before_after.jpg")
    C.side_by_side(before, out, ba)
    history = list((look or {}).get("history") or []) + [f"mask {m.kind} {m.adjustments}" for m in args.masks]
    look_path = ctx.output_path("look.json")
    C.write_look(look_path, settings, sha, args.photo.name, history)

    uncertain = list(notes)
    for i, (m, r) in enumerate(zip(args.masks, results)):
        if m.kind in ("sky", "subject", "background"):
            uncertain.append(f"Mask {i + 1} ({m.kind}) is an automatic heuristic selection ({r.coverage_pct}% of "
                             "the frame): check mask_overlay.jpg covers the intended area.")
        if r.coverage_pct < 0.5:
            uncertain.append(f"Mask {i + 1} ({m.kind}) affects almost nothing ({r.coverage_pct}% of the frame).")
    status = "partial" if any(r.coverage_pct < 0.5 for r in results) else "ok"
    data = AdjustOut(masks_applied=results, before=Stats(**C.stats(base)), after=Stats(**C.stats(after)))
    summary = "; ".join(f"{r.kind} mask on {r.coverage_pct}% of frame: inside brightness "
                        f"{r.inside_luminance_before}→{r.inside_luminance_after}" for r in results)[:290]
    return ToolResult(
        data=data, summary=summary, uncertain=uncertain, status=status,
        outputs=[OutputFile(out, f"Adjusted photo, {size}px long edge"),
                 OutputFile(ov_path, "Where each mask applied (tinted: red, blue, green… in mask order)"),
                 OutputFile(ba, "Before (left) and after (right)"),
                 OutputFile(look_path, "Updated look: pass as look_file to the next edit or export_photos")],
        next_step="Check mask_overlay.jpg covers the intended area before showing before_after.jpg; pass look.json "
                  "on to the next step.")
