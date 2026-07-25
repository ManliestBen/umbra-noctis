"""The built-in guide: every feature explained, available offline from the
tool itself — ``umbra guide`` on the command line, Help → Guide in the GUI.

Content lives here as Markdown sections; the operation reference is generated
live from the ops registry so it can never drift out of date.
"""

from __future__ import annotations

_START = """
# Getting Started

Umbra Noctis turns raw night-sky captures — Dwarf 3 smart-telescope sessions
or DSLR frames — into finished images, reproducibly.

**Install extras as needed:**

- `pip install 'umbra-noctis[gui]'` — the desktop app (`umbra gui`)
- `pip install 'umbra-noctis[dslr]'` — Canon CR2/CR3, Nikon NEF, Sony ARW,
  DNG and other camera raw files

**No telescope handy?** `umbra demo-data ./demo` writes a realistic synthetic
session (drifting star field, gradient, hot pixels, a cloudy frame, a
satellite trail, matching darks) so every command below can be practiced.

**The three workflows at a glance:**

| You shot | Use | Result |
|---|---|---|
| Deep-sky subs (Dwarf 3) | `umbra auto` or grade → stack → process | One clean, stretched image |
| Wide-angle timelapse (DSLR) | `umbra trails` / `umbra meteor-scan` | Star trails, meteor composites |
| Planetary/lunar video | `umbra planetary` | Lucky-imaging stack |
"""

_DEEPSKY = """
# Deep-Sky Workflow (Dwarf 3)

0. **Inspect** — `umbra info <path>` prints what's in any session folder or
   whole SD card (target, mode, frame count, exposure, integration) before
   you import anything.
1. **Import** — `umbra import /path/to/Astronomy` scans the SD card and
   catalogs every session by target in the library
   (`umbra library targets` shows integration totals across nights).
2. **Grade** — `umbra grade <session>` scores each sub-frame (star count,
   FWHM sharpness, eccentricity, background) and flags clouds, wind shake,
   and bright-sky frames with reasons.
3. **Stack** — `umbra stack <session> -o stacked.fits` calibrates
   (auto-matching darks by exposure+gain), registers with rotation support
   (mandatory for alt-az field rotation), and integrates with winsorized
   sigma-clipping so satellites and cosmic rays vanish. `--drizzle 2` for
   finer sampling, `--best 0.8` to keep the best 80% of frames.
4. **Process** — `umbra process stacked.fits -o final.jpg --auto-finish`
   runs the standard chain, or build your own with `--op` (see the
   *Processing Operations* topic). Keep intermediates in FITS to stay linear.
5. **Export** — JPEG for sharing, 16-bit TIFF/PNG for further editing,
   FITS for full fidelity.

`umbra auto <session> -o out/` does steps 2–5 in one command with zero
decisions. `umbra solve <image> --annotate out.jpg` plate-solves and labels
every catalog object in the field.
"""

_NIGHTSCAPE = """
# Star Trails, Meteors & Nightscapes (DSLR or Dwarf wide cam)

All commands here read camera raw (CR2/CR3/NEF/ARW/DNG — install the `dslr`
extra), JPEG, TIFF, PNG, and FITS, streaming so a 400-frame night needs the
memory of about three frames. Frames sort by filename, which for camera
numbering is shooting order.

## Star trails — `umbra trails`

Lighten (maximum) blending: no registration, so the stars' motion between
frames paints the trails. The opposite of `umbra stack` — never deep-sky
stack trail frames, alignment would erase them.

    umbra trails ./night -o trails.jpg --darks ./darks

- `--darks DIR` — cap-on frames at identical settings → master dark. Without
  darks, hot pixels are found statistically (bright in the per-pixel
  *minimum* of all frames — stars move, defects don't) and repaired.
- Gap filling is on by default: the small dark dashes the intervalometer's
  re-arm time leaves in each trail are bridged after blending.
  `--no-gap-fill` for the strict classic look.
- `--fade 0.01` — comet-tail effect: the trail's past dims by 1% per frame,
  so each star ends in a bright head with a fading tail.
- `--foreground base.tif` — also writes the *mean* of every frame: a
  noise-free landscape to blend under the trails in an editor.

## Meteor scan — `umbra meteor-scan`

Finds the handful of frames in a night that actually contain a streak:

    umbra meteor-scan ./night --copy-to keepers/ --annotate previews/

Each frame's luminance is compared against the maximum of its two neighbors —
everything static or slowly drifting cancels; what survives existed in one
frame only. Streaks are extracted with a Hough transform, and streaks that
continue along the same line in adjacent frames are reclassified
`satellite` (meteors live and die inside a single exposure; satellites and
aircraft cross many). `--sigma 4` scans more aggressively, `--min-length`
sets the shortest streak worth reporting, `--json report.json` for scripting.

## Meteor composite

Cull to the keepers, then blend with star-field alignment so every meteor
lands on one fixed sky:

    umbra trails ./keepers -o meteors.tif --align
"""

