/* =========================================================
   Antenna Bracket — 2-element ULA mount for Meijia case lid

   Holds two SMA bulkhead connectors at exactly λ/2 spacing
   (61.2mm center-to-center @ 2.45 GHz).

   Mounts on the lid exterior, centered along the top long
   edge (opposite hinges, away from display cutout).

   Antennas fold flat when lid is closed, flip up 90° for use.

   Cross-section (lid closed):
       outside
   ┌────────────────────────┐
   │  ant1 (flat)  ant2     │  ← antennas folded
   │  ┌──┐  61.2mm  ┌──┐   │
   │  │SMA│         │SMA│   │  ← bracket
   ├──┴──┴──────────┴──┴────┤
   │        LID             │
   └────────────────────────┘
       inside

   Print settings:
     Orientation : flat on bed (mounting face down)
     Layer height: 0.15-0.20 mm
     Infill      : 50%+ (small part, needs rigidity)
     Supports    : none
     Material    : PETG preferred
   ========================================================= */


// ── ANTENNA PARAMETERS ─────────────────────────────────

// λ/2 spacing at 2.45 GHz
element_spacing = 61.2;        // mm center-to-center

// SMA bulkhead barrel diameter (standard = 6.35mm / 1/4")
// Measure yours and adjust if different
sma_barrel_d = 6.35;           // mm — hole for the SMA barrel
sma_clearance = 0.2;           // mm — fit tolerance per side
sma_hole_d = sma_barrel_d + 2 * sma_clearance;  // = 6.75mm

// SMA nut flat-to-flat (hex nut that tightens from inside)
// Standard SMA nut is ~8mm across flats
sma_nut_af = 8.0;              // mm across flats
sma_nut_h  = 3.0;              // mm nut height
// Hex recess diameter (circumscribed circle of hex)
sma_nut_d  = sma_nut_af / cos(30);  // ~9.24mm


// ── BRACKET PARAMETERS ─────────────────────────────────

// Bracket body
bracket_t   = 5.0;            // mm — thickness (SMA barrel + nut must fit)
bracket_h   = 16.0;           // mm — height (short axis, perpendicular to lid edge)
bracket_pad = 10.0;           // mm — padding beyond each SMA hole

// Derived length
bracket_l = element_spacing + 2 * bracket_pad;  // ~81.2mm

// Corner rounding
corner_r = 3.0;               // mm

// Mounting holes (M3 screws to attach bracket to lid)
mount_screw_d = 3.2;          // mm — M3 clearance hole
// Mounting holes placed at each end of the bracket
mount_inset_x = bracket_pad / 2;   // mm from bracket ends
mount_inset_y = bracket_h / 2;     // mm — centered vertically

$fn = 60;


// ── DERIVED POSITIONS ──────────────────────────────────

// SMA holes centered vertically, spaced along length
sma1_x = bracket_pad;                        // = 10mm from left edge
sma1_y = bracket_h / 2;
sma2_x = bracket_pad + element_spacing;      // = 71.2mm from left edge
sma2_y = bracket_h / 2;

echo("─── Antenna Bracket ─────────────────────────────────");
echo(str("  Element spacing:    ", element_spacing, " mm (λ/2 @ 2.45 GHz)"));
echo(str("  Bracket (L×H×T):    ", bracket_l, " × ", bracket_h, " × ", bracket_t, " mm"));
echo(str("  SMA hole diameter:  ", sma_hole_d, " mm"));
echo(str("  SMA 1 position:     (", sma1_x, ", ", sma1_y, ")"));
echo(str("  SMA 2 position:     (", sma2_x, ", ", sma2_y, ")"));
echo("─────────────────────────────────────────────────────");


// ── HELPERS ────────────────────────────────────────────

module rounded_rect(l, w, h, r) {
    hull() {
        for (xi = [r, l - r])
        for (yi = [r, w - r])
            translate([xi, yi, 0])
                cylinder(r = r, h = h);
    }
}

// Hexagonal recess for SMA nut (cut from bottom)
module hex_recess(af, h) {
    d = af / cos(30);
    cylinder(d = d, h = h, $fn = 6);
}


// ── MAIN BRACKET ───────────────────────────────────────

module antenna_bracket() {
    difference() {
        // ① Solid body
        rounded_rect(bracket_l, bracket_h, bracket_t, corner_r);

        // ② SMA barrel holes (through)
        for (pos = [[sma1_x, sma1_y], [sma2_x, sma2_y]]) {
            translate([pos[0], pos[1], -0.1])
                cylinder(d = sma_hole_d, h = bracket_t + 0.2);
        }

        // ③ Hex nut recesses on bottom face (so nut sits flush)
        for (pos = [[sma1_x, sma1_y], [sma2_x, sma2_y]]) {
            translate([pos[0], pos[1], -0.1])
                hex_recess(sma_nut_af, sma_nut_h + 0.1);
        }

        // ④ Mounting screw holes (M3, through)
        for (mx = [mount_inset_x, bracket_l - mount_inset_x]) {
            translate([mx, mount_inset_y, -0.1])
                cylinder(d = mount_screw_d, h = bracket_t + 0.2);
        }
    }
}


// ── LID DRILL TEMPLATE (optional) ─────────────────────
// Thin plate with hole positions marked — tape to lid,
// drill through the marked holes.

module lid_template() {
    template_t = 1.2;    // thin enough to print fast

    difference() {
        rounded_rect(bracket_l, bracket_h, template_t, corner_r);

        // SMA holes (mark only, same diameter)
        for (pos = [[sma1_x, sma1_y], [sma2_x, sma2_y]]) {
            translate([pos[0], pos[1], -0.1])
                cylinder(d = sma_hole_d, h = template_t + 0.2);
        }

        // Mounting holes
        for (mx = [mount_inset_x, bracket_l - mount_inset_x]) {
            translate([mx, mount_inset_y, -0.1])
                cylinder(d = mount_screw_d, h = template_t + 0.2);
        }
    }
}


// ── RENDER ─────────────────────────────────────────────

// Uncomment the part you want to export:

antenna_bracket();
//lid_template();
