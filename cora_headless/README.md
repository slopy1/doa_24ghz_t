# Cora Z7 Headless DoA System

This package contains all the software and documentation for the portable Direction of Arrival (DoA) estimation system based on the BladeRF 2.0 SDR and Cora Z7 FPGA board.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│   ┌──────────────┐      UART       ┌──────────────────────┐    │
│   │   Waveshare  │◄───────────────►│      Cora Z7         │    │
│   │  ESP32 LCD   │   (Commands &   │   (PetaLinux +       │    │
│   │  (Touch UI)  │    Responses)   │    Python Scripts)   │    │
│   └──────────────┘                 └──────────┬───────────┘    │
│                                               │                 │
│                                          USB 2.0               │
│                                          (6 MSPS max)          │
│                                               │                 │
│                                    ┌──────────▼───────────┐    │
│                                    │     BladeRF 2.0      │    │
│                                    │     2×2 MIMO SDR     │    │
│                                    │     (Coherent RX)    │    │
│                                    └──────────┬───────────┘    │
│                                               │                 │
│                                    ┌──────────▼───────────┐    │
│                                    │   2-Element ULA      │    │
│                                    │   λ/2 = 61.2mm       │    │
│                                    │   @ 2.45 GHz         │    │
│                                    └─────────────────────-┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Package Contents

```
cora_headless/
├── README.md                          # This file
├── main.py                            # UART command listener (runs on Cora)
├── phase_calibration_headless.py      # Calibration script
├── aoa_estimation_headless.py         # DoA estimation with multiple algorithms
│
├── display_firmware/
│   └── doa_display_firmware.ino       # ESP32 display firmware (Arduino)
│
├── systemd/
│   └── doa-controller.service         # Auto-start service for Cora
│
└── docs/
    └── WIRING_DIAGRAM.md              # Complete electrical connections
```

## Quick Start

### 1. Deploy to Cora Z7

```bash
# Copy files to Cora (adjust IP/hostname)
scp -r main.py *_headless.py root@cora:/home/root/doa/

# SSH into Cora
ssh root@cora

# Install service
cp doa-controller.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable doa-controller
systemctl start doa-controller
```

### 2. Flash Display Firmware

1. Open `display_firmware/doa_display_firmware.ino` in Arduino IDE
2. Install required libraries:
   - LVGL (v8.x)
   - Board support for ESP32-S3
3. Select board: "ESP32S3 Dev Module" (or Waveshare-specific if available)
4. Flash via USB

### 3. Connect Hardware

Follow the wiring diagram in `docs/WIRING_DIAGRAM.md`.

### 4. First Run

1. Power on the system
2. Wait for display to show "Ready"
3. Tap **CALIBRATE** (with wired setup connected)
4. Record calibration value
5. Tap **ESTIMATE** to begin DoA measurements

## UART Protocol

### Commands (Display → Cora)

| Command            | Description                           |
|--------------------|---------------------------------------|
| `CALIBRATE`        | Run phase calibration                 |
| `ESTIMATE`         | Start DoA with default algorithm      |
| `ESTIMATE:MUSIC`   | Start with specific algorithm         |
| `STATUS`           | Query current state                   |
| `GET_CAL`          | Get calibration coefficient           |
| `SET_CAL:-12.5`    | Manually set calibration (degrees)    |
| `STOP`             | Stop current operation                |
| `SHUTDOWN`         | Safe system shutdown                  |

### Responses (Cora → Display)

| Response           | Description                           |
|--------------------|---------------------------------------|
| `OK:<msg>`         | Command acknowledged                  |
| `AOA:45.2`         | Estimated angle (degrees)             |
| `CAL:-8.7`         | Calibration coefficient (degrees)     |
| `STATUS:IDLE`      | Current state                         |
| `PROGRESS:50`      | Operation progress (0-100%)           |
| `ERROR:<msg>`      | Error message                         |
| `DONE`             | Operation completed                   |

## Supported Algorithms

| Algorithm    | Description                            | Speed    | Accuracy |
|--------------|----------------------------------------|----------|----------|
| `PHASEDIFF`  | Simple phase difference                | Fastest  | Low      |
| `MUSIC`      | Spectral search (181 points)           | Slow     | High     |
| `ROOTMUSIC`  | Polynomial root finding (default)      | Fast     | High     |
| `MVDR`       | Capon beamformer                       | Medium   | Medium   |

## Hardware Constraints

- **USB 2.0 Bandwidth**: Limited to ~6 MSPS (vs 61 MSPS theoretical)
- **Thesis Justification**: "Due to hardware constraints of the FPGA platform, the system operates at reduced bandwidth sufficient for proof-of-concept DoA estimation."

## Calibration

The system requires wired phase calibration before use:

1. Connect signal source via splitter to both RX channels
2. Use matched-length cables
3. Include 30dB attenuator for safety
4. Run calibration for 10+ seconds
5. Record the stable phase offset value

**Typical values**: -30° to +30° depending on hardware

## Troubleshooting

| Symptom                    | Cause                      | Solution                    |
|----------------------------|----------------------------|-----------------------------|
| "Disconnected" on display  | UART not connected         | Check TX/RX wiring          |
| No calibration signal      | Gain too low               | Increase RX gain            |
| Erratic AoA readings       | Missing calibration        | Run CALIBRATE first         |
| AoA stuck at 90°           | No signal / weak signal    | Check antenna connections   |
| System won't power on      | JP3 set to USB             | Set JP3 to EXT              |

## Development

### Testing Without Hardware

Both Python scripts support simulation mode when SoapySDR is unavailable:

```bash
# Test calibration
python phase_calibration_headless.py --duration=5

# Test estimation
python aoa_estimation_headless.py --cal=-10 --algo=ROOTMUSIC --single
```

### Testing main.py Locally

```bash
# Runs in stdin mode when UART unavailable
python main.py

# Enter commands manually:
> STATUS
> CALIBRATE
> ESTIMATE:MUSIC
> STOP
```

## References

- Wachowiak & Kryszkiewicz (2022) - "Angle of arrival estimation in a multi-antenna software defined radio system"
- gr-aoa: https://github.com/MarcinWachowiak/GNU-Radio-USRP-AoA
- BladeRF Wiki: https://github.com/Nuand/bladeRF/wiki
- Cora Z7 Reference: https://digilent.com/reference/programmable-logic/cora-z7/reference-manual

## License

MIT License - DoA Thesis Project 2026
