# Umbra Noctis

**Post-processing suite for the DwarfLab Dwarf 3 smart telescope.**
*Ex umbra noctis, in solem — out of the shadow of night, into the sun.*

Umbra Noctis takes the raw FITS sub-exposures your Dwarf 3 saves during a
session and turns them into images that are visibly better than the
telescope's onboard stack: smarter frame rejection, rotation-aware
registration, satellite-trail removal, gradient extraction, photometric-style
color, modern stretches, and one-click automation — with every step recorded
so any result can be reproduced.

## Highlights

- **Understands Dwarf 3 data natively** — session folders, `shotsInfo.json`,
  darks auto-matching, alt-az field rotation, the dual-band filter.
- **Full re-stacking pipeline** — grading (clouds/trailing/soft-focus
  rejection), astroalign registration, winsorized sigma-clip integration with
  quality weighting, drizzle, auto-crop.
- **Processing suite** — gradient removal, background neutralization,
  star-based white balance, SCNR, starlet-wavelet denoise, Richardson–Lucy
  deconvolution, GHS/arcsinh/histogram stretches, curves, saturation/vibrance,
  star reduction, HDR compression, dual-band Hα/OIII palettes, retouching.
- **Library** — every session cataloged by target with integration totals
  across nights.
- **Planetary** — lucky-imaging stacks from Dwarf video captures.
- **Star trails & meteor composites** — lighten-blend stacking of DSLR
  nights (`umbra trails`): Canon CR2/CR3 and other camera raws, JPEG, TIFF,
  and FITS, with dark subtraction, hot-pixel repair, gap bridging,
  comet-tail fading, noise-free foreground extraction, and an `--align`
  mode that registers the star field for meteor-shower composites.
- **Meteor quick-scan** — `umbra meteor-scan` flags the frames in a night
  that contain streaks and rejects satellites/aircraft by their multi-frame
  tracks; `--copy-to` hands the keepers straight to the compositor.
- **Built-in guide** — `umbra guide` (and Help → Guide in the app) explains
  every feature offline, including a live-generated operation reference; a
  printable field-settings card ships in `docs/FIELD_CARD.html`.
- **Plate solving & annotation** — via ASTAP, astrometry.net, or the free
  nova.astrometry.net web API.
- **Recipes & automation** — save any processing chain as JSON, replay it on
  any session, or use the built-in one-click `auto` pipeline.
- **GUI and CLI** — an intuitive guided desktop app, and a CLI that can do
  everything the GUI can (great for batch overnight runs).

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/ManliestBen/umbra-noctis.git
cd umbra-noctis
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui]"
```

### Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui]"     # dev = pytest + ruff; gui = desktop app
make check                      # lint + full test suite
```

## Five-minute start (no telescope data needed)

```bash
umbra demo-data ./demo            # generates a realistic fake session
umbra info ./demo -v              # what did we get?
umbra auto ./demo/DWARF_RAW_* -o ./demo/out   # session folder -> finished JPEG
umbra gui                         # or do it all visually
```

With real data: copy the `Astronomy` folder off your Dwarf 3 (USB or the
device's network share), then point the same commands at it.

## Documentation

Extremely detailed instructions for every feature live in [`docs/`](docs/):

- [**User Guide**](docs/USER_GUIDE.md) — every feature, explained
- [**Processing Tutorial**](docs/PROCESSING_TUTORIAL.md) — raw session to finished image, step by step
- [**CLI Reference**](docs/CLI_REFERENCE.md) — all commands and options
- [**GUI Tour**](docs/GUI_TOUR.md) — the desktop app, screen by screen
- [**Operation Reference**](docs/OPERATIONS.md) — every processing op and parameter
- [**Dwarf 3 Data Guide**](docs/DWARF3_DATA.md) — what the telescope writes and how to get it off
- [**Plate Solving Setup**](docs/PLATE_SOLVING.md) — ASTAP / astrometry.net / web API

## Project status

Core pipeline (ingest → grade → calibrate → register → stack → process →
export), library, recipes, CLI, GUI, planetary stacking, and plate-solving
adapters are implemented and tested. See [FEATURES.md](FEATURES.md) for the
full catalog and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the
roadmap of what's next (multi-session integration UI, mosaics, ML star
removal, Wi-Fi auto-import, and more).

## License

MIT
