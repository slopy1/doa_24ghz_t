#!/usr/bin/env python3
"""
aoa_estimation_fpga_kv260.py — KV260 FPGA-Accelerated DoA Driver

Port of aoa_estimation_fpga_v3.py (Cora Z7 / Phase A) to the Kria KV260
(Zynq UltraScale+ xck26, Ubuntu image). The RTL (doa_pipeline.v) is
identical; the platform layer changes are:

  Cora Z7 (PetaLinux)             →  KV260 (Ubuntu 22.04)
  ─────────────────────────────────────────────────────────
  BusyBox SysVinit                    systemd
  /dev/mem for AXI-Lite registers     PS GPIO_EMIO + libgpiod for
    (PetaLinux kernel permissive)     doa_pipeline CSRs; UIO only for DMA
  DESC_PHYS = 0x1F000000 (OCM)        udmabuf module (phys addr via sysfs)
  DMA_BUF_PHYS = 0x1F001000           follows desc in same udmabuf region
  AXI base = 0x40000000 (GP0 range)   DMA regs at 0xA0000000 (HPM0_FPD)
  Bitstream via SD card swap          fpgautil -b design.bit.bin -o dtbo

doa_pipeline register access uses the EMIO Path C handshake implemented by
fpga/rtl/emio_regfile.v. AXI DMA control uses a UIO-visible dma_safe_ctrl shim:
Linux only touches 16-byte-spaced offsets that survive the KV260 HPM0_FPD
stride bug, and the shim programs the stock AXI DMA registers inside PL.

Hardware register map (doa_pipeline.v, same as Phase A):
    0x00/04 XCORR_RE_LO/HI  48-bit signed
    0x08/0C XCORR_IM_LO/HI  48-bit signed
    0x10/14 R00_LO/HI        48-bit unsigned
    0x18/1C R11_LO/HI        48-bit unsigned
    0x20    STATUS           bit 0 = result_valid (clear-on-read)
    0x24    SNAP_COUNT
    0x28    COS_CAL          Q1.15 RW
    0x2C    SIN_CAL          Q1.15 RW
    0x30    COEFF_ADDR       FIR tap index 0..23
    0x34    COEFF_DATA       write triggers FIR load
    0x38    FILTER_CTRL      bit 0 = enable, bit 1 = loaded

Prerequisites:
    sudo apt install python3-libgpiod
    sudo modprobe u-dma-buf udmabuf0=<size>  # see setup_kv260.sh
    sudo fpgautil -b emio_doa.bit.bin -o emio_doa.dtbo -f Full -n Full

Usage:
    sudo python3 aoa_estimation_fpga_kv260.py --cal=0.0 --algo=ROOTMUSIC
"""

import mmap
import math
import os
import struct
import sys
import time
import argparse
import json
import queue
import threading
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    HAS_SOAPY = True
except ImportError:
    HAS_SOAPY = False
    print("# WARNING: SoapySDR not available, running in simulation mode")


# =============================================================================
# Configuration
# =============================================================================

class KV260Config:
    """KV260-specific parameters. AXI-Lite addresses must match the
    Vivado block design address editor (fpga/vivado_kv260/)."""

    # RF
    CENTER_FREQ  = 2.42e9
    SAMPLE_RATE  = 1e6
    BANDWIDTH    = 1e6
    RX_GAIN      = 40

    # Array geometry
    ANTENNA_SPACING_NORM = 0.5
    NUM_ELEMENTS = 2
    NUM_SOURCES  = 1

    # Processing
    SNAPSHOT_SIZE = 1024       # must match doa_pipeline SNAPSHOT_LEN
    NUM_SNAPSHOTS = 100
    MUSIC_SPECTRUM_POINTS = 181

    UPDATE_INTERVAL = 0.1
    CONTINUOUS = True

    PHASE_CAL_DEG = 0.0
    CAL_FROM_CLI = False
    ALGORITHM = "ROOTMUSIC"

    FILTER_TYPE  = "none"      # "none", "bandpass", "lowpass", "arm_bandpass"
    TONE_FREQ    = 50e3
    BPF_HALF_BW  = 400e3   # widened from 10e3 to match BLE 1 Mbps GFSK ~1.4 MHz BW
    LPF_CUTOFF   = 50e3
    # arm_bandpass: hybrid mode. Fabric FIR is bypassed, and a strictly
    # positive-frequency FFT bandpass is applied on ARM before DMA into fabric.
    # The wide passband keeps the BLE upper-side energy while rejecting the
    # negative-frequency contamination/image region seen in spectrum sweeps.
    ARM_BPF_HALF_BW = 250e3

    # --- EMIO register bridge (doa_pipeline CSRs) ---
    # ZynqMP GPIO exposes MIO first, then EMIO. On standard Kria Ubuntu,
    # EMIO bit 0 is line 78 on the PS GPIO chip.
    EMIO_GPIOCHIP = "/dev/gpiochip1"
    EMIO_BASE_LINE = 78
    EMIO_TIMEOUT_S = 0.1

    # --- UIO device node for AXI DMA safe-control shim ---
    UIO_DMA = "/dev/uio0"
    UIO_DMA_REG_NAME = "dma_safe_ctrl_regs"

    # --- udmabuf (DMA descriptor + sample buffer) ---
    # Load module before running: sudo modprobe u-dma-buf udmabuf0=<bytes>
    # Required size: PAGE_SIZE (descriptor) + SNAPSHOT_SIZE * 2 * 4 (data)
    # Minimum: 4096 + 8192 = 12288 → round up to 16384 for safety.
    UDMABUF_NAME = "udmabuf0"

    DEBUG = False
    DEBUG_TIMING = False
    PREFETCH = True

    @classmethod
    def from_args(cls, args):
        cls.CAL_FROM_CLI = args.cal is not None
        if args.cal is not None:
            cls.PHASE_CAL_DEG = float(args.cal)
        if args.algo:
            cls.ALGORITHM = args.algo.upper()
        if args.freq:
            cls.CENTER_FREQ = float(args.freq)
        if args.gain:
            cls.RX_GAIN = int(args.gain)
        if args.snapshot_size:
            cls.SNAPSHOT_SIZE = int(args.snapshot_size)
        if args.single:
            cls.CONTINUOUS = False
        if getattr(args, 'debug', False):
            cls.DEBUG = True
        if getattr(args, 'time_stages', False):
            cls.DEBUG_TIMING = True
        if getattr(args, 'no_prefetch', False):
            cls.PREFETCH = False
        if getattr(args, 'filter', None):
            cls.FILTER_TYPE = args.filter.lower()
        if getattr(args, 'gpiochip', None):
            cls.EMIO_GPIOCHIP = args.gpiochip
        if getattr(args, 'emio_base_line', None) is not None:
            cls.EMIO_BASE_LINE = int(args.emio_base_line)
        if getattr(args, 'emio_timeout', None) is not None:
            cls.EMIO_TIMEOUT_S = float(args.emio_timeout)
        return cls


