# DOA-24GHz: Direction-of-Arrival Estimation at 2.4 GHz

**Portable, real-time DoA estimation using a 2-element antenna array on an embedded FPGA platform**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This thesis project implements a portable Direction-of-Arrival (DoA) estimation system at 2.4 GHz. A two-channel coherent SDR (BladeRF 2.0 xA4) feeds an FPGA SoC that runs the cross-correlation pipeline in fabric and root-MUSIC on the application processor. The system is bench-portable: a barrel-jack-powered SDR, two λ/2-spaced whip antennas, an nRF5340 signal source, and a single Ethernet link to a host PC.

Four DoA algorithms are implemented:
- **Root-MUSIC** (default) — polynomial root finding, fast and accurate
- **MUSIC** — spectral search with pseudo-spectrum visualization
- **MVDR** (Capon) — minimum variance beamformer
- **Phase Difference** — simple and fast baseline

Based on: Wachowiak & Kryszkiewicz (2022) — *"Angle of arrival estimation in a multi-antenna software defined radio system"*

## Current Platform Status

| Platform | Role | Branch / state |
| --- | --- | --- |
| **AMD Kria KV260** (Zynq UltraScale+ K26, Ubuntu 22.04 aarch64) | **Primary** — active thesis development, current capture campaigns | `main` |
| **Digilent Cora Z7** (Zynq-7000, PetaLinux 2025.2) | **Validated reference** — end-to-end pipeline + display, frozen | `feature/fir-backpressure` (frozen, not merged) |

The two platforms run the **same `doa_pipeline` RTL** (FIR + phase-cal rotation + cross-correlation + autocorrelation accumulators) and the same root-MUSIC implementation, with platform-specific transports for AXI register I/O and DMA.

### Why two platforms?

