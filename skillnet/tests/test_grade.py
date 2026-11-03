import json
from pathlib import Path

import numpy as np
from skillnet_sdk import call_tool

from conftest import out, rgb, sha
from tools import _common as C
from tools.grade import adjust_area, grade_photo


def test_exposure_brightens_dark_photo(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "dark.jpg"), "adjustments": {"light.exposure": 1.0}},
                    output_root=tmp_path)
    assert env.status == "ok", env
    b, a = env.data["before"]["mean_luminance"], env.data["after"]["mean_luminance"]
    assert a > b + 0.05
    assert env.data["applied"]["light.exposure"] == 1.0
    graded = out(env, "graded.jpg")
    assert C.luma(rgb(graded)).mean() > C.luma(rgb(fx / "dark.jpg")).mean() + 0.05
    w, h = C.image_size(out(env, "before_after.jpg"))
    assert w > h  # side by side


def test_highlights_recover_blown_sky_and_original_untouched(fx, tmp_path):
    before_hash = sha(fx / "blown.jpg")
    env = call_tool(grade_photo, {"photo": str(fx / "blown.jpg"),
                                  "adjustments": {"light.highlights": -80, "light.whites": -30}},
                    output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["before"]["clipped_highlights_pct"] > 10
    assert env.data["after"]["clipped_highlights_pct"] < env.data["before"]["clipped_highlights_pct"] - 5
    assert sha(fx / "blown.jpg") == before_hash


def test_brighter_and_warmer_dark_cold_room(fx, tmp_path):
    src = fx / "cold_room.jpg"
    before_hash = sha(src)
    env = call_tool(grade_photo, {"photo": str(src), "adjustments": {"light.exposure": 1.8, "light.shadows": 25},
                                  "warmth": 40}, output_root=tmp_path)
    assert env.status == "ok", env
    b, a = env.data["before"], env.data["after"]
    assert b["warmth"] < -0.01  # the fixture really is cold
    assert a["mean_luminance"] > b["mean_luminance"] + 0.1
    assert a["warmth"] > b["warmth"] + 0.02, (b, a)
    assert env.data["white_balance_temp"] > 7500
    # independent measurement of the written file agrees
    g, o = rgb(out(env, "graded.jpg")), rgb(src)
    assert float((g[..., 0] - g[..., 2]).mean()) > float((o[..., 0] - o[..., 2]).mean()) + 0.02
    assert sha(src) == before_hash
    # the look keeps the warmer white balance for export
    assert env.data["applied"].get("wb.temp", 0) > 7500
    look = json.loads(out(env, "look.json").read_text())
    assert any("warmth" in h for h in look.get("history", [])), look.get("history")


def test_cooler_and_hand_set_temp_warning(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "cold_room.jpg"), "warmth": -40}, output_root=tmp_path / "a")
    assert env.data["after"]["warmth"] < env.data["before"]["warmth"] - 0.02
    env = call_tool(grade_photo, {"photo": str(fx / "cold_room.jpg"),
                                  "adjustments": {"light.exposure": 1.8, "wb.temp": 6800}}, output_root=tmp_path / "b")
    assert any("warmth argument" in u for u in env.uncertain), env.uncertain


def test_preset_and_look_file_round_trip(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "exif.jpg"), "preset": "lc.golden-hour", "preset_amount": 80},
                    output_root=tmp_path / "a")
    assert env.status == "ok"
    assert env.data["preset"] == "lc.golden-hour" and env.data["applied"]
    look = out(env, "look.json")
    doc = json.loads(look.read_text())
    assert doc["kind"] == "pro-photo-darkroom-look" and doc["settings"]
    env2 = call_tool(grade_photo, {"photo": str(fx / "exif.jpg"), "look_file": str(look)},
                     output_root=tmp_path / "b")
    assert env2.status == "ok"
    assert env2.data["applied"] == env.data["applied"]
    a1 = rgb(out(env, "graded.jpg"))
    a2 = rgb(out(env2, "graded.jpg"))
    assert np.abs(a1 - a2).mean() < 0.01


