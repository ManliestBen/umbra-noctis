# Umbra Noctis — Feature Catalog

> **Status (v0.1):** the P0 spine and most P1 features are implemented and
> tested — ingest, library, grading, calibration, registration, stacking,
> 25 processing ops, dual-band extraction, recipes/auto pipeline, plate-solve
> adapters, planetary stacking, exports, CLI, and GUI. Everything else below
> remains the roadmap; see IMPLEMENTATION_PLAN.md Phase 6.

This document is the exhaustive feature list for an application that post-processes
single images and image sets captured with the DwarfLab Dwarf 3 smart telescope.

Priority legend:
- **P0** — core; the app is not useful without it (MVP)
- **P1** — high value; expected in a serious astro tool
- **P2** — differentiating / power-user features
- **P3** — nice-to-have, long-tail ideas

---

## 1. Dwarf 3 Context (what the app must understand)

The Dwarf 3 produces data with specific characteristics that drive many features below:

- **Telephoto channel:** Sony IMX678 STARVIS 2 sensor, 3840×2160 (~8.3 MP), 2 µm pixels,
  150 mm focal length, f/4.3. Wide-angle secondary camera (lower resolution, different FOV).
- **File outputs per astro session:** individual sub-exposures as 16-bit **FITS** files,
  the device's own live-stacked result (FITS + stretched PNG/JPG), and a
  **`shotsInfo.json`** metadata file (exposure, gain, filter, binning, target, RA/Dec, etc.).
  Session folders are named with target/exposure/gain/timestamp conventions.
- **Filters:** built-in VIS, Astro (UV/IR-cut), and **dual-band (Hα + OIII)** filters.
  Dual-band data enables narrowband-style channel extraction from a color sensor.
- **Mount modes:** EQ mode (polar-aligned; long subs, no field rotation) and
  **alt-az mode (field rotation between subs is guaranteed)** — registration must
  handle rotation, and stacked corners will have rotation artifacts to crop.
- **Onboard calibration:** the device can shoot/apply darks itself; users may or may
  not have raw darks available. The app must work both with and without calibration frames.
- **Other capture modes:** burst, timelapse, video (planetary/lunar), and **mosaic** mode.
- **Transfer paths:** USB mass storage, microSD/internal storage, and network access
  to the device's storage over Wi-Fi (FTP-style access while on the same network).

---

## 2. Import, Library & Session Management

- **P0 — Folder import:** point at a copied Dwarf 3 directory tree; auto-discover sessions.
- **P0 — Session parser:** parse Dwarf folder naming conventions and `shotsInfo.json`
  into structured metadata (target, date, exposure, gain, filter, sub count, mode).
- **P0 — FITS header ingestion:** read all FITS keywords; normalize into a common schema.
- **P0 — Image catalog (database):** persistent library of every imported session and file
  (SQLite): target, date, filter, exposure, gain, integration time, location on disk.
- **P1 — Direct-from-device import:** connect to the Dwarf 3 over Wi-Fi (FTP) or USB and
  pull sessions without manual copying; show device storage usage; optional
  delete-after-verified-import.
- **P1 — Watch folder:** auto-ingest anything dropped into a designated directory.
- **P1 — Duplicate detection:** hash-based dedup so re-imports don't create copies.
- **P1 — Target-based organization:** group sessions of the same object across nights
  ("all M31 data") for multi-session integration.
- **P1 — Target name resolution:** normalize "M 31", "NGC 224", "Andromeda" to one object
  via a local catalog (Messier/NGC/IC/common names); attach object type, magnitude, size.
- **P1 — Library browser UI:** thumbnail grid, filter/sort/search by target, date, filter,
  exposure, rating, tags; calendar/timeline view of imaging nights.
- **P2 — Tags, ratings, and notes:** star ratings, free-form notes per session/image,
  color labels, "best of" flags.
- **P2 — Acquisition statistics dashboard:** total integration per target, per filter,
  per month; hours imaged; clear-night history; personal records.
