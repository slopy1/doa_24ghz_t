# Portable DoA System - Complete Wiring Diagram
# =============================================

## OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PORTABLE DOA ENCLOSURE                                │
│                                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────────────────┐ │
│  │   BATTERY   │───►│ SPDT SWITCH  │───►│      12V-to-5V BUCK             │ │
│  │  LiFePO4    │    │  (ON/OFF)    │    │      CONVERTER                  │ │
│  │  12.8V 6Ah  │    └──────────────┘    └───────────────┬─────────────────┘ │
│  └──────┬──────┘                                        │                    │
│         │                                               │ 5V Rail            │
│         │ Charge Port                                   ▼                    │
│         │                              ┌────────────────────────────────┐    │
│  ┌──────▼──────┐                       │         WAGO 221 BLOCK         │    │
│  │  DC JACK    │                       │  ┌───┬───┬───┬───┬───┐        │    │
│  │ (Back Panel)│                       │  │ 1 │ 2 │ 3 │ 4 │ 5 │        │    │
│  └─────────────┘                       │  └─┬─┴─┬─┴─┬─┴─┬─┴─┬─┘        │    │
│                                        └────┼───┼───┼───┼───┼──────────┘    │
│                                             │   │   │   │   │               │
│                          ┌──────────────────┘   │   │   │   └─────────┐     │
│                          │                      │   │   │             │     │
│                          ▼                      ▼   │   ▼             ▼     │
│                    ┌───────────┐          ┌─────────┼────────┐   ┌────────┐ │
│                    │ CORA Z7   │          │ BLADERF │        │   │ NOCTUA │ │
│                    │  DC Jack  │          │ DC Jack │        │   │  FAN   │ │
│                    │  (J15)    │          │(2.5mm)  │        │   │  5V    │ │
│                    └───────────┘          └─────────┘        │   └────────┘ │
│                                                              │              │
│                                                              ▼              │
│                                                    ┌─────────────────┐      │
│                                                    │   WAVESHARE     │      │
│                                                    │   ESP32 LCD     │      │
│                                                    │   (5V via VIN)  │      │
│                                                    └─────────────────┘      │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```


## DETAILED CONNECTIONS

### 1. Power Input (Charging)

```
COMPONENT               PIN/TERMINAL          WIRE COLOR    DESTINATION
─────────────────────────────────────────────────────────────────────────────
Panel DC Jack           Center (+)            Red           Battery Charge Input
Panel DC Jack           Sleeve (-)            Black         Battery GND
```

**Notes:**
- 5.5mm x 2.1mm center-positive jack
- Accepts 14.6V LiFePO4 charger
- Charging is independent of system operation


### 2. Power Switch

```
COMPONENT               PIN/TERMINAL          WIRE COLOR    DESTINATION
─────────────────────────────────────────────────────────────────────────────
Battery                 DC5521 Output (+)     Red           Switch Pin 1 (Common)
Switch                  Pin 2 (Normally Open) Red           Buck Converter IN(+)
Battery                 DC5521 Output (-)     Black         Buck Converter IN(-)
```

**Notes:**
- SPDT rocker switch (only using 2 pins as SPST)
- Switch position: ● = ON (system running)
- When OFF, battery is completely disconnected from system


### 3. Buck Converter to Wago Block

```
COMPONENT               PIN/TERMINAL          WIRE COLOR    DESTINATION
─────────────────────────────────────────────────────────────────────────────
Buck Converter          OUT (+) 5V            Red           Wago 221 Slot 1 (+)
Buck Converter          OUT (-)               Black         Wago 221 Slot 1 (-)
```


### 4. 5V Distribution (From Wago Block)

```
WAGO SLOT   DEVICE              CABLE TYPE              NOTES
─────────────────────────────────────────────────────────────────────────────
Slot 1      Buck Converter      14 AWG Input            Power source
Slot 2      Cora Z7             2.1mm barrel pigtail    5V center-positive
Slot 3      BladeRF             2.5mm barrel pigtail    5V center-positive
Slot 4      Waveshare Display   Dupont to VIN           5V to VIN pin
Slot 5      Noctua Fan          Fan connector           5V PWM version
```

**Important: Use a second Wago block for GND distribution!**


### 5. Data Connections

```
SOURCE              PIN/Port        →→→     DESTINATION         Pin/Port
─────────────────────────────────────────────────────────────────────────────
BladeRF             USB-B           →       Powered USB Hub     USB-A port 1
USB-UART Adapter    USB-A           →       Powered USB Hub     USB-A port 2
Powered USB Hub     USB-B upstream  →       Cora Z7             J11 USB-A host
FT232R Adapter      TX (TTL)        →       Waveshare ESP32     GPIO15 (RX)
FT232R Adapter      RX (TTL)        →       Waveshare ESP32     GPIO16 (TX)
FT232R Adapter      GND             →       Waveshare ESP32     GND
```

**UART Settings:** 115200 baud, 8N1

**CRITICAL: Wire directly to ESP32 GPIO pins, NOT to the PH2.0 connector!**
The PH2.0 header has an SP3485 RS485 transceiver that blocks TTL input on the RX direction.
Solder or use jumper wires to reach GPIO15 and GPIO16 directly on the ESP32 board/header.

**USB-UART Adapter:** FTDI FT232R with TTL header pins. Must be 3.3V logic level.
The adapter's USB side plugs into the powered USB hub and appears as `/dev/ttyUSB0` on the Cora.


### 6. RF Connections

```
SOURCE              CONNECTOR       →→→        DESTINATION
─────────────────────────────────────────────────────────────────────────────
BladeRF RX1         SMA             →   SMA Panel Mount → Antenna 1
BladeRF RX2         SMA             →   SMA Panel Mount → Antenna 2
```

**Notes:**
- Use phase-matched SMA cables if extending to panel mounts
- Antenna spacing: 61.2mm (λ/2 at 2.45 GHz)


## GROUND CONNECTIONS

```
All GND terminals connect to common ground plane:

