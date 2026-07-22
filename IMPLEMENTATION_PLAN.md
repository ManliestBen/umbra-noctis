# Dwarf 3 Post-Processing Application — Implementation Plan

Companion to `FEATURES.md`. This plan turns the feature catalog into an ordered build,
with a recommended stack, architecture, and phase-by-phase milestones.

---

## 1. Recommended Technology Stack

**Core language: Python 3.12+.** The entire scientific-astronomy ecosystem is here, and
it turns months of algorithm work into library calls:

| Concern | Library |
|---|---|
| FITS I/O, WCS, units | `astropy` |
| Array math | `numpy` (+ `numba` for hot loops) |
| Star detection / background | `sep` (SExtractor port), `photutils` |
| Registration | `astroalign` (triangle-pattern star matching; handles rotation) |
| Calibration pipeline | `ccdproc` |
| Demosaic, general CV, video I/O | `opencv-python`, `scikit-image` |
| Plate solving | `tetra3` or local astrometry.net (`solve-field`), `astroquery` for online fallback |
| ML inference (denoise/star removal) | `onnxruntime` (CPU + GPU execution providers) |
| Catalog data | bundled SQLite of Messier/NGC/IC + Gaia queries via `astroquery` |
| Database | SQLite via `sqlalchemy` |
| Device transfer | `ftplib`/`aioftp` for Wi-Fi pull from the Dwarf 3 |

**UI: PySide6 (Qt) desktop app.** Native pan/zoom performance on 8 MP frames, real
menus/shortcuts/drag-drop, easy packaging for Windows/macOS/Linux (PyInstaller/Briefcase).
Use a QOpenGLWidget-based image canvas for GPU-drawn zoom/pan with a live autostretch
shader (stretch happens on the GPU; the linear data never gets copied per adjustment).

*Alternative considered:* local web app (FastAPI + React). Better if you ever want
remote/tablet use, worse for big-image interactivity and packaging. The architecture
below keeps the core UI-agnostic so this can be revisited — the processing engine must
never import Qt.

**Rule of leverage:** integrate existing open tools (Siril CLI, GraXpert CLI,
astrometry.net) as optional backends early; replace with native implementations only
where we can do better or reduce friction.

---

## 2. Architecture

```
┌────────────────────────────────────────────────────────┐
│  UI layer (PySide6)                                    │
│  Library browser · Grading view · Canvas · Recipe UI   │
└───────────────▲────────────────────────────────────────┘
                │ Qt signals / thin view-models
┌───────────────┴────────────────────────────────────────┐
│  Application layer                                     │
│  Job engine (worker pool, progress, cancel)            │
│  Recipe runner · Undo/history · Settings               │
└───────────────▲────────────────────────────────────────┘
                │ plain-Python API (also exposed as CLI)
┌───────────────┴────────────────────────────────────────┐
│  Core engine  (no Qt imports — importable, testable)   │
│  ingest/    Dwarf session parsing, shotsInfo.json,     │
│             FITS normalization, device FTP client      │
│  library/   SQLite catalog, targets, tags, stats       │
│  calib/     master frames, bad-pixel maps              │
│  grade/     FWHM, eccentricity, star count, SNR        │
│  stack/     register, normalize, reject, combine,      │
│             drizzle, mosaics                           │
│  process/   gradient removal, color cal, stretch,      │
│             curves, denoise, decon, star removal,      │
│             dual-band extraction, masks                │
│  solve/     plate solving, annotation, photometry      │
│  export/    formats, crops, summary cards, timelapse   │
│  integrate/ siril, graxpert, astrometry.net adapters   │
└────────────────────────────────────────────────────────┘
```

Key design decisions:

1. **Engine/UI split with a CLI from day one.** Every operation is a pure function
   `f(ImageData, params) -> ImageData` or a pipeline step. The GUI and the `d3proc`
   CLI are both thin clients. This makes batch mode (§11 of FEATURES) free and makes
   the whole engine unit-testable without a display.
2. **`ImageData` core type:** numpy array (float32 internally, CFA or RGB) + FITS
   header + WCS + processing history. All ops append to history → reproducibility
   sidecars come for free.