The thesis began on the Cora Z7. The Cora pipeline reached an end-to-end validated state on the `feature/fir-backpressure` branch (RTL + GNU Radio + headless driver + touch display), but PetaLinux 2025.2 ships with a confirmed upstream regression in chipidea USB binding (AMD answer record [AR#000039143](https://adaptivesupport.amd.com/), all-platforms, fix ETA 2026.1) that breaks BladeRF USB enumeration on any rebuilt `image.ub`. Each RTL or driver iteration past that point would have required either rolling forward onto a broken USB stack or freezing on a stale pre-rebuild image. The KV260 (Kria K26 SOM, Ubuntu 22.04 aarch64) sidesteps PetaLinux entirely and bypasses the bug, so live thesis development moved there. The Cora reference branch remains in this repo as a validated baseline; current capture campaigns run on the KV260.

## Hardware

| Component | Model | Purpose |
|-----------|-------|---------|
| FPGA SoC (primary) | AMD Kria KV260 starter kit (K26 SOM, ZU+ MPSoC) | Live thesis platform — Ubuntu + headless NumPy driver |
| FPGA SoC (reference) | Digilent Cora Z7 (Zynq-7000) | Frozen end-to-end reference — PetaLinux + GNU Radio |
| SDR | Nuand BladeRF 2.0 xA4 | 2-channel coherent receiver, 1 MS/s |
| Antennas | 2× Linx ANT-2.4-CW-RCL whips | Half-wavelength ULA (61.2 mm) |
| Signal source | nRF5340 DK (Zephyr `radio_test`) | 2.419 GHz GFSK / modulated carrier |
| Display (Cora-era, optional) | Waveshare ESP32-S3 4.3" Touch LCD | LVGL touch UI via UART |
| Power | TalentCell LiFePO4 12.8 V + DC-DC buck (Cora bench); BladeRF barrel jack 5 V/2 A | |

See [docs/HARDWARE_DETAILS.md](docs/HARDWARE_DETAILS.md) for enclosure dimensions and wiring.

## RF Parameters

| Parameter | Current campaign value |
|-----------|------------------------|
| Center frequency | 2.41895 GHz (nRF ch 19 = 2.419 GHz, off-tuned 50 kHz) |
| Sample rate | 1 MS/s |
| RX bandwidth | 1 MHz |
| Antenna spacing | 61.2 mm (λ/2 at 2.45 GHz) |
| Array type | 2-element Uniform Linear Array |
| BladeRF gain | 50 dB |

## Repository Structure

```
doa_24ghz_t/
├── kv260_headless/             # KV260 driver path (PRIMARY)
│   ├── aoa_estimation_fpga_kv260.py   # NumPy + SoapySDR DoA driver
│   ├── aoa_estimation_headless.py     # ARM-only path (no FPGA accel)
│   ├── phase_calibration_headless.py  # Wired phase calibration
│   ├── emio_probe.py                  # EMIO GPIO bring-up check
│   ├── dma_probe.py                   # AXI-DMA state dump
│   └── ...
├── cora_headless/              # Cora Z7 driver (frozen reference)
│   ├── aoa_estimation_fpga_v2.py      # FPGA-accelerated DoA
│   ├── aoa_estimation_headless.py     # ARM-only baseline
│   ├── main.py                        # UART display controller
│   ├── web_dashboard.py               # HTTP + SSE web UI
│   ├── display_firmware/              # ESP32 LVGL touch display
│   └── initd/                         # SysVinit auto-start
├── fpga/
│   ├── rtl/                    # doa_pipeline + dma_safe_ctrl + supporting IP
│   ├── vivado_kv260/           # KV260 block design + constraints
│   ├── tb/                     # iverilog testbenches
│   └── GETTING_STARTED.md      # Vivado build flow
├── gnuradio_flowgraphs/        # Cora-era GRC flowgraphs (reference)
├── scripts/                    # Campaign automation, analysis, deploy
├── data/                       # Capture sessions (runA … runE, baselines)
├── results/                    # Campaign analysis outputs (plots, CSVs, fits)
├── hardware/                   # 3D-printed enclosure (OpenSCAD + STL)
└── docs/                       # Specs, thesis chapter sources, hardware details
```

## Quick Start (KV260 — primary path)

```bash
# 1. Bring up bitstream + udmabuf + EMIO gates (idempotent)
ssh ubuntu@<kv260-ip> 'sudo bash ~/doa/bench_bringup.sh'

# 2. Run a capture (60 s, root-MUSIC, unfiltered, ch 19 + 50 kHz off-tune)
ssh ubuntu@<kv260-ip> 'sudo python3 ~/doa/aoa_estimation_fpga_kv260.py \
    --filter none --algo rootmusic --freq 2.418e9 --gain 50'

# 3. Per-angle protocol (label captures by angle for the campaign)
ssh ubuntu@<kv260-ip> 'echo "50deg" > ~/doa/data/current_label.txt'
# … repeat capture for next angle …
```

Per-capture CSV + JSON sidecar lands under `~/doa/data/aoa_<LABEL>_<MODE>_<ALGO>_<TS>.csv`. See [docs/DEMO_QUICKSTART.md](docs/DEMO_QUICKSTART.md) for the full bench protocol.

## Quick Start (Cora Z7 — reference)

The Cora reference path lives on the `feature/fir-backpressure` branch (frozen, not merged into `main`):

```bash
git fetch origin feature/fir-backpressure
git checkout feature/fir-backpressure
# Then deploy to petalinux@<cora-ip>:/home/petalinux/doa/ per cora_headless/README
```

The Cora deployment includes a web dashboard (`http://<cora-ip>:8080`) and a touch display front-end. Live thesis development happens on `main` against the KV260 — this branch is preserved as the validated end-to-end baseline.

## Calibration

Wired phase calibration using a signal source, attenuator, and power splitter:

```
Signal Source (nRF5340 @ 2.419 GHz)
    → 30 dB SMA attenuator
    → 2-way power splitter
        → matched cable → BladeRF RX1
        → matched cable → BladeRF RX2
```

```bash
# KV260
sudo python3 ~/doa/phase_calibration_headless.py --freq 2.418e9 --duration 10
```

The `--filter=none` calibration is filter-agnostic (broadband static phase offset), reusable across filter regimes.

## Documentation

| Document | Description |
|----------|-------------|
| [DEMO_QUICKSTART](docs/DEMO_QUICKSTART.md) | Step-by-step bench/demo procedure |
| [DEMO_COMMANDS](docs/DEMO_COMMANDS.txt) | Command reference (nRF + driver) |
| [HARDWARE_DETAILS](docs/HARDWARE_DETAILS.md) | Enclosure, components, power |
| [INSTALL_GUIDE](INSTALL_GUIDE.md) | Host PC + KV260 software setup |
| [fpga/GETTING_STARTED](fpga/GETTING_STARTED.md) | Vivado build flow + register map |
| [docs/specs/](docs/specs/) | Phase-by-phase RTL design specs |

## FPGA Pipeline

The `doa_pipeline` IP runs the per-snapshot signal processing in fabric:

```
BladeRF IQ stream → channel_splitter → fir_filter_sc16 → phase_rotate_sc16
                                                              ↓
                                       xcorr_acc + autocorr_acc (R00, R11)
                                                              ↓
                                                    AXI-Lite read-back
```

15 AXI-Lite registers, 48-bit accumulators read as LO/HI pairs. Same RTL on both targets, two transports:

- **Cora Z7**: AXI-Lite at `0x4000_0000` via `/dev/mem` mapping; AXI-DMA on OCM (0xFFFC_0000) bypassing CMA
- **KV260**: AXI-Lite at `0xA001_0000` via EMIO GPIO bit-banged register I/O (Path C); AXI-DMA on `S_AXI_HP0_FPD` with udmabuf-allocated CMA buffers

The KV260 transport works around an AXI-Lite write-strobe stride bug observed on the Kria HPM0_FPD aperture — see [docs/specs/2026-04-22-kv260-plan-of-attack.md](docs/specs/2026-04-22-kv260-plan-of-attack.md) for the full debug arc.

## License

MIT License
