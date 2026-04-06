// =============================================================================
// DOA Flat Enclosure - BODY
// =============================================================================
//
// Flat rectangular box (no wedge) for BladeRF 2.0 xA4 + Cora Z7
// Side-by-side layout: Cora left, BladeRF right
//
// Cora Z7:   58mm W x 102mm L — Ethernet toward back, DC on left wall
// BladeRF:   63.5mm W x 101.25mm L — SMAs toward back, USB+DC toward front
//
// Back wall:  4x SMA (BladeRF) + 1x Ethernet (Cora)
// Front wall: 1x USB-B + 1x DC barrel (BladeRF) + 1x cable slot (Cora USB)
// Left wall:  1x DC barrel (Cora)
// Left+Right: 40mm fan cutout + 4x M3 screw holes each
//
// Snap-fit lid with optional M3 screw-down at corners
// =============================================================================

$fn = 40;

// =============================================================================
// ENCLOSURE DIMENSIONS
// =============================================================================

wall      = 2.5;
floor_t   = 2.5;

interior_w = 195;    // mm (was 190 — +5mm extra cable clearance around hub)
interior_d = 160;    // mm (was 150 — +10mm for SMA nut clearance + cable bend radius)
interior_h = 52;     // mm (was 43 — extra headroom for fans, cables, display clearance)
// NOTE: doa_enclosure_lid.scad re-declares wall / interior_w / interior_d /
// interior_h / ledge_drop / lid_boss_pos. Keep those two files in sync.

enc_w = interior_w + 2*wall;   // 170mm
enc_d = interior_d + 2*wall;   // 130mm
enc_h = interior_h + floor_t;  // 37.5mm

// =============================================================================
// HARDWARE
// =============================================================================

m3_insert_d  = 4.2;    // M3 heat-set insert hole (Cora, lid bosses)
m3_clear_d   = 3.4;    // M3 clearance hole
m2_insert_d  = 3.2;    // M2 heat-set insert hole (BladeRF)
standoff_od  = 8;       // standoff outer diameter

// =============================================================================
// CORA Z7 PLACEMENT
// =============================================================================
// Cora sits on the left side, 12mm from left interior wall
// Orientation: 58mm across X, 102mm along Y
// Ethernet edge faces back wall, DC barrel on left long edge

cora_pcb_w = 58;
cora_pcb_d = 102;
cora_standoff_h = 6;

// Mounting holes: 94.6mm L x 50.6mm W center-to-center
// Edge to hole center: 3.74mm all corners
cora_hole_cx = 50.6;    // hole c-to-c across X (width)
cora_hole_cy = 94.6;    // hole c-to-c along Y (depth)
cora_hole_edge = 3.74;  // edge to hole center

cora_holes = [
    [cora_hole_edge,                cora_hole_edge],                 // front-left
    [cora_hole_edge + cora_hole_cx, cora_hole_edge],                 // front-right
    [cora_hole_edge,                cora_hole_edge + cora_hole_cy],  // back-left
    [cora_hole_edge + cora_hole_cx, cora_hole_edge + cora_hole_cy]   // back-right
];

// Position of Cora PCB origin (bottom-left corner) in interior coords
cora_pos_x = 12;    // 12mm from left wall — room for DC barrel + cables
cora_pos_y = (interior_d - cora_pcb_d) / 2;   // centered along Y

// =============================================================================
// BLADERF 2.0 xA4 PLACEMENT
// =============================================================================
// BladeRF sits on the right side, 5mm from right interior wall
// Orientation: 63.5mm across X, 101.25mm along Y
// SMA edge faces back wall, USB+DC toward front

bladerf_pcb_w = 63.5;
bladerf_pcb_d = 101.25;
bladerf_standoff_h = 7;

// Mounting holes: 50.74mm W x 82.65mm L center-to-center
bladerf_hole_cx = 50.74;
bladerf_hole_cy = 82.65;

// Hole insets from PCB edges
bladerf_hole_inset_right = 6.50;   // from right PCB edge
bladerf_hole_inset_left  = 6.26;   // from left PCB edge
bladerf_hole_inset_sma   = 12.84;  // from SMA (back) edge
bladerf_hole_inset_front = 5.76;   // from front edge

// Position of BladeRF PCB origin in interior coords
// 5mm gap from right wall
bladerf_pos_x = interior_w - 5 - bladerf_pcb_w;
bladerf_pos_y = (interior_d - bladerf_pcb_d) / 1.6;  // shifted forward (was /2 for centered)

