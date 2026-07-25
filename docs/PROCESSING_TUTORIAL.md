# Processing Tutorial — from raw session to finished image

This walkthrough takes one Dwarf 3 session from the SD card to a shareable
image, twice: once the fully automatic way, once the craftsman's way. No
prior astrophotography-processing experience assumed.

Don't have data yet? Make practice data first:

```bash
umbra demo-data ./demo
```

It creates a realistic fake session — drift, field rotation, a light-pollution
gradient, hot pixels, one cloudy frame, one satellite trail — so every tool
below has something real to fix. Substitute your real session folder anywhere
you see `SESSION` below.

```bash
SESSION="./demo/DWARF_RAW_TELE_M 42_EXP_15_GAIN_80_2026-07-20-22-30-15-000"
```

---

## Part 1 — The one-command version

```bash
umbra auto "$SESSION" -o ./out
```

Watch the log. You will see, in order: the session identified; a master dark
built from the matching `DWARF_DARK_*` folder (found automatically); frames
rejected with reasons; registration with the measured field rotation;
the percentage of pixel samples removed by satellite/hot-pixel rejection;
then each processing step; then three exports (`.jpg` to share, `.tif` to
edit elsewhere, `.fits` with full fidelity and the complete processing
history in its header).

That's a finished image. Everything after this point is about doing better
than the defaults.

## Part 2 — The craftsman's version (CLI)

### Step 1: Know your data

```bash
umbra info "$SESSION" -v
umbra grade "$SESSION"
```

Read the grade table. Healthy frames have consistent star counts and FWHM.
Look for: star count collapse (clouds), FWHM jump (focus/seeing), high
ellipticity (wind/tracking), bright background (moonrise, clouds). The
verdict column tells you what auto-rejection will do; if you disagree with
any call, the GUI grade page gives you per-frame veto.

### Step 2: Stack

```bash
umbra stack "$SESSION" -o m42_stack.fits
```

Options worth knowing:

- `--best 0.8` — keep only the best 80% of accepted frames. Use when you
  have plenty of subs (>60) and want maximum sharpness.
- `--sigma 2.5` — more aggressive satellite/trail rejection (default 3.0).
- `--drizzle 2` — 2× finer output grid; only with 50+ well-dithered subs.
- `--darks /path/to/DWARF_DARK_...` — force a specific dark session;
  `--no-darks` skips the automatic search.

The output is a **linear** FITS: it looks almost black in a normal viewer,
and that is correct — the data is all there, waiting to be stretched. Every
Umbra viewer applies a temporary display autostretch so you can see what
you're doing.

### Step 3: Remove the sky gradient (single most important step)

```bash
umbra process m42_stack.fits -o step3.fits --op background_extract:degree=2
```

Light pollution puts a tilted, curved wash of brightness across every
backyard image. `degree=2` fits and removes a smooth 2-D model of it. If
your corners glow (streetlight nearby), try `degree=4`. If the background
is uneven *multiplicatively* (vignetting without flats), add
`--op background_extract:degree=2,mode=divide` as a second pass.

### Step 4: Fix the color while still linear

```bash
umbra process step3.fits -o step4.fits \
  --op background_neutralize \
  --op white_balance:auto=true \
  --op scnr:amount=0.8
```

`background_neutralize` makes the sky gray. `white_balance` auto mode scales
R/G/B so the *average detected star* is white — a solid approximation of
photometric calibration for wide Dwarf fields. `scnr` removes the residual
green cast that OSC sensors always leave (deep-sky objects are never green).

### Step 5: Denoise and (optionally) deconvolve — still linear

```bash
umbra process step4.fits -o step5.fits \
  --op denoise:method=wavelet,strength=1.2,chroma_boost=2.5 \
  --op deconvolve:iterations=12
```

Wavelet denoise thresholds the fine detail scales where noise lives, and
hits color noise harder than luminance (that's `chroma_boost`).
Deconvolution measures your stars' FWHM and undoes that blur — skip it on
noisy short-integration data; embrace it when you have an hour-plus of
signal. Dark rings around stars = too many iterations.

### Step 6: Stretch

```bash
umbra process step5.fits -o step6.fits \
  --op ghs:amount=6,focus=0.08,protect_highlights=0.8 \
  --op ghs:amount=2.5,focus=0.25,protect_highlights=0.9
```

GHS in two gentle passes: the first aims contrast just above the sky
background (that's `focus=0.08` — where the faint nebulosity lives), the
second refines the midtones. `protect_highlights` keeps star cores from
saturating. Alternatives: `--op arcsinh:factor=40` first for maximum star
color, or `--op autostretch` if you just want the safe default.

### Step 7: Finish

```bash
umbra process step6.fits -o m42_final.jpg \
  --op saturation:amount=1.4 \
  --op star_reduce:amount=0.35 \
  --op local_contrast:amount=0.35 \
  --save-recipe m42-look.json
```

Vibrance brings up the color, star reduction makes the nebula the subject,
local contrast pops the structure. `--save-recipe` captures *your entire
chain* (steps 3–7) as a JSON recipe.

### Step 8: Reuse your look forever

```bash
umbra process any_other_stack.fits -o out.jpg --recipe m42-look.json
```

## Part 3 — The same journey in the GUI

`umbra gui`, then:

1. **Library** — Open folder → double-click the session.
2. **Grade** — "Grade all frames", arrow through the frames, `X` anything
   ugly the metrics missed, continue.
3. **Stack** — press Stack, read the log, admire, continue.
4. **Process** — either press "✨ Auto-process" and then refine, or work the
   tool tree top-to-bottom exactly as in Part 2. "Hold for before" shows the
   unprocessed stack while pressed. Every tool's settings panel is generated
   from the same definitions as the CLI, so anything you learn in one
   transfers to the other. Undo freely.
5. **Export** — save JPEG/TIFF, export a before/after, copy the generated
   caption.

Shooting a wide-angle nightscape instead of a deep-sky session? That's a
different workflow (no stacking/registration) — see
[USER_GUIDE.md §10](USER_GUIDE.md#10-star-trails-meteors--nightscapes-dslr).

## Troubleshooting quick hits

| Symptom | Fix |
|---|---|
| Stack looks smeared at corners | You processed alt-az data with rotation — Umbra handles this; if you see it anyway the auto-crop was refused (pathological data); crop manually |
| Sky is orange/brown | `background_extract` then `background_neutralize` |
| Stars have dark rings | Fewer `deconvolve` iterations, or raise `regularization` |
| Image looks flat after stretch | Add `local_contrast`; try `focus` closer to the background level |
| Colored blotches in background | Raise denoise `chroma_boost` |
| Green tint everywhere | `scnr:amount=1.0` |
| Star colors gone white | Restretch with `arcsinh` first, and lower `ghs amount` |
| Satellite line survived stacking | Lower `--sigma` to 2.5, or paint it out with `clone_out` |
