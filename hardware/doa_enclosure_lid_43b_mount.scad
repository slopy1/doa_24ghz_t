// =============================================================================
// DOA Flat Enclosure - LID (Waveshare 4.3B BOX — M4 Surface Mount)
// =============================================================================
//
// DESIGN 2: M4 screw-through surface mount (flat-printable, no supports)
//
// Mates with doa_enclosure_body.scad (same lip/boss geometry as original lid).
// The Waveshare 4.3B BOX sits directly on the lid TOP surface (glass up).
// Four M4 screws from inside the enclosure pass through the lid and thread
// into the BOX's brass M4 inserts (75 x 59 mm pattern on the back panel).
// A relief slot lets the terminal block drop through the lid instead of
// needing standoffs (keeps the lid fully flat and support-free).
// A USB cable slit routes the cable into the enclosure.
//
// Print orientation: top face DOWN on bed (best surface finish for visible
// face). Registration walls and lip print upward — no supports needed.
// =============================================================================

$fn = 40;

// =============================================================================
// BODY-DERIVED CONSTANTS  --  keep in sync with doa_enclosure_body.scad
// =============================================================================

wall       = 2.5;
interior_w = 195;
interior_d = 160;
interior_h = 52;

enc_w = interior_w + 2*wall;    // 200 mm
enc_d = interior_d + 2*wall;    // 165 mm

ledge_drop = 2;

lid_boss_pos = [
    [8,                8],                  // front-left
    [interior_w - 8,   interior_d - 8]      // back-right
];
m3_clear_d = 3.4;

// =============================================================================
// LID GEOMETRY
// =============================================================================

lid_t   = 3.0;
lip_t   = 1.2;
lip_clr = 0.3;
lip_h   = ledge_drop;

// =============================================================================
// WAVESHARE ESP32-S3-TOUCH-LCD-4.3B  BOX  PARAMETERS
// (same parameter block as Design 1 — keep in sync)
// =============================================================================

box_front_w = 116.30;
box_front_h =  79.00;
box_body_w  = 111.30;
box_body_h  =  74.00;

box_lip_step = (box_front_w - box_body_w) / 2;   // 2.50 mm

box_depth = 18.00;

box_active_w   =  95.54;
box_active_h   =  54.36;
box_active_x   =  10.38;
box_active_y_top = 10.38;

// M4 mounting holes — positions relative to front face bottom-left corner.
// Back panel is inset by box_lip_step horizontally. Holes are centered
// horizontally on the back panel. Vertically: top holes 15mm from top,
// bottom holes 74mm from top (of the 79mm front face).
// NOTE: verify these positions with calipers on your unit.
box_m4_h_spacing = 75.00;
box_m4_v_spacing = 59.00;

box_m4_holes = [
    [(box_front_w - box_m4_h_spacing)/2, box_front_h - 15.00],  // top-left
    [(box_front_w + box_m4_h_spacing)/2, box_front_h - 15.00],  // top-right
    [(box_front_w - box_m4_h_spacing)/2, box_front_h - 74.00],  // bottom-left
    [(box_front_w + box_m4_h_spacing)/2, box_front_h - 74.00],  // bottom-right
];

m4_clear_d   = 4.5;    // M4 clearance hole
m4_cbore_d   = 8.0;    // M4 counterbore diameter (cap head)
m4_cbore_h   = 3.5;    // counterbore depth (underside of lid)

// Terminal block relief slot — the terminal block protrudes 3.50 mm from the
// BOX back and would prevent the BOX from sitting flat. Instead of standoffs,
// we cut a slot through the lid and let the block drop through. Zero supports.
term_block_w       = 52.50;    // terminal block width
term_block_depth   =  8.00;    // slot depth (Y direction, generous clearance)
term_block_clr     =  1.00;    // clearance around block

// USB-C port
usb_c_from_back = box_depth - 2.50;
usb_c_port_w    = 10.0;

// =============================================================================
// BOX PLACEMENT ON LID
// =============================================================================
// BOX sits on lid surface (back face down, glass up).
// Centered on lid. USB-C faces right (high-X).

box_center_x = enc_w / 2;
box_center_y = enc_d / 2;

box_origin_x = box_center_x - box_front_w / 2;
box_origin_y = box_center_y - box_front_h / 2;

// =============================================================================
// USB CABLE SLIT
// =============================================================================
// Through-lid slit on the USB side (right). The USB-C port is on the
// short edge of the BOX, above the lid surface. This slit lets the
// cable drop through the lid into the enclosure.

usb_slit_w     = 14.0;
usb_slit_len   = 20.0;    // how far the slit extends from BOX edge toward lid edge
usb_slit_y     = box_center_y;

// =============================================================================
// REGISTRATION FRAME
// =============================================================================
// Low walls on the lid surface that cradle the BOX back panel, preventing
// lateral sliding. Runs along the long edges of the BOX (leaving short
// edges open for USB access and terminal block clearance).

reg_wall_h = 3.0;    // height of registration wall
reg_wall_t = 1.5;    // thickness
reg_clr    = 0.4;    // clearance to BOX body

// =============================================================================
// RENDER
// =============================================================================

difference() {
    union() {
        top_plate();
        lid_lip();
        registration_walls();
    }
    body_corner_clearances();
    m4_through_holes();
    terminal_block_slot();
    usb_cable_slit();
}

// Uncomment to visualize display placement:
// %preview_box();

// =============================================================================
// MODULES
// =============================================================================

module top_plate() {
    cube([enc_w, enc_d, lid_t]);
}

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

module body_corner_clearances() {
    for (pos = lid_boss_pos) {
        translate([wall + pos[0], wall + pos[1], -0.1])
            cylinder(d=m3_clear_d, h=lid_t + 0.2);
    }
}

