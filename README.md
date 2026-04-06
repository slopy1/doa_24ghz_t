# DOA-24GHz: Direction-of-Arrival Estimation at 2.4 GHz

**Portable, real-time DoA estimation using a 2-element antenna array on an embedded FPGA platform**

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![GNU Radio 3.10](https://img.shields.io/badge/GNU%20Radio-3.10-green.svg)](https://www.gnuradio.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This thesis project implements a portable Direction of Arrival (DoA) estimation system at 2.4 GHz. A **Digilent Cora Z7** (Zynq-7000 SoC) runs PetaLinux with GNU Radio and custom DoA algorithms, receiving coherent IQ data from a **BladeRF 2.0 xA4** two-channel SDR. The system is self-contained in a battery-powered enclosure with a touchscreen display and web-based control interface.

Four DoA algorithms are implemented:
- **Root-MUSIC** (default) — polynomial root finding, fast and accurate
- **MUSIC** — spectral search with pseudo-spectrum visualization
- **MVDR** (Capon) — minimum variance beamformer
- **Phase Difference** — simple and fast baseline

Based on: Wachowiak & Kryszkiewicz (2022) — *"Angle of arrival estimation in a multi-antenna software defined radio system"*

## Hardware

| Component | Model | Purpose |
|-----------|-------|---------|
| FPGA SoC | Digilent Cora Z7 (Zynq-7000) | Runs PetaLinux + GNU Radio headlessly |
| SDR | Nuand BladeRF 2.0 xA4 | 2-channel coherent receiver |
| Antennas | 2x Linx ANT-2.4-CW-RCL | Half-wavelength spaced ULA (61.2 mm) |
| Display | Waveshare ESP32-S3 4.3" Touch LCD | LVGL touch UI via UART |
| Signal source | nRF5340 DK | Zephyr radio_test at 2.418 GHz |
| Power | TalentCell LiFePO4 12.8V + DC-DC buck | Portable battery operation |

See [docs/HARDWARE_DETAILS.md](docs/HARDWARE_DETAILS.md) for enclosure dimensions and wiring.

## RF Parameters

| Parameter | Value |
|-----------|-------|
| Center frequency | 2.412–2.484 GHz (WiFi Ch 1–14) |
| Sample rate | 1 MS/s |
| RX bandwidth | 1 MHz |
| Antenna spacing | 61.2 mm (lambda/2 at 2.45 GHz) |
| Array type | 2-element Uniform Linear Array |

## User Interfaces

**Web Dashboard** (primary) — Connect a browser to `http://<cora-ip>:8080` for real-time DoA control with SVG gauge, algorithm selection, calibration, and live console.

**Touch Display** — Waveshare ESP32-S3 with LVGL arc gauge and algorithm selector, communicating via UART.

## Repository Structure

```
doa_24ghz_thesis/
├── cora_headless/             # Headless system deployed on Cora Z7
│   ├── web_dashboard.py       #   Web UI (HTTP + SSE, zero dependencies)
│   ├── main.py                #   UART display controller
│   ├── aoa_estimation_headless.py    # DoA algorithms (SoapySDR + NumPy)
│   ├── phase_calibration_headless.py # Wired phase calibration
│   ├── display_firmware/      #   ESP32 LVGL touch display firmware
│   ├── initd/                 #   SysVinit auto-start script
│   └── udev/                  #   USB permission rules
├── gnuradio_flowgraphs/       # GNU Radio Companion flowgraphs
│   ├── aoa_estimation_bladerf.grc          # Real-time DoA (Qt GUI)
│   ├── phase_calibration_bladerf.grc       # Phase calibration (Qt GUI)
│   └── channel_sweep_bladerf.grc           # WiFi channel sweep (Qt GUI)
├── scripts/
│   ├── sweep_channels.py      # WiFi ch 1-14 sweep characterization
│   ├── collect_dataset.py     # HDF5 data collection (offline)
│   ├── analyze_dataset.py     # Post-processing pipeline (offline)
│   └── ...                    # Setup and utility scripts
├── src/doa24/                 # Python analysis package (offline use)
├── hardware/                  # 3D-printed enclosure (OpenSCAD + STL)
├── docs/                      # Design docs, wiring, changelog
├── configs/                   # Experiment/receiver YAML configs
└── fpga/                      # Future FPGA acceleration notes
```

## Quick Start

### On Cora Z7 (deployed system)

```bash
# Deploy scripts from host PC
scp cora_headless/*.py petalinux@192.168.1.100:/home/petalinux/doa/

# Start web dashboard
ssh petalinux@192.168.1.100 "python3 /home/petalinux/doa/web_dashboard.py &"

# Open browser to http://192.168.1.100:8080
```

See [docs/DEMO_QUICKSTART.md](docs/DEMO_QUICKSTART.md) for the full demo procedure.

### On host PC (simulation, no hardware needed)

```bash
git clone https://github.com/slopy1/doa_24ghz_t.git
cd doa_24ghz_t
pip install -r requirements.txt

# Run channel sweep in simulation mode
python scripts/sweep_channels.py --true-angle 90 --channels 1 6 11

# Open flowgraph in GNU Radio Companion
gnuradio-companion gnuradio_flowgraphs/channel_sweep_bladerf.grc
```

## WiFi Channel Sweep

The sweep script characterizes DoA accuracy across the 2.4 GHz band:

```bash
# Full 14-channel sweep with known source angle
python scripts/sweep_channels.py --true-angle 90 --cal -12.5

# Quick test on common non-overlapping WiFi channels
python scripts/sweep_channels.py --channels 1 6 11 --estimates 50 --true-angle 90
```

Outputs CSV data, comparison plots (mean AoA + std dev vs channel), and error analysis (MAE + RMSE) to `results/`.

## Calibration

Wired phase calibration using a signal source, attenuator, and power splitter:

```
Signal Source (nRF5340 @ 2.418 GHz)
    → VAT-30A+ 30 dB attenuator
    → 2-way power splitter
        → Matched cable → BladeRF RX1
        → Matched cable → BladeRF RX2
```

Run via web dashboard "Calibrate" button or directly:
```bash
python cora_headless/phase_calibration_headless.py --freq 2.418e9 --duration 10
```

## Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG](docs/CHANGELOG.md) | All additions and changes |
| [DEMO_QUICKSTART](docs/DEMO_QUICKSTART.md) | Step-by-step demo procedure |
| [DEMO_COMMANDS](docs/DEMO_COMMANDS.txt) | Command reference for nRF + Cora |
| [HARDWARE_DETAILS](docs/HARDWARE_DETAILS.md) | Enclosure, components, power |
| [BUILD_HISTORY](docs/BUILD_HISTORY.md) | Yocto/PetaLinux build errors and fixes |
| [BOOT_AUTONOMY](docs/BOOT_AUTONOMY.md) | Auto-start and init script design |
| [WIRING_DIAGRAM](cora_headless/docs/WIRING_DIAGRAM.md) | Electrical connections |
| [ASSEMBLY](hardware/ASSEMBLY.md) | Enclosure assembly instructions |
| [bibliography](docs/bibliography.md) | Academic references |
| [fpga_mapping](docs/fpga_mapping.md) | Future FPGA acceleration design |
| [INSTALL_GUIDE](INSTALL_GUIDE.md) | Host PC software setup |

## PetaLinux / Yocto Build

The Cora Z7 image is built with PetaLinux 2025.2 (Yocto Scarthgap). Custom recipes provide:
- GNU Radio 3.10.12 (headless)
- SoapySDR 0.8.1 + SoapyBladeRF 0.4.1
- libbladeRF 2.6.0
- gr-aoa 1.0.0 ([MarcinWachowiak/gr-aoa](https://github.com/MarcinWachowiak/gr-aoa))

See [docs/BUILD_HISTORY.md](docs/BUILD_HISTORY.md) for the full build log and cross-compilation fixes.

## License

MIT License
