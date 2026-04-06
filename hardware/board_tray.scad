/* =========================================================
   Sliding Board Tray — BladeRF 2.0 xA4 + Cora Z7
   For Meijia Portable Case  (268 x 153 x 52.8mm bottom)

   Both boards side by side on standoffs. Tray slides
   along the case length, leaving ~158mm for battery,
   DC-DC converter, fans, and wiring in the other half.

   Layout (top view inside case):
   ┌────────────────────────────────────────────────┐
   │                                                │
   │  ┌──────────┬──┬────────┐                      │
   │  │ BladeRF  │  │ Cora   │                      │
   │  │ 63.5 x   │  │ 58 x   │  ← tray ~110mm      │ 153mm
   │  │ 101.25   │  │ 102    │                      │
   │  │ (SMAs ↓) │  │        │                      │
   │  └──────────┴──┴────────┘                      │
   │     ~140mm wide                                │
   │     ← slides along 268mm, ~158mm free →        │
   └────────────────────────────────────────────────┘
                       268mm

   Board measurements (from calipers):
     BladeRF PCB:  63.5 x 101.25mm  (excl. SMA/barrel/ethernet)
       Holes: 50.74 x 82.65mm spacing, D=2.6mm
       Right edge to right hole center: 5.16mm
       SMA edge to front hole center: ~11.5mm
     Cora Z7 PCB:  58 x 102mm
       Holes: 50.6 x 94.6mm spacing, D=3.67mm
       Hole edge to PCB edge: 1.9mm → center offset ~3.7mm

   Print settings:
     Orientation : flat on bed (rails face up)
     Layer height : 0.20 mm
     Infill       : 30-40%
     Supports     : none needed
     Material     : PETG preferred (stiffer than PLA for a tray)
   ========================================================= */


// ── CASE DIMENSIONS ─────────────────────────────────────

case_inner_l = 268;     // mm  (length, long axis)
case_inner_w = 153;     // mm  (width, short axis)
case_inner_d =  52.8;   // mm  (bottom half depth)


// ── BOARD DIMENSIONS (PCB only, excl. connectors) ───────

// BladeRF 2.0 xA4
bladerf_w = 63.5;       // mm  (short axis — SMA connector edge)
bladerf_l = 101.25;     // mm  (long axis)

// Cora Z7
cora_w = 58;             // mm  (short axis)
cora_l = 102;            // mm  (long axis)


// ── TRAY PARAMETERS — ADJUST THESE ─────────────────────

// Clearance between tray edges and case walls
wall_clearance = 0.5;   // mm per side

// Gap between the two boards (cable routing slot)
board_gap = 10;          // mm — USB + power cables route through here

// Border around boards on the tray
tray_border = 4;         // mm on each side

// Base plate
base_t = 3.0;           // mm thickness

// Side rails (run along the tray length on both sides)
rail_h = 5.0;           // mm above base top surface
rail_w = 3.0;           // mm wide

// Standoff height (airflow clearance under boards)
standoff_h = 5.0;       // mm above base top

// BladeRF standoffs (M2.5 screws through 2.6mm holes)
bladerf_standoff_d = 6.5;    // mm outer diameter
bladerf_screw_d    = 2.6;    // mm  (matches board holes)

// Cora Z7 standoffs (M3 screws through 3.67mm holes)
cora_standoff_d = 8.0;       // mm outer diameter
cora_screw_d    = 3.67;      // mm  (matches board holes)

// Rounded corners
corner_r = 3.0;          // mm

$fn = 48;


// ── MOUNTING HOLES (measured with calipers) ─────────────
//
// Each entry is [x, y] from the board's bottom-left corner.
// x = along board width (short axis)
// y = along board length (long axis)

// BladeRF 2.0 xA4
// Hole spacing: 50.74mm (W) x 82.65mm (L), D=2.6mm
// Right edge → right hole center: 5.16mm
// SMA edge (y=0) → front hole center: ~11.5mm
bladerf_hole_x_right = bladerf_w - 5.16;               // = 58.34
bladerf_hole_x_left  = bladerf_hole_x_right - 50.74;   // = 7.60
bladerf_hole_y_front = 11.5;                            // ~11.5 (SMA side)
bladerf_hole_y_back  = 11.5 + 82.65;                   // = 94.15

board_bladerf_holes = [
    [bladerf_hole_x_left,  bladerf_hole_y_front],   // front-left
    [bladerf_hole_x_right, bladerf_hole_y_front],   // front-right
    [bladerf_hole_x_left,  bladerf_hole_y_back],    // back-left
    [bladerf_hole_x_right, bladerf_hole_y_back],    // back-right
];

// Cora Z7
// Hole spacing: 50.6mm (W) x 94.6mm (L), D=3.67mm
// Hole edge to PCB edge: 1.9mm → center = 1.9 + 3.67/2 = 3.735mm
cora_hole_offset = 1.9 + 3.67 / 2;   // = 3.735mm from each edge

board_cora_holes = [
    [cora_hole_offset,          cora_hole_offset],            // bottom-left
    [cora_hole_offset + 50.6,   cora_hole_offset],            // bottom-right
    [cora_hole_offset,          cora_hole_offset + 94.6],     // top-left
    [cora_hole_offset + 50.6,   cora_hole_offset + 94.6],     // top-right
];


// ── DERIVED ─────────────────────────────────────────────

// Both boards side by side along X (width), long axes along Y (length)
boards_max_l = max(bladerf_l, cora_l);   // = 102mm (Cora slightly longer)

// Tray outer dimensions
tray_w = tray_border + bladerf_w + board_gap + cora_w + tray_border;  // ~139.5mm
tray_l = tray_border + boards_max_l + tray_border;                     // ~110mm

