# GUI Tour

`umbra gui` opens a dark-themed window with five numbered steps down the left
side. The steps are a guided path — each one hands off to the next — but once
a step has data you can jump back and forth freely. A red night-vision theme
is in **View → Red night-vision mode** for processing at the telescope.

Star trails, meteor scanning, and nightscape composites (DSLR workflows) are
currently CLI-only — see [USER_GUIDE.md §10](USER_GUIDE.md#10-star-trails-meteors--nightscapes-dslr).

---

## 1 · Library

**What it's for:** getting data in and picking what to work on.

- **Open folder…** — point it at anything: one session folder, the whole
  `Astronomy` directory, an entire SD card copy. Every capture session found
  appears in the table (target, type, frames, exposure, gain, integration).
  Dark sessions are listed grayed out — you never work on them directly;
  they're matched to lights automatically.
- **No data yet? Create a practice session** — generates the synthetic demo
  session anywhere you choose, so you can learn the workflow tonight even if
  it's cloudy.
- Everything you open is also imported into your library database
  (duplicates recognized), building your per-target acquisition history.
- **Double-click a light session** to select it and move to Grade.

## 2 · Grade

**What it's for:** deciding which sub-exposures deserve to be stacked.

- Press **Grade all frames**. Each frame gets star count, FWHM (sharpness),
  trail (elongation), and a 0–100 score; frames that deviate from the
  session's own statistics are auto-rejected with the reason shown in red
  (clouds, trailing, soft focus, bright sky).
- Click any row to see that frame in the preview (display-autostretched).
- **Blink like a pro:** `←` / `→` step through frames — flip quickly and
  satellites/clouds jump out at you. `X` rejects the current frame, `A`
  accepts it. Your verdicts override the automatic ones.
- Nothing is deleted, ever — rejected frames are only excluded from stacking.
- **Continue to stacking →** when the accept list looks right.

## 3 · Stack

**What it's for:** turning your accepted subs into one deep, clean image.

- The **Master dark** row shows what was auto-matched (same exposure + gain,
  found near your lights). "None found" is fine too — statistical hot-pixel
  removal takes over.
- Defaults are tuned for Dwarf 3 data. The three knobs, when you want them:
  - **Rejection sigma** (3.0) — lower to 2.5 if a satellite ghost survives.
  - **Keep best** (90%) — lower with big sessions for extra sharpness.
  - **Drizzle** — off unless you have 50+ well-dithered subs.
- Press **Stack frames**. The log narrates everything: calibration, frames
  used, how many registered by stars vs. fallback, measured field rotation,
  percentage of pixel samples rejected. The preview shows the result with
  the rotation borders already auto-cropped.
- **Re-stack** anytime with different settings — the source frames are
  untouched.

## 4 · Process

**What it's for:** the darkroom. This page is where images get made.

Layout: tool tree (left) · preview canvas (center) · history (right).

- **Tool tree** — every operation, grouped in recommended order: *Linear
  (before stretch)* → *Stretch* → *After stretch* → *Geometry* → *Cosmetic*.
  Click a tool: its description appears below the tree and its settings form
  (generated from the same definitions the CLI uses — same names, same
  ranges, hover any field for help) appears under that.
- **Apply** runs the tool on a background thread and updates the preview.
- **Preview canvas** — wheel to zoom, drag to pan, double-click to fit,
  `1:1` for pixel peeping. **Display autostretch** (on by default) shows
  linear data brightly without touching it; switch it off after stretching
  to see exactly what will export.
- **Hold for before** — press and hold to flash the original stack;
  release to snap back. The fastest possible sanity check.
- **✨ Auto-process** — runs the standard chain (gradient removal → color →
  denoise → GHS ×2 → vibrance). Great as a starting point: run it, then
  refine on top, or undo and go manual.
- **History panel** — every applied step, in order. **Undo last step**,
  **Reset to stack** (back to square one), and **Save steps as recipe…**
  (your whole chain as a JSON file you can replay on any other stack from
  the CLI or share with other Dwarf owners).

## 5 · Export

**What it's for:** getting the finished image out, with the story attached.

- **Export image…** — JPEG (share), 16-bit TIFF (edit elsewhere), PNG, or
  FITS (archival; carries your full processing history in the header).
  Linear data is autostretched on export so you can't accidentally save a
  black JPEG.
- **Export before/after comparison…** — labeled side-by-side JPEG of the
  raw stack vs. your final image.
- **Shareable caption** — generated from the session metadata (target with
  friendly name, scope, frames × exposure @ gain, total integration). Edit
  it in place, then copy-paste to Reddit/AstroBin/Instagram.

---

## Keyboard reference

| Where | Key | Action |
|---|---|---|
| Grade | `←` / `→` | Previous / next frame (blink) |
| Grade | `X` | Reject current frame |
| Grade | `A` | Accept current frame |
| Any canvas | wheel | Zoom |
| Any canvas | drag | Pan |
| Any canvas | double-click | Fit to window |
| Anywhere | `Ctrl+O` | Open data folder |
| Anywhere | `Ctrl+Q` | Quit |
