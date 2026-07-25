# Plan 005: Harden the CLI surface, plate solver, and trails/meteor edge cases

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update your row in
> `plans/README.md` unless the reviewer maintains the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- umbra_noctis/cli.py umbra_noctis/recipes/auto.py umbra_noctis/solve/astrometry.py umbra_noctis/detect/meteors.py umbra_noctis/stack/trails.py umbra_noctis/export/ umbra_noctis/process/ops_stretch.py umbra_noctis/gui/pages_data.py`
> Plans 001–004 touch `cli.py` and `trails.py` lightly (lint, work_dir)
> — expected. Anything contradicting the excerpts below: STOP.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: LOW-MED
- **Depends on**: plans/004-stack-quality-and-memory.md (sequential file overlap in cli.py)
- **Category**: security + bug + tests
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

The `umbra auto` output filename is built from untrusted session metadata
(folder name / shotsInfo.json / FITS header) with only spaces stripped —
path separators survive and can write outside the chosen output directory.
The plate solver leaks a file descriptor and a full-size copy of the user's
image into `/tmp` on every call, plus a directory per `solve-field`
attempt, and reports a nova web-solve as successful even when the response
lacks coordinates (then crashes formatting `None`). `umbra process` and the
GUI preview still reject the DSLR formats the rest of the suite accepts.
First-run mistakes (missing output dir, typo'd path) produce raw
tracebacks. The meteor scanner structurally never scans the first or last
frame and silently skips mismatched shapes. And `cli.py` — the
highest-churn file — has zero tests.

## Current state

- `umbra_noctis/recipes/auto.py` (~88-93):
  ```python
  out_dir.mkdir(parents=True, exist_ok=True)
  base = session.target.replace(" ", "") or "result"
  ...
  p = export_image(img, out_dir / f"{base}.{fmt}")
  ```
  `session.target` originates from folder name / `shotsInfo.json` / FITS
  OBJECT header (`ingest/session.py`).
- `umbra_noctis/solve/astrometry.py`:
  - `solve_image` (~49-56): `tmp = Path(tempfile.mkstemp(suffix=".fits")[1])`
    — fd (index 0) leaked, file never unlinked.
  - `_solve_astap` (~87-96): writes `.wcs`/`.ini` sidecars next to the
    input; never removed.
  - `_solve_field` (~118-124): `tempfile.mkdtemp(prefix="umbra_solve_")`
    never removed.
  - `_solve_nova` (~178-186): `SolveResult(True, "nova",
    ra_deg=info.get("ra"), ...)` — may be None; `cli.py` `cmd_solve`
    (~223-225) then does `f"{result.ra_deg:.4f}"` → TypeError.
- `umbra_noctis/cli.py`:
  - `cmd_process` (~168): `img = AstroImage.from_fits(args.input)`.
  - `cmd_solve` (~227-228): `AstroImage.from_fits(args.input)` for
    annotation.
  - `main` (~500-508): `args.func(args)` with no error handling.
  - Four copies of the FITS-vs-export branch (`cmd_stack` ~141-144,
    `cmd_process` ~187-190, `cmd_trails` twice ~278-289) even though
    `export_image` (`export/writers.py:38-40`) already dispatches
    `.fits`/`.fit` to `save_fits`.
- `umbra_noctis/export/writers.py` `export_image` (~34-40) and
  `umbra_noctis/core/image.py` `save_fits` (~220 area): neither creates
  `path.parent`.
- `umbra_noctis/export/summary.py` (~32): `f"Frames: {n_used or frames} ×
  {exp:g}s @ gain {gain}"` — `exp`/`gain` can be None (guarded at other
  call sites, e.g. `cli.py` cmd_grade prints use `or '?'`).
- `umbra_noctis/process/ops_stretch.py` `curves` (~137-142):
  `pts = sorted(tuple(float(v) for v in p.split(",")) for p in
  points.split(";"))` then `PchipInterpolator(xs, ys)` — malformed text or
  duplicate x values raise bare errors that reach GUI/CLI users.
