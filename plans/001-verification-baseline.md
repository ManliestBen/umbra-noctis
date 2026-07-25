# Plan 001: Establish CI, working lint, honest tests, and bounded dependencies

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- pyproject.toml tests/ umbra_noctis/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

Nothing runs this repo's test suite except a human remembering to; ruff is
configured in `pyproject.toml` but not even installed, so the lint gate is
decorative; two test assertions end in `or True` and can never fail; and the
dependency floors (`numpy>=1.26` with numpy 2.5 installed, `opencv>=4.9`
with OpenCV 5 installed) advertise a compatibility range no one has ever
tested, with no upper bounds to stop the next breaking major. This plan is
the prerequisite for every other plan: it creates the one-command
verification gate the rest will be judged against.

## Current state

- `pyproject.toml` — deps at lines 10–18: `numpy>=1.26`, `scipy>=1.11`,
  `astropy>=6.0`, `astroalign>=2.5`, `opencv-python-headless>=4.9`,
  `pillow>=10.0`, `tifffile>=2024.1.30`. No upper bounds. `sep` is NOT
  listed even though `umbra_noctis/grade/stars.py:14` does `import sep as
  _sep` (it arrives transitively via astroalign today). Extras: `gui`
  (PySide6), `dslr` (rawpy), `dev` (pytest, ruff). `[tool.ruff]` sets only
  `line-length = 100` and `target-version = "py311"` — no `[tool.ruff.lint]`
  select, so only defaults would apply.
- There is no `.github/` directory — no CI of any kind.
- `tests/test_process_export.py:162-164`:
  ```python
  assert any("Master dark" in line for line in
             []) or True  # log lines checked implicitly via calibration history
  assert any(h["op"] == "subtract_dark" for h in img.history) or True
  ```
  Both assertions are tautologies. The surrounding test
  `test_auto_process_end_to_end` is marked `@pytest.mark.slow` (line ~150).
- `tests/test_ingest_library.py:72`: `assert not new2 or sid2 == sid` — only
  half-checks the dedup contract.
- `tests/test_grade_calib_stack.py:78-84`: `test_build_master_sigma_clip`
  uses `tempfile.mkdtemp()` with function-local `import tempfile` /
  `from astropy.io import fits as _fits` instead of the `tmp_path` fixture
  every other test uses; leaks a temp dir per run.
  `tests/test_grade_calib_stack.py:41-42`: `src` is assigned twice back to
  back; line 41 is dead.
- Known dead imports ruff's F rules will flag: `umbra_noctis/stack/register.py:26`
  (`detect_stars` unused), `umbra_noctis/process/ops_detail.py:8` (`ndimage`
  unused), `umbra_noctis/gui/app.py` (`Qt` unused). NOTE:
  `umbra_noctis/stack/integrate.py:138` has an unused
  `from ..grade.metrics import grade_session` — DELETE it here; plan 004
  re-introduces a (used) import later. There are also five intentional
  `# noqa: F401` imports of `umbra_noctis.process` (registry side-effect) —
  keep those.
- Repo conventions: 4-space indent, line length 100, docstring-first modules,
  `np` for numpy. Match them.

## Commands you will need