3. **Non-destructive recipe model:** an edit session is an ordered list of
   `(operation, params, mask?)`. Rendering = fold over the list with caching of
   intermediate results at checkpoints. Undo/redo = pointer into the list.
4. **Job engine:** `ProcessPoolExecutor` workers for CPU-heavy steps (stacking
   parallelizes per-frame); progress via a queue; every long op cancellable.
5. **Plugin-style operation registry:** each processing op self-describes (name,
   params schema, linear/non-linear stage) so the recipe UI, CLI, and docs are
   generated from one registration point. Third-party ops become possible later.

---

## 3. Phases & Milestones

Estimates assume a solo developer, part-time; treat them as relative sizes.

### Phase 0 — Foundations & Ground Truth (1–2 weeks)
- Repo scaffold: `pyproject.toml` (uv or poetry), ruff, pytest, GitHub Actions,
  package layout matching the architecture above.
- **Collect ground-truth data with your telescope:** shoot 3–4 real sessions —
  a bright target (M42/M31), a faint one, one in alt-az, one in EQ mode, one with the
  dual-band filter, plus darks. Copy the raw folder trees verbatim into a `testdata/`
  archive (kept outside git; small excerpts committed as fixtures). *Every later phase
  is validated against this data.*
- Implement `ingest/`: session discovery, folder-name parsing, `shotsInfo.json` +
  FITS header normalization. Unit tests against the fixture tree.
- Minimal viewer: open a FITS, autostretch, pan/zoom (proves the Qt canvas approach).
- **Milestone M0:** `d3proc info <session_dir>` prints a correct session report;
  viewer displays any Dwarf 3 FITS with autostretch.

### Phase 1 — Library & Grading (2–3 weeks)
- SQLite catalog + import pipeline (hashing, dedup); thumbnail generation.
- Library UI: session grid, target grouping, search/filter; target-name resolver
  with bundled Messier/NGC catalog.
- Grading engine: star detection (`sep`), FWHM, eccentricity, background, star count;
  quality plots; threshold auto-reject; blink view with keyboard accept/reject.
- **Milestone M1:** import a real session, see it in the library, blink through subs,
  auto-flag the bad ones, and the flags persist.

### Phase 2 — Calibration & Stacking: the MVP spine (3–5 weeks)
- Master dark creation + subtraction; hot-pixel map + cosmetic correction;
  no-calibration fallback path. (Flats/bias support included but secondary.)
- Registration with `astroalign` (must pass on alt-az field-rotation data);
  reference-frame auto-selection; background normalization.
- Stacking: average/median + sigma-clip family; weighted combine; CFA-aware order
  of operations (calibrate on CFA → demosaic → register → integrate), Bayer drizzle
  deferred to Phase 6.
- Auto-crop of rotation borders.
- Wire it into a **one-command pipeline**: `d3proc stack <session>` → stacked FITS.
- **Milestone M2 (the payoff moment):** your re-stack of a real session is visibly
  cleaner than the Dwarf 3's onboard stack of the same data (compare side by side —
  this is the app's reason to exist; if we can't beat onboard stacking, stop and
  integrate Siril as the stacking backend instead).

### Phase 3 — Linear Processing (3–4 weeks)
- Gradient removal: polynomial + RBF background models, auto sample grid with
  manual add/remove; GraXpert CLI adapter as an alternative backend.
- Background neutralization, manual white balance; SCNR green removal.
- Photometric color calibration (plate solve → Gaia star colors → matrix solve) —
  depends on the `solve/` module: integrate tetra3/astrometry.net here.
- Classical denoise (wavelet + bilateral, luma/chroma split).
- Histogram stretch + curves with live GPU preview; STF everywhere.
- **Milestone M3:** session → stack → gradient-free, color-calibrated, stretched
  image entirely in-app, exported as 16-bit TIFF that survives comparison with a
  Siril+GIMP workflow on the same data.

### Phase 4 — Non-Linear Suite & the "Auto" Button (3–4 weeks)
- GHS and arcsinh stretches; saturation/vibrance; masks subsystem (luminance, star,
  range, painted); multiscale local contrast + sharpening.
