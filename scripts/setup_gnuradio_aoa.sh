#!/bin/bash
# ============================================================================
# GNU Radio AoA Setup Script for BladeRF 2.0
# Based on Wachowiak & Kryszkiewicz (2022) paper
# ============================================================================

set -e

echo "=============================================="
echo "GNU Radio AoA Setup for BladeRF 2.0"
echo "=============================================="

# Step 1: Install system dependencies
echo ""
echo "[1/4] Installing system dependencies..."
sudo pacman -S --noconfirm eigen3 pybind11

# Step 2: Build and install gr-aoa
echo ""
echo "[2/4] Building gr-aoa (MUSIC/Root-MUSIC blocks)..."
cd ~/gr-aoa
rm -rf build
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
sudo ldconfig

# Step 3: Build and install gr-bladeRF (optional - for native BladeRF blocks)
echo ""
echo "[3/4] Building gr-bladeRF (native BladeRF blocks)..."
cd ~
if [ ! -d "gr-bladeRF" ]; then
    git clone https://github.com/Nuand/gr-bladeRF.git
fi
cd gr-bladeRF
rm -rf build
mkdir build && cd build
cmake ..
make -j$(nproc) || echo "gr-bladeRF build failed - will use Soapy instead"
sudo make install || echo "gr-bladeRF install failed - will use Soapy instead"
sudo ldconfig

# Step 4: Verify installation
echo ""
echo "[4/4] Verifying installation..."
echo ""
echo "Checking for gr-aoa blocks..."
python3 -c "from gnuradio import aoa; print('✓ gr-aoa blocks available')" || echo "⚠ gr-aoa not found in Python"

echo ""
echo "=============================================="
echo "✓ Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "  1. Open GNU Radio Companion: gnuradio-companion"
echo "  2. Search for 'aoa' blocks - you should see:"
echo "     - MUSIC Linear Array"
echo "     - Root MUSIC"
echo "     - Calculate Phase Difference"
echo "     - Shift Phase"
echo "     - Correlate"
echo ""
echo "  3. Create flowgraphs per the setup guide"
echo ""