- `umbra_noctis/detect/meteors.py`:
  - `scan_for_meteors` (~140-152): loop `for i in range(1, len(paths)-1)`
    — frames 0 and N-1 always "clean"; shape-mismatch skip has no log;
    `scale` computed from paths[0] only.
  - `annotate_scan` (~188-199): `jpeg = cv2.imread(str(out_path))` then
    `.shape` with no None check; also re-encodes the JPEG a second time.
- `umbra_noctis/stack/trails.py` (~110-114): demosaic happens BEFORE the
  dark check (note: an earlier audit claim of inverted order was wrong);
  the real defect is the silent skip:
  ```python
  if master_dark is not None and master_dark.data.shape == img.data.shape:
      img = subtract_dark(img, master_dark)
  ```
  — on mismatch, no log, and the CLI has already printed "master dark from
  N frames". Also `mean_acc` (float64 full-frame) is computed even when the
  caller never asks for `--foreground` (`cli.py` cmd_trails only writes
  `result.mean_image` when `args.foreground`).
- `umbra_noctis/gui/pages_data.py` (~239-244): grade preview loads with
  `AstroImage.from_fits(q.path)` inside `except Exception: pass` — blank
  panel, no diagnostic, and DSLR sessions can never preview.
- Conventions: CLI prints plain lines, no logging module; errors should be
  `print(...); sys.exit(1)`. Tests: see `tests/test_detect_ops_guide.py`
  for style; `tests/test_trails.py` for synthetic frame helpers.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Env (if missing) | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Tests | `.venv/bin/python -m pytest -q` | all pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 |
| Manual smoke | `.venv/bin/umbra demo-data /tmp/dd --frames 6 && .venv/bin/umbra info /tmp/dd/DWARF_RAW_*` | prints session summary |

## Scope

**In scope**: `umbra_noctis/cli.py`, `umbra_noctis/recipes/auto.py`,
`umbra_noctis/solve/astrometry.py`, `umbra_noctis/detect/meteors.py`,
`umbra_noctis/stack/trails.py`, `umbra_noctis/export/writers.py`,
`umbra_noctis/export/summary.py`, `umbra_noctis/core/image.py`
(save_fits mkdir only), `umbra_noctis/process/ops_stretch.py` (curves
parsing only), `umbra_noctis/gui/pages_data.py` (preview loader only),
`tests/test_cli.py` (create), `tests/test_solve.py` (create),
`tests/test_trails.py`, `tests/test_detect_ops_guide.py` (meteor edge
tests), `tests/test_process_export.py` (summary/slug tests).

