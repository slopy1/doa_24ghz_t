// =============================================================================
// DOA Flat Enclosure - LID
// =============================================================================
//
// Mates with doa_enclosure_body.scad. Drops onto the body's perimeter snap
// ledge and is retained by two M3 screws into the body's diagonal corner
// bosses (front-left and back-right).
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
//   Two slide-in rails on the long sides form channels that capture the
//   PCB edges. The display slides in from the front short end (low-Y)
//   and a stop wall at the back short end (high-Y) prevents over-insertion.
//   A small detent bump near the entry provides friction retention.
//   Front short end stays open for cable routing.
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
    [8,                8],                  // front-left
    [interior_w - 8,   interior_d - 8]      // back-right
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

// Factory mounting holes — not used for slide-in retention, kept for reference.
// ws_hole_inset = 4.00;
// ws_hole_cx    = 98.00;
// ws_hole_cy    = 60.00;
// ws_hole_measured_d = 2.28;

// Slide-in rail parameters
ws_rail_clr    = 0.3;     // clearance between rail channel and PCB edge
ws_rail_wall   = 1.5;     // rail outer wall thickness
ws_rail_lip    = 2.5;     // inward lip width that captures PCB edge
ws_rail_h      = 3.0;     // rail height below lid (total channel depth)
ws_pcb_t       = 1.6;     // PCB thickness (channel slots PCB into this layer)
ws_rail_chan_h  = ws_pcb_t + 0.4;  // channel slot height (PCB + clearance)

// Stop wall at back end (high-Y) prevents over-insertion
ws_stop_wall   = 1.5;     // stop wall thickness

// Detent bump near entry for friction retention
ws_detent_h    = 0.4;     // bump height into channel
ws_detent_w    = 8.0;     // bump width along rail
ws_detent_pos  = 10.0;    // distance from entry end (low-Y PCB edge)

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
        display_slide_rails();
        display_stop_wall();
        display_detent_bumps();
    }
    body_corner_clearances();
    display_window();
    display_rail_channels();
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
// top face of the perimeter snap ledge.
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

// Slide-in rails: two solid bars on the long (X) sides of the display area.
// Each rail runs the full PCB length plus stop wall. The inward lip that
// captures the PCB edge is cut out by display_rail_channels() below.
module display_slide_rails() {
    rail_len = ws_pcb_w + 2*ws_rail_clr + ws_stop_wall;

    for (side = [0, 1]) {
        y_off = (side == 0)
            ? ws_pcb_origin_y - ws_rail_clr - ws_rail_wall
            : ws_pcb_origin_y + ws_pcb_d + ws_rail_clr;
        translate([ws_pcb_origin_x - ws_rail_clr,
                   y_off,
                   -ws_rail_h])
            cube([rail_len,
                  ws_rail_wall,
                  ws_rail_h + 0.01]);

        // Inward lip — extends from the rail wall toward PCB center
        translate([ws_pcb_origin_x - ws_rail_clr,
                   (side == 0)
                       ? ws_pcb_origin_y - ws_rail_clr
                       : ws_pcb_origin_y + ws_pcb_d + ws_rail_clr - ws_rail_lip,
                   -ws_rail_h])
            cube([rail_len,
                  ws_rail_lip,
                  ws_rail_h + 0.01]);
    }
}

// Channel slots cut into the rails — the PCB edges slide through here.
// The channel is at the top of the rail (against the lid underside) so the
// PCB hangs at the correct depth. Below the channel, the lip supports the PCB.
module display_rail_channels() {
    // Channel runs the full rail length minus the stop wall
    chan_len = ws_pcb_w + 2*ws_rail_clr + 0.2;

    for (side = [0, 1]) {
        y_off = (side == 0)
            ? ws_pcb_origin_y - ws_rail_clr
            : ws_pcb_origin_y + ws_pcb_d + ws_rail_clr - ws_rail_lip;
        translate([ws_pcb_origin_x - ws_rail_clr - 0.1,
                   y_off,
                   -ws_rail_chan_h])
            cube([chan_len,
                  ws_rail_lip + 0.1,
                  ws_rail_chan_h + 0.01]);
    }
}

