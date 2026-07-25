# CLI Reference

Everything the GUI does, scriptable. General shape:

```
umbra <command> [arguments] [options]
umbra --version
```

All commands print progress to stderr and results to stdout, so piping and
cron jobs behave.

---

## `umbra demo-data <dir> [--frames N]`

Generate a synthetic but realistic Dwarf 3 session (lights with drift, field
rotation, gradient, hot pixels, one cloudy frame, one satellite trail — plus
a matching dark session). Practice everything without a telescope.

## `umbra info <path> [-v]`

Inspect one session folder or scan a whole tree (SD card, `Astronomy`
folder). Prints target, mode, lens, frame count, exposure, gain, integration.
`-v` adds paths, filter, RA/Dec, device-stacked outputs, onboard rejects,
and any parser warnings.

## `umbra import <path> [--db PATH]`

Walk a tree, import every session found into the library (duplicates
detected by content fingerprint). `--db` overrides the default
`~/.umbra-noctis/library.db` (or set `UMBRA_HOME`).

## `umbra library [sessions|targets|outputs] [--target NAME] [--db PATH]`

- `sessions` — every imported session (id, night, target, frames, minutes, rating).
- `targets` — per-target rollup: sessions, frames, total integration. Your
  acquisition dashboard.
- `outputs` — every registered export, newest first.

`--target` filters by any alias ("andromeda" finds M31 sessions).

## `umbra grade <session> [--json FILE]`

Score every sub (stars, FWHM, ellipticity, background, composite score) and
print the verdict table with rejection reasons. `--json` writes the full
report for scripting.

## `umbra stack <session> -o OUT [options]`

Calibrate → register → integrate.

| Option | Default | Meaning |
|---|---|---|
| `-o, --output` | required | `.fits` recommended (keeps it linear for processing) |
| `--darks DIR` | auto | Dark session folder; otherwise auto-matched by exposure+gain |
| `--no-darks` | off | Skip the automatic dark search |
| `--sigma S` | 3.0 | Pixel rejection threshold (lower = more aggressive) |
| `--best F` | 0.9 | Keep best fraction of frames by quality score |
| `--keep-all` | off | Disable quality rejection entirely |
| `--drizzle X` | 1.0 | 1.5 or 2.0 = integrate onto a finer grid |

## `umbra auto <session> -o OUTDIR [--darks DIR]`

The whole pipeline in one command: calibration (darks auto-found), grading,
registration, stacking, gradient removal, color balance, SCNR, denoise,
two-pass GHS stretch, vibrance — exports `jpg` + `tif` + `fits` into OUTDIR.

## `umbra process <input.fits> -o OUT [options]`

Apply operations to an image (usually a stack).

| Option | Meaning |
|---|---|
| `--op name:k=v,k=v` | Apply one operation. Repeatable; applied in order |
| `--recipe FILE` | Run a recipe JSON first |
| `--auto-finish` | Run the standard auto chain |
| `--save-recipe FILE` | Save everything that was applied as a recipe |

Examples:

```bash
umbra process s.fits -o out.jpg --op background_extract --op autostretch
umbra process s.fits -o out.tif --op ghs:amount=6,focus=0.1 --op saturation:amount=1.5
umbra process s.fits -o out.jpg --recipe looks/nebula.json --op star_reduce:amount=0.4
```

## `umbra ops [--markdown]`

List every registered operation grouped by pipeline stage. `--markdown`
prints the full reference (every parameter, type, default, range,
description) — [OPERATIONS.md](OPERATIONS.md) is generated from it.

## `umbra solve <input> [--annotate OUT.jpg]`

Plate-solve via ASTAP → solve-field → nova.astrometry.net (first available;
see [PLATE_SOLVING.md](PLATE_SOLVING.md)). Prints field center, scale,
rotation. `--annotate` writes a JPEG with every bundled catalog object in
the field labeled.

## `umbra planetary <video> -o OUT [--keep F] [--sharpen A]`

