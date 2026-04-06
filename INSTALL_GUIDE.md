# DoA Experiment Installation Guide

Complete setup instructions for running the 2.4 GHz Direction of Arrival experiment on a fresh Linux system.

## Hardware Requirements

| Item | Model | Purpose |
|------|-------|---------|
| SDR | Nuand BladeRF 2.0 micro xA4 | 2-channel coherent receiver |
| Antennas | 2× 2.4 GHz whip antennas | λ/2 spaced array (61mm) |
| USB Cable | USB 3.0 Type-A to Micro-B | BladeRF connection |
| **For Calibration:** | | |
| Power Splitter | Mini-Circuits ZX10-2-42-S+ | Split calibration signal |
| Attenuator | 30 dB SMA attenuator | Prevent RX overload |
| SMA Cables | 2× matched-length cables | Phase-matched connections |
| Transmitter | nRF52 or BladeRF TX | 2.44 GHz tone source |

---

## Software Requirements Summary

| Package | Version | Purpose |
|---------|---------|---------|
| GNU Radio | 3.10+ | Signal processing framework |
| BladeRF Driver | Latest | Hardware communication |
| gr-aoa | Latest | MUSIC/Root-MUSIC blocks |
| Python | 3.10+ | Scripting |
| Eigen3 | 3.3+ | Linear algebra for MUSIC |
| pybind11 | 2.0+ | Python bindings |

---

## Installation Instructions

### For Arch Linux / Garuda / Manjaro

```bash
# 1. Install GNU Radio and BladeRF
sudo pacman -S gnuradio gnuradio-companion gnuradio-osmosdr bladerf soapysdr soapysdr-bladerf

# 2. Install build dependencies
sudo pacman -S eigen3 pybind11 cmake base-devel git

# 3. Install BladeRF Python bindings
pip install "git+https://github.com/Nuand/bladeRF.git#subdirectory=host/libraries/libbladeRF_bindings/python"

# 4. Clone and build gr-aoa
cd ~
git clone https://github.com/MarcinWachowiak/gr-aoa.git
cd gr-aoa
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
sudo ldconfig

# 5. Link the Python module (if needed)
sudo ln -sf /usr/local/lib/python3.*/site-packages/gnuradio/aoa /usr/lib/python3.*/site-packages/gnuradio/aoa

# 6. Install Python dependencies
pip install numpy scipy matplotlib h5py
```

### For Ubuntu 22.04 / 24.04 / Debian

```bash
# 1. Install GNU Radio and BladeRF
sudo apt update
sudo apt install gnuradio gnuradio-dev gr-osmosdr bladerf libbladerf-dev bladerf-fpga-hostedx40

# 2. Install build dependencies
sudo apt install libeigen3-dev pybind11-dev cmake build-essential git python3-pip

# 3. Install SoapySDR BladeRF support
sudo apt install soapysdr-module-bladerf

# 4. Install BladeRF Python bindings
pip3 install "git+https://github.com/Nuand/bladeRF.git#subdirectory=host/libraries/libbladeRF_bindings/python"

# 5. Clone and build gr-aoa
cd ~
git clone https://github.com/MarcinWachowiak/gr-aoa.git
cd gr-aoa
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
sudo ldconfig

# 6. Install Python dependencies
pip3 install numpy scipy matplotlib h5py
```

### For Fedora

```bash
# 1. Install GNU Radio and BladeRF
sudo dnf install gnuradio gnuradio-devel gr-osmosdr bladeRF bladeRF-devel

# 2. Install build dependencies
sudo dnf install eigen3-devel pybind11-devel cmake gcc-c++ git python3-pip

# 3. Install BladeRF Python bindings
pip3 install "git+https://github.com/Nuand/bladeRF.git#subdirectory=host/libraries/libbladeRF_bindings/python"

# 4. Clone and build gr-aoa
cd ~
git clone https://github.com/MarcinWachowiak/gr-aoa.git
cd gr-aoa
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
sudo ldconfig

# 5. Install Python dependencies
pip3 install numpy scipy matplotlib h5py
```

---

## USB Permissions (All Distros)

If BladeRF isn't detected without sudo, add udev rules:

```bash
# Create udev rule
sudo tee /etc/udev/rules.d/88-bladerf.rules << 'EOF'
# Nuand BladeRF 2.0
ATTR{idVendor}=="2cf0", ATTR{idProduct}=="5250", MODE="0666", GROUP="plugdev"
EOF

# Reload rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# Add user to plugdev group
sudo usermod -aG plugdev $USER

# Log out and back in for group changes to take effect
```

---

## Verify Installation

