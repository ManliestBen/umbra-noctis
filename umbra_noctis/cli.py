"""``umbra`` — the Umbra Noctis command line.

Every GUI capability is also scriptable here. Quick tour:

    umbra demo-data ./demo              # fake Dwarf 3 data to play with
    umbra info ./demo/DWARF_RAW_*       # what's in a session?
    umbra auto ./demo/DWARF_RAW_* -o out/   # one command: session -> JPEG
    umbra grade ./demo/DWARF_RAW_*      # per-frame quality report
    umbra stack ./demo/DWARF_RAW_* -o stack.fits
    umbra process stack.fits -o done.jpg --op background_extract --op autostretch
    umbra ops                           # list every processing operation
    umbra trails ./canon_frames -o trails.jpg   # star trails from DSLR frames
    umbra gui                           # launch the desktop app
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _progress_printer(stage, done, total):
    pct = int(100 * done / max(total, 1))
    sys.stderr.write(f"\r  [{stage:>10}] {done}/{total} ({pct}%)")
    sys.stderr.flush()
    if done >= total:
        sys.stderr.write("\n")


def cmd_demo_data(args):
    from .synth import write_demo_session
    light, dark = write_demo_session(args.dir, n_lights=args.frames)
    print(f"Demo session created:\n  lights: {light}\n  darks:  {dark}")
    print("\nTry:  umbra auto " + str(light) + " -o " + str(Path(args.dir) / "out"))


def cmd_info(args):
    from .ingest import discover_sessions, parse_session
    path = Path(args.path)
    sessions = [parse_session(path)] if (path / "shotsInfo.json").exists() or \
        path.name.upper().startswith("DWARF_") else discover_sessions(path)
    for s in sessions:
        print(s.summary())
        if args.verbose:
            print(f"    path:     {s.path}")
            print(f"    filter:   {s.filter_hint or '(unknown)'}   "
                  f"RA/Dec: {s.ra}/{s.dec}")
            print(f"    stacked:  {len(s.stacked)}  previews: {len(s.previews)}  "
                  f"onboard-rejects: {len(s.rejected_onboard)}")
            for note in s.parse_notes:
                print(f"    note: {note}")


def cmd_import(args):
    from .ingest import discover_sessions
    from .library import Library
    lib = Library(db_path=args.db)
    sessions = discover_sessions(args.path)
    added = 0
    for s in sessions:
        sid, new = lib.import_session(s)
        tag = "added" if new else "already known"
        print(f"  [{tag:>13}] #{sid} {s.summary()}")
        added += int(new)
    print(f"\n{added} new / {len(sessions)} total sessions -> {lib.db_path}")


def cmd_library(args):
    from .library import Library
    lib = Library(db_path=args.db)
    if args.what == "targets":
        rows = lib.targets_summary()
        if not rows:
            print("Library is empty. Run: umbra import <folder>")
            return
        print(f"{'target':<28}{'sessions':>9}{'frames':>8}{'integration':>14}")
        for r in rows:
            mins = int((r["integration_s"] or 0) // 60)
            print(f"{r['target_display'] or r['target']:<28}{r['sessions']:>9}"
                  f"{r['frames'] or 0:>8}{mins:>11}min")
    elif args.what == "outputs":
        for r in lib.outputs():
            print(f"  {r['created_at']}  {r['target']:<10} {r['name']:<24} {r['path']}")
    else:  # sessions
        for r in lib.sessions(target=args.target):
            mins = int((r["integration_s"] or 0) // 60)
            stars = "*" * (r["rating"] or 0)
            print(f"  #{r['id']:<4} {r['timestamp'] or '?':<22} {r['target_display'] or '?':<26}"
                  f"{r['frame_count'] or 0:>4} fr {mins:>5}min  {stars}")


def cmd_grade(args):
    from .ingest import parse_session
    from .grade import grade_session
    s = parse_session(args.session)
    print(f"Grading {s.frame_count} frames of {s.target or s.path.name} ...")
    results = grade_session(s.lights, progress=lambda d, t: _progress_printer("grade", d, t))
    print(f"\n{'#':>4} {'stars':>6} {'FWHM':>6} {'ecc':>6} {'bg':>7} {'score':>6}  verdict")
    for i, q in enumerate(results):
        verdict = "OK" if q.accepted else "REJECT: " + ", ".join(q.reject_reasons)
        print(f"{i:>4} {q.n_stars:>6} {q.fwhm:>6.2f} {q.ellipticity:>6.2f} "
              f"{q.background:>7.4f} {q.score:>6.1f}  {verdict}")
    n_ok = sum(1 for q in results if q.accepted)
    print(f"\n{n_ok}/{len(results)} frames pass. "
          f"Stack them with: umbra stack {args.session} -o stacked.fits")
    if args.json:
        Path(args.json).write_text(json.dumps([q.to_dict() for q in results], indent=2))
        print(f"Report written to {args.json}")


def cmd_stack(args):
    from .calib.masters import build_master
    from .export import export_image
    from .ingest import parse_session
    from .recipes.auto import find_matching_darks
    from .stack import integrate

    s = parse_session(args.session)
    print(f"Stacking: {s.summary()}")

    master_dark = None
    if args.darks:
        from .ingest import parse_session as ps
        darks = ps(args.darks)
        master_dark = build_master(darks.lights)
        print(f"  master dark from {len(darks.lights)} frames")
    elif not args.no_darks:
        found = find_matching_darks(s)
        if found:
            master_dark = build_master(found.lights)
            print(f"  master dark auto-found: {found.path.name}")

    result = integrate(
        s.lights, master_dark=master_dark,
        rejection_sigma=args.sigma, drizzle=args.drizzle,
        best_fraction=args.best, quality_filter=not args.keep_all,
        progress=_progress_printer, log=lambda m: print("  " + m))

    out = Path(args.output)
    if out.suffix.lower() in (".fits", ".fit"):
        result.image.save_fits(out)
    else:
        export_image(result.image, out)
    print(f"\nStacked {result.n_used} frames "
          f"({result.n_rejected_frames} rejected) -> {out}")
    print(f"Next: umbra process {out} -o final.jpg --auto-finish")


def cmd_auto(args):
    from .recipes import auto_process
    img, result, exported = auto_process(
        args.session, args.output, darks_dir=args.darks,
        progress=_progress_printer, log=lambda m: print("  " + m))
    print("\nDone. Exported:")
    for p in exported:
        print(f"  {p}")


def cmd_process(args):
    import umbra_noctis.process  # noqa: F401
    from .core.image import AstroImage
    from .core.ops import apply_op
    from .export import export_image
    from .recipes import Recipe, run_recipe
    from .recipes.auto import AUTO_RECIPE_STEPS

    img = AstroImage.from_fits(args.input)
    if args.recipe:
        img = run_recipe(img, Recipe.load(args.recipe),
                         progress=lambda d, t, op: print(f"  [{d}/{t}] {op}"))
    if args.auto_finish:
        for step in AUTO_RECIPE_STEPS:
            print(f"  auto: {step['op']}")
            img = apply_op(img, step["op"], **step["params"])
    for op_spec in args.op or []:
        name, _, kv = op_spec.partition(":")
        params = {}
        if kv:
            for pair in kv.split(","):
                k, _, v = pair.partition("=")
                params[k] = v
        print(f"  {name} {params or ''}")
        img = apply_op(img, name, **params)

    out = Path(args.output)
    if out.suffix.lower() in (".fits", ".fit"):
        img.save_fits(out)
    else:
        export_image(img, out)
    print(f"-> {out}")
    if args.save_recipe:
        Recipe.from_history(img, Path(args.save_recipe).stem).save(args.save_recipe)
        print(f"recipe saved: {args.save_recipe}")


def cmd_ops(args):
    import umbra_noctis.process  # noqa: F401
    from .core.ops import OPS, ops_markdown
    if args.markdown:
        print(ops_markdown())
        return
    by_stage = {}
    for spec in OPS.values():
        by_stage.setdefault(spec.stage, []).append(spec)
    for stage in ("calibrate", "linear", "stretch", "nonlinear", "geometry", "cosmetic"):
        if stage not in by_stage:
            continue
        print(f"\n{stage.upper()}")
        for spec in sorted(by_stage[stage], key=lambda s: s.name):
            params = ", ".join(p.name for p in spec.params)
            print(f"  {spec.name:<24} {spec.label}  ({params})")
    print("\nDetails: umbra ops --markdown   |   usage: --op name:param=value,param=value")


def cmd_solve(args):
    from .core.image import AstroImage
    from .solve import annotate_image, solve_image
    result = solve_image(args.input)
    if not result.success:
        print(f"Solve failed: {result.message}")
        sys.exit(1)
    print(f"Solved by {result.solver}: RA {result.ra_deg:.4f}  Dec {result.dec_deg:.4f}"
          + (f"  scale {result.scale_arcsec:.2f}\"/px" if result.scale_arcsec else "")
          + (f"  rotation {result.rotation_deg:.1f} deg" if result.rotation_deg is not None else ""))
    if args.annotate:
        img = AstroImage.from_fits(args.input)
        out, objs = annotate_image(img, result, args.annotate)
        print(f"Annotated ({len(objs)} objects) -> {out}")
        for o in objs:
            print(f"  {o['name']:<10} {o['friendly']}")


def cmd_planetary(args):
    from .core.ops import apply_op
    from .export import export_image
    from .planetary import lucky_stack
    import umbra_noctis.process  # noqa: F401

    result = lucky_stack(args.video, keep_fraction=args.keep,
                         progress=_progress_printer)
    img = result.image
    if args.sharpen > 0:
        img = apply_op(img, "sharpen", amount=args.sharpen, scale="fine",
                       protect_stars=False)
    out = export_image(img, args.output)
    print(f"\nUsed best {result.n_frames_used}/{result.n_frames_total} frames -> {out}")


def cmd_trails(args):
    from .calib.masters import build_master
    from .export import export_image
    from .stack.integrate import demosaic
    from .stack.trails import collect_frames, trail_stack

    frames = collect_frames(args.frames)
    if not frames:
        print("No supported frames found (FITS/CR2/NEF/ARW/DNG/JPEG/TIFF/PNG).")
        sys.exit(1)
    print(f"Trail stacking {len(frames)} frames"
          + (" (aligned meteor composite)" if args.align else ""))

    master_dark = None
    if args.darks:
        dark_frames = collect_frames([args.darks])
        master_dark = build_master(dark_frames)
        if master_dark.cfa:
            master_dark = demosaic(master_dark)
        print(f"  master dark from {len(dark_frames)} frames")

    result = trail_stack(
        frames, master_dark=master_dark, align=args.align,
        cosmetic=not args.no_cosmetic,
        progress=_progress_printer, log=lambda m: print("  " + m))

    out = Path(args.output)
    if out.suffix.lower() in (".fits", ".fit"):
        result.image.save_fits(out)
    else:
        export_image(result.image, out)
    print(f"\nBlended {result.n_frames} frames "
          f"({result.n_skipped} skipped) -> {out}")


def cmd_gui(args):
    try:
        from .gui.app import run_gui
    except ImportError as exc:
        print(f"GUI dependencies missing ({exc}).\nInstall with: pip install 'umbra-noctis[gui]'")
        sys.exit(1)
    run_gui()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="umbra",
        description="Umbra Noctis — Dwarf 3 post-processing. "
                    "Ex umbra noctis, in solem.")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("demo-data", help="generate a synthetic Dwarf 3 session to practice on")
    p.add_argument("dir")
    p.add_argument("--frames", type=int, default=12)
    p.set_defaults(func=cmd_demo_data)

    p = sub.add_parser("info", help="inspect a session folder or a whole SD card")
    p.add_argument("path")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("import", help="import sessions into the library")
    p.add_argument("path")
    p.add_argument("--db", default=None, help="library database path (default ~/.umbra-noctis)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("library", help="browse the library")
    p.add_argument("what", nargs="?", default="sessions",
                   choices=("sessions", "targets", "outputs"))
    p.add_argument("--target")
    p.add_argument("--db", default=None)
    p.set_defaults(func=cmd_library)

    p = sub.add_parser("grade", help="score every sub-frame and flag rejects")
    p.add_argument("session")
    p.add_argument("--json", help="also write a JSON report")
    p.set_defaults(func=cmd_grade)

    p = sub.add_parser("stack", help="calibrate, register, and stack a session")
    p.add_argument("session")
    p.add_argument("-o", "--output", required=True, help=".fits recommended")
    p.add_argument("--darks", help="dark session folder (auto-detected if omitted)")
    p.add_argument("--no-darks", action="store_true", help="skip dark search")
    p.add_argument("--sigma", type=float, default=3.0, help="pixel rejection sigma")
    p.add_argument("--drizzle", type=float, default=1.0, choices=[1.0, 1.5, 2.0],
                   help="integrate onto a finer grid")
    p.add_argument("--best", type=float, default=0.9,
                   help="keep this fraction of frames by quality (0-1)")
    p.add_argument("--keep-all", action="store_true", help="disable quality rejection")
    p.set_defaults(func=cmd_stack)

    p = sub.add_parser("auto", help="one command: session folder -> finished image")
    p.add_argument("session")
    p.add_argument("-o", "--output", required=True, help="output directory")
    p.add_argument("--darks")
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("process", help="apply operations/recipes to an image")
    p.add_argument("input", help="FITS image (usually a stack)")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--op", action="append",
                   help="operation, e.g. --op ghs:amount=6,focus=0.1 (repeatable, in order)")
    p.add_argument("--recipe", help="recipe JSON file to run first")
    p.add_argument("--auto-finish", action="store_true",
                   help="run the standard auto-processing chain")
    p.add_argument("--save-recipe", help="save the applied steps as a recipe JSON")
    p.set_defaults(func=cmd_process)

    p = sub.add_parser("ops", help="list all processing operations")
    p.add_argument("--markdown", action="store_true", help="full reference as Markdown")
    p.set_defaults(func=cmd_ops)

    p = sub.add_parser("solve", help="plate-solve (and optionally annotate) an image")
    p.add_argument("input")
    p.add_argument("--annotate", help="write an annotated JPEG here")
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("planetary", help="lucky-imaging stack from a video")
    p.add_argument("video")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--keep", type=float, default=0.25, help="fraction of frames to keep")
    p.add_argument("--sharpen", type=float, default=0.8, help="wavelet sharpening amount")
    p.set_defaults(func=cmd_planetary)

    p = sub.add_parser(
        "trails",
        help="star-trail / meteor composite: lighten-blend frames as shot")
    p.add_argument("frames", nargs="+",
                   help="folder(s) of frames or individual files "
                        "(FITS, Canon CR2/CR3, NEF, ARW, DNG, JPEG, TIFF, PNG)")
    p.add_argument("-o", "--output", required=True,
                   help=".jpg/.tif/.png/.fits")
    p.add_argument("--darks",
                   help="folder of cap-on dark frames shot at the same settings")
    p.add_argument("--align", action="store_true",
                   help="register the star field first (meteor composites; "
                        "leave off for star trails)")
    p.add_argument("--no-cosmetic", action="store_true",
                   help="skip statistical hot-pixel repair")
    p.set_defaults(func=cmd_trails)

    p = sub.add_parser("gui", help="launch the desktop application")
    p.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    if args.version:
        from . import __version__
        print(f"Umbra Noctis {__version__}")
        return
    if not getattr(args, "func", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