// Hole positions relative to PCB origin
bladerf_holes = [
    [bladerf_hole_inset_left,                     bladerf_hole_inset_front],
    [bladerf_hole_inset_left + bladerf_hole_cx,   bladerf_hole_inset_front],
    [bladerf_hole_inset_left,                     bladerf_hole_inset_front + bladerf_hole_cy],
    [bladerf_hole_inset_left + bladerf_hole_cx,   bladerf_hole_inset_front + bladerf_hole_cy]
];

// =============================================================================
// ANTENNA BULKHEAD SMA (back wall, 2x at λ/2 spacing)
// =============================================================================
// Two SMA bulkhead pass-throughs for the DoA antenna array.
// Centered on the back wall with 62.5mm spacing (λ/2 at 2.4 GHz).
// A center-mark indent on the outside marks the midpoint for alignment.

ant_spacing    = 62.5;     // λ/2 at 2.4 GHz
ant_sma_d      = 6.5;      // SMA bulkhead clearance hole
ant_center_x   = interior_w / 2;   // centered on back wall
ant_z_center   = floor_t + interior_h / 2;  // centered vertically (~24mm)
ant_mark_w     = 1.0;      // center-mark notch width
ant_mark_h     = 5.0;      // center-mark notch height (vertical line)
ant_mark_depth = 0.8;      // how deep the mark cuts into the wall

// =============================================================================
// FRONT WALL PORTS (BladeRF USB-B + DC barrel)
// =============================================================================

bladerf_pcb_top_z = floor_t + bladerf_standoff_h + 1.6;

// USB-B: center at ~31.75mm from left PCB edge
usb_b_w = 13;      // width with clearance
usb_b_h = 12;      // height with clearance
usb_b_pcb_offset_x = 31.75;  // from left PCB edge
usb_b_z_center = bladerf_pcb_top_z + 6;  // ~6mm above PCB

// DC barrel (BladeRF): center at ~52.5mm from left PCB edge
bladerf_dc_dia = 11;  // diameter with clearance
bladerf_dc_pcb_offset_x = 52.5;
bladerf_dc_z_center = bladerf_pcb_top_z + 5.5;

// (Hub DC barrel jack params moved below USB HUB section)

// =============================================================================
// FRONT WALL: ETHERNET (Cora)
// =============================================================================
// Ethernet is on the short edge facing front (58mm edge)
// Centered on that short edge

cora_pcb_top_z = floor_t + cora_standoff_h + 1.6;

eth_w = 16;     // width with clearance
eth_h = 14;     // height with clearance
eth_x_center = cora_pos_x + cora_pcb_w/2;   // centered on Cora width
eth_z_center = cora_pcb_top_z + eth_h/2 + 0.5;

// =============================================================================
// LEFT WALL: DC BARREL (Cora)
// =============================================================================
// Cora DC barrel is on the left long edge (102mm edge)
// Approximate position: ~15mm from front edge of Cora

cora_dc_dia = 11;
cora_dc_y_offset = 15;   // from front Cora edge along Y
cora_dc_z_center = cora_pcb_top_z + 5;

// =============================================================================
// FAN CUTOUTS (left and right walls)
// =============================================================================

fan_hole_d  = 40;       // 40mm fan opening
fan_screw_spacing = 32; // M3 screw hole spacing for 40mm fan
fan_screw_d = 3.4;      // M3 clearance

// Fan centered vertically (raised so circle clears floor) and along wall depth
fan_z_center = floor_t + interior_h/2 + 1;  // +1mm to avoid tangent at Z=0
fan_y_center = enc_d/2;

// =============================================================================
// USB HUB (Atolla powered hub, in the gap between Cora and BladeRF)
// =============================================================================
// Hub body: 110mm L (along Y) x 44mm W (across X) x 23.35mm H
// Sits on the enclosure floor between the two boards.

hub_l = 110;    // along Y
hub_w = 44;     // across X
hub_h = 23.35;

// Center the hub in the X gap between Cora and BladeRF
hub_gap_x_start = cora_pos_x + cora_pcb_w;                    // right edge of Cora footprint
hub_gap_x_end   = bladerf_pos_x;                              // left edge of BladeRF footprint
hub_pos_x = hub_gap_x_start + (hub_gap_x_end - hub_gap_x_start - hub_w) / 2;

// Y position: centered along interior depth (TODO: adjust if USB ports need
// to face front for cable access)
hub_pos_y = (interior_d - hub_l) / 2;