- ML integration layer (onnxruntime): star removal model, ML denoise; stars/starless
  recombination workflow with star reduction.
- **Dual-band extraction:** synthetic Hα/OIII from dual-band-filter sessions,
  HOO/palette presets.
- Recipes: record/save/apply chains; ship the opinionated **"Auto process"** recipe
  (grade → stack → GraXpert-style gradient removal → PCC → GHS stretch → light
  denoise → auto-crop → export) tuned on the ground-truth targets.
- Non-destructive history/undo across the processing view.
- **Milestone M4:** one click from raw session folder to a shareable JPEG that a
  Dwarf 3 Facebook-group member would post proudly.

### Phase 5 — Solve, Annotate, Export & Share (2–3 weeks)
- Annotation overlays from plate solution + catalogs; annotated export.
- Export polish: formats, resize, acquisition summary card generator,
  before/after slider MP4/GIF, AstroBin CSV.
- Acquisition stats dashboard (integration per target, imaging-night calendar).
- **Milestone M5:** every image leaves the app with correct metadata, an annotation
  option, and a share-ready caption.

### Phase 6 — Power Features (ongoing, prioritized by your actual usage)
Pick order based on what you find yourself wanting after a month of real use:
- Multi-session integration UI; drizzle (incl. Bayer drizzle); local normalization.
- Mosaic assembly for Dwarf mosaic mode.
- Direct-from-device Wi-Fi import; watch-folder daemon; auto-process-on-arrival.
- Planetary/lunar lucky-imaging pipeline + wavelet sharpening.
- Comet stacking; photometry; blink-based mover detection.
- Batch queue UI; recipe sharing; timelapse builder (with deflicker); web gallery export.
- Wide-angle/nightscape tools: star trails, sky/foreground stacking, meteor detection.
- Acquisition feedback: sub-exposure advisor, integration planner, dither analysis.
- Retouching (clone/heal/inpaint), saturated-star repair, HDR exposure combining.

---

## 4. Testing & Validation Strategy

- **Fixture-driven unit tests:** small cropped FITS excerpts committed to the repo;
  full sessions in an out-of-repo archive pulled by a script for integration tests.
- **Golden-image regression tests:** each pipeline stage compared against stored
  reference outputs with tolerance (protects against silent algorithm regressions).
- **Metric-based quality gates:** stacking tests assert measured SNR improvement
  ≈ √N and FWHM preservation vs. the reference frame; registration tests assert
  sub-pixel residuals on synthetic star fields with known transforms.
- **Synthetic data generator:** star fields with known positions, FWHM, noise, and
  injected satellites/hot pixels — for testing detection, rejection, and alignment
  with exact ground truth.
- **The real benchmark:** an end-to-end run on each ground-truth session in CI-lite
  (nightly, local), diffed visually release-to-release.

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Native stacking can't beat Dwarf's onboard stack or Siril | Decision gate at M2: swap in Siril CLI as the stacking backend, keep our UX on top |
| Dwarf firmware changes folder/JSON formats | Version-tolerant parsers, fixtures per firmware version, graceful "unknown field" handling |
| ML model licensing (StarNet++ weights are restrictively licensed) | Prefer openly licensed models (GraXpert denoise, open star-removal efforts); make ML backends pluggable and optional |
| Alt-az field rotation breaks naive registration | astroalign handles similarity transforms natively; test fixtures explicitly include alt-az sessions |
| 8 MP × hundreds of subs → memory pressure | Stream frames through stacking (running rejection algorithms), memory-mapped FITS, tile-based processing for drizzle |
| Qt canvas performance on big images | GPU texture pyramid (mipmapped tiles), stretch as shader; prototype in Phase 0 before committing |
| Scope creep (this catalog is huge) | Phase gates; nothing from Phase 6 starts before M4 ships; FEATURES.md priorities are the arbiter |

## 6. Immediate Next Steps

1. Confirm stack choice (Python + PySide6) — or flag if you'd rather go web-based.
2. Scaffold the repo (Phase 0 layout, tooling, CI).
3. Shoot/collect the ground-truth sessions off your Dwarf 3 and archive them.
4. Build `ingest/` against your real session folders.
