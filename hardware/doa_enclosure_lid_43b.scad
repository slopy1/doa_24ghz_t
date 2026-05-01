// =============================================================================
// DOA Flat Enclosure - LID (Waveshare ESP32-S3-Touch-LCD-4.3B BOX)
// =============================================================================
//
// DESIGN 1: Drop-through mount
//
// Mates with doa_enclosure_body.scad (same lip/boss geometry as original lid).
// The Waveshare 4.3B BOX enclosure drops through a cutout from below.
// The front face lip (116.30 x 79.00) rests on the lid top surface.
// Body walls provide XY registration; lip + gravity provide Z retention.
// A USB cable slit on the right side routes a cable into the enclosure.
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
interior_h = 52;

enc_w = interior_w + 2*wall;    // 200 mm
enc_d = interior_d + 2*wall;    // 165 mm

ledge_drop = 2;

lid_boss_pos = [
    [interior_w - 8,   8],
    [8,                interior_d - 8]
];
m3_clear_d = 3.4;

// =============================================================================
// LID GEOMETRY
// =============================================================================

lid_t   = 3.0;    // top plate thickness
lip_t   = 1.2;    // downward lip wall thickness
lip_clr = 0.3;    // clearance between lip and interior wall
lip_h   = ledge_drop;

// =============================================================================
// WAVESHARE ESP32-S3-TOUCH-LCD-4.3B  BOX  PARAMETERS
// (from Waveshare dimensional drawing, unit: mm)
// =============================================================================
//
//   Front face (glass up) ........ 116.30 x 79.00 mm
//   Body (behind lip) ............ 111.30 x 74.00 mm  (tapered shell)
//   Lip step ..................... 2.50 mm all around
//   Total depth .................. 18.00 mm
//   Active area .................. 95.54 x 54.36 mm (800x480)
//   Active area offset ........... 10.38 mm left, 10.38 mm top
//                                  10.38 mm right, 14.26 mm bottom (asymmetric)
//   Mounting holes (back) ........ 75.00 x 59.00 mm c-to-c, M4 brass inserts
//   USB-C port ................... right short edge, 2.50 mm from front face
//   Terminal block ............... bottom edge of back, 52.50 x 3.50 mm protrusion
//
// NOTE: box_body_h = 74.00 is estimated from drawing (front_h - 2*lip_step).
// Measure with calipers and adjust if the vertical taper differs from horizontal.

// Front face dimensions
box_front_w = 116.30;
box_front_h =  79.00;

// Body dimensions (tapered shell behind the front face lip)
box_body_w  = 111.30;
box_body_h  =  74.00;

// Shell taper / lip overhang
box_lip_step = (box_front_w - box_body_w) / 2;   // 2.50 mm

// Total depth
box_depth = 18.00;

// Active area
box_active_w   =  95.54;
box_active_h   =  54.36;
box_active_x   =  10.38;   // from left front face edge
box_active_y_top = 10.38;  // from top front face edge
// bottom border: 79.00 - 54.36 - 10.38 = 14.26 mm

// USB-C port location (right short edge)
usb_c_from_front = 2.50;   // port center, from front face surface
usb_c_port_w     = 10.0;   // clearance width for cable+connector

// =============================================================================
// CUTOUT PARAMETERS
// =============================================================================

body_clr = 0.40;    // clearance around body in through-hole

// Through-hole sized to body (BOX body passes through, lip catches)
cutout_w = box_body_w + 2*body_clr;    // ~112.10
cutout_h = box_body_h + 2*body_clr;    // ~74.80

// =============================================================================
// BOX PLACEMENT ON LID
// =============================================================================
// Centered on lid. USB-C faces right (high-X direction).
// Adjust these if you want to shift the display position.

box_center_x = enc_w / 2;
box_center_y = enc_d / 2;

// Origin = bottom-left corner of front face (in lid coords)
box_origin_x = box_center_x - box_front_w / 2;
box_origin_y = box_center_y - box_front_h / 2;

// Body origin (offset inward by lip step)
body_origin_x = box_origin_x + box_lip_step;
body_origin_y = box_origin_y + box_lip_step;

// =============================================================================
// USB CABLE SLIT
// =============================================================================
// Slit from the cutout's right edge toward the lid perimeter,
// allowing a USB-C cable to route from the BOX port into the enclosure.

usb_slit_w     = 14.0;    // wide enough for USB-C connector + cable
usb_slit_depth = lid_t;   // full lid thickness
// Vertical position: centered on box short edge
usb_slit_y     = box_center_y;

// =============================================================================
// RENDER
// =============================================================================

difference() {
    union() {
        top_plate();
        lid_lip();
    }
    body_corner_clearances();
    box_cutout();
    usb_cable_slit();
}

// Uncomment to visualize display placement:
 %preview_box();

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

// Through-hole cutout: body passes through, front face lip rests on surface.
module box_cutout() {
    translate([body_origin_x - body_clr,
               body_origin_y - body_clr,
               -0.1])
        cube([cutout_w, cutout_h, lid_t + 0.2]);
}

// Slit from cutout right edge to lid right edge for USB cable routing.
// The cable plugs into the BOX's USB-C port (right side) and drops
// through this slit into the enclosure interior.
module usb_cable_slit() {
    slit_x_start = body_origin_x + box_body_w + body_clr;
    slit_x_end   = enc_w + 0.1;
    translate([slit_x_start - 0.1,
               usb_slit_y - usb_slit_w/2,
               -0.1])
        cube([slit_x_end - slit_x_start + 0.2,
              usb_slit_w,
              lid_t + 0.2]);
}

// =============================================================================
// PREVIEW
// =============================================================================

module preview_box() {
    // Front face / glass (dark grey, sits on lid surface)
    color("dimgrey", 0.6)
    translate([box_origin_x, box_origin_y, 0])
        cube([box_front_w, box_front_h, 2.50]);

    // Body (hangs below lid)
    color("black", 0.4)
    translate([body_origin_x, body_origin_y, -(box_depth - box_lip_step)])
        cube([box_body_w, box_body_h, box_depth - box_lip_step]);

    // Active area (green)
    color("lime", 0.7)
    translate([box_origin_x + box_active_x,
               box_origin_y + (box_front_h - box_active_y_top - box_active_h),
               2.6])
        cube([box_active_w, box_active_h, 0.3]);

    // USB-C port indicator (red, right side)
    color("red", 0.8)
    translate([box_origin_x + box_front_w - 0.1,
               box_center_y - 4.5,
               -usb_c_from_front])
        cube([5, 9, 3.5]);
}

// =============================================================================
// DIMENSION CHECKS
// =============================================================================

echo("==========================================================");
echo("DOA FLAT ENCLOSURE - LID (4.3B BOX DROP-THROUGH)");
echo("==========================================================");
echo(str("Lid outer: ", enc_w, " x ", enc_d, " x ", lid_t, " mm"));
echo(str("Cutout (body): ", cutout_w, " x ", cutout_h, " mm (through lid)"));
echo(str("Lip overhang: ", box_lip_step - body_clr, " mm (front face rests on lid)"));
echo(str("BOX front face: ", box_front_w, " x ", box_front_h, " mm"));
echo(str("BOX body: ", box_body_w, " x ", box_body_h, " mm"));
echo(str("BOX center on lid: (", box_center_x, ", ", box_center_y, ")"));
echo(str("USB slit: ", usb_slit_w, " mm wide, right side"));
echo(str("Active area: ", box_active_w, " x ", box_active_h, " mm"));
