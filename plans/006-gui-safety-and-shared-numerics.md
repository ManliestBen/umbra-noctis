# Plan 006: GUI thread safety, honest fallbacks, and one home for shared numerics

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update your row in
> `plans/README.md` unless the reviewer maintains the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- umbra_noctis/gui/ umbra_noctis/core/ umbra_noctis/stack/register.py umbra_noctis/recipes/auto.py umbra_noctis/ingest/session.py umbra_noctis/grade/ umbra_noctis/detect/meteors.py umbra_noctis/process/`
> Plans 001–005 legitimately touched several of these files; compare
> excerpts and STOP only on contradictions in the specific lines cited.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/004-stack-quality-and-memory.md, plans/005-cli-solve-trails-hardening.md
- **Category**: bug + tech-debt
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

Clicking a GUI action twice replaces the only reference to a running
`QThread` — Qt aborts the whole process ("Destroyed while thread is still
running") and the user loses their session. A dead navigation guard lets
users open the Process page with no stack and get silently no-oping
buttons. `umbra auto` promises "every decision is logged" but never prints
its log, so a failed stretch still ends with "Done." — and the silent
astroalign→phase-correlation and sep→scipy fallbacks are quality downgrades
indistinguishable from success. Under the hood, `median + 1.4826·MAD` is
hand-rolled 13 times across 8 modules with four different epsilons (one
missing entirely), luminance has 5 implementations (one using a different
formula), op registration works only via an accidental transitive import,
`discover_sessions` re-lists each directory once per file, the `linear`
flag doesn't survive a FITS round-trip (causing double-autostretch), and
grid-sampling ops NaN-poison on small images.

## Current state

- `umbra_noctis/gui/pages_process.py`:
  - ~373 (`_run_ops`) and ~128 (`run_stack`): `self.worker = FnWorker(job)`
    overwrites a possibly-running worker; `apply_btn` is disabled during
    runs (~360) but the auto-process button (~223-227) is not.
  - Signals: workers emit `finished`/`failed`; follow the existing connect
    pattern in this file.
- `umbra_noctis/gui/app.py` (~100):
  ```python
  if index >= 3 and self.state.stacked is None and index != 3:
      self._nudge(2, "Stack the session first.")
  ```
  `>= 3 and != 3` ≡ `>= 4`, so step 3 (Process) is reachable unstacked.
  No `closeEvent` exists in `MainWindow`.
- `umbra_noctis/gui/workers.py` — `FnWorker(QThread)`: injects
  `progress`/`log` kwargs if the fn accepts them (~34-37), adapts 2-arg vs
  3-arg progress (~43-48), catches all exceptions → `failed.emit(traceback
  string)` (~40-41). No tests exist; `tests/test_gui_smoke.py` deliberately
  routes around it.
- `umbra_noctis/recipes/auto.py` (~80-86): per-step `try/except` logs
  `SKIPPED <op>` into the `logs` list; `cli.py` `cmd_auto` (~151-157)
  never prints those logs and always prints "Done.".
- `umbra_noctis/stack/register.py` (~58-61): astroalign failure returns
  None → silent phase fallback in `solve_transform` (~94-100).
  `umbra_noctis/grade/stars.py` (~34-46): silent scipy fallback when sep
  missing/failing.
- Robust-sigma copies (13 sites): `calib/masters.py` (~96, ~112),
  `stack/trails.py` (~164), `stack/integrate.py` (~145, ~148, ~229),
  `process/ops_linear.py` (~68, ~220), `process/display.py` (~19),
  `detect/meteors.py` (~82), `grade/metrics.py` (~50 — NO epsilon, ~68),
  `grade/stars.py` (~60). Epsilons in use: 1e-5, 1e-6, 1e-9, 1e-12, none.
  `grade/metrics.py` also has a private `_robust_z` (~66-71).
- Luminance: `core/image.py` `AstroImage.luminance()` (Rec.709);
  `grade/stars.py` `_luminance` (Rec.709 on ndarray);
  `process/display.py:16` (`data.mean(axis=2)` — DIFFERENT formula);
  CFA superpixel binning duplicated byte-identically in
  `stack/register.py` `_lum` (~45-51) and `detect/meteors.py`
  `_luminance_small` (~62-76).
- Registry: `core/ops.py` `OPS` fills only when `umbra_noctis.process`
  imports; five `# noqa: F401` side-effect imports exist (`cli.py` ×3,
  `gui/pages_process.py`, `guide.py`); `recipes/auto.py` has NONE and works
  only because `from ..export.writers import export_image` transitively
  imports `process.display`.