**Out of scope**: solver *logic* (backend order, parsing), GUI worker
threading (plan 006), `guide.py` text (only if a flag's behavior changes —
it doesn't).

## Git workflow

Branch as dispatched; one commit per step.

## Steps

### Step 1: Slugify the auto-pipeline output name

In `recipes/auto.py`, replace the `base = ...` line with a slug through an
allowlist:

```python
import re
base = re.sub(r"[^A-Za-z0-9_-]+", "", session.target.replace(" ", "_")) or "result"
```

and after building each output path, assert containment:

```python
dest = (out_dir / f"{base}.{fmt}")
if out_dir.resolve() not in dest.resolve().parents:
    raise ValueError(f"unsafe output name derived from target {session.target!r}")
```

**Verify**: new `test_auto_output_name_is_sanitized` passes.

### Step 2: Solver temp hygiene + nova validation

In `solve/astrometry.py`:

1. `solve_image`: when given an AstroImage, create the temp FITS inside a
   `tempfile.TemporaryDirectory()` context that spans the whole function
   (all backends), so the copy is always removed; `os.close()` any fd if
   `mkstemp` remains (prefer `TemporaryDirectory` + a plain filename).
2. `_solve_astap`: delete `path.with_suffix(".wcs")` and `.ini` in a
   `finally` — but ONLY when `solve_image` created the temp copy; if the
   user passed a real path, write sidecars into a TemporaryDirectory by
   copying? No — simpler and safe: after parsing, unlink the two sidecars
   if they did not exist before the call (record existence up front).
3. `_solve_field`: wrap the mkdtemp in `tempfile.TemporaryDirectory()`.
4. `_solve_nova`: before returning success, validate `ra`/`dec` are
   present and floatable; else `SolveResult(False, "nova",
   message=f"web solve returned incomplete calibration: {info!r}")`.
5. `cmd_solve` in `cli.py`: guard the print with
   `if result.ra_deg is None: print(...); sys.exit(1)` as belt-and-braces.

**Verify**: new `tests/test_solve.py` passes (see Test plan).

### Step 3: Universal loader + output-dir creation + top-level CLI errors

1. `cli.py` `cmd_process` and `cmd_solve`: `AstroImage.from_fits` →
   `AstroImage.from_file`.
2. `gui/pages_data.py` preview: `from_file`, and replace `except
   Exception: pass` with setting the preview status label text to
   `f"Preview failed: {exc}"` (find the page's existing status/info label;
   if none exists, use `self.window().statusBar().showMessage(...)`).
3. `export/writers.py` `export_image` and `core/image.py` `save_fits`:
   `path.parent.mkdir(parents=True, exist_ok=True)` before writing.
4. `cli.py` `main`: wrap `args.func(args)`:
   ```python
   try:
       args.func(args)
   except (KeyboardInterrupt, SystemExit):
       raise
   except Exception as exc:
       if os.environ.get("UMBRA_DEBUG"):
           raise
       print(f"error: {exc}", file=sys.stderr)
       sys.exit(1)
   ```
5. Remove the four FITS-vs-export branches — call `export_image(image,
   out)` unconditionally (it already dispatches FITS).

**Verify**: `.venv/bin/umbra process /nonexistent.fits -o /tmp/x.jpg` →
prints one `error:` line, exit 1, no traceback. Full suite passes.

### Step 4: Curves input validation

In `ops_stretch.py` `curves`, parse `points` in a helper that raises
`ValueError` with the expected format on any failure:

```python
def _parse_points(points: str) -> list[tuple[float, float]]:
    try:
        pts = sorted({float(x): float(y) for x, y in
                      (p.split(",") for p in points.split(";") if p.strip())}.items())
    except (ValueError, TypeError):
        raise ValueError(
            f"curves: points must look like '0,0;0.5,0.6;1,1' — got {points!r}") from None
    if len(pts) < 2:
        raise ValueError("curves: need at least 2 control points")
    return pts
```

(The dict comprehension dedupes x values, fixing the PchipInterpolator
strictly-increasing crash.)

**Verify**: new `test_curves_rejects_malformed_points` passes.

### Step 5: Meteor scanner edges + annotate guard

In `detect/meteors.py`:

1. Scan frame 0 against frame 1 alone and frame N-1 against N-2 alone
   (residual vs the single neighbor). Keep the interior logic unchanged.
2. Log every shape-mismatch skip: `log(f"SKIP {path.name}: shape ...")`.
3. `annotate_scan`: if `cv2.imread` returns None, raise
   `RuntimeError(f"could not re-read {out_path} for annotation")`. (Keep
   the two-encode approach — restructuring is out of scope.)

**Verify**: extend meteor tests — a meteor drawn on frame 0 of 6 is now
detected (previously structurally impossible); shape-mismatch produces a
log line.

### Step 6: Trails dark logging + lazy mean

In `stack/trails.py`:

1. On dark shape mismatch, `_log(f"master dark shape {mshape} != frame
   {fshape} — dark subtraction SKIPPED")` (once, not per frame — use a
   flag).
2. Add `want_mean: bool = False` parameter; allocate/update `mean_acc` only
   when set; `TrailResult.mean_image` is None otherwise. `cli.py`
   `cmd_trails` passes `want_mean=bool(args.foreground)`.
3. `summary.py`: guard the caption interpolations —
   `f"{exp:g}" if exp else "?"` and same for gain.

**Verify**: `tests/test_trails.py` updated (`test_mean_image_is_average`
now passes `want_mean=True`); new `test_dark_mismatch_logged`;
new summary test with `exposure_s=None` session.

### Step 7: CLI characterization tests

Create `tests/test_cli.py` driving `umbra_noctis.cli.main(argv)` in-process
(no subprocess). Cover at minimum:

- `demo-data` → creates session dirs (assert on filesystem).
- `info <session>` → stdout contains target and frame count (`capsys`).
- `import` + `library targets` against a tmp `--db` → target row printed.
- `grade <session>` → verdict table lines present.
- `ops` → contains `defringe`.
- `guide` (no arg) → lists topics; `guide faq` → nonzero output.
- `process <stacked.fits> -o out.jpg --op autostretch` → file exists
  (build the input by stacking the demo session first, or simply
  `save_fits` a synthetic AstroImage).
- `trails <frames> -o out.jpg` on 4 tiny PNGs → file exists.
- error path: `main(["info", "/nonexistent"])` → SystemExit code 1 (with
  the new top-level handler) and `error:` on stderr.

Assert on artifacts and substrings, NOT exact prose.

**Verify**: `.venv/bin/python -m pytest -q tests/test_cli.py` → all pass.

## Test plan

- `tests/test_cli.py` (Step 7, ~9 tests) — pattern: `tests/test_trails.py`
  fixtures + `capsys`.
- `tests/test_solve.py`: (a) `_solve_nova` incomplete-payload → failure
  result (monkeypatch the module's HTTP helper — read the function to find
  the seam; if none exists, factor the POST into a module-level
  `_nova_post` first); (b) `solve_image` with all backends unavailable
  (monkeypatch `shutil.which` → None, no API key env) → returns
  `success=False` AND leaves no `umbra_solve_*`/temp FITS behind in
  `tempfile.gettempdir()` (snapshot dir listing before/after); (c) if a
  `_wcs_from_header`-style pure function exists, test it against a
  hand-built astropy Header with known RA/Dec.
- Meteor edge tests + trails/summary/slug/curves tests per steps above.

## Done criteria

- [ ] `.venv/bin/python -m pytest -q` exits 0; `tests/test_cli.py` ≥9 tests, `tests/test_solve.py` ≥3 tests
- [ ] `grep -n "from_fits(args.input)" umbra_noctis/cli.py` → 0 matches
- [ ] `grep -c "suffix.lower() in (\".fits\"" umbra_noctis/cli.py` → 0
- [ ] `grep -n "mkstemp" umbra_noctis/solve/astrometry.py` → 0 matches
- [ ] `grep -n "except Exception: pass" umbra_noctis/gui/pages_data.py` → 0 matches
- [ ] `UMBRA_DEBUG` handler present in `cli.py` `main`
- [ ] `.venv/bin/python -m ruff check .` exits 0
- [ ] No files outside Scope modified

## STOP conditions

- Excerpts don't match beyond plans 001–004's documented touches.
- The nova code has no clean seam to monkeypatch and factoring one out
  requires touching request/parsing logic beyond a mechanical extract.
- Removing the FITS branch changes any existing test's output (it must be
  behavior-identical — `export_image` dispatches FITS itself).
- `tests/test_detect_ops_guide.py::test_guide_covers_every_command_and_new_features`
  fails (you removed a documented flag — reconcile).

## Maintenance notes

- The top-level CLI handler means new `cmd_*` functions should raise
  informative exceptions rather than printing+exiting mid-function.
- Reviewer: check Step 1's containment assert actually triggers on a
  `..`-bearing target (the new test must construct one via a synthetic
  DwarfSession, not a real folder name — folder names can't contain `/` but
  shotsInfo.json/FITS headers can).
- The meteor first/last-frame handling slightly raises false-positive odds
  on those two frames (single-neighbor residual); acceptable — they were
  previously never scanned at all.