# =============================================================================
# Register constants (identical to v3 — same RTL)
# =============================================================================

REG_XCORR_RE_LO = 0x00
REG_XCORR_RE_HI = 0x04
REG_XCORR_IM_LO = 0x08
REG_XCORR_IM_HI = 0x0C
REG_R00_LO      = 0x10
REG_R00_HI      = 0x14
REG_R11_LO      = 0x18
REG_R11_HI      = 0x1C
REG_STATUS      = 0x20
REG_SNAP_COUNT  = 0x24
REG_COS_CAL     = 0x28
REG_SIN_CAL     = 0x2C
REG_COEFF_ADDR  = 0x30
REG_COEFF_DATA  = 0x34
REG_FILTER_CTRL = 0x38

STATUS_VALID_BIT       = 0x1
FILTER_CTRL_EN_BIT     = 0x1
FILTER_CTRL_LOADED_BIT = 0x2

NUM_UNIQUE_TAPS = 32   # was 24 — paired with NUM_HW_TAPS = 64
NUM_HW_TAPS     = 64   # was 48 — symmetric, NUM_UNIQUE_TAPS = NUM_HW_TAPS/2

PAGE_SIZE = 0x1000

# AXI DMA MM2S register offsets
MM2S_DMACR   = 0x00
MM2S_DMASR   = 0x04
MM2S_CURDESC = 0x08
MM2S_TAILDESC = 0x10

# dma_safe_ctrl maps Linux-visible safe offsets to real AXI DMA offsets by
# dividing the address by 4. These methods preserve the logical AXI DMA register
# offsets above while avoiding HPM0_FPD writes to unsafe words like 0x08.
DMA_SAFE_STRIDE_SCALE = 4

# Scatter-gather descriptor field offsets
SG_NXTDESC     = 0x00
SG_NXTDESC_MSB = 0x04
SG_BUFFER      = 0x08
SG_BUFFER_MSB  = 0x0C
SG_CONTROL     = 0x18
SG_STATUS      = 0x1C
SG_SOF = (1 << 26)
SG_EOF = (1 << 27)


# =============================================================================
# Snapshot result
# =============================================================================

@dataclass
class Snapshot:
    xcorr_re:   int
    xcorr_im:   int
    r00:        int
    r11:        int
    snap_count: int

    def covariance(self) -> np.ndarray:
        r01 = complex(self.xcorr_re, self.xcorr_im)
        return np.array([
            [self.r00,       r01],
            [np.conj(r01),   self.r11],
        ], dtype=np.complex128)


# =============================================================================
# EMIO register access
# =============================================================================

def find_uio_by_reg_name(reg_name: str, fallback: str) -> str:
    """Find a /dev/uioN by map0/name or device name, with a path fallback."""
    sysfs = Path("/sys/class/uio")
    if sysfs.exists():
        for uio in sorted(sysfs.glob("uio*")):
            candidates = [uio / "maps" / "map0" / "name", uio / "name"]
            for candidate in candidates:
                try:
                    if candidate.read_text().strip() == reg_name:
                        return f"/dev/{uio.name}"
                except OSError:
                    pass
    return fallback


class EmioGpioV1:
    """libgpiod 1.x adapter."""

    def __init__(self, chip_path: str, base_line: int):
        import gpiod

        self.gpiod = gpiod
        self.chip = gpiod.Chip(chip_path)
        self.out_offsets = [base_line + i for i in range(40)]
        self.in_offsets = [base_line + i for i in range(40, 74)]
        self.out_lines = self.chip.get_lines(self.out_offsets)
        self.in_lines = self.chip.get_lines(self.in_offsets)
        self.out_lines.request(
            consumer="doa-emio-driver",
            type=gpiod.LINE_REQ_DIR_OUT,
            default_vals=[0] * len(self.out_offsets),
        )
        self.in_lines.request(
            consumer="doa-emio-driver",
            type=gpiod.LINE_REQ_DIR_IN,
        )

    def close(self) -> None:
        self.out_lines.release()
        self.in_lines.release()
        self.chip.close()

    def set_outputs(self, values) -> None:
        self.out_lines.set_values(values)

    def get_inputs(self):
        return self.in_lines.get_values()


class EmioGpioV2:
    """libgpiod 2.x adapter."""

    def __init__(self, chip_path: str, base_line: int):
        import gpiod

        self.gpiod = gpiod
        self.out_offsets = [base_line + i for i in range(40)]
        self.in_offsets = [base_line + i for i in range(40, 74)]
        self.value_active = gpiod.line.Value.ACTIVE
        self.value_inactive = gpiod.line.Value.INACTIVE
        out_settings = gpiod.LineSettings(
            direction=gpiod.line.Direction.OUTPUT,
            output_value=self.value_inactive,
        )
        in_settings = gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)
        # Kernel GPIO ABI v2 caps a single request at GPIO_V2_LINES_MAX = 64
        # (40 OUT + 34 IN = 74 > cap). Split into two disjoint requests.
        self.out_request = gpiod.request_lines(
            chip_path,
            consumer="doa-emio-driver-out",
            config={offset: out_settings for offset in self.out_offsets},
        )
        self.in_request = gpiod.request_lines(
            chip_path,
            consumer="doa-emio-driver-in",
            config={offset: in_settings for offset in self.in_offsets},
        )

    def close(self) -> None:
        self.out_request.release()
        self.in_request.release()

    def set_outputs(self, values) -> None:
        self.out_request.set_values({
            offset: (self.value_active if value else self.value_inactive)
            for offset, value in zip(self.out_offsets, values)
        })

    def get_inputs(self):
        vals = self.in_request.get_values(self.in_offsets)
        return [int(v == self.value_active) for v in vals]