// M4 clearance holes straight through the 3mm lid.
// Counterbore on underside for M4 cap head screw.
// BOX back sits flat on the lid — no standoffs needed.
module m4_through_holes() {
    for (hole = box_m4_holes) {
        hx = box_origin_x + hole[0];
        hy = box_origin_y + hole[1];

        // Clearance hole through lid
        translate([hx, hy, -0.1])
            cylinder(d=m4_clear_d, h=lid_t + 0.2);

        // Counterbore on lid underside for screw head
        translate([hx, hy, -m4_cbore_h])
            cylinder(d=m4_cbore_d, h=m4_cbore_h + 0.1);
    }
}

// Relief slot for the terminal block — cuts through the full lid thickness.
// The terminal block (52.50mm wide, bottom edge of BOX back) drops through
// this slot so the rest of the BOX back sits flat on the lid surface.
module terminal_block_slot() {
    // Terminal block is centered on the BOX width, at the bottom edge
    // of the back panel (low-Y side when BOX origin is bottom-left).
    slot_w = term_block_w + 2*term_block_clr;
    slot_d = term_block_depth + term_block_clr;

    slot_x = box_origin_x + box_front_w/2 - slot_w/2;
    // Bottom edge of body (back panel) — the terminal block is here
    slot_y = box_origin_y + box_lip_step - term_block_clr;

    translate([slot_x, slot_y, -0.1])
        cube([slot_w, slot_d, lid_t + 0.2]);
}

// Low walls along the long (X) edges of the BOX body to prevent lateral
// sliding. BOX back sits flat on the lid surface between these walls.
// Short edges left open for USB access (right) and terminal block slot (left).
module registration_walls() {
    body_x = box_origin_x + box_lip_step;
    body_y = box_origin_y + box_lip_step;

    reg_len = box_body_w + 2*reg_clr;

    for (side = [0, 1]) {
        y_pos = (side == 0)
            ? body_y - reg_clr - reg_wall_t
            : body_y + box_body_h + reg_clr;
        translate([body_x - reg_clr, y_pos, lid_t])
            cube([reg_len, reg_wall_t, reg_wall_h]);
    }
}

// Through-lid slit for USB cable routing.
// Located on the right short edge of the BOX.
module usb_cable_slit() {
    slit_x_start = box_origin_x + box_front_w;
    translate([slit_x_start - 2,
               usb_slit_y - usb_slit_w/3,
               -0.1])
        cube([usb_slit_len + 2,
              usb_slit_w,
              lid_t + 0.2]);
}

// =============================================================================
// PREVIEW
// =============================================================================

module preview_box() {
    box_z = lid_t;   // BOX back sits directly on lid surface

    // Back panel / body (black)
    color("black", 0.4)
    translate([box_origin_x + box_lip_step,
               box_origin_y + box_lip_step,
               box_z])
        cube([box_body_w, box_body_h, box_depth - box_lip_step]);

    // Front face / glass bezel (dark grey, on top)
    color("dimgrey", 0.6)
    translate([box_origin_x,
               box_origin_y,
               box_z + box_depth - box_lip_step])
        cube([box_front_w, box_front_h, box_lip_step]);

    // Active area (green)
    color("lime", 0.7)
    translate([box_origin_x + box_active_x,
               box_origin_y + (box_front_h - box_active_y_top - box_active_h),
               box_z + box_depth + 0.1])
        cube([box_active_w, box_active_h, 0.3]);

    // USB-C port indicator (red, right side)
    color("red", 0.8)
    translate([box_origin_x + box_front_w - 0.1,
               box_center_y - 4.5,
               box_z + box_depth - 2.50 - 1.75])
        cube([5, 9, 3.5]);

    // M4 screw indicators (gold)
    color("gold")
    for (hole = box_m4_holes) {
        translate([box_origin_x + hole[0],
                   box_origin_y + hole[1],
                   box_z - 0.1])
            cylinder(d=6, h=2);
    }

    // Terminal block indicator (drops through slot, green)
    color("darkgreen", 0.6)
    translate([box_origin_x + box_front_w/2 - 52.50/2,
               box_origin_y + box_lip_step,
               box_z - 3.50])
        cube([52.50, 3.50, 3.50]);
}

// =============================================================================
// DIMENSION CHECKS
// =============================================================================

echo("==========================================================");
echo("DOA FLAT ENCLOSURE - LID (4.3B BOX M4 SURFACE MOUNT)");
echo("==========================================================");
echo(str("Lid outer: ", enc_w, " x ", enc_d, " x ", lid_t, " mm"));
echo(str("BOX front face: ", box_front_w, " x ", box_front_h, " mm"));
echo(str("BOX sits flat on lid — no standoffs"));
echo(str("M4 pattern: ", box_m4_h_spacing, " x ", box_m4_v_spacing, " mm"));
echo(str("Terminal block slot: ", term_block_w + 2*term_block_clr,
    " x ", term_block_depth + term_block_clr, " mm (through lid)"));
echo(str("USB slit: ", usb_slit_w, " x ", usb_slit_len, " mm, right side"));
echo(str("BOX top surface Z: ", lid_t + box_depth, " mm above lid bottom"));
echo(str("Counterbore: ", m4_cbore_d, " dia x ", m4_cbore_h, " deep (underside)"));
echo(str("M4 holes at:"));
for (i = [0:3])
    echo(str("  [", box_m4_holes[i][0], ", ", box_m4_holes[i][1],
        "] -> lid coords [",
        box_origin_x + box_m4_holes[i][0], ", ",
        box_origin_y + box_m4_holes[i][1], "]"));
