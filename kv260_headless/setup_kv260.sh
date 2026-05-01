#!/bin/bash
# setup_kv260.sh — One-shot KV260 DoA pipeline bring-up
#
# Run once after each boot (before starting aoa_estimation_fpga_kv260.py).
# Must be run as root.
#
# What this does:
#   1. Load the bitstream + device tree overlay via fpgautil
#   2. Load udmabuf kernel module (DMA memory allocator)
#   3. Verify DMA-safe UIO, GPIO chip, and /dev/udmabuf0 exist
#
# Usage:
#   sudo bash setup_kv260.sh [path/to/emio_doa.bit.bin]
#
# After this script succeeds:
#   sudo python3 aoa_estimation_fpga_kv260.py --algo=ROOTMUSIC

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="${APP_NAME:-emio_doa}"
FIRMWARE_DIR="/lib/firmware/xilinx/${APP_NAME}"

# Look for bitstream + dtbo in common locations (alongside script first, then
# the cora-style relative path, then /lib/firmware as a last resort).
find_artifact() {
    local name="$1"
    for path in \
        "$1" \
        "${SCRIPT_DIR}/${name}" \
        "${SCRIPT_DIR}/../fpga/vivado_kv260/${name}" \
        "/lib/firmware/xilinx/${APP_NAME}/${name}"; do
        if [ -f "$path" ]; then echo "$path"; return; fi
    done
}
BIT_BIN="${1:-$(find_artifact emio_doa.bit.bin)}"
DTBO="${DTBO:-$(find_artifact emio_doa.dtbo)}"
GPIOCHIP="${GPIOCHIP:-/dev/gpiochip1}"

SNAPSHOT_SIZE=1024            # must match KV260Config.SNAPSHOT_SIZE
UDMABUF_SIZE=$(( 4096 + SNAPSHOT_SIZE * 2 * 4 ))   # desc page + data buffer

# ── Step 1: Load bitstream + device tree overlay ─────────────────────────
if [ -f "$BIT_BIN" ] && [ -f "$DTBO" ]; then
    echo "[setup] Loading bitstream: $BIT_BIN"
    fpgautil -b "$BIT_BIN" -o "$DTBO" -f Full -n Full
    echo "[setup] Bitstream loaded"
else
    # Fallback: try xmutil (requires /lib/firmware/xilinx/${APP_NAME}/ layout)
    echo "[setup] .bit.bin or .dtbo not found at expected paths"
    echo "[setup] Trying: sudo xmutil loadapp ${APP_NAME}"
    xmutil unloadapp 2>/dev/null || true
    xmutil loadapp "${APP_NAME}"
fi

sleep 0.5   # give udev time to create /dev/uioN nodes

# ── Step 2: Load udmabuf ─────────────────────────────────────────────────
echo "[setup] Loading udmabuf (size=${UDMABUF_SIZE} bytes)"
if lsmod | grep -q u_dma_buf; then
    echo "[setup] u_dma_buf already loaded — reloading with correct size"
    rmmod u_dma_buf || true
fi
modprobe u-dma-buf udmabuf0="${UDMABUF_SIZE}"

# ── Step 3: Verify devices ───────────────────────────────────────────────
echo "[setup] Checking devices..."
fail=0
if [ -e /dev/udmabuf0 ]; then
    echo "[setup]   OK  /dev/udmabuf0"
else
    echo "[setup]   MISSING /dev/udmabuf0"
    fail=1
fi

if [ -e "$GPIOCHIP" ]; then
    echo "[setup]   OK  $GPIOCHIP"
else
    echo "[setup]   MISSING $GPIOCHIP"
    echo "[setup]   Override with: GPIOCHIP=/dev/gpiochipN sudo -E bash setup_kv260.sh"
    fail=1
fi

dma_uio=""
for uio in /sys/class/uio/uio*; do
    [ -e "$uio" ] || continue
    if [ -r "$uio/maps/map0/name" ] && [ "$(cat "$uio/maps/map0/name")" = "dma_safe_ctrl_regs" ]; then
        dma_uio="/dev/$(basename "$uio")"
        break
    fi
done

if [ -n "$dma_uio" ] && [ -e "$dma_uio" ]; then
    echo "[setup]   OK  $dma_uio (dma_safe_ctrl_regs)"
else
    echo "[setup]   MISSING DMA-safe UIO with map0/name=dma_safe_ctrl_regs"
    fail=1
fi

if [ $fail -ne 0 ]; then
    echo "[setup] ERROR: some devices missing — check bitstream and dtbo"
    exit 1
fi

PHYS=$(cat /sys/class/u-dma-buf/udmabuf0/phys_addr 2>/dev/null || echo "unknown")
echo "[setup] udmabuf0 physical address: $PHYS"
echo "[setup] Done. Run: sudo python3 aoa_estimation_fpga_kv260.py --probe"
