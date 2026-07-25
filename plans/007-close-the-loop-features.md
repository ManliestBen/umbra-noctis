# Plan 007: Close the loop — export sidecars, outputs catalog, ratings, and --flats

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update your row in
> `plans/README.md` unless the reviewer maintains the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- umbra_noctis/cli.py umbra_noctis/export/ umbra_noctis/library/catalog.py umbra_noctis/recipes/auto.py umbra_noctis/guide.py docs/CLI_REFERENCE.md`
> Plans 001–006 touch these files substantially — that is expected. Verify
> the SPECIFIC facts below against the live code (function existence,
> absence of flags) and STOP only if a feature this plan adds already
> exists.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/005-cli-solve-trails-hardening.md (cli.py churn), plans/003-library-and-ingest-integrity.md (catalog changes)
- **Category**: direction
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

Three shipped features are one missing connection away from working, and
the project's stated differentiator depends on them. (1) The README
promises "every step recorded so any result can be reproduced" — true only
for FITS: JPEG/TIFF/PNG exports carry zero provenance, and
`Library.add_output` exists but is called from nowhere, so `umbra library
outputs` is a table that can never have rows. (2) `Library.set_rating` /
`set_notes` exist and ratings already *display* in `umbra library sessions`
(`"*" * rating`) — but no interface can write them. (3) The stacking engine
fully supports flats (`integrate(master_flat=...)`, `apply_flat`) but no
CLI flag exposes them — a user who shot flats cannot use them.

## Current state

(All verified at commit 07ab720; re-verify existence, since earlier plans
rework these files.)

- `umbra_noctis/export/writers.py` — `export_image(img, path, ...)`
  dispatches by suffix; writes no metadata sidecar. `AstroImage` has
  `history_json()` (`core/image.py`) returning the full op history as JSON.
- `umbra_noctis/library/catalog.py` — `add_output(...)` (~line 182) and
  `outputs()` (~line 190s) exist; `set_rating(session_id, rating)` (~173)
  and `set_notes` (~178) exist. `grep -rn "add_output\|set_rating" umbra_noctis/ --include="*.py" | grep -v catalog.py` → only tests.
- `umbra_noctis/cli.py`:
  - `cmd_library` handles `what in ("sessions", "targets", "outputs")`;
    sessions listing prints `"*" * (r["rating"] or 0)`.
  - `cmd_stack` has `--darks` / `--no-darks` but NO `--flats`
    (`grep -n "flats" umbra_noctis/cli.py` → 0 matches).
  - `cmd_auto` / `cmd_process` export via `export_image`.
- `umbra_noctis/stack/integrate.py` — `integrate(..., master_flat=None,
  ...)` applies flats when given.
- `umbra_noctis/calib/masters.py` — `build_master(paths)` builds any master
  (darks/flats/bias); `apply_flat(light, master_flat)` exists.
- `umbra_noctis/recipes/auto.py` — `auto_process` exports 3 formats and
  returns `(img, result, exported)`.
- `umbra_noctis/guide.py` — `_DEEPSKY` documents `umbra stack` options;
  `_FAQ` mentions the library; tests in
  `tests/test_detect_ops_guide.py` assert guide coverage of flags like
  `--fade` — if you add flags, mention them in guide.py so docs stay true
  (the test only checks a fixed list; keeping the guide current is a
  correctness requirement of this plan regardless).
- `docs/CLI_REFERENCE.md` — has a section per command; follow its table
  style when documenting new flags.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Env (if missing) | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Tests | `.venv/bin/python -m pytest -q` | all pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 |

## Scope

**In scope**: `umbra_noctis/export/writers.py`,
`umbra_noctis/library/catalog.py` (only if a column/migration is needed —
see Step 2 note), `umbra_noctis/cli.py`, `umbra_noctis/recipes/auto.py`,
`umbra_noctis/gui/pages_process.py` (ExportPage sidecar+catalog call),
`umbra_noctis/guide.py` (flag documentation), `docs/CLI_REFERENCE.md`,
`tests/test_process_export.py`, `tests/test_ingest_library.py`,
`tests/test_cli.py`.

**Out of scope**: thumbnail browser, multi-session stacking, calibration
master *library* (auto-match store), Siril/GraXpert integration — all
deferred design work, see plans/README.md.

## Git workflow

Branch as dispatched; one commit per step.

## Steps

### Step 1: Provenance sidecars on every non-FITS export

In `export_image`, after a successful non-FITS write, also write
`<output>.umbra.json` next to it:

```python
sidecar = {
    "output": path.name,
    "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "software": "Umbra Noctis",
    "source": str(img.source_path) if img.source_path else None,
    "meta": {k: v for k, v in img.meta.items() if isinstance(v, (str, int, float, bool))},
    "history": img.history,
}
Path(str(path) + ".umbra.json").write_text(json.dumps(sidecar, indent=2, default=str))
```

Add parameter `sidecar: bool = True` so callers can opt out (comparison
images in `save_comparison`, if it calls export_image internally, should
pass False — check and handle).

**Verify**: new `test_export_writes_sidecar` — export a synthetic image to
JPEG, assert the `.umbra.json` exists and `json.loads` yields `history` as
a list containing the ops applied.

### Step 2: Record outputs in the library

1. In `cmd_auto` (cli.py): after `auto_process` returns, if a library DB
   exists at the default path OR `--db` was provided (add `--db` to the
   `auto` subparser, defaulting None → `Library`'s default), import the
   session (`lib.import_session`) and call `lib.add_output(...)` for each
   exported path. READ `add_output`'s actual signature first and match it;
   if it requires fields we don't have, pass sensible values (name =
   file stem, path, created timestamp).
2. Same call from the GUI ExportPage after a successful export, and from
   `cmd_process` ONLY when the input's history/meta identifies a session —
   if there is no clean way to know the session, skip cmd_process and note
   it in the commit message (don't invent a mapping).
3. `umbra library outputs` should now print rows after an `umbra auto` run.

**Verify**: new `test_outputs_recorded_after_auto` — run `auto_process` on
a demo session with a tmp db, assert `lib.outputs()` returns ≥1 row.
(Drive via `cli.main(["auto", ..., "--db", str(dbpath)])` if wiring lives
in cmd_auto.)

### Step 3: Ratings and notes from the CLI

Extend the `library` subcommand:

```
umbra library rate <session-id> <stars 0-5> [--db PATH]
umbra library note <session-id> "text"      [--db PATH]
```

Implement as two new `what` choices or subcommands — match the existing
argparse style (`what` positional with choices). Validate 0–5; print the
updated row line afterward.

**Verify**: new CLI test — import demo session, `library rate <id> 4`,
then `library sessions` output contains `****`.

### Step 4: `umbra stack --flats`

1. Add `--flats DIR` to the `stack` subparser (help: "flat-field session
   folder (t-shirt/panel flats); builds a master flat").
2. In `cmd_stack`, mirror the `--darks` handling: parse the folder,
   `build_master(flat_frames)` (median method is fine for flats — pass
   `method="median"`), demosaic the master if it has `cfa` (same as the
   trails dark handling pattern), pass `master_flat=` to `integrate`.
3. Document in `docs/CLI_REFERENCE.md` (stack options table) and mention
   flats in `guide.py` `_DEEPSKY` step 3.

**Verify**: new `test_stack_with_flats_flag` — build a synthetic session +
a "flats" folder (uniform frames with a radial falloff via the
`synthetic_flat` pattern or simply constant 0.5 frames), run
`cli.main(["stack", session, "-o", out, "--flats", flatdir, "--no-darks"])`,
assert output exists and `integrate` received a flat (assert via history:
the stacked image's history or the printed log mentions the flat — read
what `integrate`/`apply_flat` records and assert on that).

## Test plan

Four new tests as specified per step (sidecar, outputs row, rating
round-trip, flats flag), placed in the files listed in Scope, modeled on
each file's existing tests. Full suite green.

## Done criteria

- [ ] `.venv/bin/python -m pytest -q` exits 0 with the 4 new tests
- [ ] `grep -n "umbra.json" umbra_noctis/export/writers.py` → ≥1 match
- [ ] `grep -rn "add_output" umbra_noctis/cli.py umbra_noctis/gui/` → ≥2 matches
- [ ] `grep -n '"--flats"' umbra_noctis/cli.py` → 1 match
- [ ] `grep -n "flats" umbra_noctis/guide.py` → ≥1 match
- [ ] `docs/CLI_REFERENCE.md` documents `--flats`, `library rate`
- [ ] `.venv/bin/python -m ruff check .` exits 0
- [ ] No files outside Scope modified

## STOP conditions

- `add_output`'s real signature needs data that doesn't exist at the call
  sites (e.g. a mandatory FK we can't supply) — report the signature.
- Adding `--db` to `auto` conflicts with how `Library` resolves its default
  path — report rather than changing `Library`.
- The flats test can't assert flat application because nothing records it —
  in that case ADD a history record in `apply_flat` (it already calls
  `out.record("apply_flat", {})` — verify) and assert on that.

## Maintenance notes

- The sidecar schema (`output/created/software/source/meta/history`) is now
  a public contract — version it (`"sidecar_version": 1` is a cheap
  addition; include it).
- Future: `umbra process --recipe <out>.umbra.json` replay is the natural
  follow-up (recipes are already JSON op lists — the sidecar's `history` is
  nearly one).
- Reviewer: check the sidecar never captures absolute home-directory paths
  beyond `source` (privacy when sharing exports), and that `library rate`
  validates its integer.
