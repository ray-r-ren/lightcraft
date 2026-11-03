# Pro Photo Darkroom

Give it your photos. Get them professionally graded and retouched, originals untouched.

Every tool writes **new** files (graded copies, before/after images, a reusable `look.json`); the user's
originals are never modified. Edits run in a 32-bit scene-referred raw pipeline, on JPEG/PNG/TIFF/WebP and
camera raws (DNG, CR2, CR3, NEF, ARW, RAF, RW2, ORF, PEF…).

## Where to start

Call `inspect_photo` on each photo first; read `clipped_highlights_pct`, `clipped_shadows_pct`,
`mean_luminance` and `cast` before choosing any edit.

- Files: local photos go in with `upload_file` (pass the returned file_id); an https URL also works.
  Results come back as download links in `outputs`. Download the ones the user needs (the zip from
  `export_photos`, the `before_after.jpg` to show them).
- `inspect_photo` returns `suggestions` (starting slider values) and a 1024 px `preview.jpg`. Use them as a
  starting point and adjust to what the user asked for.
- Reading exposure (the same thresholds the suggestions use): `clipped_highlights_pct` above 1 means blown
  highlights; `mean_luminance` below 0.3 reads as dark and above 0.65 as bright; about 0.4–0.5 with little
  clipping is a normal exposure. `clipped_shadows_pct` above 3 means crushed blacks. Low-key or high-key
  photos can be dark or bright on purpose, so check the preview before calling one "wrong".

## Stages

1. **Inspect** — `inspect_photo(photo)`. Note `is_raw`, `preview_only` (raw only partly decodable),
   `has_edit_sidecar` (earlier Lightroom edits exist), clipping % and cast. If `preview_only` is set, tell the
   user edits use the embedded preview (lower quality) and ask for a DNG or JPEG if quality matters.
2. **Pick a look** — only when the user names a style. `list_looks(what="looks", search="film")` returns
   preset ids. Map their words: "warm/golden" → `lc.golden-hour`, `lc.warm-glow`; "film/faded/vintage" →
   `lc.faded-matte`, `lc.warm-film`, `lc.instant-70s`; "cinematic/teal and orange" → `lc.teal-orange`,
   `lc.cinematic`; "moody/dark" → `lc.moody`, `lc.moody-portrait`; "black and white" →
   `lc.bw-high-contrast`, `lc.bw-soft`. More in [looks and controls](references/looks-and-controls.md).
   For exact slider ids and ranges call `list_looks(what="controls", section="light")`.
3. **Grade** — `grade_photo(photo, preset=…, preset_amount=…, auto_tone=…, adjustments={…})`. Order inside
   one call: look_file → auto tone → profile → preset → B&W → sliders. Then compare `data.before` with
   `data.after`:
   - `clipped_highlights_pct` should not rise (the tool warns in `uncertain` if it rose > 1 point). To recover
     a blown sky use `light.highlights` -50…-80 and `light.whites` -10…-30.
   - Dark photo (`mean_luminance` < 0.25): `light.exposure` +0.5…+1.5 (stops) and `light.shadows` +30…+60;
     "far too dark" → +1.5…+2 with `light.shadows` +40. Aim for `after.mean_luminance` about 0.30–0.45
     (measured: a 0.19 night harbour reaches 0.27 at +1, 0.33 at +1.5/shadows +40, 0.39 at +2). If the
     result says "still dark", grade again with ~0.5 stop more. `auto_tone` alone lifts dark photos only a
     little (0.19 → 0.20–0.22 measured).
   - "Warmer", "cozier", "less cold" → `warmth` +40 (+60 for "noticeably/much warmer"; +80…+100 to fully
     neutralise a strong blue cast, i.e. `before.warmth` below −0.1); "cooler", "less yellow" → `warmth` −40.
     On a tinted photo the shift scales with the tint (+40…+60 removes roughly half of it) and a higher value
     never gives less warmth; when white balance runs out (common on JPEGs) the tool adds an orange or blue
     colour-grading tint and says so in `uncertain`. Don't set `wb.temp` by hand for this: 6800 on a JPEG is barely visible, and brightening a
     cold photo makes its blue tint stronger, so the result can come out *cooler*. `warmth` measures the
     result and strengthens the shift until `after.warmth` really rises. Confirm `after.warmth` is
     clearly above `before.warmth` (about +0.02 or more) before saying it is warmer. `wb.tint` + = magenta,
     − = green.
   - Start presets at `preset_amount` 60–80 for a natural result; 100 is the full look.
