# Umbra Noctis — notes for Claude

Post-processing suite for DwarfLab Dwarf 3 (and DSLR) astro sessions. See
`README.md` for what it does, `FEATURES.md` for the feature catalog, and
`docs/USER_GUIDE.md` for user-facing behavior.

## Commands

- `make check` — canonical gate: ruff lint + full pytest (what CI runs).
- `.venv/bin/python -m pytest -q -m "not slow"` — fast loop while iterating;
  skips the end-to-end tests.
- `.venv/bin/python -m ruff check .` — lint only.
- `.venv/bin/umbra <cmd>` — run the CLI itself (e.g. `umbra demo-data ./demo`,
  `umbra auto ./demo/DWARF_RAW_* -o ./demo/out`) to exercise a change for real.

## Architecture map

One line per package, roughly in pipeline order:

- `ingest` — parses Dwarf 3 session folders / `shotsInfo.json` into frame lists.
- `grade` — per-frame quality metrics (FWHM, eccentricity, star count, SNR).
- `calib` — master dark/flat building, hot-pixel maps, cosmetic correction.
- `stack` — `register` (astroalign), `integrate` (rejection + combine),
  `trails` (lighten-blend star trails, a separate non-registering path).
- `process` — the op registry and implementations, split across `ops_*.py`
  (linear, stretch, color, geometry, detail).
- `detect` — meteor/satellite streak scanning.
- `solve` — plate solving (ASTAP / astrometry.net / nova web API) + annotation.
- `planetary` — lucky-imaging stacks from video captures.
- `recipes` — orchestration: replayable op chains, the `auto` one-click pipeline.
- `library` — SQLite catalog of imported sessions, at `~/.umbra-noctis` by
  default (override via `UMBRA_HOME`).
- `core` — `AstroImage` and the op registry (`OPS`, `register_op`, `apply_op`).
- `cli.py` and `gui/` are two thin front ends over the same core engine —
  neither has logic the other doesn't call into.

## Invariants

- `AstroImage.data` is always `float32` in `[0, 1]` (linear or stretched,
  tracked by `AstroImage.linear`).
- Every op is a pure `f(AstroImage, **params) -> AstroImage`; no in-place
  mutation, no hidden state.
- Every op application appends an entry to `AstroImage.history` — recipe
  replay (`Recipe.from_history`) and reproducibility sidecars depend on this
  being complete and accurate. Don't add an op that skips it.
- Ops self-register via `@register_op` as a side effect of importing
  `umbra_noctis.process`. The `# noqa: F401` imports of that module scattered
  through `cli.py`, `guide.py`, and `gui/pages_process.py` are load-bearing —
  removing them silently empties the registry, it isn't dead code.
- Any GUI work heavier than a UI update goes through `gui/workers.FnWorker`,
  never the Qt UI thread directly.
- Raw user session files are never modified — everything reads from them and
  writes to new output paths.

## Testing conventions

- Ground truth is synthetic, built with `umbra_noctis.synth` (in particular
  `write_demo_session` and `make_star_field`), not real telescope data.
- RNG is always seeded (`np.random.default_rng(<int>)`) — no unseeded
  randomness in tests.
- Use pytest's `tmp_path` fixture for any file I/O; don't leak temp
  directories with `tempfile.mkdtemp()`.
- No network access in tests.
