import json

from skillnet_sdk import call_tool

from conftest import out, sha
from tools.inspect import inspect_photo, list_looks


def test_inspect_reads_exif_and_size(fx, tmp_path):
    before = sha(fx / "exif.jpg")
    env = call_tool(inspect_photo, {"photo": str(fx / "exif.jpg")}, output_root=tmp_path)
    assert env.status == "ok", env
    d = env.data
    assert (d["width"], d["height"]) == (1200, 800)
    assert d["is_raw"] is False
    assert "EOS R6" in d["camera"]
    assert d["iso"] == 200
    assert "250" in str(d["shutter"])
    prev = out(env, "preview.jpg")
    assert prev.stat().st_size > 1000
    assert sha(fx / "exif.jpg") == before  # read-only


def test_inspect_measures_blown_highlights(fx, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(fx / "blown.jpg")}, output_root=tmp_path)
    assert env.status == "ok"
    d = env.data
    # top 17.5 % of the frame is pure white
    assert 12 < d["clipped_highlights_pct"] < 25
    assert any("highlights" in json.dumps(s) for s in d["suggestions"])


def test_inspect_dark_photo(fx, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(fx / "dark.jpg")}, output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["mean_luminance"] < 0.15
    assert any("exposure" in json.dumps(s) or "shadows" in json.dumps(s) for s in env.data["suggestions"])


def test_inspect_camera_raw(raw_dng, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(raw_dng)}, output_root=tmp_path)
    assert env.status in ("ok", "partial"), env
    assert env.data["is_raw"] is True
    assert env.data["width"] > 0 and env.data["height"] > 0


def test_inspect_unreadable_file(fx, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(fx / "fake.jpg")}, output_root=tmp_path)
    assert env.status == "error"
    assert env.error.code == "unreadable_photo"
    assert "JPEG" in env.next_step


def test_inspect_wrong_type_rejected(fx, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(fx / "notes.txt")}, output_root=tmp_path)
    assert env.status == "error"
    assert env.error.code == "invalid_arguments"
    assert env.next_step


def test_list_looks_presets_and_controls(tmp_path):
    env = call_tool(list_looks, {"what": "both"}, output_root=tmp_path)
    assert env.status == "ok"
    ids = {p["id"] for p in env.data["presets"]}
    assert len(ids) >= 30 and "lc.golden-hour" in ids and "lc.bw-high-contrast" in ids
    ctl = {c["id"]: c for c in env.data["controls"]}
    assert ctl["light.exposure"]["min"] == -5 and ctl["light.exposure"]["max"] == 5
    full = json.loads(out(env, "controls.json").read_text())
    assert len(full["controls"]) >= 100


def test_list_looks_search_and_sections(tmp_path):
    env = call_tool(list_looks, {"what": "looks", "search": "film"}, output_root=tmp_path)
    assert env.status == "ok"
    assert env.data["presets"] and all("film" in (p["id"] + p["name"] + p["group"]).lower()
                                       for p in env.data["presets"])
    env = call_tool(list_looks, {"what": "controls", "section": "mask"}, output_root=tmp_path)
    keys = {c["id"] for c in env.data["controls"]}
    assert {"exposure", "highlights", "temp", "saturation"} <= keys
    env = call_tool(list_looks, {"what": "controls", "section": "light"}, output_root=tmp_path)
    assert all(c["id"].startswith(("light.", "profile.")) for c in env.data["controls"])


def test_list_looks_nothing_matches(tmp_path):
    env = call_tool(list_looks, {"what": "looks", "search": "zzzqqq"}, output_root=tmp_path)
    assert env.data["presets"] == []
    assert "broader" in env.next_step


def test_inspect_flags_cold_photo(fx, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(fx / "cold_room.jpg")}, output_root=tmp_path)
    assert env.data["warmth"] < -0.01
    sug = {x["control"]: x["value"] for x in env.data["suggestions"]}
    assert sug.get("warmth", 0) > 0 and sug.get("light.exposure", 0) > 0


def test_inspect_heic_refused_with_clear_next_step(fx, tmp_path):
    env = call_tool(inspect_photo, {"photo": str(fx / "IMG_4821.HEIC")}, output_root=tmp_path)
    assert env.status == "error" and env.error.code == "unsupported_format"
    assert "does not support HEIC" in env.error.message
    assert "not supported" in env.next_step and "JPEG" in env.next_step
    assert not env.outputs
