# Plate Solving Setup

Plate solving identifies exactly where an image points (RA/Dec, scale,
rotation), which unlocks field annotation and, later, photometric work.
Umbra Noctis drives external solvers rather than bundling gigabytes of star
indexes. It tries these in order:

## Option 1 — ASTAP (recommended)

Fast, small, excellent with Dwarf-sized fields.

1. Download ASTAP for your OS from the ASTAP website (hnsky.org/astap).
2. Install the **D50** star database (covers the Dwarf 3's ~2.9° field well).
3. Make sure the `astap` (or `astap_cli`) executable is on your PATH.

Test: `umbra solve your_stack.fits`

## Option 2 — astrometry.net local (`solve-field`)

The classic. On Debian/Ubuntu:

```bash
sudo apt install astrometry.net
# index files sized for the Dwarf 3 FOV (~1.7–2.9°): 4110–4112 series
sudo apt install astrometry-data-4208-4219   # or download index-41xx files
```

Umbra pre-seeds the scale search at the Dwarf 3 telephoto's ~2.75″/px, so
solves are quick.

## Option 3 — nova.astrometry.net web API (zero install)

1. Create a free account at nova.astrometry.net, copy your API key.
2. `export UMBRA_ASTROMETRY_KEY=your_key_here` (put it in your shell profile).

Images are uploaded (marked not-public) and usually solve in under a minute.
Needs internet; fine for occasional use, slow for batches.

## Using it

```bash
umbra solve m42_final.fits
# Solved by astap: RA 83.8221  Dec -5.3911  scale 2.74"/px  rotation 12.3 deg

umbra solve m42_final.fits --annotate m42_labeled.jpg
# draws circles + names for every bundled catalog object in the field
```

The bundled annotation catalog covers the Messier list plus the famous
NGC/IC showpieces with friendly names ("NGC 7000 — North America Nebula").

## Troubleshooting

| Problem | Fix |
|---|---|
| "No solver succeeded" | Install one of the three options above; `--annotate` needs a solve |
| ASTAP solves but no annotation | The field genuinely contains no bundled catalog objects — try a wider-known target to verify |
| Web API times out | Large TIFFs upload slowly — solve the FITS stack instead |
| Wrong scale reported | You solved a drizzled (×2) stack — scale halves; that's correct |
