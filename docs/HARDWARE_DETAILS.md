# Hardware Details — Portable Enclosure & Components

## Portable Enclosure

**Enclosure:** Meijia portable case, IP67 rated.

| Dimension | Imperial | Metric |
|-----------|----------|--------|
| Outside | 11.65 x 8.35 x 3.78" | 296 x 212 x 96mm |
| Inside | 10.54 x 6.04 x 3.16" | 268 x 153 x 80mm |
| Lid depth | 1.08" | 27.4mm |
| Bottom depth | 2.08" | 52.8mm |

Display mounts in lid (27.4mm deep — display at 8.6mm fits with 18.8mm to spare). All other components in bottom half.

## Display Bezel

3D-printed flat-frame mount. Source files:
- `hardware/display_bezel.scad` (OpenSCAD parametric source)
- `hardware/display_bezel.stl` and `.3mf` (exported)
- `hardware/ASSEMBLY.md` (install instructions)

Design: flat frame sits on lid exterior, display drops through cut hole from inside, optional back retainer clamps from behind.

## Display Measurements (Waveshare 4.3" 800x480)

- PCB: 106.33 x 68.2 x 8.6mm
- Glass (full incl. black frame): 106.2 x 67.8mm
- Glass/module thickness: 4.89mm
- Active area: 92.2 x 57.4mm (black border: 4.5mm top, 9.5mm bottom, 5.2mm each side)
- Bezel window: set to full glass (106.2 x 67.8mm)
- Bezel outer: ~120.8 x 82.4 x 2.5mm frame
- Lid hole to cut: ~106.9 x 68.8mm

## Components & Power

| Component | Power | Notes |
|-----------|-------|-------|
| Cora Z7 | 5V via barrel jack | JP3 set to EXT |
| BladeRF 2.0 xA4 | 5V via barrel jack (2A+) | TPS2115A auto-selects barrel over USB |
| Waveshare 4.3" display | 5V via USB-C | Mounts in lid, communicates via UART |
| Powered USB hub (Atolla) | 5V/3A own adapter | BladeRF USB + FT232R USB through hub |
| FT232R adapter | USB-powered from hub | TTL wires to ESP32 GPIO15/16 |
| 2-element ULA | Passive | lambda/2 = 61.2mm spacing @ 2.45 GHz |
| Battery | TalentCell LiFePO4 12.8V 6Ah | |
| DC-DC converter | Tobsun EA25-5V | 12.8V -> 5V, 25W |
| Power distribution | Wago 221 lever nuts | 5V bus to all devices |

## BladeRF Power Supply

The Cora Z7 USB-A host port (J11) provides limited current. The BladeRF 2.0 xA4 should be externally powered via its DC barrel jack (5V, 2A+, 5.5x2.5mm center-positive). Power options:
- **Bench supply**: 5V 2A current limit, alligator clips to barrel jack breakout wires
- **Portable**: TalentCell LiFePO4 (~13V) -> Tobsun EA25-5V 25W DC-DC converter -> 5V barrel jack
- **Wall adapter**: Any 5V 2A+ supply with 5.5x2.5mm center-positive barrel plug

The BladeRF's TPS2115A power mux auto-selects the barrel jack over USB when external power is present. Plug barrel jack first, then USB.

## Antennas

- **2x Linx ANT-2.4-CW-RCL** — 2.4 GHz helical whip, SMA, ~1 inch tall. Mounted on BladeRF RX1/RX2.
- Known issue: floppy hinge, needs to be stabilized (hot glue, heat shrink, or rigid bracket mount).

## Calibration Hardware

- **Mini-Circuits VAT-30A+** — 30 dB SMA fixed attenuator (DC-6 GHz, 1W). Place before splitter to protect BladeRF (max input ~0 dBm).
- **2-way power splitter** + **2x matched-length SMA cables** — for wired phase calibration.
- Connected as of 2026-03-18.

## Bottom Layout (approximate)

```
+----------------------------------+
|  BladeRF 2.0 xA4    |  Cora Z7  |
|  168 x 100 mm       |  89x89    |
|                      |           |
+----------------------+  USB Hub  |
|  TalentCell Battery  |  DC-DC    |
|  150 x 100 mm        |  Wago    |
+----------------------------------+
         ~296 x 212 mm
```

See `docs/WIRING_DIAGRAM.md` for detailed wiring and `docs/system_block_diagram.drawio` for the system block diagram.