class EmioRegisterIO:
    """Four-phase EMIO protocol for fpga/rtl/emio_regfile.v."""

    def __init__(self, chip_path: str, base_line: int, timeout_s: float):
        try:
            import gpiod
        except ImportError as exc:
            raise RuntimeError("python3-libgpiod is required for EMIO Path C") from exc

        if hasattr(gpiod, "request_lines"):
            self.gpio = EmioGpioV2(chip_path, base_line)
        else:
            self.gpio = EmioGpioV1(chip_path, base_line)
        self.timeout_s = timeout_s
        self._outputs = [0] * 40
        self.gpio.set_outputs(self._outputs)

    def close(self) -> None:
        self._outputs = [0] * 40
        self.gpio.set_outputs(self._outputs)
        self.gpio.close()

    @staticmethod
    def _bits(value: int, width: int):
        return [(value >> bit) & 1 for bit in range(width)]

    @staticmethod
    def _word(bits) -> int:
        value = 0
        for bit, bit_value in enumerate(bits):
            value |= (bit_value & 1) << bit
        return value & 0xFFFFFFFF

    def _drive(self, addr: int, wdata: int, we: bool, re: bool, req: bool) -> None:
        values = [0] * 40
        values[0:5] = self._bits(addr & 0x1F, 5)
        values[5:37] = self._bits(wdata & 0xFFFFFFFF, 32)
        values[37] = 1 if we else 0
        values[38] = 1 if re else 0
        values[39] = 1 if req else 0
        self._outputs = values
        self.gpio.set_outputs(values)

    def _wait_done(self, expected: int):
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            inputs = self.gpio.get_inputs()
            if inputs[32] == expected:
                return inputs
            time.sleep(0.00001)
        raise TimeoutError(f"timeout waiting for EMIO done={expected}")

    def write32(self, offset: int, value: int) -> None:
        addr = (offset >> 2) & 0x1F
        self._drive(addr, value, we=True, re=False, req=False)
        self._drive(addr, value, we=True, re=False, req=True)
        self._wait_done(1)
        self._drive(addr, value, we=True, re=False, req=False)
        self._wait_done(0)
        self._drive(0, 0, we=False, re=False, req=False)

    def read32(self, offset: int) -> int:
        addr = (offset >> 2) & 0x1F
        self._drive(addr, 0, we=False, re=True, req=False)
        self._drive(addr, 0, we=False, re=True, req=True)
        inputs = self._wait_done(1)
        if inputs[33] != 1:
            raise RuntimeError("EMIO read completed without rdata_valid")
        value = self._word(inputs[0:32])
        self._drive(addr, 0, we=False, re=True, req=False)
        self._wait_done(0)
        self._drive(0, 0, we=False, re=False, req=False)
        return value


# =============================================================================
# KV260Pipeline — hardware abstraction
# =============================================================================

