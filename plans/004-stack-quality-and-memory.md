# Plan 004: Make quality scoring real and remove the pipeline's memory ceilings

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update your row in
> `plans/README.md` unless the reviewer maintains the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- umbra_noctis/stack/integrate.py umbra_noctis/grade/metrics.py umbra_noctis/calib/masters.py umbra_noctis/planetary/lucky.py umbra_noctis/stack/register.py umbra_noctis/gui/pages_process.py umbra_noctis/cli.py`
> Plan 001 will already have removed two dead imports from `integrate.py` —
> that exact change is expected, not drift. Anything else: compare excerpts,
> STOP on mismatch.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/001-verification-baseline.md
- **Category**: bug + perf
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

Two independent problems share these files. (1) **Three advertised stacking
features are silently inert**: `integrate()` fills `FrameQuality` via
`grade_frame`, which never sets `score` (only `grade_session`'s
rank-composite does), so quality *weighting* multiplies by all-ones, the
*best-fraction* cut actually ranks by raw star count, and *reference-frame
selection* always picks index 0 instead of the sharpest frame. (2) **The
pipeline cannot run its stated workload**: `integrate` holds every decoded
frame in RAM (300 Dwarf frames ≈ 30 GB) before its disk-backed reduction
even starts, its memmap goes to `/tmp` (usually tmpfs = RAM) with no
free-space check and leaks on failure; `build_master` np.stacks all
calibration frames (~5× cube peak); `lucky_stack` buffers up to 2000
decoded video frames (~50 GB at 1080p) and leaks the capture handle on
error.

## Current state

- `umbra_noctis/grade/metrics.py`:
  - `FrameQuality.score: float = 0.0` (dataclass, ~line 35).
  - `grade_frame(...)` (~lines 46-63) returns a FrameQuality WITHOUT score.
  - `grade_session(...)` (~lines 84-130) loads frames, calls `grade_frame`,
    then computes the rank-composite score in its tail (~lines 118-129):
    ```python
    score = (0.35 * pct_rank(n_stars)
             + 0.30 * pct_rank(fwhm, invert=True)
             + 0.20 * pct_rank(ecc, invert=True)
             + 0.15 * pct_rank(bg, invert=True))
    for q, s in zip(results, score):
        q.score = round(float(s) * 100, 1)
    ```
- `umbra_noctis/stack/integrate.py` (all line refs to commit 07ab720):
  - ~119-133: the calibrate loop appends every calibrated+demosaiced frame
    to `frames: list[AstroImage]` and grades each with `grade_frame`.
  - ~150-169: inline session-relative rejection (clouds/soft/bright sky) —
    duplicates `grade_session` logic; then:
    ```python
    kept_idx.sort(key=lambda i: -(qualities[i].score or 0))   # all zeros — dead
    ranked = sorted(kept_idx, key=lambda i: -(qualities[i].n_stars))
    n_keep = max(3, int(round(len(ranked) * best_fraction)))
    ```
  - ~179: `ref_local = pick_reference(used_q)` — `pick_reference`
    (`stack/register.py`, tail) maxes over `score`, all zeros → index 0.
  - ~199-203: `weights` from `max(q.score, 1.0)` → all ones.
  - ~206-216: `tempfile.TemporaryDirectory(prefix="umbra_stack_")` (no
    `dir=`), `np.memmap(... mode="w+", shape=(n, out_h, out_w[, 3]))`, warp
    loop fills `cube[i]` from the RESIDENT `used` list.
  - ~222-246: strip reduction (`strip_rows=128` fixed), success-path-only
    `del cube; tmpdir.cleanup()`.
- `umbra_noctis/calib/masters.py` `build_master` (~lines 22-56): appends
  every `AstroImage.from_file(p).data` to a list, `np.stack`, then
  median/mean/sigma-clip on the whole cube. Sigma-clip branch (~46-51):
  `master = (cube * weights).sum(0) / np.maximum(weights.sum(0), 1.0)` —
  a pixel where ALL samples are rejected becomes 0, not the median.
  No shape validation across frames (np.stack raises a bare numpy error).
- `umbra_noctis/planetary/lucky.py` `lucky_stack` (~lines 33-105): single
  pass appends every decoded RGB float32 frame to `frames` (cap
  `max_frames=2000`), `cap.release()` only after a clean loop; selection
  keeps `keep_fraction`; alignment re-derives gray via `f.mean(axis=2)`.
- `umbra_noctis/gui/pages_process.py` `StackPage.run_stack` (~118-133):
  calls `integrate(..., quality_filter=False)` after the Grade page already
  graded — `integrate` re-grades every frame anyway.
- `umbra_noctis/cli.py` `cmd_stack` (~112-148) calls `integrate(...)`;
  output path is `args.output`.
- Ground-truth test exemplars: `tests/test_grade_calib_stack.py` (esp. the
  slow `test_end_to_end_integration_improves_snr`), synthetic sessions via
  `umbra_noctis/synth.py:write_demo_session`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Env (if missing) | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Full tests | `.venv/bin/python -m pytest -q` | all pass |
| Focused | `.venv/bin/python -m pytest -q tests/test_grade_calib_stack.py` | all pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 |

## Scope

**In scope**: `umbra_noctis/stack/integrate.py`,
`umbra_noctis/grade/metrics.py`, `umbra_noctis/stack/register.py`
(pick_reference only), `umbra_noctis/calib/masters.py`,
`umbra_noctis/planetary/lucky.py`, `umbra_noctis/gui/pages_process.py`
(the `run_stack` call only), `umbra_noctis/cli.py` (`cmd_stack` work-dir
wiring only), `tests/test_grade_calib_stack.py`, `tests/test_planetary.py`
(create).

**Out of scope**: `stack/trails.py`, `detect/`, multiprocessing (deferred),
`stack/register.py` beyond `pick_reference`, any change to the strip
rejection *math* (winsorized sigma-clip stays byte-identical in intent).

## Git workflow

Branch as dispatched; one commit per step.

## Steps

### Step 1: Extract `score_qualities` and use it in `integrate`

1. In `grade/metrics.py`, extract the score-computation tail of
   `grade_session` into a module-level `score_qualities(results:
   list[FrameQuality]) -> list[FrameQuality]` (the `pct_rank` composite,
   verbatim). `grade_session` calls it.
2. In `integrate.py`, after the grading loop completes, call
   `score_qualities(qualities)`.
3. Delete the dead first sort (`kept_idx.sort(key=... score ...)`) and
   change the real ranking to score: `ranked = sorted(kept_idx, key=lambda
   i: -(qualities[i].score))`.

**Verify**: new test `test_integrate_scores_frames` passes; full suite
passes (the slow SNR test guards against regression — it MUST still pass).

### Step 2: Let callers supply qualities (skip double grading)

Add parameter `qualities: list | None = None` to `integrate`. When given
(must be same length/order as `light_paths`), skip `grade_frame` in the
load loop and use the provided list. In `gui/pages_process.py`
`run_stack`, pass the Grade page's stored qualities
(`self.state.qualities` — confirm the attribute name by reading
`gui/state.py`; STOP if no such state exists).

**Verify**: `.venv/bin/python -m pytest -q` all pass;
`grep -n "qualities=" umbra_noctis/gui/pages_process.py` → 1 match.

### Step 3: Two-pass integrate (drop the resident frame list)

Restructure `integrate`:

- **Pass 1** (metrics): for each path — load, calibrate (dark/flat/
  cosmetic/demosaic), `grade_frame` (unless `qualities` supplied), record
  only the FrameQuality; discard pixels. Score + quality-filter + pick
  reference exactly as now (the reference's *luminance stats* needed for
  normalization can be captured during pass 2's first read of the
  reference, or by reloading the reference frame once — either is fine;
  document the choice in a comment).
- **Pass 2** (integration): for each KEPT path — reload, calibrate
  identically, solve transform against the reference frame's luminance,
  warp, write `cube[i]`, release. `register_frames` currently takes a list
  of images; either keep using `solve_transform` per frame here or load
  pairs — the requirement is: at no point may more than 3 full frames be
  resident.
- Calibration must be identical in both passes — extract a
  `_load_calibrated(path) -> AstroImage` closure used by both.

**Verify**: full suite passes INCLUDING the slow SNR + rejection tests
(they are the golden regression); new test
`test_integrate_peak_frames_resident` is impractical — instead assert
correctness only, and add `test_integrate_two_pass_matches_reference` per
the Test plan.

### Step 4: Memmap location, free-space check, failure-path cleanup

1. Add `work_dir: str | Path | None = None` to `integrate`. Use
   `tempfile.TemporaryDirectory(prefix="umbra_stack_", dir=work_dir)`.
2. Before creating the memmap, compute its byte size; if
   `shutil.disk_usage(resolved_dir).free < size * 1.1`, raise
   `RuntimeError` naming the size, the directory, and the `work_dir`
   parameter as the remedy.
3. Wrap memmap use so cleanup happens on ALL paths:
   `with tempfile.TemporaryDirectory(...) as tmp:` and a `try/finally`
   that `del cube` before the context exits.
4. In `cli.py` `cmd_stack`, pass `work_dir=Path(args.output).parent`.

**Verify**: new test `test_integrate_cleans_tmp_on_failure` passes.

### Step 5: Stream `build_master`, fix its edge cases

1. Validate every frame's shape against the first; on mismatch raise
   `ValueError` naming both the offending path and both shapes.
2. `method="mean"`: running float64 accumulator, no cube at all.
3. `median` / `sigma_clip`: write frames into a `np.memmap` cube in a
   `TemporaryDirectory` (same pattern as integrate), reduce in row strips
   (reuse a small helper or inline; strips of ~64 rows are fine).
4. Sigma-clip all-rejected fallback: `np.where(wsum > 0, weighted_mean,
   med)` instead of the `np.maximum(..., 1.0)` divide.

**Verify**: existing `test_build_master_sigma_clip` passes unchanged (the
numerics for median/mean must be identical; sigma-clip differs only at
all-rejected pixels); new `test_build_master_mixed_shapes_raises` and
`test_build_master_all_rejected_pixel_falls_back_to_median` pass.

### Step 6: Two-pass `lucky_stack` + handle safety

1. Pass 1: read frames, compute gray + Laplacian-variance score, keep ONLY
   scores (and the running frame count). `try/finally` around the loop
   guaranteeing `cap.release()`.
2. Select `n_keep` indices as now.
3. Pass 2: re-open the capture, decode sequentially, process only chosen
   indices: convert to RGB float32, align by phase correlation against the
   best frame's gray (compute the reference gray when its index streams
   by — the best-scoring frame is by definition in the chosen set; buffer
   the reference frame first by doing pass 2 in two sub-reads OR simply
   buffer only frames in the chosen set as they stream and process at the
   end — chosen set is ≤ keep_fraction × total; with the default 0.25 and
   max_frames 2000 that can still be large, so cap resident chosen frames:
   accumulate into the running sum immediately, using the FIRST chosen
   frame encountered as alignment reference instead of the global best.
   Document this reference change in the docstring).
4. Log (via a `log` callback param defaulting to None, or the existing
   `progress`) when `max_frames` truncates the video.
5. Use ONE grayscale formula everywhere (`cv2.cvtColor` BGR2GRAY in pass 1;
   reuse for alignment) — remove the `f.mean(axis=2)` re-derivation.

**Verify**: new `tests/test_planetary.py` passes (see Test plan); full
suite passes.

## Test plan

Extend `tests/test_grade_calib_stack.py` (follow its `_img` helper style):

1. `test_integrate_scores_frames` — run `integrate` on a demo session
   (`write_demo_session(tmp_path, n_lights=8)`), assert
   `result.qualities` has at least one `score > 0` and that scores are not
   all equal.
2. `test_reference_is_not_blindly_first` — build a session where frame 0 is
   the ruined/cloudy one (write_demo_session ruins the middle frame — so
   instead: assert `result.reference_index` equals the index of the
   highest-score kept frame).
3. `test_integrate_two_pass_matches_reference` — stack the same 6-frame
   demo session and compare against the pre-change output? Not available —
   instead assert structural invariants: output shape equals input frame
   shape, output is finite, and the slow SNR test (already existing) still
   passes. The SNR + satellite-rejection slow tests are the real gate.
4. `test_integrate_cleans_tmp_on_failure` — monkeypatch
   `umbra_noctis.stack.register.solve_transform` to raise on the 2nd frame;
   call `integrate` with `work_dir=tmp_path`; assert it raises AND
   `list(tmp_path.glob("umbra_stack_*"))` is empty afterward.
5. `test_build_master_mixed_shapes_raises` — two FITS of different shapes →
   `ValueError` whose message contains the second filename.
6. `test_build_master_all_rejected_pixel_falls_back_to_median` — construct
   8 frames constant 0.1 with one pixel alternating 0.0/1.0 extremes such
   that sigma-clip rejects all samples at that pixel; assert the master
   pixel ≈ median, not 0. (If constructing full rejection is fiddly, drive
   the helper directly with a tiny cube via the same code path.)

Create `tests/test_planetary.py`:

7. `test_lucky_stack_picks_sharp_frames(tmp_path)` — write a 20-frame
   200×200 video with `cv2.VideoWriter` (mp4v): 15 blurred frames
   (`cv2.GaussianBlur(base, (15,15), 0)`) and 5 sharp frames of the same
   scene; `lucky_stack(path, keep_fraction=0.25)` → `n_frames_used == 5`
   and the result is sharper (Laplacian variance) than the blurred input.
8. `test_lucky_stack_truncation_and_release(tmp_path)` — call with
   `max_frames=10` on the 20-frame video; assert `n_frames_total == 10`
   (and no exception).

**Verification**: `.venv/bin/python -m pytest -q` → all pass, ≥8 new.

## Done criteria

- [ ] `.venv/bin/python -m pytest -q` exits 0 (slow SNR/rejection tests included)
- [ ] `grep -n "def score_qualities" umbra_noctis/grade/metrics.py` → 1 match
- [ ] `grep -n "frames.append" umbra_noctis/stack/integrate.py` → 0 matches (no resident frame list)
- [ ] `grep -n "disk_usage" umbra_noctis/stack/integrate.py` → ≥1 match
- [ ] `grep -n "np.stack" umbra_noctis/calib/masters.py` → 0 matches
- [ ] `tests/test_planetary.py` exists with ≥2 passing tests
- [ ] `.venv/bin/python -m ruff check .` exits 0
- [ ] No files outside Scope modified

## STOP conditions

- The slow `test_end_to_end_integration_improves_snr` or the satellite
  rejection assertion fails after Step 1 or Step 3 — the numerics changed;
  report the before/after values, do not tune thresholds to pass.
- `gui/state.py` has no stored qualities for Step 2.
- Step 3's restructure makes any registration test fail
  (`test_registration_recovers_known_transform` etc.).
- Video tests can't run because `cv2.VideoWriter` produces unreadable files
  in this environment — report codec details, don't ship untested code.

## Maintenance notes

- Turning on real scores CHANGES stack output vs. previous releases (better
  reference, real weighting). Release notes should say so.
- Future parallelization (deferred PERF-04) should slot into pass 1/pass 2
  boundaries — keep `_load_calibrated` pure.
- Reviewer: scrutinize that pass-1 and pass-2 calibration cannot diverge
  (single shared closure) and that the memmap `finally` covers the warp
  loop, not just the reduction.
