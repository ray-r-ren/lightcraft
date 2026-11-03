import json
import re
import shutil
import subprocess
import zipfile

import pypdf
from skillnet_sdk import call_tool, local_host

from conftest import make_small, out, sha
from tools import _common as C
from tools.export import export_chunk, export_photos
from tools.grade import grade_photo


def _unzip(env, dest):
    z = out(env, "exported.zip")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(dest)
        return sorted(zf.namelist())


def test_batch_jpeg_with_look_and_contact_sheet(fx, tmp_path):
    g = call_tool(grade_photo, {"photo": str(fx / "exif.jpg"), "preset": "lc.teal-orange"},
                  output_root=tmp_path / "g")
    photos = [str(fx / n) for n in ("blown.jpg", "dark.jpg", "exif.jpg")]
    env = call_tool(export_photos, {"photos": photos, "look_file": str(out(g, "look.json")), "long_edge": 1024,
                                    "contact_sheet": True}, output_root=tmp_path / "e")
    assert env.status == "ok", env
    assert env.data["exported"] == 3 and env.data["failed"] == []
    names = _unzip(env, tmp_path / "x")
    assert names == ["blown.jpg", "dark.jpg", "exif.jpg"]
    for n in names:
        w, h = C.image_size(tmp_path / "x" / n)
        assert max(w, h) <= 1024
    assert max(C.image_size(tmp_path / "x" / "blown.jpg")) == 1024
    assert C.image_size(tmp_path / "x" / "dark.jpg") == (1000, 700)  # never enlarged
    pdf = pypdf.PdfReader(out(env, "contact_sheet.pdf"))
    assert len(pdf.pages) == 1


def test_original_plus_xmp_keeps_bytes_and_lightroom_fields(fx, tmp_path):
    g = call_tool(grade_photo, {"photo": str(fx / "exif.jpg"), "adjustments": {
        "light.exposure": 0.4, "light.highlights": -55, "color.vibrance": 22, "wb.temp": 5600,
        "vignette.amount": -20}}, output_root=tmp_path / "g")
    env = call_tool(export_photos, {"photos": [str(fx / "exif.jpg"), str(fx / "sunset.png")],
                                    "format": "original_xmp", "look_file": str(out(g, "look.json"))},
                    output_root=tmp_path / "e")
    assert env.status == "ok"
    names = _unzip(env, tmp_path / "x")
    assert "exif.jpg" in names and "exif.xmp" in names and "sunset.xmp" in names
    assert sha(tmp_path / "x" / "exif.jpg") == sha(fx / "exif.jpg")
    xmp = (tmp_path / "x" / "exif.xmp").read_text()
    fields = dict(re.findall(r"<crs:(\w+)>([^<]*)</crs:", xmp))
    assert fields["Exposure2012"] == "+0.40" and fields["Highlights2012"] == "-55"
    assert fields["Vibrance"] == "22" and fields["PostCropVignetteAmount"] == "-20"
    assert fields["WhiteBalance"] == "Custom" and int(fields["IncrementalTemperature"]) < 0

    # independent check: the engine's own Camera Raw reader recovers the same edits from crs: alone
    d = tmp_path / "rt"
    d.mkdir()
    shutil.copyfile(fx / "exif.jpg", d / "exif.jpg")
    (d / "exif.xmp").write_text(re.sub(r"\s*<lc:settings>.*?</lc:settings>", "", xmp, flags=re.S))
    (d / "s.jsonl").write_text(json.dumps({"command": "develop.get"}) + "\n")
    res = subprocess.run(["lightcraft-cli", "run", "--import", str(d / "exif.jpg"), "--script", str(d / "s.jsonl")],
                         capture_output=True, text=True, timeout=120)
    got = json.loads(res.stdout.strip().splitlines()[-1])["result"]
    assert abs(got["light"]["exposure"] - 0.4) < 1e-6 and got["light"]["highlights"] == -55
    assert got["color"]["vibrance"] == 22 and got["vignette"]["amount"] == -20
    assert abs(got["wb"]["temp"] - 5600) < 25


def test_formats_png16_and_webp(fx, tmp_path):
    env = call_tool(export_photos, {"photos": [str(fx / "sunset.png")], "format": "tiff", "bit_depth": 16,
                                    "long_edge": 0}, output_root=tmp_path / "t")
    assert env.status == "ok"
    names = _unzip(env, tmp_path / "t")
    assert names == ["sunset.tif"]
    depth = subprocess.run(["identify", "-format", "%z", str(tmp_path / "t" / "sunset.tif")], capture_output=True,
                           text=True).stdout
    assert depth.strip() == "16"
    env = call_tool(export_photos, {"photos": [str(fx / "blown.jpg")], "format": "webp", "long_edge": 600},
                    output_root=tmp_path / "w")
    names = _unzip(env, tmp_path / "w")
    assert names == ["blown.webp"]
    assert C.image_size(tmp_path / "w" / "blown.webp") == (600, 400)


def test_partial_when_one_photo_is_broken(fx, tmp_path):
    env = call_tool(export_photos, {"photos": [str(fx / "blown.jpg"), str(fx / "fake.jpg")], "long_edge": 500},
                    output_root=tmp_path)
    assert env.status == "partial"
    assert env.data["exported"] == 1
    assert env.data["failed"][0]["name"] == "fake.jpg" and env.data["failed"][0]["reason"]


def test_all_broken_and_bad_input(fx, tmp_path):
    env = call_tool(export_photos, {"photos": [str(fx / "fake.jpg")]}, output_root=tmp_path / "a")
    assert env.status == "error" and env.error.code == "export_failed" and env.next_step
    env = call_tool(export_photos, {"photos": []}, output_root=tmp_path / "b")
    assert env.status == "error" and env.error.code == "invalid_arguments"
    env = call_tool(export_photos, {"photos": [str(fx / "blown.jpg")], "preset": "lc.nope"},
                    output_root=tmp_path / "c")
    assert env.status == "error" and env.error.code == "unknown_preset"


def test_large_batch_fans_out(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    photos = [str(make_small(src / f"p{i:02d}.jpg", f"rgb({100 + i * 7},{150 - i * 3},{90 + i * 5})"))
              for i in range(18)]
    env = call_tool(export_photos, {"photos": photos, "long_edge": 200, "contact_sheet": True},
                    output_root=tmp_path / "out", host=local_host(export_chunk))
    assert env.status == "ok", env
    assert env.data["exported"] == 18
    names = _unzip(env, tmp_path / "x")
    assert names == [f"p{i:02d}.jpg" for i in range(18)]
    assert len(pypdf.PdfReader(out(env, "contact_sheet.pdf")).pages) == 1


def test_heic_in_batch_fails_only_that_photo(fx, tmp_path):
    env = call_tool(export_photos, {"photos": [str(fx / "blown.jpg"), str(fx / "IMG_4821.HEIC")], "long_edge": 400},
                    output_root=tmp_path / "a")
    assert env.status == "partial" and env.data["exported"] == 1
    assert "HEIC" in env.data["failed"][0]["reason"]
    env = call_tool(export_photos, {"photos": [str(fx / "IMG_4821.HEIC")]}, output_root=tmp_path / "b")
    assert env.status == "error"
    print(env.error.code, env.error.message, env.next_step)
    assert "HEIC" in env.error.message + env.next_step
