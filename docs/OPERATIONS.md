# Operation Reference

## Stage: linear

### `background_extract` — Background / gradient removal

Model and remove the sky background (the #1 fix for backyard imaging).

    A grid of sample boxes is placed across the image; boxes contaminated by
    stars or nebulosity are rejected by sigma-clipping against their
    neighbors, a 2-D polynomial is fit per channel, and the model is
    subtracted (or divided out). The original median level is restored so the
    image doesn't go dark.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `degree` | int | 2 | 1–4 | Polynomial degree of the sky model (2 handles most light-pollution gradients; 4 for corner glows) |
| `samples` | int | 24 | 8–64 | Sample grid resolution per axis |
| `mode` | choice | subtract | subtract, divide | subtract = additive gradients (light pollution); divide = multiplicative (vignetting) |

### `background_neutralize` — Neutralize background color

Equalize the RGB background medians so the sky is gray, not orange.
    Run after background_extract, before any stretch.

### `banding_reduce` — Reduce row/column banding

Suppress horizontal/vertical pattern banding by subtracting each
    line's robust background offset from the global background level.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `axis` | choice | rows | rows, cols, both | Direction of the banding pattern |
| `protect` | float | 0.9 | 0.5–1.0 | Percentile of pixels treated as background per line |

### `deconvolve` — Deconvolution (Richardson–Lucy)

Sharpen by undoing the blur the optics/atmosphere applied.

    Richardson–Lucy with a Gaussian PSF. By default the PSF width is measured
    from the stars in the image itself. Apply on LINEAR data only, ideally
    after denoising. If stars grow dark rings, lower iterations or raise
    regularization.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `iterations` | int | 15 | 1–60 | More iterations = sharper but riskier |
| `psf_fwhm` | float | 0.0 | 0.0–12.0 | PSF size in px; 0 = measure automatically from stars |
| `regularization` | float | 0.002 | 0.0–0.02 | Damping against ringing |

### `denoise` — Noise reduction

Reduce noise while preserving stars and structure.

    Wavelet mode decomposes the image into à-trous (starlet) scales and
    soft-thresholds the finest scales where noise lives; structure at larger
    scales is untouched. On color images the chroma is denoised harder than
    luminance, which is where the "watercolor blotch" look comes from.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `method` | choice | wavelet | wavelet, bilateral, gaussian | wavelet = starlet soft-threshold (best); bilateral = edge-preserving; gaussian = simple blur |
| `strength` | float | 1.0 | 0.0–4.0 | Threshold multiplier / blur size |
| `chroma_boost` | float | 2.0 | 0.0–6.0 | Extra denoise on color channels (chroma noise is uglier than luma) |

### `dualband_extract` — Dual-band Hα/OIII extraction

Turn a session shot through the Dwarf 3's built-in dual-band filter
    into a narrowband-style image.

    Through that filter, the sensor's red pixels see almost pure Hα and the
    green/blue pixels see almost pure OIII — so R becomes a synthetic Hα
    channel and a weighted G+B average becomes OIII. Backgrounds are
    equalized before combination. Run on LINEAR stacked data, then stretch.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `palette` | choice | HOO | HOO, OHH, HA, OIII | HOO = Hα→red, OIII→green+blue (natural bicolor). HA/OIII output the raw extracted channel as mono |
| `ha_boost` | float | 1.0 | 0.2–4.0 | Hα channel gain |
| `oiii_boost` | float | 1.0 | 0.2–4.0 | OIII channel gain |

### `scnr` — Remove green cast (SCNR)

Subtractive Chromatic Noise Reduction: clamps green to the average of
    red and blue. Deep-sky objects are almost never green — leftover green is
    sensor artifact. Safe default after color balancing.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 1.0 | 0.0–1.0 | 1.0 = full removal |

### `white_balance` — White balance (star-based or manual)

Color-balance the image. Auto mode assumes the *average* star in a wide
    field is roughly solar-colored — a good approximation for Dwarf 3 fields
    (full photometric calibration via plate solve is in `umbra solve`).

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `r` | float | 1.0 | 0.2–5.0 | Red gain (ignored when auto=true) |
| `g` | float | 1.0 | 0.2–5.0 | Green gain |
| `b` | float | 1.0 | 0.2–5.0 | Blue gain |
| `auto` | bool | True |  | Derive gains so the average detected star is white |

## Stage: stretch

### `arcsinh` — Arcsinh stretch

Color-preserving stretch: scales R, G, B by the same luminance-derived
    factor, so star colors survive where a plain histogram stretch would
    bleach them white. Great first stretch for star fields and clusters.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `factor` | float | 30.0 | 1.0–1000.0 | Stretch factor (log-ish scale) |
| `black_point` | float | 0.0 | 0.0–0.5 | Subtract before stretching |

### `autostretch` — Auto-stretch (permanent STF)

Apply the same statistics-driven stretch the screen preview uses,
    permanently. A reliable one-click starting point for any stack.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `target_background` | float | 0.22 | 0.05–0.5 | Post-stretch sky level |
| `linked` | bool | True |  | Stretch channels together (keep color) or separately (also neutralizes color casts) |

### `ghs` — Generalized hyperbolic stretch

Generalized Hyperbolic Stretch (Honours/Payne GHS).

    The modern astro stretch: `focus` aims the contrast budget at a chosen
    brightness level, while the protect parameters spare shadows and star
    cores. Typical deep-sky use: focus just above the sky background,
    protect_highlights ~0.7, amount 3–8, applied in 2–3 passes.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 5.0 | 0.0–15.0 | Stretch intensity (D) |
| `focus` | float | 0.0 | 0.0–1.0 | Symmetry point SP: intensity level that gets the most contrast (set near the background level to lift faint nebulosity) |
| `protect_shadows` | float | 0.0 | 0.0–1.0 | LP: keep contrast out of levels below this |
| `protect_highlights` | float | 1.0 | 0.0–1.0 | HP: compress above this (protects star cores) |

### `histogram_stretch` — Histogram (midtone) stretch

The classic three-slider stretch (identical math to PixInsight's
    HistogramTransformation). Iterate gently: several small stretches beat
    one aggressive one.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `shadows` | float | 0.0 | 0.0–0.99 | Black point (clips below) |
| `midtones` | float | 0.5 | 0.001–0.999 | Midtone balance: <0.5 brightens, >0.5 darkens |
| `highlights` | float | 1.0 | 0.01–1.0 | White point |

## Stage: nonlinear

### `curves` — Curves

Classic monotone-spline curves. An S-shape adds contrast; lifting only
    the lower-mid region brightens nebulosity. The 'saturation' channel
    applies the curve to color saturation instead of brightness.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `points` | str | 0,0;0.5,0.5;1,1 |  | Semicolon-separated x,y control points, e.g. '0,0;0.25,0.2;0.7,0.8;1,1' |
| `channel` | choice | all | all, r, g, b, saturation | What the curve drives |

### `hdr_compress` — HDR compression (rescue bright cores)

Compress large-scale brightness range so M42's core or M31's bulge
    keeps detail after a hard stretch, while small-scale contrast survives.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 0.5 | 0.0–1.0 | How much to flatten large-scale range |
| `radius` | int | 80 | 20–400 | Scale treated as 'large' |

### `hue_shift` — Selective hue rotation

Rotate hues (e.g. to tune a dual-band palette). Simple RGB rotation
    about the gray axis; luminance is preserved.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `degrees` | float | 0.0 | -180.0–180.0 | Rotate all hues by this angle |

### `local_contrast` — Local contrast (HDR reveal)

Large-scale unsharp mask: brings out galaxy arms and nebula filaments
    without changing global brightness. The counterpart of hdr_compress.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 0.4 | 0.0–1.5 | Strength |
| `radius` | int | 60 | 10–300 | Structure size in px to enhance |

### `saturation` — Saturation / vibrance

Boost color. Use after stretching. Vibrance mode is the default
    because plain saturation quickly clips nebula cores to neon.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 1.3 | 0.0–3.0 | 1 = unchanged, >1 boosts |
| `vibrance` | bool | True |  | Protect already-saturated pixels and boost muted ones (safer than raw saturation) |
| `luminance_protect` | float | 0.15 | 0.0–0.5 | Don't saturate the darkest sky (keeps noise monochrome) |

### `sharpen` — Multiscale sharpening

Wavelet-scale sharpening (the RegiStax idea, applied to deep-sky).
    Boosts the chosen starlet scale instead of naive unsharp masking, so it
    lifts real structure with less noise amplification. Use after stretch.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 0.5 | 0.0–2.0 | Boost for the detail scales |
| `scale` | choice | medium | fine, medium, large | Which structure size to emphasize |
| `protect_stars` | bool | True |  | Exclude stars (avoids halos) |

### `star_reduce` — Star reduction

Shrink stars so the nebula/galaxy becomes the subject. Morphological
    erosion blended in only under a star mask — the background is untouched.
    Run AFTER stretching. For full removal, use an external StarNet++/GraXpert
    via `umbra integrate-tool` (see docs).

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `amount` | float | 0.5 | 0.0–1.0 | 0 = off, 1 = maximum shrink |
| `grow` | float | 2.0 | 1.0–5.0 | Star mask size multiplier |

## Stage: geometry

### `crop` — Crop

Crop to a pixel rectangle. (The stacker's auto-crop handles stacking
    borders automatically; this is for framing.)

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `x` | int | 0 |  | Left edge (px) |
| `y` | int | 0 |  | Top edge (px) |
| `width` | int | 0 |  | Width; 0 = to the right edge |
| `height` | int | 0 |  | Height; 0 = to the bottom edge |

### `flip` — Flip / mirror



| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `direction` | choice | horizontal | horizontal, vertical |  |

### `invert` — Invert

Negative view — surprisingly useful for spotting faint halos and
    gradient residuals during inspection.

### `resize` — Resample

Resample the image. Downsizing 2× is also a cheap noise reduction —
    a good trick for web-bound Dwarf images.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `scale` | float | 0.5 | 0.05–4.0 | Size multiplier (0.5 = half size) |
| `method` | choice | lanczos | lanczos, cubic, area | area is best for downsizing, lanczos for upsizing |

### `rotate` — Rotate



| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `degrees` | float | 0.0 | -360.0–360.0 | Counter-clockwise. Multiples of 90 are lossless |
| `expand` | bool | True |  | Grow canvas to fit instead of clipping corners |

## Stage: cosmetic

### `clone_out` — Clone-out a defect

Remove a residual satellite streak segment, dust blob, or edge artifact.
    With no source given, OpenCV inpainting fills from the surroundings;
    with a source, a feathered patch is cloned over.

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `x` | int | 0 |  | Center of the blemish |
| `y` | int | 0 |  | Center of the blemish |
| `radius` | int | 12 | 2–200 | Patch radius |
| `src_x` | int | -1 |  | Source center; -1 = auto (inpaint) |
| `src_y` | int | -1 |  | Source center; -1 = auto (inpaint) |