Lucky-imaging pipeline for Dwarf video captures: sharpness-rank all frames,
keep the best fraction (`--keep`, default 0.25), align, stack, wavelet-
sharpen (`--sharpen`, default 0.8; 0 disables).

## `umbra trails <frames...> -o OUT [options]`

Star-trail / meteor composites by **lighten (maximum) blending** — the
opposite of `umbra stack`: frames are *not* registered, so the stars' motion
between frames paints the trails. Accepts folders or files in any supported
format: Dwarf FITS, DSLR raw (Canon CR2/CR3, NEF, ARW, DNG — needs the
`dslr` extra: `pip install 'umbra-noctis[dslr]'`), JPEG, TIFF, PNG. Frames
stream through running accumulators, so a 400-frame night uses the memory
of ~3 frames.

| Option | Meaning |
|---|---|
| `--darks DIR` | Cap-on dark frames (same settings) → master dark subtraction |
| `--align` | Register the star field to the first frame before blending — use for **meteor-shower composites** (stars stay put, meteors accumulate); leave off for star trails |
| `--no-cosmetic` | Skip statistical hot-pixel repair (on by default when no darks are given) |
| `--fade F` | Comet-tail look: the trail's past dims by `F` per frame (try 0.005–0.02) |
| `--no-gap-fill` | Don't bridge the small dark dashes the intervalometer re-arm gap leaves in trails (bridging is on by default, directional so trails aren't thickened) |
| `--foreground P` | Also write the mean of all frames to `P` — a noise-free landscape/base image |

```bash
umbra trails ./canon_night -o trails.jpg --darks ./canon_darks
umbra trails ./canon_night -o comet.jpg --fade 0.01 --foreground base.tif
umbra trails ./perseids/*.CR2 -o meteors.tif --align
```

## `umbra meteor-scan <frames...> [options]`

Quick-scan a whole night and flag the frames that contain meteor streaks.
Each frame's luminance is compared against the maximum of its two neighbors
(static stars, hot pixels, and skyglow cancel; slow star drift is covered),
the residual is thresholded robustly, and streaks are found with a Hough
transform. Streaks continuing along the same line in adjacent frames are
reclassified `satellite` — meteors live inside a single exposure. Streams at
reduced resolution: hundreds of raw frames scan in a couple of minutes.

| Option | Meaning |
|---|---|
| `--min-length N` | Shortest streak worth reporting, full-res pixels (default 40) |
| `--sigma K` | Detection threshold above noise (default 6; lower = more sensitive) |
| `--copy-to DIR` | Copy meteor frames into `DIR` (ready for `umbra trails --align`) |
| `--annotate DIR` | Write JPEG previews with each streak outlined for a quick human veto |
| `--json FILE` | Full machine-readable report |

```bash
umbra meteor-scan ./perseids --copy-to keepers/ --annotate previews/
umbra trails ./keepers -o meteors.tif --align
```

## `umbra guide [topic]`

The built-in manual. No argument lists the topics (getting started, deep-sky
workflow, star trails & meteors, processing, generated op reference, recipes,
GUI, FAQ); `umbra guide all` prints everything. The same guide is in the
desktop app under Help → Guide. A printable field-settings card for DSLR
nights lives at [docs/FIELD_CARD.html](FIELD_CARD.html).

## `umbra gui`

Launch the desktop app (requires the `gui` extra: `pip install -e ".[gui]"`).

---

## Batch patterns

Stack every session on a card overnight:

```bash
for s in /data/Astronomy/DWARF_RAW_*; do
  umbra auto "$s" -o "processed/$(basename "$s")" || echo "FAILED: $s"
done
```

Re-apply your signature look to every stack:

```bash
for f in stacks/*.fits; do
  umbra process "$f" -o "final/$(basename "${f%.fits}").jpg" --recipe my-look.json
done
```

Nightly grade report as JSON for your own scripts:

```bash
umbra grade "$SESSION" --json report.json && jq '[.[] | select(.accepted)] | length' report.json
```
