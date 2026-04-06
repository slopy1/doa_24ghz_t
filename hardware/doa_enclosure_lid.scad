// =============================================================================
// DOA Flat Enclosure - LID
// =============================================================================
//
// Mates with doa_enclosure_body.scad. Drops onto the body's perimeter snap
// ledge and is retained by two M3 screws into the body's diagonal corner
// bosses.
//
// Houses a Waveshare ESP32-S3-Touch-LCD-4.3 mounted glass-side up, with
// cables (UART/RS-485/power) feeding down into the enclosure interior.
//
//   PCB outline ............... 106.00 x 68.00 mm
//   Glass ..................... 106.10 x 67.80 mm (≈ flush with PCB)
//   Active area ............... 95.54 x 54.36 mm (800x480)
//   Stack depth ............... 8.80 mm  (glass top -> PCB bottom)
//   Mounting holes ............ 98.00 x 60.00 mm c-to-c, 4 mm edge inset,
//                               2.28 mm dia (measured, M2 clearance)
//   Active area offset ........ 5.23 mm left, 5.33 mm right,
//                               4.35 mm top, 9.09 mm bottom (ASYMMETRIC —
//                               FPC ribbon side has a fatter black frame)
//
// Retention strategy:
//   Solid lid with an active-area window cut through for the screen.
//   On the underside, a U-shaped pocket (walls on the two long sides,
//   open on both short ends for cables) locates the PCB. Four M2 bosses
//   inside the pocket support the PCB; self-tapping screws from below
//   secure it. Cables route out both open short ends into the enclosure.
//
// Print orientation: lid flat on bed, top face up (lip hangs down).
// =============================================================================

$fn = 40;

// =============================================================================
// BODY-DERIVED CONSTANTS  --  keep in sync with doa_enclosure_body.scad
// =============================================================================

wall       = 2.5;
interior_w = 195;
interior_d = 160;
interior_h = 52;      // matches body

enc_w = interior_w + 2*wall;    // 200 mm
enc_d = interior_d + 2*wall;    // 165 mm

ledge_drop = 2;       // distance from wall top down to top of body ledge

// Body's two diagonal M3 retention bosses (interior coords, from body SCAD)
lid_boss_pos = [
    [interior_w - 8,   8],                  // front-right
    [8,                interior_d - 8]      // back-left
];
m3_clear_d = 3.4;

// =============================================================================
// LID GEOMETRY
// =============================================================================

lid_t   = 3.0;    // top plate thickness
lip_t   = 1.2;    // downward lip thickness
lip_clr = 0.3;    // clearance between lip outside face and interior wall
lip_h   = ledge_drop;    // lip drops 2 mm from lid underside to seat on ledge

// =============================================================================
// WAVESHARE ESP32-S3-TOUCH-LCD-4.3 PARAMETERS
// (all values from ESP32-S3-Touch-LCD-4.3-Sch.pdf page 3, unit: mm)
// =============================================================================

ws_pcb_w      = 106.00;
ws_pcb_d      =  68.00;
ws_glass_w    = 106.10;
ws_glass_d    =  67.80;
ws_active_w   =  95.54;
ws_active_d   =  54.36;

// Active area offsets from PCB bottom-left corner, in PCB-local coords.
// Vertical asymmetry: 4.35 top vs 9.09 bottom — the long black frame is on
// the ribbon (bottom) edge. If you rotate the display so the RS-485 J1 port
// faces a specific enclosure edge, the asymmetry rotates with it.
ws_active_off_x = 5.23;   // from left PCB edge  (106.10 - 95.54 - 5.33)
ws_active_off_y = 9.09;   // from "bottom" PCB edge (ribbon side)

// Factory mounting holes — used for M2 screw-down retention.
ws_hole_inset = 4.00;
ws_hole_cx    = 98.00;
ws_hole_cy    = 60.00;
ws_hole_measured_d = 2.28;    // measured; M2 clearance fit

