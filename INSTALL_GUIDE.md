# DoA-24GHz Installation Guide

Two installation paths depending on what you're trying to do:

| Path | Audience | Hardware required |
|------|----------|-------------------|
| **A: Host PC** | Browse the repo, replay captured data, run offline analysis | None — pure Python |
| **B: KV260 deployment** | Reproduce the live capture pipeline | KV260 + BladeRF 2.0 xA4 + 2× whip antennas + nRF5340 (or other 2.4 GHz tone source) |

A Cora Z7 (frozen reference) path also exists on the `feature/fir-backpressure` branch — see the bottom of this document.

---

## Path A: Host PC (offline analysis)

For reading capture sessions, regenerating campaign plots, or browsing the codebase. No SDR or FPGA hardware needed.

### Requirements

- Python 3.10 or newer
- A Linux, macOS, or Windows host with `pip`

### Install

```bash
git clone https://github.com/slopy1/doa_24ghz_t.git
cd doa_24ghz_t
pip install -r requirements.txt
```

### Sanity check

```bash
# Re-render an existing campaign's plots from CSV/JSON
python3 scripts/analyze_campaign.py --campaign-dir results/campaign_20260429_203028_v2/
```

If the script runs without import errors and writes PNGs, your environment is ready.

---

## Path B: KV260 deployment (live capture)