- **P2 — Disk space manager:** show space used per target/session; archive-to-external
  and verify; optionally keep only stacked results and prune rejected subs.
- **P1 — Non-Dwarf format import:** generic FITS from other rigs, DNG/TIFF/PNG stills,
  XISF (PixInsight interchange), and SER planetary video — so data from other tools or
  a future second telescope isn't locked out.
- **P1 — Immutable originals & quarantine trash:** raw files are never modified or
  deleted by processing; rejected/deleted items go to a reviewable quarantine first.
- **P2 — Metadata editing:** correct misidentified target names, add missing
  coordinates/notes; fixes propagate through the catalog without touching raw files.
- **P2 — Session split/merge:** split a folder that contains two targets; merge
  interrupted sessions of the same target/night into one logical session.
- **P2 — Phone-app export import:** attach the DwarfLab mobile app's processed JPGs to
  the matching target/session as reference versions.
- **P2 — Project archive bundle:** export a session + masters + recipe + outputs as one
  portable archive for backup or sharing a full reprocessing challenge.
- **P3 — Multi-device support:** handle two Dwarf units, or mixed Dwarf 2 / Dwarf 3 data.
- **P3 — Cloud backup hooks:** sync library or masters to S3/Backblaze/Drive.

## 3. Calibration

- **P0 — Master dark creation & subtraction:** stack dark frames into a master dark;
  subtract from lights (with exposure/gain matching and mismatch warnings).
- **P0 — Work-without-calibration mode:** sensible defaults (hot-pixel removal via
  outlier rejection) when the user has no darks/flats — common for smart-telescope users.
- **P1 — Master flat / dark-flat / bias support:** full calibration pipeline for users
  who shoot flats (e.g., with a tracing panel or t-shirt method).
- **P1 — Calibration library:** store master darks/flats indexed by exposure, gain, and
  temperature-ish proxy (date); auto-match the right master to a session.
- **P1 — Bad-pixel map:** build hot/cold pixel maps from darks or from statistics across
  subs; apply cosmetic correction.
- **P1 — Synthetic flat generation:** model vignetting and dust shadows from the light
  frames themselves when no real flats exist — the common case for smart-telescope users.
- **P2 — Dark scaling/optimization:** scale a mismatched master dark (different exposure
  or gain) to fit the lights instead of refusing to calibrate.
- **P2 — Lens correction model:** a stored optical model of the Dwarf 3 telephoto
  (vignetting falloff, distortion) applied as a substitute or supplement for flats.
- **P2 — Amp-glow handling:** dark-based removal plus a fallback synthetic model.
- **P2 — Defect-aware Bayer handling:** all calibration performed pre-demosaic on CFA
  data for correctness (IMX678 is a color sensor with an RGGB CFA).
- **P3 — Sensor characterization tool:** measure read noise, gain (e⁻/ADU), and dark
  current from user-captured frame sets; use results to optimize stacking weights.

## 4. Frame Evaluation & Sub Selection

- **P0 — Per-frame quality metrics:** star count, FWHM (sharpness), eccentricity
  (trailing), median background level, SNR estimate — computed on import or on demand.
- **P0 — Auto-rejection:** threshold-based rejection of clouds-passed-through, trailed,
  or out-of-focus subs before stacking; user-adjustable thresholds.
- **P1 — Blink comparator:** rapidly flip through subs (autostretched) to eyeball
  satellites, planes, clouds; keyboard accept/reject.
- **P1 — Quality plots:** graph FWHM / background / star count vs. time to see when the
  night degraded; click a point to view that frame.
- **P1 — Best-N selection:** "stack only the best 80%" by a chosen metric or a
  weighted composite score.
- **P2 — Satellite/aircraft trail detection:** Hough-transform line detection to flag
  (not just reject — pixel rejection during stacking usually handles them) frames.
- **P2 — ML frame classifier:** train/use a small model to classify subs as
  good / cloudy / trailed / aurora-glow etc.
- **P2 — Sky-quality estimation:** compute sky brightness (mag/arcsec²) per frame from
  calibrated background + plate scale; track your site's SQM over time.