// M2 screw parameters
ws_m2_tap_d    = 1.6;     // M2 self-tap pilot (into plastic boss)
ws_boss_od     = 6.0;     // boss outer diameter
ws_boss_h      = 3.0;     // boss height below lid (PCB rests on these)

// PCB pocket on lid underside — walls on long sides, open on short ends.
ws_pocket_clr  = 0.3;     // clearance between pocket wall and PCB edge
ws_pocket_wall = 1.5;     // pocket side wall thickness
ws_pocket_h    = ws_boss_h;  // pocket depth = boss height (PCB sits on bosses)

// Active area window (cut all the way through for the screen)
ws_win_margin  = 1.0;     // margin around active area
ws_win_w = ws_active_w + 2*ws_win_margin;   // 97.54
ws_win_d = ws_active_d + 2*ws_win_margin;   // 56.36

// Orient the PCB so its long axis runs along the lid's long axis (X).
// Centered on the lid footprint. If you want the RS-485 port (PCB's long
// "bottom" edge) to face a specific enclosure edge, rotate/translate here.
ws_pcb_origin_x = (enc_w - ws_pcb_w) / 2;   // 44.5
ws_pcb_origin_y = (enc_d - ws_pcb_d) / 2;   // 43.5

// =============================================================================
// RENDER
// =============================================================================

difference() {
    union() {
        top_plate();
        lid_lip();
        display_pocket();
        display_mount_bosses();
    }
    body_corner_clearances();
    display_window();
    display_screw_holes();
}

// Uncomment to visualize display placement before printing:
 //%preview_waveshare();

// =============================================================================
// MODULES
// =============================================================================

module top_plate() {
    cube([enc_w, enc_d, lid_t]);
}

// Downward lip that slots inside the body's interior walls and rests on the
// top face of the perimeter snap ledge. In assembled Z-coords, the lid
// top-plate bottom face lands at Z = enc_h and the lip bottom at
// Z = enc_h - lip_h = 43.5, which equals the body's ledge top.
module lid_lip() {
    lip_outer_w = interior_w - 2*lip_clr;
    lip_outer_d = interior_d - 2*lip_clr;

    translate([wall + lip_clr, wall + lip_clr, -lip_h])
    difference() {
        cube([lip_outer_w, lip_outer_d, lip_h + 0.01]);
        translate([lip_t, lip_t, -0.1])
            cube([lip_outer_w - 2*lip_t,
                  lip_outer_d - 2*lip_t,
                  lip_h + 0.3]);
    }
}

// M3 clearance holes through the lid at the body's two diagonal bosses.
module body_corner_clearances() {
    for (pos = lid_boss_pos) {
        translate([wall + pos[0], wall + pos[1], -0.1])
            cylinder(d=m3_clear_d, h=lid_t + 0.2);
    }
}

// PCB pocket: U-channel on the lid underside. Two walls on the long (X)
// sides locate the PCB in Y. Both short (Y) ends are open for cables.
module display_pocket() {
    pocket_inner_w = ws_pcb_w + 2*ws_pocket_clr;
    pocket_inner_d = ws_pcb_d + 2*ws_pocket_clr;

    // Two long-side walls only (no walls on the short/cable ends)
    for (side = [0, 1]) {
        y_off = (side == 0)
            ? ws_pcb_origin_y - ws_pocket_clr - ws_pocket_wall
            : ws_pcb_origin_y + ws_pcb_d + ws_pocket_clr;
        translate([ws_pcb_origin_x - ws_pocket_clr - ws_pocket_wall,
                   y_off,
                   -ws_pocket_h])
            cube([pocket_inner_w + 2*ws_pocket_wall,
                  ws_pocket_wall,
                  ws_pocket_h + 0.01]);
    }
}