// Stop wall at the back short end (high-X) prevents over-insertion.
// The display slides in from the front (low-X) end.
module display_stop_wall() {
    stop_x = ws_pcb_origin_x + ws_pcb_w + ws_rail_clr;
    translate([stop_x,
               ws_pcb_origin_y - ws_rail_clr - ws_rail_wall,
               -ws_rail_h])
        cube([ws_stop_wall,
              ws_pcb_d + 2*ws_rail_clr + 2*ws_rail_wall,
              ws_rail_h + 0.01]);
}

// Small detent bumps on each rail's inner lip near the entry end.
// These provide friction retention so the display doesn't slide out.
module display_detent_bumps() {
    for (side = [0, 1]) {
        y_pos = (side == 0)
            ? ws_pcb_origin_y - ws_rail_clr + 0.1
            : ws_pcb_origin_y + ws_pcb_d + ws_rail_clr - 0.1;
        // Bump sits inside the channel, protruding inward
        translate([ws_pcb_origin_x + ws_detent_pos,
                   y_pos,
                   -ws_rail_chan_h/2])
            rotate([0, 0, 0])
            scale([1, (side == 0) ? -1 : 1, 1])
            // Half-cylinder bump
            rotate([0, 90, 0])
            cylinder(d=ws_detent_h*2, h=ws_detent_w, $fn=20);
    }
}

// Active area window — cuts through the lid plate.
module display_window() {
    win_cx = ws_pcb_origin_x + ws_active_off_x + ws_active_w/2;
    win_cy = ws_pcb_origin_y + ws_active_off_y + ws_active_d/2;
    translate([win_cx - ws_win_w/2,
               win_cy - ws_win_d/2,
               -0.1])
        cube([ws_win_w, ws_win_d, lid_t + 0.2]);
}

// =============================================================================
// PREVIEW (display placement sanity check)
// =============================================================================

module preview_waveshare() {
    // PCB (dark blue) — hangs below the lid plate in the rail channels
    color("navy", 0.5)
    translate([ws_pcb_origin_x, ws_pcb_origin_y, -ws_pcb_t])
        cube([ws_pcb_w, ws_pcb_d, ws_pcb_t]);

    // LCD back stack (grey translucent)
    color("grey", 0.4)
    translate([ws_pcb_origin_x, ws_pcb_origin_y, -8.80])
        cube([ws_pcb_w, ws_pcb_d, 8.80 - ws_pcb_t - 0.5]);

    // Glass (cyan translucent)
    color("cyan", 0.35)
    translate([ws_pcb_origin_x - (ws_glass_w - ws_pcb_w)/2,
               ws_pcb_origin_y + (ws_pcb_d - ws_glass_d)/2,
               lid_t - 0.1])
        cube([ws_glass_w, ws_glass_d, 0.6]);

    // Active area (green)
    color("lime", 0.7)
    translate([ws_pcb_origin_x + ws_active_off_x,
               ws_pcb_origin_y + ws_active_off_y,
               lid_t + 0.5])
        cube([ws_active_w, ws_active_d, 0.3]);

    // Slide direction arrow (red) — shows insertion direction
    color("red", 0.8)
    translate([ws_pcb_origin_x - 15, ws_pcb_origin_y + ws_pcb_d/2, -ws_pcb_t/2])
        rotate([0, 90, 0])
        cylinder(d=2, h=12, $fn=12);
}

// =============================================================================
// DIMENSION CHECKS
// =============================================================================

echo("==========================================================");
echo("DOA FLAT ENCLOSURE - LID (SLIDE-IN)");
echo("==========================================================");
echo(str("Lid outer: ", enc_w, " x ", enc_d, " x ", lid_t, " mm"));
echo(str("Lip drop: ", lip_h, " mm (seats on body ledge)"));
echo(str("Display window: ", ws_win_w, " x ", ws_win_d,
    " mm (active area + ", ws_win_margin, " mm margin)"));
echo(str("Slide rails: lip=", ws_rail_lip, " mm, channel=",
    ws_rail_chan_h, " mm (PCB ", ws_pcb_t, " + 0.4 clr)"));
echo(str("Stop wall: ", ws_stop_wall, " mm at high-X end"));
echo(str("Detent bumps: ", ws_detent_h, " mm x ", ws_detent_w,
    " mm, ", ws_detent_pos, " mm from entry"));