```bash
# 1. Check BladeRF connection
bladeRF-cli -p
# Should show: "Nuand bladeRF 2.0"

# 2. Check GNU Radio
gnuradio-config-info --version
# Should show: 3.10.x or higher

# 3. Check gr-aoa blocks
gnuradio-companion
# In GRC, search for "aoa" - should show:
#   - MUSIC Linear Array
#   - Root MUSIC Linear Array
#   - Shift Phase
#   - Correlate
#   - Calculate Phase Difference

# 4. Check Python BladeRF
python3 -c "from bladerf import _bladerf; print('BladeRF Python OK')"
```

---

## Copy Project Files

Copy these files from your main laptop:

```
doa_24ghz_thesis/
├── gnuradio_flowgraphs/
│   ├── phase_calibration_bladerf.grc    # Phase calibration
│   └── aoa_estimation_bladerf.grc       # AoA estimation
├── scripts/
│   ├── transmit_tone.py                 # TX script
│   └── collect_dataset.py               # Data collection
├── src/
│   └── doa24/                           # Python library
├── configs/
│   └── receiver.yaml                    # Settings
└── requirements.txt                     # Python deps
```

Or clone from git if you've pushed to a repository:
```bash
git clone https://github.com/YOUR_USERNAME/doa_24ghz_thesis.git
cd doa_24ghz_thesis
pip install -r requirements.txt
```

---

## Quick Test (No Transmitter Needed)

To verify the setup works without a TX signal:

```bash
# Open the calibration flowgraph
gnuradio-companion /path/to/doa_24ghz_thesis/gnuradio_flowgraphs/phase_calibration_bladerf.grc
```

Run the flowgraph - you should see:
- Spectrum display (will show noise floor)
- Phase display (will show random values without signal)

If you see the GUI with live plots, the setup is working!

---

## Demo Workflow for Professor

### Preparation (Before Demo)
1. Install all software (above)
2. Let BladeRF warm up 30 minutes
3. Do wired calibration, record phase offset

### Live Demo
1. **Show hardware setup:** BladeRF + 2 antennas at λ/2 spacing
2. **Start TX:** Position transmitter at known angle
3. **Run AoA flowgraph:**
   ```bash
   gnuradio-companion gnuradio_flowgraphs/aoa_estimation_bladerf.grc
   ```
4. **Show results:**
   - AoA estimate matches TX position
   - Move TX, show angle changes
   - MUSIC pseudo-spectrum shows peak at correct angle

### Talking Points
- "Using Root-MUSIC algorithm from Wachowiak paper"
- "2-element array with λ/2 spacing at 2.4 GHz"
- "Phase calibration compensates for hardware offsets"
- "Band-pass filter rejects WiFi interference"

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| BladeRF not detected | Check USB cable, run `bladeRF-cli -p` with sudo |
| gr-aoa blocks missing | Re-run `sudo ldconfig`, restart GRC |
| Python import error | Check PYTHONPATH includes /usr/local/lib |
| No signal in spectrum | Verify TX is running, check frequency |
| Noisy AoA estimates | Enable band-pass filter, reduce WiFi interference |

---

## Contact

For questions about this experiment setup, refer to:
- Paper: Wachowiak & Kryszkiewicz (2022), doi:10.1007/s11276-022-03010-z
- gr-aoa repo: https://github.com/MarcinWachowiak/gr-aoa
  On the Arch Laptop

  # 1. Install deps
  sudo pacman -S python python-numpy python-matplotlib

  # 2. Copy from USB
  cp -r /path/to/usb/doa_24ghz_thesis ~/doa_24ghz_thesis

  # 3. Run the demo (shows calibration plots + DoA algorithm comparison)
  cd ~/doa_24ghz_thesis
  python scripts/demo_calibration.py

  # 4. Try different simulated source angles
  python scripts/demo_calibration.py --sim-angle 45
  python scripts/demo_calibration.py --sim-angle -20
  python scripts/demo_calibration.py --sim-angle 0

  # 5. View raw IQ data individually
  python scripts/view_iq_data.py recordings/cal_run1/cal_ch0.32fc
  python scripts/view_iq_data.py recordings/cal_run1/cal_ch1.32fc


  The demo_calibration.py script will automatically find the calibration files in recordings/cal_run1/ and show:
  - Raw IQ time domain (both channels)
  - Power spectral density
  - Inter-channel phase measurement over time (the calibration result)
  - MUSIC spatial spectrum for a simulated source
  - Bar chart comparing all 4 algorithms (Phase Diff, MUSIC, Root-MUSIC, MVDR)
  ctrl+q to copy · 4 snippets