// Retainer style — change this to preview each option:
//   1 = (a) Four corner posts (free drop-in, no snap force)
//   2 = (b) Side walls with inward snap lips (locks down, long sides closed)
//   3 = (d) End clips only (locks down, long sides open for airflow + cables)
hub_retainer_style = 1;

// =============================================================================
// FRONT WALL: USB HUB DC BARREL JACK
// =============================================================================
// Replaces the old Cora USB cable slot. The hub's barrel jack exits
// through the front wall, roughly centered on the hub's X position.

hub_dc_dia = 13;     // generous clearance — fits most 5.5mm barrel jacks
hub_dc_x_center = hub_pos_x + hub_w/2;   // centered on hub
hub_dc_z_center = floor_t + hub_h/2;      // centered on hub height

// =============================================================================
// SNAP-FIT LEDGE
// =============================================================================
// Inner shelf: 1.5mm wide, 1.5mm tall, running 2mm below top edge
// This runs around the full interior perimeter

ledge_width  = 1.5;
ledge_height = 1.5;
ledge_drop   = 2;    // distance from top edge to top of ledge

// =============================================================================
// LID BOSS / CORNER ALIGNMENT BOSSES
// =============================================================================

lid_boss_d = 8;

// Two diagonal bosses at front-right and back-left interior corners.
// The snap-fit ledge provides primary retention around the full perimeter;
// these two M3 screw points just resist lid lift-off. Diagonal placement
// anchors one screw over the BladeRF front corner and the other over the
// Cora back corner. Clears all 8 board standoffs in 3D.
lid_boss_pos = [
    [interior_w - 8,   8],                  // front-right
    [8,                interior_d - 8]      // back-left
];

// =============================================================================
// RENDER
// =============================================================================

difference() {
    union() {
        shell();
        snap_fit_ledge();
        cora_standoffs();
        bladerf_standoffs();
        lid_bosses();
        usb_hub_retainer();   // TODO: you decide the retention style — see module below
    }

    antenna_bulkhead_holes();
    antenna_center_mark();
    ethernet_cutout();
    front_usb_b_cutout();
    front_dc_barrel_cutout();
    front_hub_dc_cutout();
    left_dc_barrel_cutout();
    fan_cutouts();
}

// Preview boards — uncomment to visualize:
 %preview_boards();

// =============================================================================
// MODULES
// =============================================================================

// --- Main shell (flat rectangular box) ---
module shell() {
    difference() {
        cube([enc_w, enc_d, enc_h]);
        translate([wall, wall, floor_t])
            cube([interior_w, interior_d, interior_h + 1]);
    }
}

// --- Snap-fit ledge (inner shelf around perimeter) ---
// Extend 0.1mm into walls to avoid coincident faces (non-manifold)
module snap_fit_ledge() {
    ledge_z = floor_t + interior_h - ledge_drop - ledge_height;
    overlap = 0.1;

    translate([wall - overlap, wall - overlap, ledge_z])
    difference() {
        cube([interior_w + 2*overlap, interior_d + 2*overlap, ledge_height]);
        translate([ledge_width + overlap, ledge_width + overlap, -0.1])
            cube([interior_w - 2*ledge_width,
                  interior_d - 2*ledge_width,
                  ledge_height + 0.2]);
    }
}

// --- Cora Z7 standoffs ---
module cora_standoffs() {
    for (h = cora_holes) {
        translate([wall + cora_pos_x + h[0],
                   wall + cora_pos_y + h[1],
                   floor_t - 0.1])
        difference() {
            cylinder(d=standoff_od, h=cora_standoff_h + 0.1);
            cylinder(d=m3_insert_d, h=cora_standoff_h + 1);
        }
    }
}

// --- BladeRF standoffs ---
module bladerf_standoffs() {
    for (h = bladerf_holes) {
        translate([wall + bladerf_pos_x + h[0],
                   wall + bladerf_pos_y + h[1],
                   floor_t - 0.1])
        difference() {
            cylinder(d=standoff_od, h=bladerf_standoff_h + 0.1);
            cylinder(d=m2_insert_d, h=bladerf_standoff_h + 1);
        }
    }
}

// --- USB hub retainer (dispatches on hub_retainer_style) ---
module usb_hub_retainer() {
    if      (hub_retainer_style == 1) hub_retainer_posts_a();
    else if (hub_retainer_style == 2) hub_retainer_side_walls_b();
    else if (hub_retainer_style == 3) hub_retainer_end_clips_d();
}

