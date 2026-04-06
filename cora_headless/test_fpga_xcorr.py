#!/usr/bin/env python3
"""
test_fpga_xcorr.py — Test the xcorr_acc FPGA IP via AXI DMA (Scatter Gather).

Pushes known synthetic IQ data through DMA -> xcorr_acc and reads back
the cross-correlation registers. Compares FPGA result with NumPy reference.

Run on Cora Z7 as root:
    sudo python3 test_fpga_xcorr.py

Register map (xcorr_acc_axi @ 0x4000_0000):
    0x00  XCORR_RE     (signed 32-bit)
    0x04  XCORR_IM     (signed 32-bit)
    0x08  STATUS       (bit 0 = result_valid, sticky, clear-on-read)
    0x0C  SNAP_COUNT   (unsigned 32-bit)

AXI DMA @ 0x4040_0000 (MM2S channel, Scatter Gather mode):
    0x00  MM2S_DMACR   (control: bit 0=run, bit 2=reset)
    0x04  MM2S_DMASR   (status: bit 0=halted, bit 1=idle, bit 3=SGIncld)
    0x08  MM2S_CURDESC (current descriptor pointer)
    0x10  MM2S_TAILDESC (tail descriptor pointer — writing starts transfer)

SG Descriptor format (0x40 bytes each):
    0x00  NXTDESC      (next descriptor address)
    0x04  NXTDESC_MSB  (upper 32 bits, 0 for 32-bit)
    0x08  BUFFER_ADDR  (source buffer physical address)
    0x0C  BUFFER_ADDR_MSB
    0x10  Reserved
    0x14  Reserved
    0x18  CONTROL      [22:0]=length, [26]=SOF, [27]=EOF
    0x1C  STATUS       [31]=Cmplt, [30]=DecErr, [29]=SlvErr, [28]=IntErr

Data format: 32-bit AXI-Stream, two beats per sample:
    Beat 0: {ch0_q[31:16], ch0_i[15:0]}  (SC16 little-endian)
    Beat 1: {ch1_q[31:16], ch1_i[15:0]}
"""

import mmap
import os
import struct
import time
import math
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
XCORR_BASE = 0x40000000
DMA_BASE   = 0x40400000
PAGE_SIZE  = 0x1000

# Physical memory layout in high DDR (Cora Z7 has 512 MB: 0x00000000-0x1FFFFFFF)
# Using region near top, unlikely to be touched by Linux.
DESC_PHYS    = 0x1F000000   # SG descriptor (0x40 bytes, must be 0x40-aligned)
DMA_BUF_PHYS = 0x1F001000   # IQ data buffer (4K-aligned)
SNAPSHOT_LEN = 1024          # must match FPGA parameter

# DMA MM2S registers (offsets from DMA_BASE)
MM2S_DMACR    = 0x00
MM2S_DMASR    = 0x04
MM2S_CURDESC  = 0x08
MM2S_TAILDESC = 0x10

# SG descriptor offsets
SG_NXTDESC    = 0x00
SG_NXTDESC_MSB = 0x04
SG_BUFFER     = 0x08
SG_BUFFER_MSB = 0x0C
SG_CONTROL    = 0x18
SG_STATUS     = 0x1C

# SG control bits
SG_SOF = (1 << 26)
SG_EOF = (1 << 27)


def mmap_region(fd, base, size=PAGE_SIZE):
    return mmap.mmap(fd, size, offset=base)


def reg_read(m, offset):
    return struct.unpack_from("<I", m, offset)[0]


def reg_read_signed(m, offset):
    return struct.unpack_from("<i", m, offset)[0]


def reg_write(m, offset, value):
    struct.pack_into("<I", m, offset, value & 0xFFFFFFFF)


def sc16_pack(i_val, q_val):
    """Pack signed I/Q into a 32-bit SC16 word: {Q[31:16], I[15:0]}."""
    i16 = int(i_val) & 0xFFFF
    q16 = int(q_val) & 0xFFFF
    return (q16 << 16) | i16


