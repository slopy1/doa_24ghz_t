#!/bin/bash
# bench_bringup.sh — One-shot bench bring-up for a fresh KV260 boot
#
# Run this once after every Kria boot, before main.py.
# Idempotent: safe to re-run if anything looks wrong.
#
# Steps:
#   1. Unload any stock overlay (k26-starter-kits) that grabbed slot 0
#   2. Load emio_doa.bit.bin + emio_doa.dtbo via fpgautil
#   3. (Re)load u-dma-buf with the size the driver expects
#   4. Run emio_probe.py — must hit 5/5 OK
#   5. Verify dma_safe_ctrl_regs UIO is enumerated
#
# Exit 0 = ready to run main.py. Exit non-0 = stop and read the message.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIT_BIN="${BIT_BIN:-${SCRIPT_DIR}/emio_doa.bit.bin}"
DTBO="${DTBO:-${SCRIPT_DIR}/emio_doa.dtbo}"
SNAPSHOT_SIZE=1024
UDMABUF_SIZE=$(( 4096 + SNAPSHOT_SIZE * 2 * 4 ))   # = 12288

if [ ! -f "$BIT_BIN" ] || [ ! -f "$DTBO" ]; then
    echo "[bringup] ERROR: missing $BIT_BIN or $DTBO"
    echo "[bringup]        scp them from the host into ${SCRIPT_DIR}/"
    exit 1
fi

# ── 1. Free slot 0 (k26-starter-kits or stale overlay) ────────────────────
echo "[bringup] (1/5) Unloading any existing overlay..."
xmutil unloadapp >/dev/null 2>&1 || true
# Clean stale configfs detritus from a failed apply (per PROJECT_HISTORY bug #60)
rmdir /sys/kernel/config/device-tree/overlays/Full 2>/dev/null || true

# ── 2. Load bitstream + dtbo ──────────────────────────────────────────────
echo "[bringup] (2/5) Loading bitstream: $(basename "$BIT_BIN")"
fpgautil -b "$BIT_BIN" -o "$DTBO" -f Full -n Full
sleep 0.5   # give udev time to create /dev/uioN nodes

# ── 3. Reload u-dma-buf at the size the driver expects ────────────────────
echo "[bringup] (3/5) Reloading u-dma-buf (size=${UDMABUF_SIZE})..."
modprobe -r u-dma-buf 2>/dev/null || true
modprobe u-dma-buf udmabuf0="${UDMABUF_SIZE}"

# ── 4. Verify dma_safe_ctrl_regs is enumerated ────────────────────────────
echo "[bringup] (4/5) Checking dma_safe_ctrl_regs UIO..."
dma_uio=""
for uio in /sys/class/uio/uio*; do
    [ -e "$uio" ] || continue
    if [ "$(cat "$uio/maps/map0/name" 2>/dev/null)" = "dma_safe_ctrl_regs" ]; then
        dma_uio="/dev/$(basename "$uio")"
        break
    fi
done
if [ -z "$dma_uio" ]; then
    echo "[bringup] ERROR: dma_safe_ctrl_regs UIO not found"
    echo "[bringup]        check /dev/uio* and /sys/class/uio/*/maps/map0/name"
    exit 2
fi
echo "[bringup]        OK  $dma_uio"

# ── 5. EMIO gate test (must be 5/5 OK) ────────────────────────────────────
echo "[bringup] (5/5) EMIO probe..."
if ! python3 "${SCRIPT_DIR}/emio_probe.py"; then
    echo "[bringup] ERROR: EMIO probe failed — bitstream may be partially loaded"
    exit 3
fi

PHYS=$(cat /sys/class/u-dma-buf/udmabuf0/phys_addr 2>/dev/null || echo "?")
echo "[bringup] DONE.  udmabuf phys=${PHYS}  uio=${dma_uio}"
echo "[bringup] Now run: sudo python3 main.py"