- **P2 — Session context enrichment:** auto-compute moon phase, moon altitude, and
  moon–target separation for every session and store it with the metadata.

## 5. Registration & Stacking (re-stacking the raw subs, better than onboard)

- **P0 — Star-based registration:** detect stars, match patterns, solve
  translation + **rotation** + scale (alt-az field rotation makes rotation mandatory);
  fall back to affine/homography for mosaic edges.
- **P0 — Stacking with pixel rejection:** average and median combine; sigma-clipping /
  kappa-sigma / winsorized rejection to remove satellites, cosmic rays, hot pixels.
- **P0 — CFA-aware pipeline:** demosaic (VNG/AHD/bilinear options) at the right stage;
  option to do the entire stack in CFA space with drizzle-style reconstruction.
- **P1 — Weighted stacking:** weight subs by SNR/FWHM/star count rather than equally.
- **P1 — Multi-session integration:** stack subs from many nights of the same target,
  each session calibrated with its own masters, normalized before combining.
- **P1 — Drizzle (×1, ×1.5, ×2):** exploit dither/field rotation between subs to
  recover resolution beyond the 2 µm pixels; CFA drizzle to skip interpolation entirely.
- **P1 — Reference frame selection:** automatic (best quality) or manual choice.
- **P1 — Normalization:** additive/multiplicative background normalization across subs
  so rejection works when sky brightness changed during the night.
- **P2 — Mosaic assembly:** register and blend Dwarf 3 mosaic-mode panels into one image
  (feathered seams, photometric matching between panels).
- **P2 — Comet/asteroid stacking:** stack aligned on a moving object (given motion rate
  or two reference positions), plus star-aligned + comet-aligned composite mode.
- **P2 — Local normalization:** correct per-frame gradients before rejection for cleaner
  stacks under light pollution.