4. **Local** — only when part of the image needs it ("darken the sky", "brighten the face"):
   `adjust_area(photo, masks=[…], look_file=<latest look.json>)`. Mask kinds: `linear` (start → end gradient),
   `radial` (center, rx, ry), `luminance` (lum_lo..lum_hi), `color` (pick [x, y]), `sky`, `subject`,
   `background`. Coordinates are 0–1 from the top-left. Local adjustment keys are short (`exposure`,
   `highlights`, `temp`, `clarity`, `saturation`…), not the global `light.*` ids. Check `coverage_pct` and
   look at `mask_overlay.jpg` (tinted where each mask applies: 1st red, 2nd blue, 3rd green) before
   showing the result.
5. **Retouch** — `retouch_photo(photo, look_file=…, aspect="4:5", straighten="auto", spots=[…])`.
   `aspect` is width:height as given (`4:5`, `9:16` portrait; `16:9` landscape; `1:1` square).
   `angle` is degrees, positive = clockwise. `straighten="auto"` levels a tilted horizon;
   `"vertical"` fixes converging verticals. Spots: give x, y (0–1) and radius (fraction of the long edge,
   0.005–0.03 for dust); `auto_dust=true` finds small dark dust spots on smooth areas.
6. **Export** — `export_photos(photos=[…], look_file=<latest look.json>, format="jpeg", long_edge=…)`.
   For a whole shoot: grade one hero photo, then pass its look.json here for every photo so the set is
   consistent. "Lightroom-compatible" / "keep my raws" → `format="original_xmp"` (byte-identical original
   plus an `.xmp` sidecar with the global edits in Camera Raw form). Add `contact_sheet=true` for a PDF
   proof sheet. Report `failed` items.

Always pass the **latest** `look.json` forward (grade → adjust_area → retouch → export) so edits stack;
each call returns an updated one. A call without `look_file` starts again from the untouched photo.

### Example decisions

- *"Fix this overexposed beach photo and make it warm."* inspect shows `clipped_highlights_pct` 18 →
  `grade_photo(preset="lc.golden-hour", preset_amount=70, adjustments={"light.highlights": -70,
  "light.whites": -20})`; confirm `after.clipped_highlights_pct` dropped, show before_after.jpg, then
  `export_photos` with the look.json.
- *"Instagram portrait crop, straighten the horizon, sky a bit darker."* `retouch_photo(aspect="4:5",
  straighten="auto")` → `adjust_area(masks=[{"kind": "linear", "start": [0.5, 0], "end": [0.5, 0.45],
  "adjustments": {"exposure": -0.7}}], look_file=…)` → `export_photos(long_edge=1080, look_file=…)`.
- *"Same look on all 40 wedding photos, web size, plus a proof sheet."* grade one photo, then
  `export_photos(photos=[40 ids], look_file=…, long_edge=2048, contact_sheet=true)` in one call.

## Pitfalls

- **Brightening shifts colour.** Raising exposure on a cold photo also strengthens its cool tint (measured:
  warmth −0.022 → −0.036 after +1.8 stops). When the user wants it brighter *and* warmer, pass `warmth`
  in the same `grade_photo` call as the exposure change and check `data.after.warmth`.
- **Slider units.** `light.exposure` is in stops (−5…5); most sliders are −100…100; `wb.temp` is 2000–50000
  with 6500 = as shot on JPEGs and real Kelvin on raws; colour-grading hue is 0–360 and sat 0–100.
  Out-of-range values are clamped and noted in `uncertain`; unknown ids are ignored and listed in
  `rejected_controls` (status `partial`). Check ids with `list_looks(what="controls")`.
- **Global vs local ids.** `grade_photo` takes `light.highlights`; `adjust_area` masks take `highlights`.
  A global id inside a mask fails with `unknown_control`.
- **Sky / subject / background masks are heuristic** (no AI model): they can miss or spill. Always check
  `coverage_pct` and `mask_overlay.jpg`; if wrong, use a `linear` or `luminance` mask instead. Coverage
  below 0.5 % makes the result `partial`.