def make_test_data(phase_deg, amplitude=1000):
    """
    Generate SNAPSHOT_LEN sample pairs with a known phase offset.
    ch0 = (amplitude, 0) for all samples
    ch1 = amplitude * exp(j*phase) for all samples

    Returns bytes ready for DMA (two 32-bit beats per sample).
    """
    phase_rad = math.radians(phase_deg)
    ch0_i, ch0_q = amplitude, 0
    ch1_i = int(round(amplitude * math.cos(phase_rad)))
    ch1_q = int(round(amplitude * math.sin(phase_rad)))

    words = []
    for _ in range(SNAPSHOT_LEN):
        words.append(sc16_pack(ch0_i, ch0_q))  # beat 0: ch0
        words.append(sc16_pack(ch1_i, ch1_q))  # beat 1: ch1
    return struct.pack(f"<{len(words)}I", *words)


def numpy_reference(phase_deg, amplitude=1000):
    """Compute expected cross-correlation with NumPy (no 1/N division)."""
    phase_rad = math.radians(phase_deg)
    ch0 = np.full(SNAPSHOT_LEN, amplitude + 0j)
    ch1 = np.full(SNAPSHOT_LEN, amplitude * np.exp(1j * phase_rad))
    r01 = np.sum(ch0 * np.conj(ch1))
    return int(r01.real), int(r01.imag)


def setup_sg_descriptor(desc_m, buf_phys, nbytes):
    """Build a single SG descriptor that points to the data buffer."""
    # Point NXTDESC to itself (single-descriptor ring)
    reg_write(desc_m, SG_NXTDESC, DESC_PHYS)
    reg_write(desc_m, SG_NXTDESC_MSB, 0)
    # Buffer address
    reg_write(desc_m, SG_BUFFER, buf_phys)
    reg_write(desc_m, SG_BUFFER_MSB, 0)
    # Reserved fields
    reg_write(desc_m, 0x10, 0)
    reg_write(desc_m, 0x14, 0)
    # Control: SOF + EOF + byte length
    reg_write(desc_m, SG_CONTROL, SG_SOF | SG_EOF | (nbytes & 0x7FFFFF))
    # Clear status (must be 0 before DMA processes it)
    reg_write(desc_m, SG_STATUS, 0)


def run_dma_transfer(dma_m, desc_m, buf_m, data_bytes):
    """Write data to buffer, set up SG descriptor, kick off DMA."""
    nbytes = len(data_bytes)

    # Write IQ data into the DMA buffer
    buf_m.seek(0)
    buf_m.write(data_bytes)

    # Reset DMA
    reg_write(dma_m, MM2S_DMACR, 0x0004)
    time.sleep(0.01)
    # Wait for reset to clear
    for _ in range(100):
        if not (reg_read(dma_m, MM2S_DMACR) & 0x0004):
            break
        time.sleep(0.001)

    # Build the SG descriptor
    setup_sg_descriptor(desc_m, DMA_BUF_PHYS, nbytes)

    # Set current descriptor pointer (must be set while halted)
    reg_write(dma_m, MM2S_CURDESC, DESC_PHYS)

    # Start DMA (set run bit)
    reg_write(dma_m, MM2S_DMACR, 0x0001)
    time.sleep(0.001)

    # Write tail descriptor to kick off transfer
    # Since we have a single descriptor, tail = current = DESC_PHYS
    reg_write(dma_m, MM2S_TAILDESC, DESC_PHYS)

    # Wait for completion — poll descriptor status for Cmplt bit
    for i in range(2000):
        desc_status = reg_read(desc_m, SG_STATUS)
        if desc_status & 0x80000000:  # Cmplt bit
            break
        time.sleep(0.001)
    else:
        dma_sr = reg_read(dma_m, MM2S_DMASR)
        print(f"  WARNING: DMA did not complete")
        print(f"    DMASR=0x{dma_sr:08X}  DESC_STATUS=0x{desc_status:08X}")
        # Decode error bits
        if dma_sr & 0x0010: print("    -> DMAIntErr (internal error)")
        if dma_sr & 0x0020: print("    -> DMASlvErr (slave error)")
        if dma_sr & 0x0040: print("    -> DMADecErr (decode error)")
        if desc_status & 0x10000000: print("    -> DESC IntErr")
        if desc_status & 0x20000000: print("    -> DESC SlvErr")
        if desc_status & 0x40000000: print("    -> DESC DecErr")
        return False

    return True


