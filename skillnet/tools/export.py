"""export_photos: one look over many photos, full-quality files, zip + optional contact sheet."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool, worker)

from . import _common as C
from .grade import LookFile

PhotoFile = Annotated[InputFile, FileConstraints(extensions=C.ACCEPT_EXTS)]
Format = Literal["jpeg", "png", "tiff", "webp", "avif", "jxl", "original_xmp"]
EXT = {"jpeg": ".jpg", "png": ".png", "tiff": ".tif", "webp": ".webp", "avif": ".avif", "jxl": ".jxl"}
CSPACE = {"srgb": "srgb", "display_p3": "displayP3", "adobe_rgb": "adobeRgb"}
CHUNK = 8          # photos per worker container
FAN_OUT_FROM = 17  # fan out for batches at least this big
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class Options(ToolInput):
    preset: str | None = None
    preset_amount: float = 100
    format: Format = "jpeg"
    long_edge: int = 3000
    quality: int = 90
    color_space: Literal["srgb", "display_p3", "adobe_rgb"] = "srgb"
    bit_depth: Literal[8, 16] = 8


class PhotoResult(ToolOutput):
    name: str
    ok: bool
    width: int = 0
    height: int = 0
    bytes: int = 0
    reason: str | None = None


def _export_one(ctx: ToolContext, src: Path, index: int, opts: Options, look: dict | None, out_dir: Path,
                thumb_dir: Path | None, wd: Path) -> tuple[PhotoResult, list[Path], list[str]]:
    name = src.name
    try:
        photo = C.stage_photo(src, wd, index)
        sha = C.sha256_file(photo)
        cmds, notes = C.look_commands(look, sha)
        if opts.preset:
            cmds.append({"command": "preset.apply", "params": {"id": opts.preset, "amount": opts.preset_amount}})
        dest_dir = out_dir / f"{index:03d}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        if opts.format == "original_xmp":
            target = dest_dir / photo.name
            cmds.append(C.export_cmd(target, 0, opts.quality, format="original"))
            cmds += [{"command": "photo.inspect"}, {"command": "develop.get"}]
        else:
            target = dest_dir / (photo.stem + EXT[opts.format])
            extra: dict[str, Any] = {"colorSpace": CSPACE[opts.color_space]}
            if opts.format in ("png", "tiff") and opts.bit_depth == 16:
                extra["bitDepth"] = 16
            cmds.append(C.export_cmd(target, opts.long_edge, opts.quality, format=opts.format, **extra))
        if thumb_dir is not None:
            thumb_dir.mkdir(parents=True, exist_ok=True)
            cmds.append(C.export_cmd(thumb_dir / f"{index:03d}_{photo.stem}.jpg", 600, 85, format="jpeg"))
        res = C.run_chain(ctx, photo, cmds, wd)
        exp = res.get("app.export") or {}
        files = sorted(p for p in dest_dir.iterdir() if p.is_file())
        if not files:
            raise ToolError("export_failed", "no file written", "retry")
        w, h = int(exp.get("width") or 0), int(exp.get("height") or 0)
        if opts.format == "original_xmp":
            info = res.get("photo.inspect") or {}
            w, h = w or int(info.get("width") or 0), h or int(info.get("height") or 0)
            for x in (f for f in files if f.suffix.lower() == ".xmp"):
                lost = C.add_crs_to_xmp(x, res.get("develop.get") or {},
                                       info.get("kind") == "raw" or photo.suffix.lower() in C.RAW_EXTS)
                if lost:
                    notes = notes + [f"Lightroom won't see these edits from the sidecar (kept only for this skill "
                                     f"and LightCraft): {', '.join(lost)}."]
        return (PhotoResult(name=name, ok=True, width=w, height=h, bytes=sum(f.stat().st_size for f in files)),
                files, notes)
    except ToolError as e:
        return PhotoResult(name=name, ok=False, reason=e.message[:200]), [], []


class ChunkIn(ToolInput):
    photos: list[InputFile]
    start: int = 0
    options: Options
    look_file: InputFile | None = None
    contact_sheet: bool = False


class ChunkOut(ToolOutput):
    results: list[PhotoResult]
    notes: list[str]


@worker(title="Export a group of photos", timeout_s=1700)
def export_chunk(args: ChunkIn, ctx: ToolContext) -> ToolResult[ChunkOut]:
    """Export a slice of an export_photos batch with the same look and options."""
    look = C.read_look(args.look_file)
    wd = C.work_dir()
    out_dir = wd / "out"
    results, notes = [], []
    for i, p in enumerate(args.photos):
        r, files, n = _export_one(ctx, p, args.start + i, args.options, look, out_dir, wd / "thumbs"
                                  if args.contact_sheet else None, wd)
        results.append(r)
        notes += n
        for f in files:
            shutil.copyfile(f, ctx.output_path(f"{args.start + i:03d}__{f.name}"))
    if args.contact_sheet and (wd / "thumbs").exists():
        for t in sorted((wd / "thumbs").iterdir()):
            shutil.copyfile(t, ctx.output_path(f"thumb__{t.name}"))
    return ToolResult(data=ChunkOut(results=results, notes=sorted(set(notes))),
                      summary=f"{sum(r.ok for r in results)} of {len(results)} exported")


# ----------------------------------------------------------------------------------------------
# contact sheet

def _pdf_from_jpegs(pages: list[Path], out: Path, page_pt: tuple[float, float]) -> None:
    """Write a minimal PDF with one full-page JPEG per page (no ImageMagick PDF coder needed)."""
    objs: list[bytes] = []
    pw, ph = page_pt
    kids = []
    n = len(pages)
    # object numbering: 1 catalog, 2 pages, then per page: page, content, image
    for i, jp in enumerate(pages):
        w, h = C.image_size(jp)
        data = jp.read_bytes()
        page_no, cont_no, img_no = 3 + i * 3, 4 + i * 3, 5 + i * 3
        kids.append(f"{page_no} 0 R")
        scale = min(pw / w, ph / h)
        dw, dh = w * scale, h * scale
        ox, oy = (pw - dw) / 2, (ph - dh) / 2
        content = f"q {dw:.2f} 0 0 {dh:.2f} {ox:.2f} {oy:.2f} cm /Im0 Do Q".encode()
        objs.append((page_no, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.2f} {ph:.2f}] /Resources << "
                              f"/XObject << /Im0 {img_no} 0 R >> >> /Contents {cont_no} 0 R >>".encode()))
        objs.append((cont_no, b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"))
        objs.append((img_no, (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
                              f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n").encode()
                     + data + b"\nendstream"))
    allobjs = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
               (2, f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n} >>".encode())] + objs
    allobjs.sort(key=lambda t: t[0])
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for num, body in allobjs:
        offsets.append(len(buf))
        buf += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(allobjs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += f"trailer\n<< /Size {len(allobjs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    out.write_bytes(bytes(buf))


def _contact_sheet(thumbs: list[Path], out: Path, paper: str, columns: int, rows: int, wd: Path) -> int:
    page_px = (1240, 1754) if paper == "a4" else (1275, 1650)
    page_pt = (595.28, 841.89) if paper == "a4" else (612.0, 792.0)
    per_page = columns * rows
    cell_w = page_px[0] // columns - 16
    cell_h = (page_px[1] - 40) // rows - 40
    pages = []
    for p0 in range(0, len(thumbs), per_page):
        chunk = thumbs[p0:p0 + per_page]
        page = wd / f"sheet{p0 // per_page:03d}.jpg"
        args = ["montage"]
        if Path(FONT).exists():
            args += ["-font", FONT, "-pointsize", "14"]
        for t in chunk:
            label = t.stem.removeprefix("thumb__").split("_", 1)[-1][:40]
            args += ["-label", label, str(t)]
        args += ["-tile", f"{columns}x{rows}", "-geometry", f"{cell_w}x{cell_h}+8+8", "-gravity", "south",
                 "-background", "white",
                 "-quality", "88", str(page)]
        subprocess.run(args, check=True, capture_output=True, timeout=300)
        subprocess.run(["convert", str(page), "-background", "white", "-gravity", "center", "-extent",
                        f"{page_px[0]}x{page_px[1]}", "-quality", "88", str(page)], check=True, capture_output=True,
                       timeout=120)
        pages.append(page)
    _pdf_from_jpegs(pages, out, page_pt)
    return len(pages)


# ----------------------------------------------------------------------------------------------

class ExportIn(ToolInput):
    photos: list[PhotoFile] = Field(min_length=1, max_length=200,
                                    description="The photos to export (file ids from upload_file or https URLs), "
                                                "1-200. Originals are never modified.")
    look_file: LookFile | None = Field(default=None, description="look.json from grade_photo / adjust_area / "
                                                                 "retouch_photo, applied to every photo. Spot, "
                                                                 "red-eye, crop position and upright edits only "
                                                                 "carry over to the photo they were made on.")
    preset: str | None = Field(default=None, max_length=80, description="Optional preset look id (list_looks) "
                                                                        "applied after the look file.")
    preset_amount: float = Field(default=100, ge=0, le=200, description="Preset strength, 0-200 %.")
    format: Format = Field(default="jpeg", description="jpeg, png, tiff, webp, avif, jxl (JPEG XL), or "
                                                       "original_xmp = the untouched original plus an XMP edit "
                                                       "sidecar ('Lightroom-compatible', 'keep my raw').")
    long_edge: int = Field(default=3000, ge=0, le=20000, description="Long edge in px; 0 = full size. 'For "
                                                                     "Instagram' ≈ 1080, 'for web' ≈ 2048.")
    quality: int = Field(default=90, ge=1, le=100, description="JPEG/WebP/AVIF/JPEG XL quality 1-100.")
    color_space: Literal["srgb", "display_p3", "adobe_rgb"] = Field(
        default="srgb", description="srgb (web, phones; default), display_p3 (Apple wide gamut), adobe_rgb (print).")
    bit_depth: Literal[8, 16] = Field(default=8, description="16 only for png and tiff (editing masters).")
    contact_sheet: bool = Field(default=False, description="Also make a contact-sheet PDF of thumbnails with "
                                                           "file names.")
    paper: Literal["a4", "letter"] = Field(default="a4", description="Contact sheet paper size.")
    columns: int = Field(default=4, ge=1, le=10, description="Contact sheet thumbnails per row.")
    rows: int = Field(default=5, ge=1, le=12, description="Contact sheet rows per page.")


class ExportOut(ToolOutput):
    exported: int
    failed: list[PhotoResult]
    photos: list[PhotoResult]
    format: str
    contact_sheet_pages: int
    zip_bytes: int


@tool(kind="export", title="Apply a look to many photos and export", long_running=True, timeout_s=1800,
      examples=[{"arguments": {"photos": ["a.jpg", "b.jpg"], "look_file": "look.json", "long_edge": 2048}},
                {"arguments": {"photos": ["a.dng"], "format": "original_xmp"}}])
def export_photos(args: ExportIn, ctx: ToolContext) -> ToolResult[ExportOut]:
    """Use when the user wants the finished files: 'export full size', 'save as JPEG/TIFF for print', 'web-size \
copies', 'same look on all photos from the shoot', 'contact sheet'. Final step: applies one look.json and/or preset to \
every photo (one consistent grade) and exports JPEG, PNG, TIFF (8/16-bit), WebP, AVIF, JPEG XL, or the untouched \
original plus an XMP edit sidecar, with size, quality and colour space options and an optional contact-sheet PDF. \
Returns one zip and per-photo results (size, bytes, failures); large batches are split across several machines."""
    C.check_preset(args.preset)
    look = C.read_look(args.look_file)
    opts = Options(preset=args.preset, preset_amount=args.preset_amount, format=args.format,
                   long_edge=args.long_edge, quality=args.quality, color_space=args.color_space,
                   bit_depth=args.bit_depth)
    wd = C.work_dir()
    out_dir, thumb_dir = wd / "out", wd / "thumbs"
    results: list[PhotoResult] = [PhotoResult(name=p.name, ok=False, reason="not processed") for p in args.photos]
    files_by_index: dict[int, list[Path]] = {}
    thumbs: list[Path] = []
    notes: set[str] = set()
    n = len(args.photos)
    done_parallel = False
    if n >= FAN_OUT_FROM:
        items = [{"photos": [Path(p) for p in args.photos[s:s + CHUNK]], "start": s,
                  "options": opts.model_dump(), "look_file": Path(args.look_file) if args.look_file else None,
                  "contact_sheet": args.contact_sheet} for s in range(0, n, CHUNK)]
        items = [{k: v for k, v in it.items() if v is not None} for it in items]
        try:
            ctx.progress(5, f"exporting {n} photos on {len(items)} machines")
            fan = ctx.fan_out(export_chunk, items)
            done_parallel = True
        except ToolError as e:
            if e.code not in ("not_available_here", "not_available"):
                raise
            fan = []
        for it, r in zip(items, fan):
            start = it["start"]
            if not r.ok:
                for k in range(start, min(n, start + CHUNK)):
                    results[k] = PhotoResult(name=args.photos[k].name, ok=False,
                                             reason=f"worker failed: {(r.error or {}).get('message', 'unknown error')}"[:200])
                continue
            data = r.data if isinstance(r.data, dict) else {}
            for j, pr in enumerate(data.get("results") or []):
                results[start + j] = PhotoResult(**pr)
            notes.update(data.get("notes") or [])
            for f in r.files:
                f = Path(f)
                if f.name.startswith("thumb__"):
                    thumbs.append(f)
                elif "__" in f.name:
                    idx = int(f.name.split("__", 1)[0])
                    files_by_index.setdefault(idx, []).append(f)
    if not done_parallel:
        for i, p in enumerate(args.photos):
            ctx.progress(5 + 80 * i / n, f"exporting {i + 1} of {n}")
            r, files, nn = _export_one(ctx, p, i, opts, look, out_dir, thumb_dir if args.contact_sheet else None,
                                       wd)
            results[i] = r
            files_by_index[i] = files
            notes.update(nn)
        if args.contact_sheet and thumb_dir.exists():
            thumbs = sorted(thumb_dir.iterdir())
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    if not ok:
        raise ToolError("export_failed", f"None of the {n} photos could be exported: "
                        f"{failed[0].reason if failed else ''}"[:300],
                        "Run inspect_photo on one of them to see whether it can be read; pass JPEG/TIFF/raw files.")
    ctx.progress(88, "packing the zip")
    zpath = ctx.output_path("exported.zip")
    used: set[str] = set()
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED) as z:
        for i in sorted(files_by_index):
            for f in files_by_index[i]:
                arc = f.name.split("__", 1)[-1] if "__" in f.name else f.name
                stem, dot, ext = arc.rpartition(".")
                base, k = arc, 1
                while base.lower() in used:
                    k += 1
                    base = f"{stem}-{k}.{ext}" if dot else f"{arc}-{k}"
                used.add(base.lower())
                z.write(f, base)
    outputs = [OutputFile(zpath, f"{len(ok)} exported photo(s)")]
    pages = 0
    if args.contact_sheet and thumbs:
        ctx.progress(93, "making the contact sheet")
        sheet = ctx.output_path("contact_sheet.pdf")
        pages = _contact_sheet(sorted(thumbs, key=lambda t: t.name), sheet, args.paper, args.columns, args.rows, wd)
        outputs.append(OutputFile(sheet, f"Contact sheet, {pages} page(s)"))
    uncertain = sorted(notes)
    if args.bit_depth == 16 and args.format not in ("png", "tiff"):
        uncertain.append(f"16-bit output is only available for png and tiff; {args.format} was written in 8-bit.")
    if args.format == "original_xmp":
        uncertain.append("original_xmp keeps each original byte-for-byte; its .xmp sidecar carries the global edits "
                         "in Adobe Camera Raw form (light, white balance, colour, B&W, curve, grading, detail, "
                         "vignette, grain, crop), which Lightroom renders with its own engine, so the look is "
                         "close but not identical.")
    for r in failed:
        uncertain.append(f"{r.name}: {r.reason}")
    data = ExportOut(exported=len(ok), failed=failed, photos=results if n <= 60 else ok[:60],
                     format=args.format, contact_sheet_pages=pages, zip_bytes=zpath.stat().st_size)
    summary = f"Exported {len(ok)} of {n} photo(s) as {args.format}"
    if args.format != "original_xmp":
        summary += f" (long edge {args.long_edge or 'full'})"
    if failed:
        summary += f"; {len(failed)} failed"
    if pages:
        summary += f"; contact sheet {pages} page(s)"
    return ToolResult(data=data, summary=summary, uncertain=uncertain, status="partial" if failed else "ok",
                      outputs=outputs,
                      next_step="Download exported.zip for the user" + (" and report the failed photos." if failed
                                                                         else "."))