// Four bosses inside the pocket at the factory mounting hole positions.
// The PCB rests on these. Connected to the lid plate above.
module display_mount_bosses() {
    for (hx = [ws_hole_inset, ws_hole_inset + ws_hole_cx],
         hy = [ws_hole_inset, ws_hole_inset + ws_hole_cy]) {
        translate([ws_pcb_origin_x + hx,
                   ws_pcb_origin_y + hy,
                   -ws_boss_h])
            cylinder(d=ws_boss_od, h=ws_boss_h + 0.01);
    }
}

// Active area window — cuts through the lid plate only (the pocket
// walls and bosses are outside the active area so they stay intact).
module display_window() {
    win_cx = ws_pcb_origin_x + ws_active_off_x + ws_active_w/2;
    win_cy = ws_pcb_origin_y + ws_active_off_y + ws_active_d/2;
    translate([win_cx - ws_win_w/2,
               win_cy - ws_win_d/2,
               -0.1])
        cube([ws_win_w, ws_win_d, lid_t + 0.2]);
}

// M2 pilot holes through the bosses and lid plate for self-tapping screws.
module display_screw_holes() {
    for (hx = [ws_hole_inset, ws_hole_inset + ws_hole_cx],
         hy = [ws_hole_inset, ws_hole_inset + ws_hole_cy]) {
        translate([ws_pcb_origin_x + hx,
                   ws_pcb_origin_y + hy,
                   -ws_boss_h - 0.1])
            cylinder(d=ws_m2_tap_d, h=ws_boss_h + lid_t + 0.2);
    }
}

// =============================================================================
// PREVIEW (display placement sanity check)
// =============================================================================

module preview_waveshare() {
    // PCB (dark blue) — hangs below the lid plate
    color("navy", 0.5)
    translate([ws_pcb_origin_x, ws_pcb_origin_y, -8.80])
        cube([ws_pcb_w, ws_pcb_d, 1.6]);

    // LCD back stack (grey translucent)
    color("grey", 0.4)
    translate([ws_pcb_origin_x, ws_pcb_origin_y, -8.80 + 1.6])
        cube([ws_pcb_w, ws_pcb_d, 8.80 - 1.6 - 0.5]);

    // Glass (cyan translucent) — pokes up through the lid cutout, ~4 mm
    // above the lid top surface (retained by the bezel above it).
    color("cyan", 0.35)
    translate([ws_pcb_origin_x - (ws_glass_w - ws_pcb_w)/2,
               ws_pcb_origin_y + (ws_pcb_d - ws_glass_d)/2,
               lid_t - 0.1])
        cube([ws_glass_w, ws_glass_d, 0.6]);

    // Active area (green) — verify asymmetry relative to the PCB/cutout
    color("lime", 0.7)
    translate([ws_pcb_origin_x + ws_active_off_x,
               ws_pcb_origin_y + ws_active_off_y,
               lid_t + 0.5])
        cube([ws_active_w, ws_active_d, 0.3]);

    // Factory mounting holes (yellow dots) — documentation only
    color("yellow")
    for (hx = [ws_hole_inset, ws_hole_inset + ws_hole_cx],
         hy = [ws_hole_inset, ws_hole_inset + ws_hole_cy]) {
        translate([ws_pcb_origin_x + hx, ws_pcb_origin_y + hy, -8.80])
            cylinder(d=ws_hole_measured_d, h=2);
    }
}

// =============================================================================
// DIMENSION CHECKS
// =============================================================================

echo("==========================================================");
echo("DOA FLAT ENCLOSURE - LID");
echo("==========================================================");
echo(str("Lid outer: ", enc_w, " x ", enc_d, " x ", lid_t, " mm"));
echo(str("Lip drop: ", lip_h, " mm (seats on body ledge)"));
echo(str("Display window: ", ws_win_w, " x ", ws_win_d,
    " mm (active area + ", ws_win_margin, " mm margin)"));
echo(str("PCB pocket: walls on long sides, open on short ends, depth=",
    ws_pocket_h, " mm"));
echo(str("Display bosses: 4x M2, OD=", ws_boss_od, " mm, height=",
    ws_boss_h, " mm, pilot=", ws_m2_tap_d, " mm"));