_PROCESSING = """
# Processing Operations

Operations are pure, ordered, and recorded: every op appends itself to the
image's history, so any result can be reproduced exactly. Apply them from
the CLI (`umbra process in.fits -o out.jpg --op ghs:amount=6`), from recipes,
or from the GUI's Process page — same registry everywhere.

**Recommended order** (the `--auto-finish` chain follows it):
calibrate-stage fixes → linear fixes (`background_extract`,
`background_neutralize`, `vignette_correct`, `white_balance`, `scnr`,
`denoise`, `deconvolve`) → stretch (`ghs` / `autostretch` / `arcsinh`) →
nonlinear polish (`curves`, `saturation`, `local_contrast`, `sharpen`,
`star_reduce`, `hdr_compress`) → cosmetic (`defringe`, `clone_out`).

Highlights for night-sky work:

- `background_extract` — removes skyglow gradients (light pollution).
- `vignette_correct` — synthetic-flat division; rescues dark corners of
  fast wide-angle lenses and the Dwarf's vignetting when no flats exist.
- `defringe` — suppresses the purple/green chromatic-aberration fringes a
  fast lens shot wide open leaves around bright stars.
- `dualband_extract` — Hα/OIII palettes from the Dwarf 3's dual-band filter.
- `star_reduce` — shrinks stars so the nebula becomes the subject.

The complete parameter-by-parameter reference is the *ops* topic
(`umbra guide ops`, same content as `umbra ops --markdown`), generated live
from the registry.
"""

_RECIPES = """
# Recipes & Automation

Any processing chain can be saved and replayed:

    umbra process stack.fits -o test.jpg --op background_extract --op ghs:amount=6 \\
        --save-recipe orion.json
    umbra process another_stack.fits -o out.jpg --recipe orion.json

Recipes are plain JSON lists of registry calls — edit them by hand, commit
them to git, share them. `umbra auto` is itself a built-in recipe.

Batch a whole card overnight:

    for s in /data/Astronomy/DWARF_RAW_*; do
        umbra auto "$s" -o "out/$(basename "$s")"
    done
"""

_GUI = """
# The Desktop App

`umbra gui` opens a guided five-step workflow — Library, Grade, Stack,
Process, Export — mirroring the CLI exactly (anything the app does, the CLI
can script). Notable:

- **Red night-vision mode** (View menu) for use in the field.
- Frame grading with per-frame verdicts and reasons before stacking.
- The Process page generates its tool panels from the same operation
  registry as the CLI, parameters and all.
- Help → Guide opens this guide; Help → About for version info.
"""

_FAQ = """
# FAQ & Field Notes

**Which output format when?** FITS while data is linear (between stack and
final stretch), 16-bit TIFF for editing elsewhere, JPEG only as the last
step.

**Long-exposure noise reduction (LENR) on the camera?** OFF for anything
you'll stack (trails, meteors — it blanks the sensor between frames and
dashes your trails); ON only for a single continuous bulb exposure.

**Where does the library live?** `~/.umbra-noctis` by default; `umbra import`
and `umbra library` take `--db` to use another location. Raw files are
never modified.

**Stacking looks misaligned / trails look erased?** You used the wrong tool:
`umbra stack` aligns stars (deep-sky), `umbra trails` does not (trails).

**Meteor scan flags a plane?** Aircraft blink and satellites persist — both
usually classify as `satellite` via the multi-frame track check, but a slow
tumbling satellite flare inside one frame can fool it. The `--annotate`
previews exist for a quick human veto.

**Canon raw won't load?** `pip install 'umbra-noctis[dslr]'`.
"""

# topic key -> (title, static markdown or None when generated)
_TOPICS: dict[str, tuple[str, str | None]] = {
    "start": ("Getting started", _START),
    "deepsky": ("Deep-sky workflow (Dwarf 3)", _DEEPSKY),
    "nightscape": ("Star trails, meteors & nightscapes", _NIGHTSCAPE),
    "processing": ("Processing operations", _PROCESSING),
    "ops": ("Operation reference (generated)", None),
    "recipes": ("Recipes & automation", _RECIPES),
    "gui": ("The desktop app", _GUI),
    "faq": ("FAQ & field notes", _FAQ),
}


def topics() -> list[tuple[str, str]]:
    """(key, title) for every guide topic, in reading order."""
    return [(key, title) for key, (title, _) in _TOPICS.items()]


def render(topic: str = "all") -> str:
    """Render one topic (or ``all``) as Markdown."""
    if topic == "all":
        return "\n\n---\n\n".join(render(k) for k in _TOPICS)
    if topic not in _TOPICS:
        known = ", ".join(_TOPICS)
        raise KeyError(f"Unknown guide topic {topic!r}. Topics: {known}, all")
    title, body = _TOPICS[topic]
    if body is None:  # generated topics
        from .core.ops import ops_markdown
        return ops_markdown()
    return body.strip()