- **P2 — Super-resolution stacking experiments:** Bayer drizzle + many-frame SR.
- **P2 — Multi-exposure HDR integration:** combine short- and long-exposure sets of the
  same target (e.g., M42's core plus its faint outer nebulosity) into one linear image.
- **P2 — WCS-based registration:** align frames/stacks via their plate solutions when
  star matching struggles (sparse fields, very different framings across nights).
- **P2 — Walking-noise mitigation:** detect drift-correlated pattern noise from
  inadequate dithering; counter it with rejection tuning and drift-aware weighting.
- **P3 — Composite stacking modes:** maximum/minimum/sum combines for star trails,
  meteor composites, and satellite-trail art.
- **P3 — GPU-accelerated stacking:** CUDA/OpenCL/wgpu path for big multi-night stacks.
- **P3 — Live re-stack preview:** watch the stack improve as frames are added (useful
  when tethered to the device mid-session via watch-folder).

## 6. Linear Post-Processing (before stretch)

- **P0 — Auto-stretch preview (STF):** view linear data with a non-destructive screen
  stretch at all times.
- **P0 — Background/gradient removal:** polynomial and RBF background extraction with
  automatic + manual sample placement (Dwarf users often shoot from light-polluted
  yards; this is the single highest-impact processing step).
- **P0 — Background neutralization & white balance:** neutralize sky background; basic
  RGB channel alignment.
- **P1 — Photometric color calibration:** plate-solve the image, look up catalog star
  colors (Gaia), and solve a color matrix — accurate color without guesswork.
- **P1 — Green cast removal (SCNR-style).**
- **P1 — Denoising, classical:** anisotropic/bilateral/wavelet/TGV noise reduction with
  luminance/chroma separation and strength masks.
- **P1 — Denoising, ML:** integrate an open denoiser (e.g., GraXpert's model) or ship a
  trained ONNX model; run locally on CPU/GPU.
- **P1 — Deconvolution:** Richardson–Lucy / Wiener with PSF estimated from measured star
  FWHM; regularized to avoid ringing; star-masked application.
- **P2 — BlurXTerminator-style ML sharpening (open equivalent):** ML PSF correction for
  stars + structure sharpening, if a suitable open model exists or is trained.
- **P2 — Hot-column/row and banding suppression** for pattern noise.
- **P2 — Saturated star repair:** reconstruct blown-out star cores and restore their
  catalog-appropriate color instead of leaving white discs.
- **P2 — Chromatic aberration & atmospheric dispersion correction:** per-channel
  sub-pixel realignment plus a radial CA model for the Dwarf optics at low altitudes.
- **P3 — Continuum subtraction & superluminance:** isolate Hα emission by subtracting
  a broadband session from a dual-band session of the same target; build a synthetic
  luminance from all available data across filters.

## 7. Stretching & Non-Linear Processing

- **P0 — Histogram transformation:** midtone/shadow/highlight stretch with live
  histogram and clipping indicators.
- **P0 — Curves:** RGB/K/L/saturation curves with spline editing.
- **P0 — Geometry basics:** crop (with aspect-ratio presets), rotate/flip, and
  resample/downscale — trivial but mandatory, and easy to forget in an astro tool.
- **P1 — Generalized Hyperbolic Stretch (GHS):** the modern, control-rich stretch.
- **P1 — Arcsinh stretch:** color-preserving stretch for star fields.
- **P1 — Masked stretch / iterative stretch presets:** protect stars while lifting faint
  nebulosity.
- **P1 — Saturation & vibrance tools** with luminance masking.
- **P1 — Star removal (ML):** StarNet++-class model run locally; produces starless +
  stars-only layers.
- **P1 — Stars/starless workflow:** process nebula and stars separately; screen/add
  stars back with adjustable intensity and size reduction.
- **P1 — Star reduction (morphological)** for when full removal isn't wanted.
- **P2 — HDR compression / local contrast (multiscale):** reveal core detail in M42,
  M31 without flattening the image.
- **P2 — Unsharp mask & multiscale sharpening** with edge/star protection masks.
- **P2 — Dual-band channel extraction:** from dual-band-filter RGB data, extract
  synthetic **Hα (from R)** and **OIII (from G/B)** channels; recombine as HOO or
  false-color palettes (foraxx-style), with palette presets. This is a killer feature
  for Dwarf 3's built-in dual-band filter.
- **P2 — Selective color / hue rotation** for palette work.
- **P2 — Masks subsystem:** luminance masks, star masks, range masks, painted masks;
  every tool accepts a mask.
- **P2 — Layers/history:** non-destructive operation stack with re-ordering, on/off
  toggles, and per-op parameters editable after the fact.
- **P2 — Retouching tools:** clone/heal brush and content-aware inpainting for residual
  satellite trails, dust artifacts, and edge blemishes that survived stacking.
- **P3 — Cosmetic diffraction spikes:** optional synthetic star spikes for aesthetics.
- **P3 — Pixel math console** for power users.

## 8. Planetary / Lunar / Solar (video & burst modes)

- **P1 — Video ingestion:** load Dwarf 3 MP4/AVI captures; extract frames.
- **P1 — Lucky imaging pipeline:** rank frames by sharpness, select best N%,
  align (planet centroid / surface features), and stack.
- **P1 — Wavelet sharpening (RegiStax-style)** for stacked planetary/lunar results.
- **P2 — Planet derotation** for long capture runs (Jupiter rotates fast).
- **P2 — Lunar/solar mosaic stitching** from panned video or burst panels.
- **P3 — Animation builder:** planetary rotation GIFs, lunar libration sequences.

## 9. Plate Solving, Annotation & Scientific Tools

- **P1 — Local plate solving:** bundled astrometric solver (astrometry.net index subset
  for the Dwarf 3 FOV ~3°×1.7°, or tetra3-style solver); fall back to the online
  astrometry.net API.
- **P1 — Annotation overlay:** label Messier/NGC/IC objects, named stars, galaxies with
  catalog data in the field; export annotated versions.
- **P2 — Constellation lines & boundaries overlay:** especially useful for wide-angle
  frames and orientation context on telephoto fields.
- **P2 — Photometry:** aperture photometry on stars; variable-star light curves across a
  session's subs; comet brightness estimates.
- **P2 — Astrometry of movers:** measure asteroid/comet positions against Gaia; find
  moving objects by blinking registered subs automatically.
- **P2 — SNR/statistics inspector:** region stats, per-channel histograms, pixel probe.
- **P3 — Supernova/nova check:** difference against a survey image (e.g., DSS fetch) of
  the same field and highlight new point sources.
- **P3 — Satellite identification:** given timestamp + location + trail, suggest which
  satellite crossed the frame (TLE lookup).
- **P3 — Exoplanet transit light curves:** guided photometry workflow for bright
  transits (HD 189733-class), which are genuinely within the Dwarf 3's reach.
- **P3 — AAVSO report export:** format variable-star photometry for AAVSO submission.

## 10. Export, Sharing & Reporting

- **P0 — Export formats:** 16-bit TIFF/PNG, JPEG (quality control), FITS; sRGB tagging;
  resize/crop on export.
- **P1 — Auto-crop of stacking edges:** detect and crop rotation/dither borders.
- **P1 — Acquisition summary card:** generated caption/overlay with target, date(s),
  total integration, sub count, filter, equipment ("Dwarf 3, 150 mm f/4.3") — ready to
  paste into Instagram/Reddit/Astrobin posts.
- **P1 — Before/after comparison export:** side-by-side or slider GIF/MP4.
- **P2 — AstroBin-ready export:** filename + acquisition CSV matching AstroBin's
  bulk-upload format.
- **P2 — Timelapse builder:** compile timelapse-mode stills (or nightly stacks of a
  target over months — e.g., comet evolution) into MP4.
- **P2 — Timelapse deflicker:** smooth frame-to-frame brightness variations before
  encoding.
- **P2 — XISF export** for round-tripping with PixInsight users.
- **P2 — Social media presets:** aspect/size presets (square, 4:5, story) with
  safe-area preview so the target doesn't get cropped by the platform.
- **P2 — Print-oriented export:** 300 DPI TIFF with soft-proofing padding/border tools.
- **P3 — Web gallery generator:** static HTML gallery of processed images with metadata.
- **P3 — Direct upload:** push to AstroBin (API) / Flickr from inside the app.

## 11. Automation, Pipelines & Reproducibility

- **P1 — Processing recipes:** save a parameterized chain (calibrate → grade → stack →
  gradient removal → color cal → stretch → denoise) as a named recipe.
- **P1 — One-click "Auto" pipeline:** opinionated default recipe tuned for Dwarf 3 data;
  produces a good image from a raw session folder with zero decisions.
- **P1 — Batch processing:** run a recipe across many sessions/targets overnight; job
  queue with progress, logs, and per-job results.
- **P1 — Full reproducibility:** every output records the exact operations + parameters
  + input hashes (sidecar JSON); re-run or tweak any historical result.
- **P2 — CLI interface:** every pipeline runnable headless (`d3proc stack ./M31_*/`),
  enabling cron jobs and scripting.
- **P2 — Preset marketplace/import:** share recipes as files; import others' recipes.
- **P2 — Output version management:** keep multiple named versions of a final image per
  target (e.g., "HOO palette", "natural color", "2026 reprocess"); compare versions
  side by side; every version keeps its full recipe.
- **P3 — Auto-import-and-process daemon:** when the Dwarf appears on the network after
  a session, pull new data, run the auto recipe, and drop a JPEG in an outbox /
  send a notification.
- **P3 — Live session alerts:** while the daemon watches an in-progress session over
  Wi-Fi, alert your phone if frame quality collapses (clouds rolled in, dew on lens).

## 12. UI / UX Platform Features

- **P0 — High-quality image viewer:** GPU-drawn pan/zoom (to 1:1 and beyond), fast on
  8 MP × dozens of frames; autostretch toggle; channel toggles.
- **P0 — Dark theme** (astronomers process at night) + optional red-light mode.
- **P1 — Before/after and A|B split view** on every processing step.
- **P1 — Undo/redo everywhere;** processing history panel.
- **P1 — Background job engine:** stacking never blocks the UI; progress + cancel.
- **P2 — Session-to-final workspace:** guided left-to-right workflow (Import → Grade →
  Stack → Process → Export) for beginners, with an "expert mode" exposing everything.
- **P2 — Keyboard-first grading** (like photo culling apps: arrows + X/P keys).
- **P2 — Color management:** monitor ICC profile awareness.
- **P2 — Guided onboarding & education:** jargon-explaining tooltips ("what is FWHM?"),
  a bundled sample session, and an interactive first-stack tutorial — most Dwarf 3
  owners are astro beginners.
- **P3 — Inspection display LUTs:** inverted and false-color views for hunting faint
  halos, gradients, and processing artifacts.
- **P3 — Localization** and full accessibility pass.

## 13. Integrations (leverage existing open tools rather than rebuild)

- **P1 — Siril integration:** drive Siril in script mode as an alternative
  stacking/processing backend (mature, battle-tested with Dwarf data).
- **P1 — GraXpert integration:** background extraction + ML denoise via its CLI.
- **P2 — StarNet++ / open star-removal models** via ONNX runtime.
- **P2 — Astrometry.net** local `solve-field` and web API.
- **P2 — External editor round-trip:** "Edit in GIMP/Photoshop/Affinity" with 16-bit TIFF
  handoff and automatic re-import of the result as a new version.

## 14. Wide-Angle Camera & Nightscapes (the Dwarf 3's second lens)

- **P2 — Wide-cam ingestion:** catalog wide-angle captures alongside telephoto sessions;
  keep the two cameras' outputs linked when shot the same night.
- **P2 — Star-trail composites:** max-value stacking with gap filling across timelapse
  sets; comet-tail style trail fading option. *(Shipped as `umbra trails`: streaming
  lighten blend with dark subtraction, statistical hot-pixel repair, and an `--align`
  meteor-composite mode. Reads DSLR frames — Canon CR2/CR3, NEF, ARW, DNG via the
  `dslr` extra — plus JPEG/TIFF/PNG/FITS, so the whole suite now ingests DSLR files
  through `AstroImage.from_file`. Directional gap filling and comet-tail `--fade`
  shipped too, plus `--foreground` mean extraction for nightscape bases.)*
- **P2 — Nightscape processing:** sky/foreground segmentation masks so the sky can be
  stacked (noise reduction) while the landscape stays static; separate white balance
  for sky vs. ground.
- **P2 — Meteor & transient hunting:** scan timelapse/wide frames for transient trails,
  distinguish meteors from satellites/planes by trail profile, and build meteor-shower
  composites onto a single base frame. *(Shipped as `umbra meteor-scan`:
  neighbor-maximum residual + Hough streak extraction, satellite rejection by
  cross-frame colinear tracks, `--copy-to`/`--annotate`/`--json`; composites via
  `umbra trails --align`.)*
- **P3 — Panorama stitching** of wide-cam frames (Milky Way arches).
- **P3 — All-night sky movie:** wide-cam timelapse with the telephoto's live stack
  progress as picture-in-picture — a shareable "how the night went" reel.

## 15. Acquisition Feedback (close the loop for your next session)

- **P2 — Sub-exposure advisor:** from measured sky background and sensor read noise,
  recommend the exposure/gain that swamps read noise at your site — answers "should I
  shoot 15 s or 60 s subs?" with your own data.
- **P2 — Integration planner:** estimate additional integration hours needed to reach a
  target SNR ("2 more clear nights on M33 gets you to your M31 result's quality").
- **P2 — Dither adequacy analysis:** measure inter-frame offsets across a session and
  warn when walking noise is likely, with suggested settings changes.
- **P3 — Equipment health trends:** FWHM/tilt/vignetting drift across months of
  sessions to catch focus motor or collimation problems early.

---

## Feature-count sanity check

P0 items form a complete minimal loop: import a Dwarf session → grade subs → calibrate →
register/stack (rotation-aware) → remove gradient → stretch → export. Everything else
layers on top without reworking that spine.
