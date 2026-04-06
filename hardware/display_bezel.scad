/* =========================================================
   Waveshare 4.3" Display Flat-Frame Bezel
   For Meijia Portable Case  (295.9 x 212.1mm lid)

   Display PCB:    106.33 x 68.2 x 8.6mm
   Glass measured: 106.2  x 67.8mm (full glass incl. black frame)
   Active area:    ~95    x 54mm   (inside black frame — window opening)

   Why flat frame (not a deep channel):
     Lid interior depth ≈ 9-10mm  (12.52mm rim - ~3mm panel)
     Display depth     =  8.6mm  → barely fits, no room for a channel
     Solution: frame sits on lid EXTERIOR, display drops straight
     through a cut hole into the lid interior — glass presses
     against the frame back surface from inside.

   Install order:
     1. Print bezel() face-down, lid_template() flat
     2. Lay lid_template on lid exterior, trace & cut hole
     3. M3 screws or 2mm bead of silicone fix frame to lid exterior
     4. From inside, push display glass against frame window
     5. Run a bead of silicone around PCB edges from inside
     6. Optional: print back_retainer() and screw in for positive lock

   Print settings:
     Orientation : face DOWN (flat on bed — cleanest window edges)
     Layer height : 0.15 mm
     Infill       : 40%
     Supports     : none needed
   ========================================================= */


// ── ADJUST THESE ──────────────────────────────────────────

// Screen window opening = full glass (including black border frame)
// Measured from display face
screen_l = 106.2;   // mm  (full glass, long axis)
screen_w =  67.8;   // mm  (full glass, short axis)

// Fit tolerance on each side of PCB channel (back pocket + lid hole)
// 0.25 = snug | 0.4 = loose
clearance = 0.30;   // mm per side

// Frame thickness (how far screen glass sits below lid surface)
// Thicker = stronger frame, deeper recess. 2.5mm is a good balance.
face_t    = 2.5;    // mm

// Frame border width around the PCB pocket
border    = 7.0;    // mm each side

// Rounded corners
corner_r  = 4.0;    // mm

// Screw holes (M3 pilot, screws come from inside case through lid)
screw_d   = 2.8;    // mm  (2.8 for M3 pilot / heat-insert OD)


// ── FIXED — from datasheet / measurement ─────────────────

pcb_l = 106.33;
pcb_w =  68.20;
pcb_t =   8.60;    // used for back_retainer standoff reference only


// ── DERIVED ───────────────────────────────────────────────

chan_l  = pcb_l + 2 * clearance;   // lid hole to cut = this
chan_w  = pcb_w + 2 * clearance;
outer_l = chan_l + 2 * border;
outer_w = chan_w + 2 * border;

// Back pocket depth: shallow register that centers display on frame
pocket_d = 1.0;    // mm — just enough to locate the PCB

$fn = 64;

echo("─── Bezel dimensions ────────────────────────────────");
echo(str("  Frame (L x W x thick):    ", outer_l, " x ", outer_w, " x ", face_t, " mm"));
echo(str("  CUT LID HOLE (L x W):     ", chan_l,  " x ", chan_w,  " mm"));
echo(str("  Screen window (L x W):    ", screen_l, " x ", screen_w, " mm"));
echo(str("  Border around window:     ", (outer_l-screen_l)/2, " mm each side"));
echo("─────────────────────────────────────────────────────");


// ─────────────────────────────────────────────────────────
// Helper
// ─────────────────────────────────────────────────────────

module rounded_box(l, w, h, r) {
    hull() {
        for (xi = [r, l - r])
        for (yi = [r, w - r])
            translate([xi, yi, 0])
                cylinder(r = r, h = h);
    }
}


// ─────────────────────────────────────────────────────────
// MAIN BEZEL  — print this face-down
// ─────────────────────────────────────────────────────────
//
//  Front (outside of case):
//  ┌─────────────────────────────────────────┐
//  │  ●                                  ●  │  ← corner screw holes
//  │     ┌─────────────────────────────┐     │
//  │     │   SCREEN WINDOW  (air)      │     │
//  │     └─────────────────────────────┘     │
//  │  ●                                  ●  │
//  └─────────────────────────────────────────┘
//  Back (inside of case / against lid):
//  ┌─────────────────────────────────────────┐
//  │     ┌───────────────────────────────┐   │  ← 1mm back pocket
//  │     │  LID HOLE + PCB fits here     │   │    (locates display)
//  │     └───────────────────────────────┘   │
//  └─────────────────────────────────────────┘
//  Display glass rests against the frame back surface
//  around the pocket opening. PCB drops through lid hole.

module bezel() {
    difference() {

        // ① Flat plate
        rounded_box(outer_l, outer_w, face_t, corner_r);

        // ② Screen window — centered, full depth
        translate([(outer_l - screen_l) / 2,
                   (outer_w - screen_w) / 2,
                   -0.1])
            cube([screen_l, screen_w, face_t + 0.2]);

        // ③ Back pocket — shallow recess, matches lid hole
        //   Display glass edge rests on the 1mm step around this opening
        translate([(outer_l - chan_l) / 2,
                   (outer_w - chan_w) / 2,
                   face_t - pocket_d])
            cube([chan_l, chan_w, pocket_d + 0.1]);

        // ④ Corner pilot holes (M3 screws from inside lid)
        si = border / 2;
        for (x = [si, outer_l - si])
        for (y = [si, outer_w - si])
            translate([x, y, -0.1])
                cylinder(d = screw_d, h = face_t + 0.2);
    }
}


// ─────────────────────────────────────────────────────────
// LID CUTTING TEMPLATE  — print flat, place on lid, trace
// Outer outline = frame footprint
// Inner cutout  = the hole to cut through the lid
// ─────────────────────────────────────────────────────────

module lid_template() {
    template_t = 1.2;    // thin — just for tracing
    wall       = 2.0;    // keep inner + outer reference

    translate([0, -(outer_w + 12), 0])
    difference() {
        // Outer reference (same footprint as bezel frame)
        rounded_box(outer_l, outer_w, template_t, corner_r);

        // Inner cutout = lid hole
        translate([(outer_l - chan_l) / 2,
                   (outer_w - chan_w) / 2,
                   -0.1])
            cube([chan_l, chan_w, template_t + 0.2]);
    }
}


// ─────────────────────────────────────────────────────────
// BACK RETAINER  — optional, print separately
// Locks display from inside. Screws through lid into bezel
// pilot holes. Add M3 x 10mm screws + 3.5mm spacers/washers
// to span the lid thickness.
// ─────────────────────────────────────────────────────────

module back_retainer() {
    ret_t = 2.0;

    translate([outer_l + 12, 0, 0])
    difference() {
        rounded_box(outer_l, outer_w, ret_t, corner_r);

        // Central window — clears display body, retains by edges only
        // Make it 4mm smaller each side than the PCB
        inset = 4.0;
        translate([(outer_l - chan_l + inset) / 2,
                   (outer_w - chan_w + inset) / 2,
                   -0.1])
            cube([chan_l - inset, chan_w - inset, ret_t + 0.2]);

        // Corner holes matching bezel pilot holes
        si = border / 2;
        for (x = [si, outer_l - si])
        for (y = [si, outer_w - si])
            translate([x, y, -0.1])
                cylinder(d = screw_d, h = ret_t + 0.2);
    }
}


// ─────────────────────────────────────────────────────────
// Render — comment/uncomment as needed
// ─────────────────────────────────────────────────────────

bezel();
// lid_template();    // uncomment to also render cutting template
// back_retainer();   // uncomment to also render back retainer