// (a) Four corner posts — hub drops between them, no snap force
module hub_retainer_posts_a() {
    post_size = 3;
    post_tol  = 0.4;
    // Offsets from the hub origin for the four corner posts (each post sits
    // just outside the hub corner with post_tol clearance on both axes)
    corner_offsets = [
        [-post_size - post_tol, -post_size - post_tol],  // front-left
        [hub_w + post_tol,      -post_size - post_tol],  // front-right
        [-post_size - post_tol, hub_l + post_tol],       // back-left
        [hub_w + post_tol,      hub_l + post_tol]        // back-right
    ];
    for (c = corner_offsets)
        translate([wall + hub_pos_x + c[0], wall + hub_pos_y + c[1], floor_t])
            cube([post_size, post_size, hub_h]);
}

// (b) Side walls with inward snap lips on the long (110mm) edges
module hub_retainer_side_walls_b() {
    tol     = 0.4;
    wall_t  = 2;
    lip_in  = 1;      // how far the lip projects inward from the wall face
    lip_h   = 1.5;    // vertical thickness of the lip (sits above hub top)
    wall_y  = hub_pos_y - tol;
    wall_len = hub_l + 2*tol;
    for (side = [-1, 1]) {
        x_wall = (side == -1) ? hub_pos_x - tol - wall_t : hub_pos_x + hub_w + tol;
        x_lip  = (side == -1) ? hub_pos_x - tol          : hub_pos_x + hub_w + tol - lip_in;
        translate([wall + x_wall, wall + wall_y, floor_t])
            cube([wall_t, wall_len, hub_h + lip_h]);
        translate([wall + x_lip,  wall + wall_y, floor_t + hub_h])
            cube([lip_in, wall_len, lip_h]);
    }
}

// (d) End clips — short walls with snap lips on the 44mm ends only
module hub_retainer_end_clips_d() {
    tol     = 0.4;
    wall_t  = 2;
    lip_in  = 1;
    lip_h   = 1.5;
    clip_x  = hub_pos_x - tol;
    clip_len = hub_w + 2*tol;
    for (side = [-1, 1]) {
        y_wall = (side == -1) ? hub_pos_y - tol - wall_t : hub_pos_y + hub_l + tol;
        y_lip  = (side == -1) ? hub_pos_y - tol          : hub_pos_y + hub_l + tol - lip_in;
        translate([wall + clip_x, wall + y_wall, floor_t])
            cube([clip_len, wall_t, hub_h + lip_h]);
        translate([wall + clip_x, wall + y_lip,  floor_t + hub_h])
            cube([clip_len, lip_in, lip_h]);
    }
}

// --- Lid corner bosses ---
module lid_bosses() {
    boss_h = interior_h - ledge_drop;  // up to just below ledge top
    for (pos = lid_boss_pos) {
        translate([wall + pos[0], wall + pos[1], floor_t - 0.1])
        difference() {
            cylinder(d=lid_boss_d, h=boss_h + 0.1);
            cylinder(d=m3_insert_d, h=boss_h + 1);
        }
    }
}

// --- Antenna bulkhead SMA holes (back wall) ---
module antenna_bulkhead_holes() {
    for (side = [-1, 1]) {
        translate([wall + ant_center_x + side * ant_spacing/2,
                   enc_d - wall - 0.1,
                   ant_z_center])
            rotate([-90, 0, 0])
                cylinder(d=ant_sma_d, h=wall + 0.2);
    }
}

// --- Center mark between the two antenna holes (back wall exterior) ---
module antenna_center_mark() {
    // Vertical slit
    translate([wall + ant_center_x - ant_mark_w/2,
               enc_d - ant_mark_depth,
               ant_z_center - ant_mark_h/2])
        cube([ant_mark_w, ant_mark_depth + 0.1, ant_mark_h]);

    // "λ/2" engraved above the slit
    translate([wall + ant_center_x,
               enc_d + 0.01,
               ant_z_center + ant_mark_h/2 + 2])
        rotate([90, 0, 0])
            mirror([1, 0, 0])
                linear_extrude(height = ant_mark_depth + 0.1)
                    text("λ/2", size=5, halign="center", valign="bottom",
                         font="DejaVu Sans");
}

// --- Ethernet cutout (front wall, Cora) ---
module ethernet_cutout() {
    translate([wall + eth_x_center - eth_w/2,
               -0.1,
               eth_z_center - eth_h/2])
        cube([eth_w, wall + 0.2, eth_h]);
}