def test_black_and_white_has_no_colour(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "sunset.png"), "black_and_white": True}, output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["treatment"] == "bw"
    assert env.data["before"]["mean_saturation"] > 0.2
    assert env.data["after"]["mean_saturation"] < 0.03


def test_black_and_white_film_grain_adds_texture(fx, tmp_path):
    """'Moody black and white with grain': B&W stays colourless and grain adds measurable pixel texture."""
    flat = call_tool(grade_photo, {"photo": str(fx / "sunset.png"), "black_and_white": True},
                     output_root=tmp_path / "flat")
    grainy = call_tool(grade_photo, {"photo": str(fx / "sunset.png"), "black_and_white": True,
                                     "adjustments": {"grain.amount": 60}}, output_root=tmp_path / "grain")
    assert grainy.status == "ok", grainy
    assert grainy.data["applied"]["grain.amount"] == 60
    assert grainy.data["after"]["mean_saturation"] < 0.03

    def texture(p):
        a = C.luma(rgb(p))
        return float(np.abs(np.diff(a, axis=1)).mean())

    assert texture(out(grainy, "graded.jpg")) > texture(out(flat, "graded.jpg")) + 0.01


def test_graded_file_label_reports_real_size(fx, tmp_path):
    """A small photo is not upscaled to preview_size, and the output says its real size."""
    env = call_tool(grade_photo, {"photo": str(fx / "sunset.png"), "adjustments": {"light.exposure": 0.3},
                                  "preview_size": 4096}, output_root=tmp_path)
    assert env.status == "ok"
    g = next(o for o in env.outputs if o.name == "graded.jpg")
    assert C.image_size(Path(g.path)) == (640, 480)
    assert "640x480" in g.description


def test_strong_blue_cast_warms_noticeably_and_monotonically(fx, tmp_path):
    """A far-too-dark, very blue photo: warmth +45 removes a large share of the cast, +80 is never less warm."""
    src = fx / "harbour.jpg"
    before_hash = sha(src)
    res = {}
    for w in (45, 80):
        env = call_tool(grade_photo, {"photo": str(src), "adjustments": {"light.exposure": 1.5, "light.shadows": 40},
                                      "warmth": w}, output_root=tmp_path / str(w))
        assert env.status == "ok", env
        res[w] = env
    b45, a45 = res[45].data["before"], res[45].data["after"]
    assert b45["warmth"] < -0.2  # really blue
    assert a45["warmth"] > b45["warmth"] + 0.08, (b45, a45)
    assert a45["mean_luminance"] > 0.3
    assert res[80].data["after"]["warmth"] >= a45["warmth"] - 0.005
    # independent measurement of the written file: red minus blue rose clearly
    g, o = rgb(out(res[45], "graded.jpg")), rgb(src)
    assert float((g[..., 0] - g[..., 2]).mean()) > float((o[..., 0] - o[..., 2]).mean()) + 0.08
    # the tint that made it possible is part of the reusable look and is reported
    assert res[45].data["applied"].get("grading.global.sat", 0) > 0
    assert any("colour-grading tint" in u for u in res[45].uncertain)
    assert sha(src) == before_hash


def test_still_dark_is_flagged(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "harbour.jpg"), "adjustments": {"light.exposure": 0.4}},
                    output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["after"]["mean_luminance"] < 0.3
    assert any("still dark" in u for u in env.uncertain)
    assert "light.exposure" in env.next_step


def test_heic_is_refused_clearly(fx, tmp_path):
    for fn, extra in ((grade_photo, {"warmth": 30}), (adjust_area, {"masks": [
            {"kind": "sky", "adjustments": {"exposure": -0.5}}]})):
        env = call_tool(fn, {"photo": str(fx / "IMG_4821.HEIC"), **extra}, output_root=tmp_path / fn.__name__)
        assert env.status == "error" and env.error.code == "unsupported_format"
        assert "not support" in env.error.message and "HEIC" in env.error.message
        assert "JPEG" in env.next_step
        assert not env.outputs