// Board origins on tray (bottom-left corner of each PCB)
// Both centered vertically (Y) on the tray
bladerf_x = tray_border;
bladerf_y = tray_border + (boards_max_l - bladerf_l) / 2;   // +0.375mm centering

cora_x = tray_border + bladerf_w + board_gap;
cora_y = tray_border + (boards_max_l - cora_l) / 2;          // +0mm (longest board)

// Cable slot between boards (vertical cut along Y axis)
slot_x_pos = tray_border + bladerf_w;    // starts at right edge of BladeRF
slot_y_pos = 0;                           // full tray length

echo("─── Tray dimensions ─────────────────────────────────");
echo(str("  Tray (W x L x base):       ", tray_w, " x ", tray_l, " x ", base_t, " mm"));
echo(str("  Total height (base+rail):   ", base_t + rail_h, " mm"));
echo(str("  Slide range along length:   ", case_inner_l - tray_l, " mm"));
echo(str("  Slide range across width:   ", case_inner_w - tray_w, " mm"));
echo(str("  Free along case length:     ", case_inner_l - tray_l, " mm"));
echo(str("  BladeRF origin on tray:     (", bladerf_x, ", ", bladerf_y, ")"));
echo(str("  Cora origin on tray:        (", cora_x, ", ", cora_y, ")"));
echo("─────────────────────────────────────────────────────");


// ─────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────

module rounded_box(l, w, h, r) {
    hull() {
        for (xi = [r, l - r])
        for (yi = [r, w - r])
            translate([xi, yi, 0])
                cylinder(r = r, h = h);
    }
}

// Parametric standoff: different hole/OD per board
module standoff(x, y, od, id) {
    translate([x, y, base_t]) {
        difference() {
            cylinder(d = od, h = standoff_h);
            translate([0, 0, -0.1])
                cylinder(d = id, h = standoff_h + 0.2);
        }
    }
}


// ─────────────────────────────────────────────────────────
// BOARD TRAY — main module
// ─────────────────────────────────────────────────────────
//
//  Top view:
//    ┌──────────────────────────────────┐
//    │  ┌──────────┐ slot ┌──────────┐  │
//    │  │ BladeRF  │      │ Cora Z7  │  │
//    │  │ 63.5mm   │      │  58mm    │  │
//    │  │          │      │          │  │
//    │  └──────────┘      └──────────┘  │
//    └──────────────────────────────────┘
//       rail (left)          rail (right)
//
//  Side view (cross-section along X):
//       rail                              rail
//    ┌──┐                                ┌──┐
//    │  │  ○ BladeRF      ○ Cora         │  │
//    │  ├──┤══════════╡  ╞══════════════─┤  │
//    └──┴──┴──────────┘  └───────────────┴──┘
//           base plate    cable slot    base plate

module board_tray() {
    difference() {
        union() {
            // ① Base plate
            rounded_box(tray_w, tray_l, base_t, corner_r);

            // ② Side rails (along Y axis, both X edges)
            // Left rail (x=0)
            rounded_box(rail_w, tray_l, base_t + rail_h, corner_r);
            // Right rail (x=tray_w)
            translate([tray_w - rail_w, 0, 0])
                rounded_box(rail_w, tray_l, base_t + rail_h, corner_r);

            // ③ BladeRF standoffs (M2.5, D=2.6mm holes)
            for (h = board_bladerf_holes)
                standoff(
                    bladerf_x + h[0],
                    bladerf_y + h[1],
                    bladerf_standoff_d,
                    bladerf_screw_d
                );

            // ④ Cora Z7 standoffs (M3, D=3.67mm holes)
            for (h = board_cora_holes)
                standoff(
                    cora_x + h[0],
                    cora_y + h[1],
                    cora_standoff_d,
                    cora_screw_d
                );
        }

        // ⑤ Cable routing slot between boards (through base plate)
        //    Runs along Y axis between the two boards
        translate([slot_x_pos, -0.1, -0.1])
            cube([board_gap, tray_l + 0.2, base_t + 0.2]);

        // ⑥ Ventilation slots under each board (optional — uncomment)
        //    Lengthwise slots for airflow from Noctua fans underneath
        // for (i = [1:3]) {
        //     // Under BladeRF
        //     translate([bladerf_x + bladerf_w * i/4 - 3, bladerf_y + 15, -0.1])
        //         cube([6, bladerf_l - 30, base_t + 0.2]);
        //     // Under Cora
        //     translate([cora_x + cora_w * i/4 - 3, cora_y + 15, -0.1])
        //         cube([6, cora_l - 30, base_t + 0.2]);
        // }
    }
}


// ─────────────────────────────────────────────────────────
// BOARD OUTLINES — ghost preview (not printed)
// ─────────────────────────────────────────────────────────

module board_ghosts() {
    ghost_h = 1.6;   // typical PCB thickness
    z = base_t + standoff_h;

    // BladeRF PCB outline
    %translate([bladerf_x, bladerf_y, z])
        cube([bladerf_w, bladerf_l, ghost_h]);

    // Cora Z7 PCB outline
    %translate([cora_x, cora_y, z])
        cube([cora_w, cora_l, ghost_h]);
}


// ─────────────────────────────────────────────────────────
// CASE OUTLINE — ghost preview (not printed)
// Shows tray position within the case bottom half.
// ─────────────────────────────────────────────────────────

module case_ghost() {
    %translate([-wall_clearance, -wall_clearance, -1])
        difference() {
            cube([case_inner_w, case_inner_l, 1]);
            translate([1, 1, -0.1])
                cube([case_inner_w - 2, case_inner_l - 2, 1.2]);
        }
}


// ─────────────────────────────────────────────────────────
// Render
// ─────────────────────────────────────────────────────────

board_tray();
board_ghosts();     // transparent board outlines
//case_ghost();    // uncomment to see case boundary