┌─────────────────────────────────────────────────────────────────┐
│                     WAGO 221 (GND Block)                        │
│                                                                  │
│    Battery(-)  Buck(-)  Cora(-)  BladeRF(-)  Display(-)  Fan(-) │
│        │         │        │         │           │          │    │
│        └─────────┴────────┴─────────┴───────────┴──────────┘    │
│                            │                                     │
│                      COMMON GND                                  │
│                  (Copper tape plane)                             │
└─────────────────────────────────────────────────────────────────┘
```


## CABLE/PIGTAIL SPECIFICATIONS

| Purpose                | Cable Type                    | Length   | Notes                    |
|------------------------|-------------------------------|----------|--------------------------|
| Battery to Switch      | 18 AWG silicone               | 10cm     | Red (+)                  |
| Switch to Buck         | 18 AWG silicone               | 15cm     | Red (+)                  |
| Buck to Wago           | 18 AWG silicone               | 10cm     | Red/Black pair           |
| Wago to Cora           | 2.1mm barrel pigtail          | 15cm     | Center-positive          |
| Wago to BladeRF        | 2.1mm-to-2.5mm adapter        | 15cm     | Check BladeRF version    |
| Wago to Display        | Dupont female pigtail         | 20cm     | VIN and GND              |
| Wago to Fan            | Noctua OmniJoin or direct     | 15cm     | 3-pin connector          |
| UART (Cora↔Display)    | 3-wire Dupont                 | 25cm     | TX, RX, GND              |
| USB Data               | USB 3.0 A-to-B, short         | 15cm     | Signal only, no power    |
| SMA extensions         | RG316 or phase-matched        | 10-15cm  | Panel mount              |


## JUMPER SETTINGS

### Cora Z7 (JP3 - Power Select)
```
  ┌─────┐
  │USB│EXT│  ← Set jumper to EXT position
  └─────┘
```

### BladeRF 2.0 micro
- If your board has power select jumpers (J70), verify correct position for DC jack power
- Consult: https://github.com/Nuand/bladeRF/wiki/bladeRF-Accessories


## ASSEMBLY ORDER

1. **Test components individually** before installing in enclosure
2. Install Buck converter (attach to enclosure floor with thermal pad)
3. Mount Wago blocks (use DIN rail or adhesive)
4. Install Cora Z7 on standoffs
5. Install BladeRF on standoffs (10mm gap from Cora)
6. Route power cables to Wago blocks
7. Connect power pigtails to each device
8. Connect UART wires between Cora and Display
9. Connect USB between BladeRF and Cora
10. Mount fan (intake on right wall)
11. Install panel-mount connectors (DC jack, SMA, switch)
12. Final cable management with zip ties
13. Apply copper tape shielding to lid interior
14. Close enclosure and test


## POWER-ON CHECKLIST

Before first power-on:

- [ ] Verify all GND connections are joined
- [ ] Check polarity on all barrel jacks (center = +5V)
- [ ] Confirm Cora Z7 JP3 is set to EXT
- [ ] Measure Buck converter output: should read 5.0V ±0.1V
- [ ] Verify USB cable is connected but not providing power
- [ ] Antennas are attached (never power RF without load!)

Power-on sequence:
1. Connect battery (if removable)
2. Flip switch to ON
3. Wait for Cora Z7 power LED
4. Wait for BladeRF LEDs
5. Wait for Display boot screen
6. System ready when display shows "● Ready"