Reproduces the live thesis pipeline. Tested on Ubuntu 22.04 LTS for AMD/Xilinx Kria (`xilinx-zynqmp-common-20232-*` images and Canonical's official Kria image).

### Hardware checklist

| Item | Notes |
|------|-------|
| AMD Kria KV260 vision starter kit | K26 SOM, included KV260 carrier card |
| BladeRF 2.0 xA4 | **Barrel-jack 5 V/2 A required** before USB (USB 5 V is insufficient at full RF power) |
| USB 3.0 cable | Type-A to Type-B Micro |
| 2× 2.4 GHz whip antennas | λ/2-spaced (61.2 mm), SMA |
| 2× matched SMA cables, 1× 30 dB attenuator, 1× 2-way splitter | For wired phase calibration |
| nRF5340 DK (or any tunable 2.4 GHz CW source) | Zephyr `radio_test` ch 19 = 2.419 GHz |

### 1. System packages (KV260, Ubuntu 22.04 aarch64)

```bash
sudo apt update
sudo apt install -y \
    build-essential cmake git pkg-config \
    libusb-1.0-0-dev \
    python3-dev python3-pip python3-numpy python3-scipy python3-matplotlib \
    python3-libgpiod libgpiod-dev \
    fpgautil device-tree-compiler
```

The `fpgautil` and `device-tree-compiler` packages come from the AMD/Xilinx Kria archive. If `fpgautil` is missing, follow the [Canonical Kria install guide](https://ubuntu.com/download/amd) to add the Xilinx PPA.

### 2. SoapySDR + libbladeRF + SoapyBladeRF (build from source)

The Ubuntu 22.04 packaged versions of `soapysdr` and `libbladerf` are too old to stream cleanly at 1 MS/s coherent on the Kria. Build all three from upstream:

```bash
# SoapySDR
cd ~ && git clone https://github.com/pothosware/SoapySDR.git
cd SoapySDR && mkdir build && cd build
cmake .. && make -j$(nproc) && sudo make install
sudo ldconfig

# libbladeRF (Nuand)
cd ~ && git clone https://github.com/Nuand/bladeRF.git
cd bladeRF/host && mkdir build && cd build
cmake .. && make -j$(nproc) && sudo make install
sudo ldconfig

# SoapyBladeRF (Pothosware)
cd ~ && git clone https://github.com/pothosware/SoapyBladeRF.git
cd SoapyBladeRF && mkdir build && cd build
cmake .. && make -j$(nproc) && sudo make install
sudo ldconfig
```

Verify:

```bash
SoapySDRUtil --info | grep -i bladerf      # SoapyBladeRF should be listed
SoapySDRUtil --rate-test --args="driver=bladerf" --rate=1e6
# Expect "All complete!" with no overflow warnings.
```

### 3. u-dma-buf (DMA-coherent buffer for the BladeRF → DDR data path)

The KV260 image blocks `/dev/mem` (`CONFIG_STRICT_DEVMEM=y`), so the driver allocates DMA buffers via [u-dma-buf](https://github.com/ikwzm/udmabuf) instead. Build from source (apt and DKMS packages are stale on Ubuntu 22.04 aarch64):

```bash
cd ~ && git clone https://github.com/ikwzm/udmabuf.git
cd udmabuf && make
sudo make install
# Verify the module loads:
sudo modprobe u-dma-buf udmabuf0=12288
ls /sys/class/u-dma-buf/      # should show udmabuf0
```

The u-dma-buf module is non-persistent across reboots — `bench_bringup.sh` re-modprobes on every session.

### 4. BladeRF udev rules

```bash
sudo tee /etc/udev/rules.d/88-nuand.rules > /dev/null << 'EOF'
ATTR{idVendor}=="2cf0", ATTR{idProduct}=="5246", MODE="0660", GROUP="plugdev"
ATTR{idVendor}=="2cf0", ATTR{idProduct}=="5250", MODE="0660", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG plugdev $USER
# log out + back in for the group change
```

### 5. Deploy the driver and bring-up scripts

```bash
# From a host PC:
scp -r kv260_headless/ ubuntu@<kv260-ip>:~/doa/
scp fpga/vivado_kv260/built/*.bit.bin ubuntu@<kv260-ip>:~/doa/
scp fpga/vivado_kv260/built/*.dtbo    ubuntu@<kv260-ip>:~/doa/
scp scripts/bench_bringup.sh          ubuntu@<kv260-ip>:~/doa/
```

### 6. Bring-up + first capture

```bash
# On the KV260:
sudo bash ~/doa/bench_bringup.sh   # idempotent: unloadapp + fpgautil + udmabuf + EMIO gate

# Then run a 60 s capture:
sudo python3 ~/doa/aoa_estimation_fpga_kv260.py \
    --filter none --algo rootmusic --freq 2.418e9 --gain 50
```

You should see real-time AoA estimates printed to stdout at ≈7.7 Hz.

### Gotchas

- **BladeRF barrel jack must be powered before the KV260 USB connection.** USB 5 V at the SoM port is not enough current at full RF gain.
- **`/dev/mem` is blocked.** Use UIO + udmabuf, not `mmap` on `/dev/mem`. Sysfs path is `/sys/class/u-dma-buf/`.
- **`kria-dashboard` snap can reload starter kits mid-session.** If the bitstream evaporates after a few minutes, re-run `bench_bringup.sh` or `sudo snap disable kria-dashboard`.
- **Fan-gate pin A12 must be driven constantly high** in any custom bitstream, or the carrier card thermally shuts the SOM down within 15–60 s. The supplied `kv260_emio_doa.bit.bin` already does this.
- **No RTC** on the carrier — `sudo date -s ...` after each reboot if your captures need real timestamps.

---

## Cora Z7 (legacy reference)

The Cora pipeline is preserved as a validated end-to-end baseline on the `feature/fir-backpressure` branch:

```bash
git fetch origin feature/fir-backpressure
git checkout feature/fir-backpressure
cat cora_headless/README.md   # full deployment notes
```

The Cora path uses GNU Radio 3.10.12 + `gnuradio.soapy` (not gr-osmosdr) + `gr-aoa` and PetaLinux 2025.2. It is not actively maintained on `main` — see the README's "Why two platforms?" section for context.

---

## Troubleshooting

| Issue | First thing to check |
|-------|----------------------|
| `SoapySDRUtil --info` doesn't list bladerf | `sudo ldconfig`, confirm SoapyBladeRF install path is in `/usr/local/lib/SoapySDR/modules*/` |
| `bladeRF-cli -p` hangs | Barrel jack 5 V is missing or undervolt — verify with a multimeter |
| Driver immediately exits with `OSError: [Errno 19] No such device` | `bench_bringup.sh` didn't run, or `kria-dashboard` reaped the bitstream |
| `run_snapshot` returns `None` ~12% of the time | Known: fabric STATUS_VALID race; in-flight work, not a configuration error |
| AoA rate ≈ 1 Hz instead of ≈ 7 Hz with `--filter=none` | Pre-2026-04-29 driver — pull latest and rerun |