// --- USB-B cutout (front wall, BladeRF) ---
module front_usb_b_cutout() {
    usb_x = bladerf_pos_x + usb_b_pcb_offset_x;
    translate([wall + usb_x - usb_b_w/2,
               -0.1,
               usb_b_z_center - usb_b_h/2])
        cube([usb_b_w, wall + 0.2, usb_b_h]);
}

// --- DC barrel cutout (front wall, BladeRF) ---
module front_dc_barrel_cutout() {
    dc_x = bladerf_pos_x + bladerf_dc_pcb_offset_x;
    translate([wall + dc_x, -0.1, bladerf_dc_z_center])
        rotate([-90, 0, 0])
            cylinder(d=bladerf_dc_dia, h=wall + 0.2);
}

// --- USB hub DC barrel jack (front wall) ---
module front_hub_dc_cutout() {
    translate([wall + hub_dc_x_center, -0.1, hub_dc_z_center])
        rotate([-90, 0, 0])
            cylinder(d=hub_dc_dia, h=wall + 0.2);
}

// --- DC barrel cutout (left wall, Cora) ---
module left_dc_barrel_cutout() {
    dc_y = cora_pos_y + cora_dc_y_offset;
    translate([-0.1, wall + dc_y, cora_dc_z_center])
        rotate([0, 90, 0])
            cylinder(d=cora_dc_dia, h=wall + 0.2);
}

// --- Fan cutouts (left and right walls) ---
module fan_cutouts() {
    // Left wall
    translate([-0.1, fan_y_center, fan_z_center])
    rotate([0, 90, 0]) {
        cylinder(d=fan_hole_d, h=wall + 0.2);
        for (dx=[-1,1], dy=[-1,1])
            translate([dy*fan_screw_spacing/2, dx*fan_screw_spacing/2, 0])
                cylinder(d=fan_screw_d, h=wall + 0.2);
    }

    // Right wall
    translate([enc_w - wall - 0.1, fan_y_center, fan_z_center])
    rotate([0, 90, 0]) {
        cylinder(d=fan_hole_d, h=wall + 0.2);
        for (dx=[-1,1], dy=[-1,1])
            translate([dy*fan_screw_spacing/2, dx*fan_screw_spacing/2, 0])
                cylinder(d=fan_screw_d, h=wall + 0.2);
    }
}

// =============================================================================
// PREVIEW BOARDS
// =============================================================================

module preview_boards() {
    // --- Cora Z7 PCB (green) ---
    color("green", 0.4)
    translate([wall + cora_pos_x,
               wall + cora_pos_y,
               floor_t + cora_standoff_h])
        cube([cora_pcb_w, cora_pcb_d, 1.6]);

    // Cora hole markers (yellow)
    color("yellow")
    for (h = cora_holes)
        translate([wall + cora_pos_x + h[0],
                   wall + cora_pos_y + h[1],
                   floor_t + cora_standoff_h + 1.6])
            cylinder(d=3, h=3);

    // --- BladeRF PCB (red) ---
    color("red", 0.4)
    translate([wall + bladerf_pos_x,
               wall + bladerf_pos_y,
               floor_t + bladerf_standoff_h])
        cube([bladerf_pcb_w, bladerf_pcb_d, 1.6]);

    // BladeRF hole markers (cyan)
    color("cyan")
    for (h = bladerf_holes)
        translate([wall + bladerf_pos_x + h[0],
                   wall + bladerf_pos_y + h[1],
                   floor_t + bladerf_standoff_h + 1.6])
            cylinder(d=3, h=3);

    // --- Antenna bulkheads (gold) ---
    color("gold")
    for (side = [-1, 1]) {
        translate([wall + ant_center_x + side * ant_spacing/2,
                   enc_d - wall,
                   ant_z_center])
            rotate([-90, 0, 0])
                cylinder(d=9.5, h=15);
    }
    // Center mark indicator (red)
    color("red")
    translate([wall + ant_center_x, enc_d + 0.1, ant_z_center])
        sphere(d=3);

    // --- Front port indicators (orange) ---
    color("orange", 0.6) {
        // USB-B
        usb_x = bladerf_pos_x + usb_b_pcb_offset_x;
        translate([wall + usb_x - usb_b_w/2, -5, usb_b_z_center - usb_b_h/2])
            cube([usb_b_w, 5, usb_b_h]);
        // DC barrel (BladeRF)
        dc_x = bladerf_pos_x + bladerf_dc_pcb_offset_x;
        translate([wall + dc_x, -5, bladerf_dc_z_center])
            rotate([-90, 0, 0])
                cylinder(d=bladerf_dc_dia, h=5);
        // Hub DC barrel
        translate([wall + hub_dc_x_center, -5, hub_dc_z_center])
            rotate([-90, 0, 0])
                cylinder(d=hub_dc_dia, h=5);
    }