class KV260Pipeline:
    """Low-level interface to doa_pipeline IP on KV260 Ubuntu.

    doa_pipeline registers: PS GPIO_EMIO + libgpiod four-phase handshake.
    DMA control registers: UIO mmap of dma_safe_ctrl's 16-byte-spaced window.
    DMA descriptor + buffer: udmabuf (different from Cora's hardcoded OCM).

    Usage:
        with KV260Pipeline(config) as pipe:
            pipe.write_calibration(cal_deg=0.0)
            pipe.load_fir_taps(taps_q15)
            pipe.set_filter_enable(True)
            snap = pipe.run_snapshot(ch0, ch1)
    """

    def __init__(self, config: KV260Config):
        self.config = config
        self.reg_io = None      # EMIO/libgpiod — doa_pipeline registers
        self.dma_fd = None      # /dev/uioN — dma_safe_ctrl registers
        self.udmabuf_fd = None  # /dev/udmabuf0 — DMA memory
        self.dma_m = None
        self.desc_m = None
        self.buf_m = None
        self._desc_phys = None
        self._buf_phys = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def open(self) -> None:
        """Open EMIO register bridge, DMA UIO, and udmabuf DMA memory."""
        self.reg_io = EmioRegisterIO(
            self.config.EMIO_GPIOCHIP,
            self.config.EMIO_BASE_LINE,
            self.config.EMIO_TIMEOUT_S,
        )

        dma_uio = find_uio_by_reg_name(self.config.UIO_DMA_REG_NAME, self.config.UIO_DMA)
        if not Path(dma_uio).exists():
            raise RuntimeError(
                f"{dma_uio} not found — is the EMIO + DMA-safe overlay loaded?\n"
                f"  Run: sudo fpgautil -b emio_doa.bit.bin -o emio_doa.dtbo -f Full -n Full"
            )
        self.dma_fd = os.open(dma_uio, os.O_RDWR | os.O_SYNC)
        self.dma_m    = mmap.mmap(self.dma_fd, PAGE_SIZE)

        # ── DMA memory via udmabuf ────────────────────────────────────────
        # udmabuf allocates physically contiguous memory and exposes the
        # physical address via sysfs — no hardcoded OCM address needed.
        name = self.config.UDMABUF_NAME
        sysfs = Path(f"/sys/class/u-dma-buf/{name}")
        buf_size  = self.config.SNAPSHOT_SIZE * 2 * 4   # SC16, 2 beats/sample
        buf_pages = ((buf_size + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
        required  = PAGE_SIZE + buf_pages                # desc page + data
        if not sysfs.exists():
            raise RuntimeError(
                f"/sys/class/u-dma-buf/{name} not found. "
                f"Run: sudo modprobe u-dma-buf {name}={required}"
            )
        udmabuf_phys = int((sysfs / "phys_addr").read_text().strip(), 16)
        udmabuf_size = int((sysfs / "size").read_text().strip())

        if udmabuf_size < required:
            raise RuntimeError(
                f"udmabuf size {udmabuf_size} < required {required}. "
                f"Reload with: sudo modprobe u-dma-buf {name}={required}"
            )

        self.udmabuf_fd = os.open(f"/dev/{name}", os.O_RDWR | os.O_SYNC)
        # Descriptor occupies first PAGE_SIZE bytes; data buffer follows.
        self.desc_m = mmap.mmap(self.udmabuf_fd, PAGE_SIZE, offset=0)
        self.buf_m  = mmap.mmap(self.udmabuf_fd, buf_pages, offset=PAGE_SIZE)
        self._desc_phys = udmabuf_phys
        self._buf_phys  = udmabuf_phys + PAGE_SIZE

        # Sanity-check AXI-Lite decode
        _ = self._read32(REG_STATUS)

    def close(self) -> None:
        if self.reg_io is not None:
            self.reg_io.close()
            self.reg_io = None
        for m in (self.dma_m, self.desc_m, self.buf_m):
            if m is not None:
                m.close()
        self.dma_m = self.desc_m = self.buf_m = None
        for fd_attr in ("dma_fd", "udmabuf_fd"):
            fd = getattr(self, fd_attr)
            if fd is not None:
                os.close(fd)
                setattr(self, fd_attr, None)

    # ── raw register accessors ─────────────────────────────────────────────

    def _read32(self, offset: int) -> int:
        return self.reg_io.read32(offset)

    def _read32_signed(self, offset: int) -> int:
        value = self._read32(offset)
        return value - (1 << 32) if value & (1 << 31) else value

    def _write32(self, offset: int, value: int) -> None:
        self.reg_io.write32(offset, value & 0xFFFFFFFF)

    def _read_48(self, lo_off: int, hi_off: int, signed: bool) -> int:
        lo = self._read32(lo_off)
        hi = self._read32(hi_off) & 0xFFFF
        combined = (hi << 32) | lo
        if signed and (combined & (1 << 47)):
            combined -= (1 << 48)
        return combined

    # ── calibration ───────────────────────────────────────────────────────

    def write_calibration(self, cal_deg: float) -> None:
        phi = math.radians(cal_deg)
        cos_q15 = max(-32768, min(32767, int(round(math.cos(phi) * 32767.0)))) & 0xFFFF
        sin_q15 = max(-32768, min(32767, int(round(math.sin(phi) * 32767.0)))) & 0xFFFF
        self._write32(REG_COS_CAL, cos_q15)
        self._write32(REG_SIN_CAL, sin_q15)

    def read_calibration(self) -> Tuple[int, int]:
        return (self._read32_signed(REG_COS_CAL), self._read32_signed(REG_SIN_CAL))

    # ── FIR ───────────────────────────────────────────────────────────────

    def load_fir_taps(self, taps_q15: np.ndarray) -> None:
        if len(taps_q15) != NUM_UNIQUE_TAPS:
            raise ValueError(f"Expected {NUM_UNIQUE_TAPS} taps, got {len(taps_q15)}")
        for idx in range(NUM_UNIQUE_TAPS):
            tap = max(-32768, min(32767, int(taps_q15[idx]))) & 0xFFFF
            self._write32(REG_COEFF_ADDR, idx)
            self._write32(REG_COEFF_DATA, tap)
        cur = self._read32(REG_FILTER_CTRL)
        self._write32(REG_FILTER_CTRL, (cur & FILTER_CTRL_EN_BIT) | FILTER_CTRL_LOADED_BIT)

    def set_filter_enable(self, enable: bool) -> None:
        cur = self._read32(REG_FILTER_CTRL)
        self._write32(REG_FILTER_CTRL,
                      (cur | FILTER_CTRL_EN_BIT) if enable else (cur & ~FILTER_CTRL_EN_BIT))

    # ── DMA snapshot ──────────────────────────────────────────────────────

    def _write_desc(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.desc_m, offset, value & 0xFFFFFFFF)

    def _read_desc(self, offset: int) -> int:
        return struct.unpack_from("<I", self.desc_m, offset)[0]

    def _write_dma(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.dma_m, self._dma_safe_offset(offset), value & 0xFFFFFFFF)

    def _read_dma(self, offset: int) -> int:
        return struct.unpack_from("<I", self.dma_m, self._dma_safe_offset(offset))[0]

    @staticmethod
    def _dma_safe_offset(offset: int) -> int:
        if offset & 0x3:
            raise ValueError(f"DMA register offset must be 32-bit aligned: 0x{offset:x}")
        return offset * DMA_SAFE_STRIDE_SCALE

    def _setup_sg_descriptor(self, nbytes: int) -> None:
        self._write_desc(SG_NXTDESC,     self._desc_phys)
        self._write_desc(SG_NXTDESC_MSB, 0)
        self._write_desc(SG_BUFFER,      self._buf_phys)
        self._write_desc(SG_BUFFER_MSB,  0)
        self._write_desc(0x10, 0)
        self._write_desc(0x14, 0)
        self._write_desc(SG_CONTROL, SG_SOF | SG_EOF | (nbytes & 0x7FFFFF))
        self._write_desc(SG_STATUS, 0)

    def run_snapshot(self, ch0: np.ndarray, ch1: np.ndarray) -> Optional[Snapshot]:
        """Stream one snapshot through the PL pipeline and read results."""
        n = self.config.SNAPSHOT_SIZE
        debug_t = self.config.DEBUG_TIMING
        t0 = time.perf_counter() if debug_t else 0.0
        scale = 32767.0
        ch0_i = np.clip(np.real(ch0[:n]) * scale, -32768, 32767).astype(np.int16)
        ch0_q = np.clip(np.imag(ch0[:n]) * scale, -32768, 32767).astype(np.int16)
        ch1_i = np.clip(np.real(ch1[:n]) * scale, -32768, 32767).astype(np.int16)
        ch1_q = np.clip(np.imag(ch1[:n]) * scale, -32768, 32767).astype(np.int16)

        buf = np.empty(n * 2, dtype=np.uint32)
        buf[0::2] = (ch0_q.astype(np.uint16).astype(np.uint32) << 16) | ch0_i.astype(np.uint16).astype(np.uint32)
        buf[1::2] = (ch1_q.astype(np.uint16).astype(np.uint32) << 16) | ch1_i.astype(np.uint16).astype(np.uint32)

        data_bytes = buf.tobytes()
        nbytes = len(data_bytes)
        t_pack = time.perf_counter() if debug_t else 0.0

        _ = self._read32(REG_STATUS)  # clear sticky valid

        # Reset DMA MM2S channel
        self._write_dma(MM2S_DMACR, 0x0004)
        for _ in range(100):
            if not (self._read_dma(MM2S_DMACR) & 0x0004):
                break
            time.sleep(0.0001)

        self.buf_m.seek(0)
        self.buf_m.write(data_bytes)

        self._setup_sg_descriptor(nbytes)
        self._write_dma(MM2S_CURDESC, self._desc_phys)
        self._write_dma(MM2S_DMACR, 0x0001)
        time.sleep(0.0001)
        self._write_dma(MM2S_TAILDESC, self._desc_phys)
        t_dma_kick = time.perf_counter() if debug_t else 0.0

        # Wait for DMA completion (descriptor status bit 31).
        # _read_desc is mmap (~ns), so 200×100µs = 20ms is plenty.
        for _ in range(200):
            if self._read_desc(SG_STATUS) & 0x80000000:
                break
            time.sleep(0.0001)
        else:
            print("ERROR:DMA timeout - check bitstream loaded and addresses match BD", flush=True)
            return None
        t_dma_done = time.perf_counter() if debug_t else 0.0

        # Wait for pipeline result. EMIO _read32 is ~1.3ms, which is its own pacer
        # — no sleep needed. 50 iters caps each failure at ~65ms (vs 1.18s previously).
        for _ in range(50):
            if self._read32(REG_STATUS) & STATUS_VALID_BIT:
                break
        else:
            return None  # not a fault — filter needs more samples or RTL race
        t_pl_done = time.perf_counter() if debug_t else 0.0

        snap = Snapshot(
            xcorr_re   = self._read_48(REG_XCORR_RE_LO, REG_XCORR_RE_HI, signed=True),
            xcorr_im   = self._read_48(REG_XCORR_IM_LO, REG_XCORR_IM_HI, signed=True),
            r00        = self._read_48(REG_R00_LO,       REG_R00_HI,       signed=False),
            r11        = self._read_48(REG_R11_LO,       REG_R11_HI,       signed=False),
            snap_count = self._read32(REG_SNAP_COUNT),
        )
        if debug_t:
            t_reads = time.perf_counter()
            print(
                f"# t_ms pack={1e3*(t_pack-t0):.2f} "
                f"dma_kick={1e3*(t_dma_kick-t_pack):.2f} "
                f"dma_done={1e3*(t_dma_done-t_dma_kick):.2f} "
                f"pl_done={1e3*(t_pl_done-t_dma_done):.2f} "
                f"reg_reads={1e3*(t_reads-t_pl_done):.2f} "
                f"total={1e3*(t_reads-t0):.2f}",
                flush=True,
            )
        return snap

    def probe(self) -> dict:
        """Read all registers for diagnostic output."""
        return {
            "xcorr_re":   self._read_48(REG_XCORR_RE_LO, REG_XCORR_RE_HI, True),
            "xcorr_im":   self._read_48(REG_XCORR_IM_LO, REG_XCORR_IM_HI, True),
            "r00":        self._read_48(REG_R00_LO,       REG_R00_HI,       False),
            "r11":        self._read_48(REG_R11_LO,       REG_R11_HI,       False),
            "status":     self._read32(REG_STATUS),
            "snap_count": self._read32(REG_SNAP_COUNT),
            "cos_cal":    self._read32_signed(REG_COS_CAL),
            "sin_cal":    self._read32_signed(REG_SIN_CAL),
            "filter_ctrl": self._read32(REG_FILTER_CTRL),
            "desc_phys":  hex(self._desc_phys),
            "buf_phys":   hex(self._buf_phys),
        }


# =============================================================================
# FIR coefficient generation (identical to v3 — NumPy windowed-sinc)
# =============================================================================

def _sinc_lowpass_48(cutoff_hz: float, fs: float) -> np.ndarray:
    N = NUM_HW_TAPS
    fc = cutoff_hz / fs
    n = np.arange(N)
    h = np.sinc(2 * fc * (n - (N - 1) / 2))
    h *= np.blackman(N)
    h /= np.sum(h)
    return h


def design_fir_taps(config: KV260Config) -> Optional[np.ndarray]:
    # arm_bandpass mode keeps the fabric FIR bypassed and filters on ARM
    if config.FILTER_TYPE in ("none", "arm_bandpass"):
        return None
    fs = config.SAMPLE_RATE
    if config.FILTER_TYPE == "lowpass":
        taps = _sinc_lowpass_48(config.LPF_CUTOFF, fs)
    elif config.FILTER_TYPE == "bandpass":
        f_lo = config.TONE_FREQ - config.BPF_HALF_BW
        f_hi = config.TONE_FREQ + config.BPF_HALF_BW
        taps = _sinc_lowpass_48(f_hi, fs) - _sinc_lowpass_48(f_lo, fs)
    else:
        return None
    peak = np.max(np.abs(np.fft.fft(taps, 512)))
    if peak > 0:
        taps /= peak
    taps = 0.5 * (taps + taps[::-1])
    taps_q15 = np.clip(np.round(taps * 32767.0), -32768, 32767).astype(np.int16)
    return taps_q15[:NUM_UNIQUE_TAPS]


def build_one_sided_bandpass_mask(config: KV260Config, nfft: int) -> np.ndarray:
    freqs = np.fft.fftfreq(nfft, 1.0 / config.SAMPLE_RATE)
    mask = ((freqs > 0.0) &
            (np.abs(freqs - config.TONE_FREQ) <= config.ARM_BPF_HALF_BW))
    return mask.astype(np.float32)


# =============================================================================
# DoA algorithms (identical to v3 — pure NumPy, vendor-neutral)
# =============================================================================

def steering_vector(theta_deg: float, d_lambda: float, n_elements: int) -> np.ndarray:
    n = np.arange(n_elements)
    phase = 2 * np.pi * d_lambda * (n - (n_elements - 1) / 2) * np.cos(np.deg2rad(theta_deg))
    return np.exp(1j * phase)


def root_music_doa(R: np.ndarray, d_lambda: float, num_sources: int = 1) -> float:
    if R.shape == (2, 2) and num_sources == 1:
        return _root_music_2x2(R, d_lambda)
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    eigenvectors = eigenvectors[:, np.argsort(eigenvalues)]
    En = eigenvectors[:, :R.shape[0] - num_sources]
    C = En @ En.conj().T
    roots = np.roots([C[0, 1], C[0, 0] + C[1, 1], C[1, 0]])
    best = roots[np.argmin(np.abs(np.abs(roots) - 1))]
    return float(np.rad2deg(np.arccos(np.clip(np.angle(best) / (2 * np.pi * d_lambda), -1, 1))))


def _root_music_2x2(R: np.ndarray, d_lambda: float) -> float:
    # Hermitian 2×2: closed-form noise-subspace eigenvector and quadratic root,
    # avoiding np.linalg.eigh + np.roots for ~10–50× speedup at this size.
    a = float(R[0, 0].real)
    d = float(R[1, 1].real)
    b = complex(R[0, 1])
    tr = a + d
    det = a * d - (b.real * b.real + b.imag * b.imag)
    disc = max(0.0, tr * tr - 4.0 * det)
    lam_min = 0.5 * (tr - np.sqrt(disc))
    e0 = b
    e1 = complex(lam_min - a, 0.0)
    if abs(e0) + abs(e1) < 1e-15:
        e0, e1 = complex(lam_min - d, 0.0), b.conjugate()
    norm = np.sqrt(abs(e0) ** 2 + abs(e1) ** 2)
    if norm < 1e-15:
        return 90.0
    e0 /= norm
    e1 /= norm
    C01 = e0 * e1.conjugate()
    C10 = e1 * e0.conjugate()
    if abs(C01) < 1e-15:
        return 90.0
    A = C01
    B = complex(1.0, 0.0)  # |e0|^2 + |e1|^2 = 1 by normalization
    Cc = C10
    sq = np.sqrt(B * B - 4.0 * A * Cc)
    r1 = (-B + sq) / (2.0 * A)
    r2 = (-B - sq) / (2.0 * A)
    best = r1 if abs(abs(r1) - 1.0) < abs(abs(r2) - 1.0) else r2
    return float(np.rad2deg(np.arccos(np.clip(np.angle(best) / (2.0 * np.pi * d_lambda), -1.0, 1.0))))


def music_doa(R: np.ndarray, d_lambda: float,
              num_sources: int = 1, num_points: int = 181) -> float:
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    En = eigenvectors[:, np.argsort(eigenvalues)][:, :R.shape[0] - num_sources]
    angles = np.linspace(0, 180, num_points)
    spectrum = np.array([
        1.0 / (np.abs(steering_vector(t, d_lambda, R.shape[0]).conj() @ En @ En.conj().T
                      @ steering_vector(t, d_lambda, R.shape[0])) + 1e-10)
        for t in angles
    ])
    return float(angles[np.argmax(spectrum)])


# =============================================================================
# SDR source (BladeRF via SoapySDR — same as v3, works on Ubuntu)
# =============================================================================

class BladeRFSource:
    def __init__(self, config: KV260Config):
        self.config = config
        self.sdr = None
        self.rx_stream = None

    def setup(self) -> bool:
        if not HAS_SOAPY:
            return False
        try:
            results = SoapySDR.Device.enumerate("driver=bladerf")
            if not results:
                print("ERROR:No BladeRF device found")
                return False
            self.sdr = SoapySDR.Device(results[0])
            for ch in [0, 1]:
                self.sdr.setSampleRate(SOAPY_SDR_RX, ch, self.config.SAMPLE_RATE)
                self.sdr.setFrequency(SOAPY_SDR_RX, ch, self.config.CENTER_FREQ)
                self.sdr.setBandwidth(SOAPY_SDR_RX, ch, self.config.BANDWIDTH)
                self.sdr.setGain(SOAPY_SDR_RX, ch, self.config.RX_GAIN)
            self.rx_stream = self.sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0, 1])
            self.sdr.activateStream(self.rx_stream)
            return True
        except Exception as e:
            print(f"ERROR:BladeRF setup failed: {e}")
            return False

    def read(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        n = self.config.SNAPSHOT_SIZE
        ch0 = np.zeros(n, dtype=np.complex64)
        ch1 = np.zeros(n, dtype=np.complex64)
        got = 0
        attempts = 0
        max_attempts = 64
        while got < n and attempts < max_attempts:
            view0 = ch0[got:]
            view1 = ch1[got:]
            sr = self.sdr.readStream(self.rx_stream, [view0, view1], n - got, timeoutUs=1000000)
            attempts += 1
            if sr.ret > 0:
                got += sr.ret
                continue
            if sr.ret == 0 or sr.ret == -1 or sr.ret == -4:
                continue  # timeout/overflow are advisory in SoapyBladeRF; keep draining
            return None, None  # STREAM_ERROR / CORRUPTION / etc. are fatal
        if got < n:
            return None, None
        return ch0, ch1

    def close(self):
        if self.sdr and self.rx_stream:
            self.sdr.deactivateStream(self.rx_stream)
            self.sdr.closeStream(self.rx_stream)
        if self.sdr:
            self.sdr = None


class SimulatedSource:
    """Synthetic IQ — 90° phase offset (broadside + 30° = 120° AoA)."""

    def __init__(self, config: KV260Config):
        self.config = config
        self._n = 0

    def setup(self) -> bool:
        return True

    def read(self) -> Tuple[np.ndarray, np.ndarray]:
        n = self.config.SNAPSHOT_SIZE
        t = np.arange(self._n, self._n + n) / self.config.SAMPLE_RATE
        self._n += n
        f = self.config.TONE_FREQ
        ch0 = np.exp(1j * 2 * np.pi * f * t).astype(np.complex64)
        ch1 = np.exp(1j * (2 * np.pi * f * t + np.pi / 2)).astype(np.complex64)
        return ch0, ch1

    def close(self):
        pass


# =============================================================================
# Main estimator loop
# =============================================================================

def load_calibration(cal_path: Path, warn: bool = False) -> Optional[float]:
    try:
        d = json.loads(cal_path.read_text())
        if not isinstance(d, dict):
            raise ValueError("expected JSON object")
        value = d.get("phase_offset_deg")
        if value is None:
            return None
        return float(value)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
        if warn:
            print(f"# WARNING: invalid calibration file {cal_path}: {e}",
                  flush=True)
        return None


def run(config: KV260Config) -> None:
    cal_path = Path(__file__).parent / "calibration.json"
    file_cal = load_calibration(cal_path, warn=not config.CAL_FROM_CLI)
    cal_deg = config.PHASE_CAL_DEG if config.CAL_FROM_CLI or file_cal is None else file_cal

    source = BladeRFSource(config) if HAS_SOAPY else SimulatedSource(config)
    if not source.setup():
        print("ERROR:SDR source failed to initialize")
        sys.exit(1)

    taps_q15 = design_fir_taps(config)

    arm_bpf_mask = None
    if config.FILTER_TYPE == "arm_bandpass":
        nfft = int(config.SNAPSHOT_SIZE)
        arm_bpf_mask = build_one_sided_bandpass_mask(config, nfft)
        print(f"# ARM-side one-sided bandpass: {config.TONE_FREQ/1e3:.0f} kHz "
              f"± {config.ARM_BPF_HALF_BW/1e3:.0f} kHz "
              f"positive bins only ({int(arm_bpf_mask.sum())} of {nfft} bins)",
              flush=True)

    prefetch_q: Optional[queue.Queue] = None
    prefetch_stop: Optional[threading.Event] = None
    prefetch_thread: Optional[threading.Thread] = None
    if config.PREFETCH:
        prefetch_q = queue.Queue(maxsize=1)
        prefetch_stop = threading.Event()

        def _prefetch_worker():
            i = 0
            while not prefetch_stop.is_set():
                t0 = time.perf_counter() if config.DEBUG_TIMING else 0.0
                pair = source.read()
                if config.DEBUG_TIMING:
                    dt = (time.perf_counter() - t0) * 1e3
                    i += 1
                    if i % 20 == 1:
                        print(f"# acquire(prefetch) #{i}: {dt:.2f} ms", flush=True)
                while not prefetch_stop.is_set():
                    try:
                        prefetch_q.put(pair, timeout=0.5)
                        break
                    except queue.Full:
                        continue

        prefetch_thread = threading.Thread(target=_prefetch_worker, daemon=True)
        prefetch_thread.start()
        if config.DEBUG_TIMING:
            print("# prefetch: ON", flush=True)

    next_call_idx = [0]

    def _next_samples():
        next_call_idx[0] += 1
        t0 = time.perf_counter() if config.DEBUG_TIMING else 0.0
        if prefetch_q is None:
            pair = source.read()
        else:
            try:
                pair = prefetch_q.get(timeout=2.0)
            except queue.Empty:
                return None, None
        if config.DEBUG_TIMING and (next_call_idx[0] % 20 == 1):
            dt = (time.perf_counter() - t0) * 1e3
            mode = "queue.get" if prefetch_q is not None else "source.read"
            print(f"# acquire({mode}) #{next_call_idx[0]}: {dt:.2f} ms", flush=True)
        return pair

    try:
        with KV260Pipeline(config) as pipe:
            pipe.write_calibration(cal_deg)

            if taps_q15 is not None:
                pipe.load_fir_taps(taps_q15)
                pipe.set_filter_enable(True)
                print(f"# FIR loaded: {config.FILTER_TYPE}", flush=True)
            else:
                pipe.set_filter_enable(False)
                if arm_bpf_mask is not None:
                    print("# Fabric FIR bypassed; ARM bandpass active", flush=True)

            if config.DEBUG:
                print(f"# probe: {pipe.probe()}", flush=True)

            R_accum = np.zeros((config.NUM_ELEMENTS, config.NUM_ELEMENTS), dtype=np.complex128)
            snap_count = 0
            last_emit = time.monotonic()
            source_none_count = 0
            snapshot_none_count = 0
            aoa_count = 0
            aoa_window_start = time.monotonic()
            loop_iter_idx = 0
            cal_mtime_cache = -1.0  # invalidate so first iteration loads
            t_loop_prev = time.perf_counter()
            t_prev_iter0 = time.perf_counter()
            snap_success = 0
            snap_fail = 0
            t_fail_total = 0.0

            while config.CONTINUOUS or snap_count < config.NUM_SNAPSHOTS:
                loop_iter_idx += 1
                t_iter0 = time.perf_counter() if config.DEBUG_TIMING else 0.0
                t_gap = (t_iter0 - t_loop_prev) if config.DEBUG_TIMING else 0.0

                # Hot-reload calibration only when the CLI did not provide
                # an explicit run calibration. Campaign scripts pass --cal.
                # Mtime-cache: stat is ~µs; full json open+parse on SD is ~100ms.
                if not config.CAL_FROM_CLI:
                    try:
                        cur_mtime = cal_path.stat().st_mtime
                    except OSError:
                        cur_mtime = -1.0
                    if cur_mtime != cal_mtime_cache:
                        cal_mtime_cache = cur_mtime
                        new_cal = load_calibration(cal_path)
                        if new_cal is not None and abs(new_cal - cal_deg) > 0.001:
                            print(f"# Calibration updated: {cal_deg:.2f} -> {new_cal:.2f}", flush=True)
                            cal_deg = new_cal
                            pipe.write_calibration(cal_deg)
                t_cal = time.perf_counter() if config.DEBUG_TIMING else 0.0

                ch0, ch1 = _next_samples()
                if ch0 is None or ch1 is None:
                    source_none_count += 1
                    if source_none_count == 10 or source_none_count % 50 == 0:
                        print(f"ERROR:SDR source returned no samples "
                              f"({source_none_count} consecutive reads)", flush=True)
                    continue
                source_none_count = 0

                if arm_bpf_mask is not None:
                    ch0 = np.fft.ifft(np.fft.fft(ch0) * arm_bpf_mask).astype(np.complex64)
                    ch1 = np.fft.ifft(np.fft.fft(ch1) * arm_bpf_mask).astype(np.complex64)

                t_snap0 = time.perf_counter() if config.DEBUG_TIMING else 0.0
                snap = pipe.run_snapshot(ch0, ch1)
                if snap is None:
                    if config.DEBUG_TIMING:
                        t_fail_total += time.perf_counter() - t_snap0
                        snap_fail += 1
                    snapshot_none_count += 1
                    if snapshot_none_count == 10 or snapshot_none_count % 50 == 0:
                        print(f"ERROR:FPGA snapshot unavailable "
                              f"({snapshot_none_count} consecutive attempts)", flush=True)
                    continue
                if config.DEBUG_TIMING:
                    snap_success += 1
                snapshot_none_count = 0

                R_accum += snap.covariance()
                snap_count += 1

                if config.DEBUG_TIMING:
                    t_iter_end = time.perf_counter()
                    period = t_iter0 - t_prev_iter0
                    t_prev_iter0 = t_iter0
                    if loop_iter_idx % 20 == 1:
                        n_total = snap_success + snap_fail
                        fail_pct = (100.0 * snap_fail / n_total) if n_total else 0.0
                        avg_fail_ms = (1e3 * t_fail_total / snap_fail) if snap_fail else 0.0
                        print(
                            f"# loop #{loop_iter_idx}: period={1e3*period:.2f} "
                            f"gap_pre={1e3*t_gap:.2f} "
                            f"cal={1e3*(t_cal-t_iter0):.2f} "
                            f"iter_total={1e3*(t_iter_end-t_iter0):.2f} ms | "
                            f"snap ok={snap_success} fail={snap_fail} "
                            f"({fail_pct:.0f}%) avg_fail={avg_fail_ms:.0f} ms",
                            flush=True,
                        )
                    t_loop_prev = t_iter_end

                now = time.monotonic()
                if snap_count >= config.NUM_SNAPSHOTS or (now - last_emit) >= config.UPDATE_INTERVAL:
                    R = R_accum / snap_count
                    R_accum[:] = 0
                    snap_count = 0
                    last_emit = now

                    try:
                        algo = config.ALGORITHM
                        if algo == "ROOTMUSIC":
                            angle = root_music_doa(R, config.ANTENNA_SPACING_NORM, config.NUM_SOURCES)
                        elif algo == "MUSIC":
                            angle = music_doa(R, config.ANTENNA_SPACING_NORM, config.NUM_SOURCES, config.MUSIC_SPECTRUM_POINTS)
                        else:
                            angle = root_music_doa(R, config.ANTENNA_SPACING_NORM, config.NUM_SOURCES)

                        print(f"AOA:{angle:.1f}", flush=True)
                        aoa_count += 1
                        if config.DEBUG_TIMING and aoa_count % 10 == 0:
                            elapsed = now - aoa_window_start
                            rate = aoa_count / elapsed if elapsed > 0 else 0.0
                            print(f"# rate: {aoa_count} AoA in {elapsed:.1f}s = "
                                  f"{rate:.2f} Hz", flush=True)
                    except Exception as e:
                        print(f"ERROR:{e}", flush=True)

    except KeyboardInterrupt:
        pass
    finally:
        if prefetch_stop is not None:
            prefetch_stop.set()
        source.close()


# =============================================================================
# Entry point
# =============================================================================

def parse_args():
    p = argparse.ArgumentParser(description="KV260 FPGA DoA driver")
    p.add_argument("--cal", type=float, default=None)
    p.add_argument("--algo", default="ROOTMUSIC")
    p.add_argument("--freq", type=float, default=None)
    p.add_argument("--gain", type=int, default=None)
    p.add_argument("--filter", default="none")
    p.add_argument("--snapshot-size", type=int, default=None)
    p.add_argument("--single", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--time-stages", action="store_true",
                   help="Print per-stage ms timings inside run_snapshot()")
    p.add_argument("--no-prefetch", action="store_true",
                   help="Disable BladeRF acquire-overlap prefetch thread")
    p.add_argument("--probe", action="store_true", help="dump registers and exit")
    p.add_argument("--gpiochip", default=None, help="PS GPIO chip for EMIO lines")
    p.add_argument("--emio-base-line", type=int, default=None,
                   help="line offset for EMIO bit 0 on the selected gpiochip")
    p.add_argument("--emio-timeout", type=float, default=None,
                   help="seconds to wait for each EMIO transaction")
    return p.parse_args()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: must run as root (UIO, udmabuf, and GPIO line requests require it)")
        sys.exit(1)

    args = parse_args()
    config = KV260Config.from_args(args)

    if args.probe:
        with KV260Pipeline(config) as pipe:
            import pprint
            pprint.pprint(pipe.probe())
        sys.exit(0)

    run(config)
