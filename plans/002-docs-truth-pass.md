# Plan 002: Make every doc surface tell the truth (and add CLAUDE.md)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- docs/ README.md FEATURES.md IMPLEMENTATION_PLAN.md umbra_noctis/guide.py umbra_noctis/process/ops_detail.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/001-verification-baseline.md (needs the venv; run its env step if absent)
- **Category**: docs
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

Three doc surfaces actively lie: the `star_reduce` docstring tells users to
run a CLI command (`umbra integrate-tool`) that does not exist — and that
text is emitted by `umbra ops --markdown` AND `umbra guide ops` AND
`docs/OPERATIONS.md`; the built-in FAQ claims "every command takes `--db`"
when only two do; and `docs/OPERATIONS.md`/`USER_GUIDE.md`/`FEATURES.md`
claim "25 ops" while the registry holds 27 (the two missing — `defringe`,
`vignette_correct` — are exactly the DSLR-workflow ops). Meanwhile the
README's install steps describe an environment that doesn't match reality
(no dev extra, no test instructions), there is no CLAUDE.md for the agents
that regularly work this repo, and IMPLEMENTATION_PLAN.md still tells
readers to "scaffold the repo" as its next step.

## Current state

- `umbra_noctis/process/ops_detail.py:44` (inside `star_reduce` docstring):
  `For full removal, use an external StarNet++/GraXpert via `umbra
  integrate-tool` (see docs).` — no such command exists (see
  `umbra_noctis/cli.py` subparsers).
- `umbra_noctis/guide.py:186-187` (in `_FAQ`): says `~/.umbra-noctis` by
  default and "every command takes `--db`". Only `umbra import` and
  `umbra library` define `--db` (`cli.py`, search `"--db"`).
- `docs/OPERATIONS.md` — hand-committed copy of the op reference; 25 op
  headings, missing `defringe` and `vignette_correct`. The live generator is
  `umbra ops --markdown` (implemented by `ops_markdown()` in
  `umbra_noctis/core/ops.py:106`).
- `docs/USER_GUIDE.md` — line ~164 claims "All 25 operations live in one
  registry"; its stage-by-stage list omits the two new ops; the guide has NO
  section for `umbra trails`, `umbra meteor-scan`, or `umbra guide`.
- `FEATURES.md:5` — "25 processing ops".
- `IMPLEMENTATION_PLAN.md` — line ~13 mandates "Python 3.12+" while
  `pyproject.toml` says `>=3.11`; "Immediate Next Steps" (~line 215) lists
  four long-completed tasks (confirm stack, scaffold repo, collect data,
  build ingest); the architecture diagram (~line 74) shows an `integrate/`
  package that doesn't exist.
- `README.md` — install section (~lines 49-53) says `python -m venv .venv`
  then `pip install -e ".[gui]"`; never mentions the `dev` extra or how to
  run tests; no CLAUDE.md exists in the repo.
- The nightscape prose to reuse for the USER_GUIDE section already exists,
  reviewed, in `umbra_noctis/guide.py` (`_NIGHTSCAPE` block).
- A test already exists asserting the guide mentions every command:
  `tests/test_detect_ops_guide.py::test_guide_covers_every_command_and_new_features`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Env (if missing) | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Regenerate op ref | `.venv/bin/umbra ops --markdown > docs/OPERATIONS.md` | file rewritten |
| Tests | `.venv/bin/python -m pytest -q` | all pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 |

## Scope

**In scope**:
- `umbra_noctis/process/ops_detail.py` (docstring text only)
- `umbra_noctis/guide.py` (text only)
- `docs/OPERATIONS.md`, `docs/USER_GUIDE.md`, `README.md`, `FEATURES.md`,
  `IMPLEMENTATION_PLAN.md`
- `CLAUDE.md` (create), `Makefile` (create)
- `tests/test_detect_ops_guide.py` (extend one test)

**Out of scope**:
- Any code behavior change. Adding a global `--db` flag was considered and
  rejected — fix the text instead.
- `docs/FIELD_CARD.html`, `docs/CLI_REFERENCE.md` (already current),
  `docs/GUI_TOUR.md`/`PROCESSING_TUTORIAL.md` beyond the one-line cross-refs
  in Step 4.

## Git workflow

Branch as dispatched; commit per step, short imperative messages.

## Steps

### Step 1: Fix the lying text

1. `ops_detail.py` `star_reduce` docstring: replace the `umbra
   integrate-tool` sentence with: `For full star removal, export a 16-bit
   TIFF (umbra process ... -o starless-input.tif), run an external
   StarNet++/GraXpert on it, and re-import the result.`
2. `guide.py` `_FAQ`: replace the `--db` sentence with: "`~/.umbra-noctis`
   by default; `umbra import` and `umbra library` take `--db` to use
   another location."
3. `FEATURES.md:5` and `docs/USER_GUIDE.md` (~164): replace the literal
   "25" with "every" / "all" phrasing that cannot drift.

**Verify**: `grep -rn "integrate-tool" umbra_noctis/ docs/` → no matches.
`.venv/bin/python -m pytest -q tests/test_detect_ops_guide.py` → pass.

### Step 2: Regenerate OPERATIONS.md and pin it with a test

