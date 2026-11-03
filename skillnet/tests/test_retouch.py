import numpy as np
from skillnet_sdk import call_tool

from conftest import DUST, out, rgb, sha
from tools import _common as C
from tools.retouch import retouch_photo


def _horizon_rows(path):
    g = C.luma(rgb(path))
    h, w = g.shape
    rows = []
    for x in (int(w * 0.15), int(w * 0.85)):
        rows.append(int(np.argmax(np.abs(np.diff(g[:, x])))))
    return rows, h


def test_crop_to_16_9(fx, tmp_path):
    env = call_tool(retouch_photo, {"photo": str(fx / "blown.jpg"), "aspect": "16:9"}, output_root=tmp_path)
    assert env.status == "ok", env
    w, h = C.image_size(out(env, "retouched.jpg"))
    assert abs(w / h - 16 / 9) / (16 / 9) < 0.01
    assert abs(env.data["full_width"] / env.data["full_height"] - 16 / 9) < 0.02


def test_auto_straighten_and_portrait_crop(fx, tmp_path):
    before = sha(fx / "tilted.jpg")
    rows0, _ = _horizon_rows(fx / "tilted.jpg")
    assert abs(rows0[0] - rows0[1]) > 40  # the fixture really is tilted
    env = call_tool(retouch_photo, {"photo": str(fx / "tilted.jpg"), "straighten": "auto", "aspect": "4:5"},
                    output_root=tmp_path)
    assert env.status == "ok"
    assert abs(env.data["rotation_deg"] + 5) < 0.6
    res = out(env, "retouched.jpg")
    w, h = C.image_size(res)
    assert abs(w / h - 0.8) < 0.01
    rows, hh = _horizon_rows(res)
    assert abs(rows[0] - rows[1]) <= max(3, hh * 0.006)
    assert sha(fx / "tilted.jpg") == before


def test_explicit_angle_sign(fx, tmp_path):
    env = call_tool(retouch_photo, {"photo": str(fx / "blown.jpg"), "angle": 3}, output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["rotation_deg"] == 3
    rows, _ = _horizon_rows(out(env, "retouched.jpg"))
    assert rows[1] > rows[0] + 10  # positive = clockwise: right side of the horizon drops


def test_spot_heal_and_auto_dust(fx, tmp_path):
    w, h = 1200, 800
    spots = [{"x": x / w, "y": y / h, "radius": 0.012} for x, y in DUST[:2]]
    env = call_tool(retouch_photo, {"photo": str(fx / "dusty.jpg"), "spots": spots, "auto_dust": True},
                    output_root=tmp_path)
    assert env.status == "ok", env
    assert env.data["spots_healed"] >= 2
    a, b = rgb(fx / "dusty.jpg"), rgb(out(env, "retouched.jpg"))
    for x, y in DUST[:2]:
        assert a[y - 3:y + 4, x - 3:x + 4].mean() < 0.3
        assert b[y - 3:y + 4, x - 3:x + 4].mean() > 0.6
    if env.data["dust_found"]:
        x, y = DUST[2]
        assert b[y - 3:y + 4, x - 3:x + 4].mean() > 0.6


def test_detail_settings_applied(fx, tmp_path):
    env = call_tool(retouch_photo, {"photo": str(fx / "exif.jpg"), "sharpen": 40, "noise_reduction": 30,
                                    "lens_corrections": True}, output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["applied"].get("detail.sharpenAmount") == 40
    assert env.data["applied"].get("detail.nrLuminance") == 30


def test_nothing_to_do(fx, tmp_path):
    env = call_tool(retouch_photo, {"photo": str(fx / "blown.jpg")}, output_root=tmp_path)
    assert env.status == "error" and env.error.code == "nothing_to_do"
    assert "aspect" in env.next_step


def test_bad_crop_box(fx, tmp_path):
    env = call_tool(retouch_photo, {"photo": str(fx / "blown.jpg"), "crop_box": [0.5, 0.5, 0.8, 0.8]},
                    output_root=tmp_path)
    assert env.status == "error" and env.error.code == "invalid_arguments"