def run_test(dma_m, desc_m, buf_m, xcorr_m, phase_deg):
    """Run one test case with a given phase offset."""
    print(f"\n--- Test: {phase_deg} degree phase offset ---")

    # Read STATUS to clear any previous sticky valid
    reg_read(xcorr_m, 0x08)

    # Generate and transfer data
    data = make_test_data(phase_deg)
    ok = run_dma_transfer(dma_m, desc_m, buf_m, data)

    if not ok:
        return

    # Small delay for pipeline to finish
    time.sleep(0.01)

    # Read xcorr registers
    xcorr_re = reg_read_signed(xcorr_m, 0x00)
    xcorr_im = reg_read_signed(xcorr_m, 0x04)
    status   = reg_read(xcorr_m, 0x08)
    snap_cnt = reg_read(xcorr_m, 0x0C)

    # NumPy reference
    ref_re, ref_im = numpy_reference(phase_deg)

    # Compute phase from FPGA result
    if xcorr_re != 0 or xcorr_im != 0:
        fpga_phase = math.degrees(math.atan2(xcorr_im, xcorr_re))
    else:
        fpga_phase = float('nan')

    ref_phase = math.degrees(math.atan2(ref_im, ref_re))

    print(f"  FPGA:  re={xcorr_re:>12d}  im={xcorr_im:>12d}  "
          f"phase={fpga_phase:>8.2f} deg")
    print(f"  NumPy: re={ref_re:>12d}  im={ref_im:>12d}  "
          f"phase={ref_phase:>8.2f} deg")
    print(f"  STATUS=0x{status:08X}  SNAP_COUNT={snap_cnt}")

    if status & 1:
        print("  result_valid: YES")
    else:
        print("  result_valid: NO (snapshot may not have completed)")


def main():
    print("=== xcorr_acc FPGA IP Test (SG DMA) ===")
    print(f"SNAPSHOT_LEN={SNAPSHOT_LEN}")
    print(f"DESC   @ 0x{DESC_PHYS:08X}")
    print(f"BUFFER @ 0x{DMA_BUF_PHYS:08X}")

    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)

    # Map register regions
    xcorr_m = mmap_region(fd, XCORR_BASE)
    dma_m   = mmap_region(fd, DMA_BASE)

    # Map SG descriptor region (one page)
    desc_m = mmap_region(fd, DESC_PHYS, PAGE_SIZE)

    # Map DMA data buffer (2 beats * SNAPSHOT_LEN * 4 bytes = 8 KB)
    buf_size = SNAPSHOT_LEN * 2 * 4
    # Round up to page size
    buf_pages = (buf_size + PAGE_SIZE - 1) // PAGE_SIZE * PAGE_SIZE
    buf_m = mmap_region(fd, DMA_BUF_PHYS, buf_pages)

    # Print initial register state
    print(f"\nInitial registers:")
    print(f"  XCORR_RE   = 0x{reg_read(xcorr_m, 0x00):08X}")
    print(f"  XCORR_IM   = 0x{reg_read(xcorr_m, 0x04):08X}")
    print(f"  STATUS     = 0x{reg_read(xcorr_m, 0x08):08X}")
    print(f"  SNAP_COUNT = {reg_read(xcorr_m, 0x0C)}")
    print(f"  DMA CR     = 0x{reg_read(dma_m, MM2S_DMACR):08X}")
    print(f"  DMA SR     = 0x{reg_read(dma_m, MM2S_DMASR):08X}")

    # Run test cases: 0, 45, 90, 180 degrees (same as simulation)
    for phase in [0, 45, 90, 180]:
        run_test(dma_m, desc_m, buf_m, xcorr_m, phase)

    # Cleanup
    xcorr_m.close()
    dma_m.close()
    desc_m.close()
    buf_m.close()
    os.close(fd)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