- **look.json from another photo**: grade and colour settings carry over; spots, red-eye, crop position and
  upright corrections are dropped (they belong to the original photo), and the aspect ratio is re-applied.
  The tool says so in `uncertain`.
- **Auto straighten / upright need lines.** On photos without a clear horizon or straight edges nothing
  changes and `uncertain` says so; pass an explicit `angle` instead.
- **Stats are measured on a 1024 px rendering.** They're good for before/after comparison, not for pixel
  forensics.
- **Previews vs final files.** `grade_photo`, `adjust_area` and `retouch_photo` return preview-size images
  (`preview_size`, default 2048 px). Full-resolution files come from `export_photos` (`long_edge=0`).
  Export never enlarges: a 1000 px photo asked for at 3000 stays 1000.
- **Raws that only give a preview**: compressed Olympus ORF / Samsung SRW, Nikon HE NEF and some CR3
  variants decode only the embedded JPEG; `inspect_photo` sets `preview_only`.
- **HEIC is not supported.** Tools answer `unsupported_format` for .heic/.heif. Tell the user plainly
  that HEIC photos are not supported and no edited file was made, and ask for a JPEG copy (iPhone: share
  or export as JPEG). Then start again with the JPEG.
- **Removing a strong cast lowers saturation.** Neutralising a very blue photo drops `mean_saturation`
  (measured 0.65 → 0.23 at warmth +45); that is the blue leaving, not a fault. Add `color.vibrance` +15…+25
  if the result looks flat (measured 0.23 → 0.26 at +20).
- **XMP sidecars carry global edits only.** Lightroom reads light, white balance, colour, B&W, HSL mix,
  curve, colour grading, detail, vignette, grain and crop from them and renders with its own engine (close,
  not identical). Masks, spots, red-eye, upright and colour profiles stay in this skill's own field;
  `uncertain` lists what Lightroom won't see. For those, deliver rendered files instead.
- **16-bit** only applies to `png` and `tiff`; `display_p3` / `adobe_rgb` need a colour-managed viewer.

## Evidence

- Show `before_after.jpg` (left = before, right = after) for every edit you describe.
- Quote measured numbers from `data`: brightness `before.mean_luminance → after.mean_luminance`,
  highlight clipping `before.clipped_highlights_pct → after.clipped_highlights_pct`, colour temperature
  `before.warmth → after.warmth` (red minus blue; higher = warmer).
- List what changed from `data.applied` (control id → value) and the preset id/amount.
- For masks: `coverage_pct` and the inside/outside luminance before → after, plus `mask_overlay.jpg`.
- For retouch: `full_width × full_height`, `aspect_ratio`, `rotation_deg`, `spots_healed`.
- For export: `exported`, each photo's width/height/bytes, and every `failed` entry with its reason.
- Repeat anything in `uncertain` to the user plainly.

## Done when

- The output files exist and open; `export_photos` reports `exported` equal to the number of photos (or the
  user has been told which failed and why).
- Dimensions and aspect ratio match the request (check `aspect_ratio` / `width` / `height`).
- Highlight clipping is not worse than before unless the user wanted that look.
- The user has seen `before_after.jpg` for the hero photo, and has the downloaded zip.
- The originals were never modified: tools only ever write new copies, so nothing needs undoing. To roll
  back an edit, call again with an earlier `look.json` (or none).

## Can't do

- Generative fill or AI object removal: spot healing patches from nearby texture only. Suggest a dedicated
  generative editor for removing large objects or people.
- AI Denoise, Super Resolution, and AI 'object'/'describe' masks: use `noise_reduction` and `sharpen` in
  `retouch_photo` instead, or a dedicated upscaler.
- Face detection or recognising people (subject masks are a heuristic, not face detection).
- HDR or panorama merging; video, slideshows with music, books, map views; printing to a printer.
- Exact camera-maker or Lightroom/Capture One colour: looks are approximations.
- Full decoding of compressed ORF/SRW, Nikon HE NEF and some CR3 variants (embedded preview only).
- HEIC photos: ask the user to export them as JPEG first.

## Credits

Built on LightCraft by ray-r-ren / storytold (MIT OR Apache-2.0; see the LICENSE files shipped with this
skill).