def test_unknown_controls(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "blown.jpg"),
                                  "adjustments": {"light.highlights": -40, "light.sparkle": 10}},
                    output_root=tmp_path / "p")
    assert env.status == "partial"
    assert env.data["rejected_controls"] == ["light.sparkle"]
    env = call_tool(grade_photo, {"photo": str(fx / "blown.jpg"), "adjustments": {"sparkle": 10}},
                    output_root=tmp_path / "e")
    assert env.status == "error" and env.error.code == "unknown_control"
    assert "list_looks" in env.next_step


def test_unknown_preset(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "blown.jpg"), "preset": "lc.no-such-look"},
                    output_root=tmp_path)
    assert env.status == "error" and env.error.code == "unknown_preset"
    assert "list_looks" in env.next_step


def test_out_of_range_is_clamped_and_reported(fx, tmp_path):
    env = call_tool(grade_photo, {"photo": str(fx / "dark.jpg"), "adjustments": {"light.shadows": 250}},
                    output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["applied"]["light.shadows"] == 100
    assert any("clamped" in u for u in env.uncertain)


# ---------------------------------------------------------------- adjust_area

def test_radial_mask_brightens_inside_more(fx, tmp_path):
    env = call_tool(adjust_area, {"photo": str(fx / "dark.jpg"), "masks": [
        {"kind": "radial", "center": [0.5, 0.5], "rx": 0.15, "ry": 0.15, "feather": 20,
         "adjustments": {"exposure": 1.0}}]}, output_root=tmp_path)
    assert env.status == "ok", env
    m = env.data["masks_applied"][0]
    assert 2 < m["coverage_pct"] < 40
    inside = m["inside_luminance_after"] - m["inside_luminance_before"]
    outside = m["outside_luminance_after"] - m["outside_luminance_before"]
    assert inside > 0.03 and inside > outside + 0.03
    assert out(env, "mask_overlay.jpg").stat().st_size > 1000


def test_linear_gradient_darkens_top_only(fx, tmp_path):
    env = call_tool(adjust_area, {"photo": str(fx / "exif.jpg"), "masks": [
        {"kind": "linear", "start": [0.5, 0.0], "end": [0.5, 0.35], "adjustments": {"exposure": -1.0}}]},
                    output_root=tmp_path)
    assert env.status == "ok"
    before = C.luma(rgb(fx / "exif.jpg", 1024))
    after = C.luma(rgb(out(env, "adjusted.jpg"), 1024))
    h = before.shape[0]
    top_b, top_a = before[: h // 6].mean(), after[: h // 6].mean()
    bot_b, bot_a = before[-h // 4:].mean(), after[-h // 4:].mean()
    assert top_a < top_b - 0.08
    assert abs(bot_a - bot_b) < 0.03


def test_sky_mask_and_look_chaining(fx, tmp_path):
    g = call_tool(grade_photo, {"photo": str(fx / "exif.jpg"), "adjustments": {"color.vibrance": 20}},
                  output_root=tmp_path / "g")
    env = call_tool(adjust_area, {"photo": str(fx / "exif.jpg"), "look_file": str(out(g, "look.json")),
                                  "masks": [{"kind": "sky", "adjustments": {"exposure": -0.7}}]},
                    output_root=tmp_path / "a")
    assert env.status in ("ok", "partial")
    look = json.loads(out(env, "look.json").read_text())
    assert look["settings"].get("masks")
    assert any("vibrance" in h for h in look["history"])


def test_mask_errors(fx, tmp_path):
    env = call_tool(adjust_area, {"photo": str(fx / "blown.jpg"), "masks": [
        {"kind": "radial", "adjustments": {"exposure": 1}}]}, output_root=tmp_path / "a")
    assert env.status == "error" and env.error.code == "invalid_arguments"
    assert "center" in env.error.message
    env = call_tool(adjust_area, {"photo": str(fx / "blown.jpg"), "masks": [
        {"kind": "linear", "start": [0.5, 0], "end": [0.5, 0.4], "adjustments": {"light.exposure": -1}}]},
                    output_root=tmp_path / "b")
    assert env.status == "error" and env.error.code == "unknown_control"
    assert env.next_step