- `umbra_noctis/ingest/session.py` `discover_sessions` (~223-232): three
  `rglob` walks; the `*.fits` walk does `len(list(parent.glob("*.fits")))`
  per file → O(files²).
- `umbra_noctis/core/image.py`: `save_fits` writes no linearity marker;
  `from_fits` hardcodes `linear=True`. Round-tripping a stretched image
  re-autostretches on export (`export/writers.py` ~42-43).
- Grid sampling: `process/ops_linear.py` `background_extract` (~58-63) and
  `calib/masters.py` `synthetic_flat` (~155-163) produce empty boxes when
  the image is smaller than the sample grid → NaN model.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Env (if missing) | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Tests | `.venv/bin/python -m pytest -q` | all pass |
| GUI tests only | `.venv/bin/python -m pytest -q tests/test_gui_smoke.py tests/test_gui_workers.py` | pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 |

## Scope

**In scope**: `umbra_noctis/gui/pages_process.py`, `umbra_noctis/gui/app.py`,
`umbra_noctis/gui/workers.py` (only if a guard helper is needed),
`umbra_noctis/cli.py` (cmd_auto printing), `umbra_noctis/recipes/auto.py`
(degraded marker), `umbra_noctis/stack/register.py`,
`umbra_noctis/grade/stars.py`, `umbra_noctis/core/stats.py` (create),
`umbra_noctis/core/image.py`, `umbra_noctis/core/ops.py`,
`umbra_noctis/process/display.py`, `umbra_noctis/process/ops_linear.py`,
`umbra_noctis/calib/masters.py`, `umbra_noctis/stack/integrate.py`,
`umbra_noctis/stack/trails.py`, `umbra_noctis/detect/meteors.py`,
`umbra_noctis/grade/metrics.py`, `umbra_noctis/ingest/session.py`,
`tests/test_gui_workers.py` (create), `tests/` extensions.

**Out of scope**: op *behavior* beyond the display.py luminance formula
change; parallelization; `pick_reference` (plan 004 owns it);
gui orchestration consolidation (deferred DEBT-07).

## Git workflow

Branch as dispatched; one commit per step. Steps 5–8 are mechanical
consolidations — keep them in separate commits from the behavioral steps.

## Steps

### Step 1: Worker lifecycle safety

In `gui/pages_process.py` (both `run_stack` and `_run_ops`) and any other
`FnWorker` launch site (`grep -n "FnWorker(" umbra_noctis/gui/`):

1. Refuse to start when busy:
   ```python
   if getattr(self, "worker", None) is not None and self.worker.isRunning():
       return
   ```
2. Disable the triggering button(s) — including the auto-process button —
   on start; re-enable in BOTH the finished and failed handlers.
3. Keep a reference until done: connect
   `self.worker.finished.connect(self.worker.deleteLater)` and only
   replace `self.worker` after `isRunning()` is False.
4. In `gui/app.py` `MainWindow`, add:
   ```python
   def closeEvent(self, event):
       for page in (self.stack_page, self.process_page, self.grade_page):
           w = getattr(page, "worker", None)
           if w is not None and w.isRunning():
               w.quit(); w.wait(5000)
       event.accept()
   ```
   (Adjust attribute names to the real pages that own workers — grep first.)

**Verify**: `.venv/bin/python -m pytest -q tests/test_gui_smoke.py` passes.

### Step 2: Fix the navigation guard

`gui/app.py` ~100: change to `if index >= 3 and self.state.stacked is None:`
(drop `and index != 3`).

