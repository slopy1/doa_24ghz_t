# Display Bezel Assembly Instructions

Flush-mount bezel for Waveshare 4.3" (800x480) display in Meijia portable case lid.

## Files

| File | Description |
|------|-------------|
| `display_bezel.scad` | OpenSCAD parametric source (edit parameters here) |
| `display_bezel.stl` | Exported mesh for slicing |
| `display_bezel.3mf` | Exported mesh (with print settings) |

## 3 Printable Pieces

The SCAD file contains 3 modules. Uncomment the ones you need at the bottom of the file.

### 1. `bezel()` — Main frame (REQUIRED)

Flat frame that sits on the **lid exterior**. Has a centered window for the display glass and a shallow 1mm back pocket that locates the PCB.

- **Size:** ~120.8 x 82.4 x 2.5mm
- **Print:** face DOWN on bed (cleanest window edges)
- **Settings:** 0.15mm layers, 40% infill, no supports

### 2. `lid_template()` — Cutting guide (OPTIONAL)

Thin 1.2mm stencil matching the bezel footprint. The inner cutout is the exact hole to cut through the lid.

- **Print:** flat, ~15 min print time
- **Use:** tape to lid, trace inner rectangle with marker, remove, cut along line

### 3. `back_retainer()` — Inner clamp plate (OPTIONAL but recommended)

Flat plate that goes on the **inside** of the lid over the display back. Sandwiches the display between itself and the bezel frame. Has a central window for the PCB body and ribbon cable.

- **Size:** same footprint as bezel, 2mm thick
- **Print:** flat, no supports

## Assembly

### Tools needed

- Dremel / rotary tool with cutting disc (or jigsaw)
- File or sandpaper (clean up cut edges)
- Calipers or ruler
- Marker
- 4x M3 x 10mm screws (if using back retainer)

### Steps

```
Step 1: TRACE THE CUT
  - Print lid_template() or measure 106.9 x 68.8mm rectangle
  - Center it on the lid exterior (case is 268 x 153mm interior)
  - Tape template, trace inner rectangle with marker

Step 2: CUT THE LID
  - Drill starter holes at corners
  - Cut along traced lines with Dremel cutting disc
  - File edges smooth — doesn't need to be perfect,
    the bezel frame covers rough edges

Step 3: TEST FIT BEZEL
  - Place bezel() frame on lid exterior over the hole
  - Window should be centered in the cut opening
  - The 1mm back pocket should align with the hole edges

Step 4: MOUNT BEZEL TO LID
  Option A (screws): drill M3 pilot holes through lid at corner marks,
    screw from inside through lid into bezel pilot holes
  Option B (adhesive): run a bead of silicone or epoxy around
    the bezel back surface, press onto lid, clamp until cured

Step 5: INSERT DISPLAY
  - From INSIDE the lid, slide display up through the hole
  - Glass face presses against the bezel frame back surface
  - Verify the screen is visible through the window

Step 6: SECURE DISPLAY
  Option A (back retainer): place back_retainer() over display back,
    align corner holes, drive M3x10 screws through retainer → lid → bezel
  Option B (adhesive): run a bead of hot glue or silicone around
    the PCB edges from inside — simple and effective
```

### Cross-section when assembled

```
OUTSIDE (visible)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┌────────────────────────────┐
│  BEZEL FRAME  [WINDOW]     │  2.5mm — sits on lid exterior
└────────────────────────────┘
┌────────────────────────────┐
│  LID PANEL                 │  ~3mm plastic
└────────────────────────────┘
┌────────────────────────────┐
│  DISPLAY (glass → PCB)     │  8.6mm — glass faces up
└────────────────────────────┘
┌────────────────────────────┐
│  BACK RETAINER (optional)  │  2mm — clamps display edges
└────────────────────────────┘
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSIDE (hidden, 27.4mm lid depth)
```

## Parameters Reference

Edit these in `display_bezel.scad`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `screen_l` | 106.2 | Window opening, long axis (full glass) |
| `screen_w` | 67.8 | Window opening, short axis (full glass) |
| `clearance` | 0.30 | PCB fit tolerance per side |
| `face_t` | 2.5 | Frame thickness |
| `border` | 7.0 | Frame border width around PCB |
| `corner_r` | 4.0 | Corner rounding radius |
| `screw_d` | 2.8 | M3 pilot hole diameter |

## Meijia Case Dimensions

| | Imperial | Metric |
|---|----------|--------|
| Outside | 11.65 x 8.35 x 3.78" | 296 x 212 x 96mm |
| Inside | 10.54 x 6.04 x 3.16" | 268 x 153 x 80mm |
| Lid depth | 1.08" | 27.4mm |
| Bottom depth | 2.08" | 52.8mm |
