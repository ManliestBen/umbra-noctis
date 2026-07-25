# Umbra Noctis — User Guide

Every feature, explained. If you're brand new, read the
[Processing Tutorial](PROCESSING_TUTORIAL.md) first — it walks one session
from raw folder to finished JPEG. This guide is the reference you come back to.

**Contents**

1. [Getting your data off the Dwarf 3](#1-getting-your-data-off-the-dwarf-3)
2. [The library](#2-the-library)
3. [Frame grading](#3-frame-grading)
4. [Calibration](#4-calibration)
5. [Registration & stacking](#5-registration--stacking)
6. [Processing operations](#6-processing-operations)
7. [Dual-band narrowband imaging](#7-dual-band-narrowband-imaging)
8. [Recipes & the Auto pipeline](#8-recipes--the-auto-pipeline)
9. [Planetary & lunar stacking](#9-planetary--lunar-stacking)
10. [Plate solving & annotation](#10-plate-solving--annotation)
11. [Exporting & sharing](#11-exporting--sharing)
12. [Reproducibility: history & sidecars](#12-reproducibility-history--sidecars)
13. [Data safety](#13-data-safety)

---

## 1. Getting your data off the Dwarf 3

The telescope saves each astro session as a folder named like:

```
DWARF_RAW_TELE_M 42_EXP_15_GAIN_80_2026-07-20-22-30-15-123/
├── 0000.fits … 0159.fits     ← the individual sub-exposures (what we want!)
├── stacked.fits / .jpg       ← the device's own stack (we'll beat it)
└── shotsInfo.json            ← target, exposure, gain, RA/Dec, counts
```

Dark-frame sessions look the same but start with `DWARF_DARK_`. Copy the whole
`Astronomy` folder to your computer via USB, the microSD card, or the device's
network share — details and tips in [DWARF3_DATA.md](DWARF3_DATA.md).

**Umbra Noctis never modifies these folders.** Everything it does works from
read-only copies, and outputs always go to new files.

## 2. The library

Every session you open is cataloged in a SQLite database at
`~/.umbra-noctis/library.db` (change the location with the `UMBRA_HOME`
environment variable).

What the library gives you:

- **Target grouping across nights.** "M 31", "m031", and "Andromeda" all
  resolve to one target (M31 — Andromeda Galaxy), so three nights of data
  show up as one object with a combined integration total.
- **Integration bookkeeping:** `umbra library targets` prints total sessions,
  frames, and minutes per target — your personal acquisition dashboard.
- **Duplicate detection:** re-importing the same data from a different path
  is recognized by content fingerprint and not double-counted.
- **Ratings & notes:** session rows store a 0–5 rating and free-form notes
  (`Library.set_rating` / `set_notes`, surfaced in the GUI library page).
- **Output tracking:** every export can be registered against its target, so
  "show me every version of M42 I've made" is one query (`umbra library outputs`).

CLI: `umbra import <folder>`, `umbra library [sessions|targets|outputs]`.
GUI: page **1 · Library** (importing happens automatically when you open a folder).

## 3. Frame grading

Not every sub deserves to be stacked. Grading measures each frame:

| Metric | What it detects | How |
|---|---|---|
| Star count | Clouds, fog, dew | sep/scipy source extraction |
| FWHM (px) | Focus drift, bad seeing | Median star profile width |
| Ellipticity | Trailing (wind, tracking error) | Star second moments |
| Background | Moonlight, clouds, twilight | Median sky level |
| Noise | General frame quality | Robust MAD estimate |

**Auto-rejection is session-relative:** a frame is rejected when it deviates
from *this session's* median by more than 3.5 robust standard deviations —
so the thresholds adapt to your sky instead of needing tuning. Reasons are
always given ("clouds (few stars)", "star trailing", …).

**The composite score (0–100)** ranks frames within a session:
35% star count, 30% FWHM, 20% ellipticity, 15% background. Use it with
best-N selection ("stack only the best 80%": `umbra stack --best 0.8`).

**Manual veto:** in the GUI grade page, arrow keys blink through frames,
`X` rejects, `A` accepts. Rejection never deletes anything — rejected frames
are simply excluded from stacking.

CLI: `umbra grade <session> [--json report.json]`.

## 4. Calibration

Umbra Noctis works with whatever calibration data you have:

**With darks (recommended).** Shoot a dark session on the Dwarf 3 (same
exposure and gain as your lights, cap on). When a `DWARF_DARK_*` folder with
matching exposure/gain sits near your lights, it is found and used
automatically. What happens:

1. Darks are combined into a **master dark** (sigma-clipped mean — outliers
   like cosmic-ray hits in individual darks are rejected).
2. If exposure differs from the lights, the dark is **scaled** by the
   exposure ratio.
3. A **hot-pixel map** is derived from the master dark (pixels brighter than
   median + 8·MAD) and those pixels are repaired by local median in every
   light (CFA-aware: on raw mosaics, same-color neighbors are used).

**Without darks.** Hot pixels are found statistically instead: a pixel that
is bright in the *minimum* of several lights is a defect, not a star (stars
move between frames; defects don't). You still get clean stacks.

**Flats.** If you shoot flats, `build_master` + `apply_flat` handle them
(division by the median-normalized master). If you don't — most Dwarf users
don't — the **synthetic flat** tool models the vignetting from your stacked
image itself: box-median samples are fit with a 2-D polynomial and divided
out. Use `background_extract` with `mode=divide` for the same effect inside
a recipe.

## 5. Registration & stacking

The heart of the app. `umbra stack <session> -o out.fits` or GUI page **3**.

**Registration.** Every frame is aligned to a reference frame (chosen
automatically as the highest-quality frame) using astroalign's
triangle-pattern star matching. This solves translation + **rotation** +
scale, which matters because in alt-az mode the Dwarf 3's field *rotates*
between subs — translation-only alignment would smear the corners. If star
matching fails (very few stars), FFT phase correlation recovers translation
as a fallback. On raw CFA data, matching runs on 2×2 superpixels so the
Bayer pattern can't corrupt star shapes.

**Normalization.** Each frame's background level and spread are matched to
the reference before combination, so sky brightness changes during the night
don't defeat pixel rejection.

**Pixel rejection (winsorized sigma-clip).** For every output pixel, the
stack of input samples is compared to its median; samples more than
`--sigma` (default 3.0) robust deviations away — satellite trails, plane
lights, cosmic rays, remaining hot pixels — are clamped to the clip boundary
and down-weighted 4×. Robust MAD sigma is used specifically so a bright
satellite can't inflate the deviation estimate enough to hide itself.

**Quality weighting.** Frames are weighted by their grade score, so a
mediocre frame contributes without dragging the result down.

**Drizzle (×1.5 / ×2).** Integration onto a finer grid. Only worth it with
many well-dithered subs (50+); otherwise it just spreads noise.

**Auto-crop.** After integration, the image is cropped to the region covered
by *every* frame, removing the rotated/dithered borders automatically.

**Memory.** Registered frames stream through a disk-backed cube and are
reduced in horizontal strips, so 8 MP × 100+ frame stacks don't need
gigabytes of RAM.

The stacking log always reports: frames used/rejected (with reasons), how
many were star-solved vs phase-only, the maximum field rotation, and what
percentage of pixel samples the rejection removed.

## 6. Processing operations

Every operation lives in one registry; the GUI tool panels, the CLI, recipes,
and [OPERATIONS.md](OPERATIONS.md) (full parameter tables) are all generated
from it. CLI syntax: `--op name:param=value,param=value`, repeatable and
applied in order.

**Recommended order** (the GUI tool tree is arranged this way):

1. **Linear stage** — `background_extract` (gradient removal — do this
   first, always), `background_neutralize`, `white_balance` (auto mode makes
   the average star white), `scnr` (kill green cast), `denoise`
   (starlet-wavelet with separate chroma strength), `deconvolve`
   (Richardson–Lucy, PSF measured from your stars), `banding_reduce`.
2. **Stretch** — one of `ghs` (most control: aim contrast at the faint
   stuff with `focus`, protect star cores with `protect_highlights`),
   `arcsinh` (best star colors), `histogram_stretch` (classic), or
   `autostretch` (one-click starting point). Small multiple stretches beat
   one big one.
3. **After stretch** — `curves` (including a saturation channel), `saturation`
   (vibrance mode), `star_reduce`, `sharpen` (wavelet-scale, star-protected),
   `local_contrast`, `hdr_compress` (rescue M42-core-style blowouts),
   `hue_shift`.
4. **Geometry / cosmetic anytime** — `crop`, `rotate`, `flip`, `resize`,
   `invert`, `clone_out` (heal residual trails and blemishes with inpainting).

Every operation's full documentation — what it does, when to use it, every
parameter with ranges — is in [OPERATIONS.md](OPERATIONS.md) or
`umbra ops --markdown`.

## 7. Dual-band narrowband imaging

The Dwarf 3's built-in **dual-band filter** passes only Hα (656 nm) and OIII
(501 nm). Through it, the sensor's red pixels record nearly pure Hα and the
green/blue pixels nearly pure OIII — which means a color camera gives you
two narrowband channels for free.

`dualband_extract` turns a dual-band stack into:

- **HOO palette** — Hα→red, OIII→teal. The natural bicolor look
  (red nebulae with blue-green OIII shells; great on the Veil, Rosette,
  Crescent).
- **OHH** — inverted assignment for variety.
- **HA / OIII** — the raw extracted channel as a mono image (useful for
  making a luminance layer or blending by hand).

Workflow: stack the dual-band session normally → `dualband_extract` (on
linear data) → `background_extract` if needed → stretch → `hue_shift` /
`curves` to taste. Emission nebulae only — galaxies and clusters are
broadband targets; use the VIS/Astro filter for those.

## 8. Recipes & the Auto pipeline

A **recipe** is a JSON list of operations with parameters:

```json
{
  "name": "my-nebula-look",
  "steps": [
    {"op": "background_extract", "params": {"degree": 2}},
    {"op": "ghs", "params": {"amount": 6.0, "focus": 0.08}},
    {"op": "saturation", "params": {"amount": 1.4}}
  ]
}
```

- **Create one from work you already did:** GUI → Process page → "Save steps
  as recipe", or CLI `--save-recipe my.json` — the recipe is extracted from
  the image's recorded history.
- **Replay:** `umbra process stack.fits -o out.jpg --recipe my.json`, or
  batch over many stacks in a shell loop.
- **Share:** recipes are plain JSON; trade them with other Dwarf owners.

**The Auto pipeline** (`umbra auto <session> -o out/`, or the ✨ button in
the GUI) is the built-in opinionated recipe: master-dark calibration (auto-
found), grade & reject, register, stack, gradient removal, background
neutralization, star-based white balance, SCNR, mild wavelet denoise,
two-pass GHS stretch, vibrance — then exports JPG + 16-bit TIFF + FITS.
Every step it took is in the output's history, so an auto result is a
starting point you can audit and refine, never a black box.

## 9. Planetary & lunar stacking

Dwarf 3 video captures (Moon, Jupiter, Saturn) use a different physics:
seeing changes frame to frame, so you keep only the lucky sharp frames.

`umbra planetary video.mp4 -o moon.jpg --keep 0.25 --sharpen 0.8`

1. Every frame is scored with the variance-of-Laplacian sharpness metric.
2. The best `--keep` fraction is kept (25% default; 10% in bad seeing,
   50% in excellent seeing).
3. Frames are aligned by phase correlation on the subject (auto-cropped).
4. Aligned frames are averaged, then wavelet-sharpened (`sharpen`,
   scale=fine — the RegiStax trick).

## 10. Plate solving & annotation

`umbra solve image.fits --annotate labeled.jpg`

Solving tries, in order: **ASTAP** (install it — fastest), local
**astrometry.net** (`solve-field`), then the free **nova.astrometry.net web
API** (set `UMBRA_ASTROMETRY_KEY`; get a key free at nova.astrometry.net).
Setup instructions: [PLATE_SOLVING.md](PLATE_SOLVING.md). Search is
pre-seeded with the Dwarf 3 telephoto's pixel scale (~2.75″/px) for speed.

A successful solve reports field center RA/Dec, scale, and rotation, and
`--annotate` renders labels for every bundled catalog object in the field
(Messier + famous NGC/IC, with friendly names).

## 11. Exporting & sharing

- **Formats:** 16-bit TIFF (further editing), 16-bit PNG (mono) / 8-bit PNG
  (color), JPEG with quality control (sharing), 32-bit FITS (archival, full
  history in the header). Linear data exported to a display format is
  autostretched automatically so you never get an accidentally-black JPEG.
- **Before/after comparison** (`save_comparison`, or the Export page
  button): labeled side-by-side JPEG — forum gold.
- **Acquisition caption** (Export page, editable): target, telescope, frame
  count, exposure, gain, nights, total integration — generated from the
  session metadata, ready to paste into Reddit/AstroBin/Instagram.
- **Acquisition card** (`acquisition_card`): the image with the caption
  rendered underneath as one shareable JPEG.
- **Resize on export:** `export_image(..., resize_long_edge=2048)` for
  web-friendly files (downsizing is also free noise reduction).

## 12. Reproducibility: history & sidecars

Every `AstroImage` carries a `history` list — every operation and its exact
parameters, timestamped. It survives into FITS headers (HISTORY cards), can
be dumped as JSON (`history_json()`), and can be converted straight back into
a runnable recipe (`Recipe.from_history`). Two years from now you'll be able
to answer "how did I process this?" — and re-run it on better data.

## 13. Data safety

- Raw session folders are **read-only** to the entire pipeline.
- Grading/rejection only mark frames; nothing is ever deleted.
- All outputs go to new files; `save_fits` refuses nothing but overwrites
  only the explicit path you gave it.
- The library stores references and metadata, never your pixels — deleting
  `~/.umbra-noctis` costs you catalog info only.