The worktree has no `.venv` (it's gitignored). Create one first:

| Purpose | Command | Expected on success |
|---|---|---|
| Env | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Tests (full) | `.venv/bin/python -m pytest -q` | all pass (43 today) |
| Tests (fast) | `.venv/bin/python -m pytest -q -m "not slow"` | all pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 after this plan |

## Scope

**In scope** (the only files you should modify/create):
- `.github/workflows/ci.yml` (create)
- `pyproject.toml`
- `tests/test_process_export.py`, `tests/test_ingest_library.py`,
  `tests/test_grade_calib_stack.py`
- Mechanical lint fixes across `umbra_noctis/**/*.py` and `tests/**/*.py`
  (unused imports/variables, import sorting, modernizations ruff `--fix`
  makes) — no logic changes.

**Out of scope** (do NOT touch):
- Any behavioral change to `umbra_noctis/` beyond deleting provably-unused
  imports/variables. The dead sort at `stack/integrate.py:166` looks dead but
  is entangled with plan 004 — leave it.
- `docs/` (plan 002), `plans/` other than the index row.

## Git workflow

- Branch: work on the current worktree branch as dispatched.
- Commit per step; message style: short imperative summary line, blank line,
  body if needed (matches `git log`: e.g. "Meteor quick-scan, built-in guide,
  and nightscape editing features").

## Steps

### Step 1: Create the venv and record the baseline

Run the env command from the table, then the full test suite.

**Verify**: `.venv/bin/python -m pytest -q` → `43 passed` (41 fast + 2 slow).
If the slow tests fail, STOP (they have possibly never run — that's a report,
not something to patch around).

### Step 2: Fix the dishonest and leaky tests

1. In `tests/test_process_export.py` delete the tautological pair and replace
   with a real assertion:
   ```python
   assert any(h["op"] == "subtract_dark" for h in img.history), \
       "auto pipeline should have found and subtracted the darks next door"
   ```
   (Delete the `assert any("Master dark" ...) or True` line entirely.)
2. In `tests/test_ingest_library.py:72` replace with
   `assert (new2, sid2) == (False, sid)`.
3. In `tests/test_grade_calib_stack.py`: change
   `test_build_master_sigma_clip` to take `tmp_path` and write via
   `tmp_path / f"d{i}.fits"`; remove the function-local `tempfile`/`_fits`
   imports (use the module-level `fits` import if one exists, else add it at
   top); delete the dead first `src = ...` assignment at line 41.

**Verify**: `.venv/bin/python -m pytest -q` → all pass. If the new
`subtract_dark` assertion FAILS, this is a real shipped bug in dark
auto-matching — STOP and report exactly which assertion failed and what
`[h["op"] for h in img.history]` contains.

### Step 3: Enable ruff properly and fix everything it finds

1. In `pyproject.toml` add:
   ```toml
   [tool.ruff.lint]
   select = ["E", "F", "I", "UP", "B"]
   ```
2. Run `.venv/bin/python -m ruff check . --fix`, then fix remaining
   violations by hand. Expected specific fixes: the dead imports listed in
   Current state (including `integrate.py:138`'s unused `grade_session`
   import and the shadowing `import numpy as _np` at `integrate.py:140` —
   replace `_np` usages in that function with the module-level `np`).
   Keep the five `# noqa: F401` registry imports.
3. Do NOT change logic to satisfy `B` warnings — if a `B` finding requires a
   behavioral fix (e.g. mutable default), fix it only if provably equivalent;
   otherwise add a targeted `# noqa` with a one-line reason.

**Verify**: `.venv/bin/python -m ruff check .` → `All checks passed!` and
`.venv/bin/python -m pytest -q` → all pass.

### Step 4: Bound the dependencies and declare `sep`

In `pyproject.toml` change the dependency list to:

```toml
dependencies = [
    "numpy>=1.26,<3",
    "scipy>=1.11,<2",
    "astropy>=6.0,<9",
    "astroalign>=2.5,<3",
    "sep>=1.2,<2",
    "opencv-python-headless>=4.9,<6",
    "pillow>=10.0,<13",
    "tifffile>=2024.1.30",
]
```

Add one test in `tests/test_grade_calib_stack.py`:

```python
def test_sep_backend_available():
    from umbra_noctis.grade import stars
    assert stars._HAVE_SEP, "sep must be installed — star detection quality depends on it"
```

**Verify**: `.venv/bin/pip install -e ".[dev]"` → exit 0 (resolves under the
new bounds); `.venv/bin/python -m pytest -q` → all pass.

### Step 5: Add the CI workflow

Create `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push: {branches: [main]}
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "${{ matrix.python-version }}"}
      - name: System libs for headless Qt
        run: sudo apt-get update && sudo apt-get install -y libegl1 libxkbcommon-x11-0 libglib2.0-0
      - name: Install
        run: pip install -e ".[dev,gui]"
      - name: Lint
        run: ruff check .
      - name: Tests (full suite, slow included)
        run: pytest -q
```

(The gui extra is installed so `tests/test_gui_smoke.py` actually runs —
it sets `QT_QPA_PLATFORM=offscreen` itself. The `dslr` extra is deliberately
NOT installed so the rawpy ImportError path in `tests/test_trails.py` stays
exercised.)

**Verify**: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`
→ no output, exit 0 (if pyyaml is unavailable, `.venv/bin/pip install pyyaml`
first). Also `.venv/bin/python -m pytest -q` one final time → all pass.

## Test plan

- Modified assertions in `test_process_export.py`, `test_ingest_library.py`
  (they now genuinely gate dark-matching and dedup).
- New `test_sep_backend_available`.
- No new test files; CI is verified by YAML parse locally (it can only truly
  run on GitHub).

## Done criteria

- [ ] `.venv/bin/python -m ruff check .` exits 0
- [ ] `.venv/bin/python -m pytest -q` exits 0, ≥44 tests
- [ ] `grep -rn "or True" tests/` returns no matches
- [ ] `grep -n "sep>=" pyproject.toml` returns one match
- [ ] `.github/workflows/ci.yml` exists and parses as YAML
- [ ] `git status` shows no modified files outside the Scope list

## STOP conditions

- The Step 1 baseline run fails (slow tests may never have been run).
- The Step 2 `subtract_dark` assertion fails — real bug, report it.
- Ruff `--fix` produces a diff in more than ~60 files (unexpected churn scale).
- Dependency resolution under the new bounds fails.

## Maintenance notes

- Plan 004 will re-import `grade_session` (or a new `score_qualities`) into
  `integrate.py` — the deletion here is not a verdict on the design.
- If a future contributor adds the `dslr` extra to CI, keep one job without
  it so the ImportError message stays tested.
- Reviewer: check the ruff commit contains no logic changes — it should be
  imports, whitespace, and modernization only.