1. `.venv/bin/umbra ops --markdown > docs/OPERATIONS.md`
2. Extend `test_guide_covers_every_command_and_new_features` (or add a new
   test beside it) with:
   ```python
   ops_doc = Path("docs/OPERATIONS.md").read_text()
   for name in OPS:
       assert f"`{name}`" in ops_doc, f"docs/OPERATIONS.md is stale: missing {name}"
   ```
   (Use `Path(__file__).parent.parent / "docs" / "OPERATIONS.md"` so it works
   from any cwd.)

**Verify**: `grep -c "^### " docs/OPERATIONS.md` → 27. Tests pass.

### Step 3: Bring USER_GUIDE.md up to date

Add a new numbered section "Star trails, meteors & nightscapes (DSLR)" —
adapt the `_NIGHTSCAPE` text from `umbra_noctis/guide.py` (copy the prose,
adjust headings to the file's existing style) — and a short "The built-in
guide" paragraph mentioning `umbra guide` and Help → Guide. Update the table
of contents. Mention `defringe` and `vignette_correct` in the ops
enumeration where the other cosmetic/linear ops are listed.

**Verify**: `grep -n "meteor-scan" docs/USER_GUIDE.md` → at least one match.

### Step 4: Retire IMPLEMENTATION_PLAN.md's stale claims

1. Fix "Python 3.12+" → "Python 3.11+".
2. Replace the "Immediate Next Steps" list with a two-line note: the plan is
   complete through Phase 5; FEATURES.md (with its "(Shipped as ...)"
   annotations) is the living roadmap.
3. Annotate the architecture diagram's `integrate/` entry as "(planned — not
   yet built)".
4. In `docs/GUI_TOUR.md` and `docs/PROCESSING_TUTORIAL.md`, add one
   cross-reference line each pointing to the USER_GUIDE nightscape section
   (do not restructure these files).

**Verify**: `grep -n "3.12+" IMPLEMENTATION_PLAN.md` → no matches.

### Step 5: README development section + Makefile

1. In README.md, correct the install block to include the dev extra and add
   a "Development" subsection:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev,gui]"     # dev = pytest + ruff; gui = desktop app
   make check                      # lint + full test suite
   ```
2. Create `Makefile`:
   ```makefile
   .PHONY: check lint test
   check: lint test
   lint:
   	.venv/bin/python -m ruff check .
   test:
   	.venv/bin/python -m pytest -q
   ```

**Verify**: `make check` → exits 0.

### Step 6: Create CLAUDE.md

Create `CLAUDE.md` (~60 lines) covering exactly:

1. **Commands**: `make check` (canonical gate); `.venv/bin/python -m pytest
   -q -m "not slow"` (fast inner loop); `.venv/bin/python -m ruff check .`;
   `.venv/bin/umbra <cmd>` for manual runs.
2. **Architecture map**: one line per package — ingest → grade → calib →
   stack (register/integrate/trails) → process (ops_*) → export; detect
   (meteor scan), solve (plate solving), planetary, recipes (orchestration),
   library (sqlite catalog at `~/.umbra-noctis`), core (AstroImage + op
   registry); `cli.py` and `gui/` are two thin front ends over the same core.
3. **Invariants** (each one sentence): `AstroImage.data` is float32 in
   [0, 1]; ops are pure `f(AstroImage, **params) -> AstroImage` and must call
   nothing that mutates input; every op application appends to `history`
   (recipes replay depends on it); ops self-register when
   `umbra_noctis.process` is imported — the `import umbra_noctis.process  #
   noqa: F401` lines are load-bearing; GUI long work must go through
   `gui/workers.FnWorker`, never the UI thread; raw user files are never
   modified.
4. **Testing conventions**: synthetic ground truth via
   `synth.write_demo_session`; seeded RNG only; `tmp_path` always; no
   network in tests.

**Verify**: `test -f CLAUDE.md && wc -l CLAUDE.md` → file exists.

## Test plan

- Extended staleness test in `tests/test_detect_ops_guide.py` (Step 2) —
  model after the existing `test_guide_covers_every_command_and_new_features`.
- Full suite green: `.venv/bin/python -m pytest -q`.

## Done criteria

- [ ] `grep -rn "integrate-tool" umbra_noctis/ docs/` → 0 matches
- [ ] `grep -c "^### " docs/OPERATIONS.md` → 27
- [ ] `grep -rn "every command takes" umbra_noctis/guide.py` → 0 matches
- [ ] `grep -n "meteor-scan" docs/USER_GUIDE.md` → ≥1 match
- [ ] `CLAUDE.md` and `Makefile` exist; `make check` exits 0
- [ ] `.venv/bin/python -m pytest -q` exits 0

## STOP conditions

- `umbra ops --markdown` emits anything other than 27 `###` headings
  (registry drifted — report the actual list).
- The guide-coverage test fails after your text edits (you removed a string
  it requires — reconcile, don't delete the test).

## Maintenance notes

- `docs/OPERATIONS.md` is now pinned by a test; regenerating it is part of
  adding any op. Consider (future) generating it in CI instead.
- CLAUDE.md should stay under ~80 lines; it's a map, not a manual.
