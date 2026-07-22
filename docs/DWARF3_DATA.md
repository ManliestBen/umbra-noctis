# Dwarf 3 Data Guide — what the telescope writes and how to get it off

## What a session looks like on disk

Astro-mode captures land under the device's `Astronomy` folder, one directory
per capture run:

```
Astronomy/
├── DWARF_RAW_TELE_M 42_EXP_15_GAIN_80_2026-07-20-22-30-15-123/
│   ├── 0000.fits … 0159.fits      # individual 16-bit sub-exposures
│   ├── stacked.fits               # the onboard live-stack result
│   ├── stacked.jpg / .png         # stretched previews the app shows you
│   └── shotsInfo.json             # capture metadata
├── DWARF_DARK_EXP_15_GAIN_80_2026-07-20-20-05-01-000/
│   └── 0000.fits … 0039.fits      # dark frames (lens covered)
└── ...
```

Folder-name anatomy: `DWARF_<KIND>_<LENS>_<TARGET>_EXP_<seconds>_GAIN_<gain>_<timestamp>`
— `RAW` = lights, `DARK` = darks; `TELE` = the 150 mm telephoto,
`WIDE` = the wide-angle camera.

`shotsInfo.json` carries target name, exposure, gain, IR-filter position,
binning, RA/Dec of the goto, and shots taken/stacked counts. Umbra Noctis
reads all of it, and falls back to FITS headers when fields are missing —
firmware naming changes won't break imports.

**Umbra parses tolerantly:** any folder with FITS files gets recognized even
if the name doesn't match (you'll see a parser note in `umbra info -v`).

## Getting data onto your computer

1. **USB** — connect the Dwarf 3, it presents its storage as a drive; copy
   the `Astronomy` folder (or just the session folders you want).
2. **microSD** — pop the card into a reader and copy.
3. **Wi-Fi** — with the Dwarf on your home network, its storage is
   reachable over the network (the DwarfLab app exposes the album; community
   tools and recent firmware expose an FTP share). Copy sessions to a local
   folder, then `umbra import` it.

Whichever route: **copy, don't move**, until your backup habits say
otherwise. Umbra treats the copied folders as read-only.

## Practical capture advice (it pays off at processing time)

- **Shoot darks.** Same exposure, same gain, lens cap on, ~20–40 frames,
  roughly the same ambient temperature as your lights (end of the session
  is ideal). Name/date them the way the device does and Umbra matches them
  to lights automatically forever.
- **EQ mode when possible.** Polar-aligning the Dwarf (EQ mode) removes
  field rotation and allows longer subs. Alt-az still stacks perfectly here
  — rotation is solved per frame — but EQ wastes fewer edge pixels and
  tolerates longer exposures.
- **More subs beat longer subs** at fixed total time for rejection quality:
  120 × 15 s gives the sigma-clip a lot more statistics than 30 × 60 s.
- **Dual-band filter for emission nebulae only** (Veil, Rosette, Crescent,
  North America…). Galaxies and clusters want the Astro (UV/IR-cut) filter.
- **Let it dither** (the Dwarf's stacking interval naturally drifts a bit;
  in alt-az, rotation acts as a dither too). Drizzle needs it.
- Keep sessions of the same target on the same exposure/gain settings across
  nights — multi-night integration is then trivial.

## What Umbra Noctis does with each file type

| File | Used for |
|---|---|
| `0000.fits …` (lights) | Everything — grading, calibration, stacking |
| `DWARF_DARK_*/…fits` | Master dark + hot-pixel map, auto-matched by exposure/gain |
| `stacked.fits` | Comparison baseline ("beat the onboard stack"); quick preview |
| `stacked.jpg/png` | Library thumbnails only |
| `shotsInfo.json` | Session metadata (authoritative over folder name) |

## Where Umbra keeps its own data

| Path | Contents |
|---|---|
| `~/.umbra-noctis/library.db` | Session catalog, frame grades, ratings, outputs |
| (your chosen output dirs) | Every export — Umbra never writes into session folders |

Set `UMBRA_HOME=/somewhere/else` to relocate the library (useful for a
shared NAS setup).
