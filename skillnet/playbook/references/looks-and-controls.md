# Looks and controls

`list_looks` is the source of truth; this page maps user words to ids so the first call is usually right.

## Preset looks (`grade_photo` `preset`, `export_photos` `preset`)

| User says | Preset ids |
|---|---|
| warm, golden, sunset glow | `lc.golden-hour`, `lc.warm-glow`, `lc.golden-glow` (portraits), `lc.desert-warmth` |
| cool, crisp morning, blue | `lc.cool-morning`, `lc.blue-hour`, `lc.winter-blue`, `lc.concrete-cool` |
| punchy, vivid, pop | `lc.vivid-pop`, `lc.crisp-landscape`, `lc.crisp-vista`, `lc.deep-sky`, `lc.lush-greens` |
| soft, pastel, airy, bright | `lc.soft-pastel`, `lc.bright-airy`, `lc.fresh-bright`, `lc.spring-fresh`, `lc.summer-haze` |
| film, faded, matte | `lc.faded-matte`, `lc.warm-film`, `lc.muted-film`, `lc.faded-urban` |
| vintage, retro, 70s | `lc.instant-70s`, `lc.cross-process`, `lc.bleach-bypass` |
| cinematic, teal and orange | `lc.teal-orange`, `lc.cinematic`, `lc.neon-night` |
| moody, dark | `lc.moody`, `lc.moody-portrait`, `lc.dark-moody-food`, `lc.gritty-street` |
| portrait, skin | `lc.soft-skin`, `lc.clean-studio`, `lc.golden-glow` |
| foggy, misty | `lc.misty-morning` |
| autumn | `lc.autumn-gold` |
| food | `lc.fresh-bright`, `lc.warm-table`, `lc.dark-moody-food` |
| black and white | `lc.bw-high-contrast`, `lc.bw-soft`, `lc.bw-selenium`, `lc.bw-sepia` (or `black_and_white=true`) |

Colour profiles (`grade_photo` `profile`) set the base rendering before the preset: `lc.color`, `lc.neutral`,
`lc.vivid`, `lc.landscape`, `lc.portrait`, `lc.mono`, plus creative ones (`lc.film.*`, `lc.cine.*`,
`lc.muted.*`, `lc.bw.*`). Leave it unset unless the user asks for a specific rendering.

## Global slider ids (`grade_photo` `adjustments`)

| Panel | Ids (range) |
|---|---|
| Light | `light.exposure` (−5…5 stops), `light.contrast`, `light.highlights`, `light.shadows`, `light.whites`, `light.blacks` (−100…100) |
| White balance | prefer grade_photo's `warmth` (−100…100, measured); `wb.temp` (2000…50000; 6500 = as shot on JPEG, Kelvin on raw), `wb.tint` (−150…150, + = magenta) |
| Colour | `color.vibrance`, `color.saturation` (−100…100) |
| Effects | `effects.texture`, `effects.clarity`, `effects.dehaze` (−100…100), `vignette.amount` (− darkens edges), `grain.amount` — all under `section="effects"` |
| Tone curve | `curve.highlights`, `curve.lights`, `curve.darks`, `curve.shadows` (−100…100) |
| Colour mixer | `mixer.<red/orange/yellow/green/aqua/blue/purple/magenta>.<hue/sat/lum>` (−100…100) |
| B&W mix | `bw.<colour>` (−100…100), used with `black_and_white=true` |
| Colour grading | `grading.<shadows/midtones/highlights/global>.hue` (0…360), `.sat` (0…100), `.lum` (−100…100), `grading.blending`, `grading.balance` |
| Detail | `detail.sharpenAmount` (0…150), `detail.nrLuminance`, `detail.nrColor` (0…100) |

## Local keys (`adjust_area` mask `adjustments`)

`exposure` (−4…4 stops), `contrast`, `highlights`, `shadows`, `whites`, `blacks`, `temp` (+ warm / − cool),
`tint`, `texture`, `clarity`, `dehaze`, `hue`, `saturation`, `sharpness`, `noise` (−100…100), and
`color_hue` (0…360) with `color_sat` (0…100) for a colour wash. `list_looks(what="controls",
section="mask")` lists them.

## Starting recipes (adjust to taste, then check the before/after numbers)

- Blown sky: `light.highlights` −60…−80, `light.whites` −10…−30. In tests a 17.7 % clipped sky fell to 0 %
  with −80 plus a preset.
- Underexposed: `auto_tone=true`, or `light.exposure` +0.7…+1.3 with `light.shadows` +40.
- Flat / hazy: `effects.dehaze` +15…+30, `light.contrast` +15, `color.vibrance` +15.
- Darken a sky only: `adjust_area` `linear` mask from `[0.5, 0]` to `[0.5, 0.45]`, `exposure` −0.5…−1.
- Spotlight a subject: `adjust_area` `radial` mask at the subject with `invert=true`, `exposure` −0.5.