    // --- Ethernet indicator (blue) ---
    color("blue", 0.6)
    translate([wall + eth_x_center - eth_w/2, -5, eth_z_center - eth_h/2])
        cube([eth_w, 5, eth_h]);

    // --- Cora DC barrel indicator (purple) ---
    color("purple", 0.6) {
        dc_y = cora_pos_y + cora_dc_y_offset;
        translate([-5, wall + dc_y, cora_dc_z_center])
            rotate([0, 90, 0])
                cylinder(d=cora_dc_dia, h=5);
    }

    // --- USB hub body (grey translucent) ---
    color("grey", 0.5)
    translate([wall + hub_pos_x, wall + hub_pos_y, floor_t])
        cube([hub_w, hub_l, hub_h]);

    // --- Gap annotation ---
    gap = bladerf_pos_x - (cora_pos_x + cora_pcb_w);
    echo(str("Gap between boards: ", gap, "mm"));
    echo(str("Hub clearance in gap (each side): ", (gap - hub_w) / 2, "mm"));
}

// =============================================================================
// DIMENSION CHECKS
// =============================================================================

echo("==========================================================");
echo("DOA FLAT ENCLOSURE - BODY");
echo("==========================================================");
echo(str("Exterior: ", enc_w, " x ", enc_d, " x ", enc_h, "mm"));
echo(str("Interior: ", interior_w, " x ", interior_d, " x ", interior_h, "mm"));
echo(str("Wall: ", wall, "mm   Floor: ", floor_t, "mm"));
echo("");

echo("--- CORA Z7 ---");
echo(str("  PCB: ", cora_pcb_w, " x ", cora_pcb_d, "mm"));
echo(str("  Position (interior): X=", cora_pos_x, "  Y=", cora_pos_y));
echo(str("  Clearance right edge: ",
    bladerf_pos_x - (cora_pos_x + cora_pcb_w), "mm (gap to BladeRF)"));
echo(str("  Clearance left wall: ", cora_pos_x, "mm"));
echo(str("  Clearance back wall: ",
    interior_d - (cora_pos_y + cora_pcb_d), "mm"));
echo(str("  Standoff height: ", cora_standoff_h, "mm"));

echo("");
echo("--- BLADERF 2.0 xA4 ---");
echo(str("  PCB: ", bladerf_pcb_w, " x ", bladerf_pcb_d, "mm"));
echo(str("  Position (interior): X=", bladerf_pos_x, "  Y=", bladerf_pos_y));
echo(str("  Clearance right wall: ",
    interior_w - (bladerf_pos_x + bladerf_pcb_w), "mm"));
echo(str("  Clearance back wall: ",
    interior_d - (bladerf_pos_y + bladerf_pcb_d), "mm"));
echo(str("  Standoff height: ", bladerf_standoff_h, "mm"));

echo("");
echo("--- USB HUB ---");
echo(str("  Hub: ", hub_w, " x ", hub_l, " x ", hub_h, "mm"));
echo(str("  Position (interior): X=", hub_pos_x, "  Y=", hub_pos_y));
echo(str("  Gap clearance per side: ",
    (bladerf_pos_x - (cora_pos_x + cora_pcb_w) - hub_w) / 2, "mm"));

echo("");
echo("--- SNAP-FIT ---");
echo(str("  Ledge: ", ledge_width, "mm wide, ", ledge_height, "mm tall"));
echo(str("  Ledge top Z: ", floor_t + interior_h - ledge_drop, "mm"));
echo(str("  Enclosure top Z: ", enc_h, "mm"));

echo("");
echo("--- ANTENNA BULKHEADS (back wall) ---");
echo(str("  Spacing: ", ant_spacing, " mm (lambda/2 at 2.4 GHz)"));
echo(str("  Center X: ", wall + ant_center_x, " mm from left edge"));
echo(str("  Left SMA X: ", wall + ant_center_x - ant_spacing/2, " mm"));
echo(str("  Right SMA X: ", wall + ant_center_x + ant_spacing/2, " mm"));
echo(str("  Z height: ", ant_z_center, " mm"));

echo("");
echo(">>> Uncomment %preview_boards() to visualize board placement <<<");
echo(">>> Adjust cora_dc_y_offset after test-fitting Cora board <<<");