**Verify**: extend `tests/test_gui_smoke.py`: with a fresh state (session
set, no stack), `window.goto(3)` leaves `stack_widget.currentIndex() == 2`.
(Follow the smoke test's existing offscreen setup.)

### Step 3: Make fallbacks and the auto log visible

1. `cli.py` `cmd_auto`: `auto_process` already takes a `log` callback
   (`log=lambda m: print("  " + m)` is used by cmd_stack) — pass one so
   SKIPPED lines print; after the run, if any log line starts with
   "SKIPPED", print a warning summary line and exit 0 still.
2. `recipes/auto.py`: when a skipped step's op is a stretch
   (`step["op"] in ("ghs", "autostretch", "arcsinh", "histogram_stretch")`),
   append a log line `"WARNING: stretch failed — output will look dark"`.
3. `stack/register.py` `solve_transform`: when the stars solver returns
   None and phase fallback is used, record it — add an optional
   `log=None` param is overkill; instead the Transform already carries
   `method="phase"`; ensure `integrate`'s existing registration summary
   line (it already logs star-solved vs phase-only counts) still prints —
   nothing to change there IF that logging exists (verify by reading
   ~180-190 of integrate.py); if the GUI path never surfaces it, leave for
   the log panel which receives `integrate`'s `log` callback. So: register
   needs NO change if the count line exists — confirm and move on.
4. `grade/stars.py`: at module import, nothing; instead in `detect_stars`,
   when `_HAVE_SEP` is False, emit a one-time
   `warnings.warn("sep not installed — falling back to lower-quality scipy
   star detection", RuntimeWarning, stacklevel=2)` guarded by a module
   flag.

**Verify**: run
`.venv/bin/umbra demo-data /tmp/dd2 --frames 6 && .venv/bin/umbra auto /tmp/dd2/DWARF_RAW_* -o /tmp/dd2/out`
→ per-step log lines appear in stdout.

### Step 4: `ensure_ops_loaded`

In `core/ops.py`:

```python
def ensure_ops_loaded() -> None:
    """Populate the registry (idempotent). Ops self-register when
    umbra_noctis.process is imported."""
    if not OPS:
        import umbra_noctis.process  # noqa: F401
```

Call it at the top of `apply_op` and `ops_markdown`. Then delete the five
`# noqa: F401` side-effect imports (`cli.py` ×3, `gui/pages_process.py:16`,
`guide.py` ops topic) and any other `import umbra_noctis.process` whose
only purpose was registration — EXCEPT `umbra_noctis/process/__init__.py`
itself. Add one to `recipes/auto.py`? No — `apply_op` now self-heals.

**Verify**: `.venv/bin/python -c "from umbra_noctis.recipes.auto import AUTO_RECIPE_STEPS; from umbra_noctis.core.ops import apply_op, OPS, ensure_ops_loaded; ensure_ops_loaded(); print(len(OPS))"` → `27`. Full suite passes.

### Step 5: `core/stats.py` — one robust-sigma home

Create `umbra_noctis/core/stats.py`:

```python
"""Robust statistics shared by grading, stacking, calibration, detection."""
import numpy as np

MAD_TO_SIGMA = 1.4826

def median_mad(a, axis=None):
    med = np.nanmedian(a, axis=axis)
    mad = np.nanmedian(np.abs(a - (med if axis is None else np.expand_dims(med, axis))), axis=axis)
    return med, mad

def robust_sigma(a, axis=None, eps=1e-9):
    _, mad = median_mad(a, axis=axis)
    return MAD_TO_SIGMA * mad + eps
```

Move `_robust_z` from `grade/metrics.py` here as `robust_z`. Migrate the 13
scalar/axis call sites listed in Current state to these helpers,
preserving each site's existing epsilon by passing `eps=` explicitly
(`integrate.py` strip loop keeps 1e-5, `meteors.py` keeps 1e-6,
`ops_linear.py:220` keeps 1e-12, others 1e-9; `grade/metrics.py:50` gains
the default 1e-9 — a deliberate, tiny behavior fix). The strip-loop site is
axis-aware — keep its allocation pattern (compute med once, reuse).

**Verify**: full suite passes (numeric outputs unchanged except the
metrics.py epsilon); `grep -rn "1.4826" umbra_noctis/ --include="*.py" | grep -v core/stats.py` → 0 matches.

### Step 6: One luminance + one superpixel binning

In `core/stats.py` (or a new `core/pixels.py` if you prefer — pick one and
say so in the commit) add `luminance(data)` (Rec.709, handles 2-D
passthrough) and `superpixel_bin(lum)` (the 2×2 reshape-mean). Then:

- `AstroImage.luminance()` delegates.
- `grade/stars.py:_luminance` → delete, import shared.
- `stack/register.py:_lum` → keep the function (it composes
  luminance+binning for CFA) but implement via the shared helpers.
- `detect/meteors.py:_luminance_small` → same.
- `process/display.py:16` → use Rec.709 luminance. NOTE: this visibly
  (slightly) changes autostretch of color images — intended, document in
  the commit message.

**Verify**: full suite passes. If any display/export test asserts exact
pixel values for COLOR images, adjust the expected values in the same
commit with a comment (mono is unaffected).

### Step 7: FITS round-trip fidelity + grid guards + discovery walk

1. `core/image.py` `save_fits`: write `header["UMBLIN"] = bool(self.linear)`.
   `from_fits`: `linear=bool(header.get("UMBLIN", True))`.
2. `background_extract` and `synthetic_flat`: clamp the grid —
   `samples = min(samples, h, w)` / `ny, nx = max(1, min(...)), ...` and
   skip zero-area boxes; guard: if fewer than 6 samples collected, return
   the input unchanged with a history note instead of a NaN model.
3. `ingest/session.py` `discover_sessions`: single `os.walk` pass that
   collects `shotsInfo.json` dirs, `DWARF_*` dirs, and per-directory FITS
   counts in one traversal (dict keyed by dirpath), preserving the current
   ordering semantics (sorted output).

**Verify**: new tests: `test_linear_flag_roundtrip` (save stretched →
reload → `linear is False`); `test_background_extract_tiny_image` (16×16
input returns finite, unchanged-or-sane output, no NaN); existing
discovery tests in `tests/test_ingest_library.py` still pass.

### Step 8: Workers unit tests

Create `tests/test_gui_workers.py` (`pytest.importorskip("PySide6")`, set
`QT_QPA_PLATFORM=offscreen` like the smoke test, create/reuse a
QApplication). Call `FnWorker.run()` SYNCHRONOUSLY (not `.start()`):

- success path emits `finished` with the fn's return value;
- fn taking `progress` gets a callable; both 2-arg and 3-arg progress
  signatures are adapted;
- an fn that raises → `failed` emits a string containing the exception
  message; no exception escapes `run()`.

**Verify**: `.venv/bin/python -m pytest -q tests/test_gui_workers.py` → ≥3
tests pass.

## Test plan

Summarized in steps: gui nav-guard test, workers tests (×3+),
`test_linear_flag_roundtrip`, `test_background_extract_tiny_image`,
stats/luminance covered by the unchanged full suite. Model GUI tests on
`tests/test_gui_smoke.py`.

## Done criteria

- [ ] `.venv/bin/python -m pytest -q` exits 0; `tests/test_gui_workers.py` exists
- [ ] `grep -rn "1.4826" umbra_noctis --include="*.py" | grep -v stats` → 0 matches
- [ ] `grep -n "index != 3" umbra_noctis/gui/app.py` → 0 matches
- [ ] `grep -n "ensure_ops_loaded" umbra_noctis/core/ops.py` → ≥2 matches; `grep -rn "noqa: F401" umbra_noctis/cli.py` → 0 matches
- [ ] `grep -n "UMBLIN" umbra_noctis/core/image.py` → 2 matches
- [ ] `grep -n "glob(\"\*.fits\")" umbra_noctis/ingest/session.py` → 0 matches (single-walk version)
- [ ] `.venv/bin/python -m ruff check .` exits 0
- [ ] No files outside Scope modified

## STOP conditions

- Any excerpt mismatch beyond plans 001–005's documented touches.
- Step 5/6 migration changes any test's numeric outcome beyond the two
  documented deliberate changes (metrics epsilon, display luminance) —
  report the exact test and delta.
- The Qt worker changes make the smoke test hang (>60s) — report, don't
  add waits.
- `integrate.py`'s registration-summary log line (Step 3.3) doesn't exist —
  report instead of inventing new logging.

## Maintenance notes

- `core/stats.py` is now the only legal home for robust statistics — CI
  could later grep-guard `1.4826`.
- The display luminance change slightly alters every color autostretch
  preview/JPEG; release notes should mention it.
- Reviewer: read the worker diff against Qt object-lifetime rules
  (deleteLater on finished; no reference drop while running), and check the
  two-arg/three-arg progress adaptation still matches all call sites
  (`grep -n "progress" umbra_noctis/gui/pages_*.py`).
