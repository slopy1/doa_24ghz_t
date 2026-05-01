#!/usr/bin/env python3
"""
aoa_estimation_fpga_v3.py - Phase A FPGA-Accelerated DoA Driver

Drives the `doa_pipeline` block inside the Phase A bitstream, which moves
the FIR filter, calibration phase rotation, cross-correlation, and
auto-correlations into fabric. The ARM side now only streams raw SC16
samples through DMA and reads the result latches.

Compared to v2 (Phase 0 'xcorr_acc only' path):
  - No software FIR filter        (hardware 48-tap symmetric FIR in fabric)
  - No software calibration rotate (hardware Q1.15 rotator in fabric)
  - No software r00/r11 power sum  (hardware autocorr_acc in fabric)
  - XCORR/R00/R11 are 48-bit, split LO/HI pairs
  - Full 15-register AXI-Lite map at 0x4000_0000

Hardware register map (see doa_pipeline.v header for details):
    0x00/04 XCORR_RE_LO/HI  48-bit signed, read LO then HI
    0x08/0C XCORR_IM_LO/HI  48-bit signed, read LO then HI
    0x10/14 R00_LO/HI        48-bit unsigned
    0x18/1C R11_LO/HI        48-bit unsigned
    0x20    STATUS           bit 0 = result_valid (clear-on-read)
    0x24    SNAP_COUNT       monotonically increasing
    0x28    COS_CAL          Q1.15 signed, RW, sign-extended on read
    0x2C    SIN_CAL          Q1.15 signed, RW, sign-extended on read
    0x30    COEFF_ADDR       FIR tap index 0..23
    0x34    COEFF_DATA       write triggers FIR coefficient load (Q1.15)
    0x38    FILTER_CTRL      bit 0 = enable, bit 1 = loaded flag

Output Protocol (unchanged from v2, so main.py swap is drop-in):
    AOA:<value>     - Estimated angle in degrees (0-180, broadside=90)
    ERROR:<msg>     - Error message

Usage (called by main.py, runs standalone for manual testing):
    sudo python3 aoa_estimation_fpga_v3.py \
        --cal=16.33 --algo=ROOTMUSIC --filter=bandpass

Requires: root access for /dev/mem (AXI-Lite + DMA).
Phase A bitstream must be loaded — v2 and v3 are NOT interchangeable.
"""

import numpy as np
import json
import mmap
import os
import struct
import argparse
import sys
import time
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# Try to import SoapySDR (simulated source used if absent)
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

class PhaseAConfig:
    """Phase A driver + estimation parameters. Single source of truth for
    sample rate, snapshot sizes, filter presets, and base addresses."""

    # --- RF ---
    CENTER_FREQ = 2.42e9
    SAMPLE_RATE = 1e6        # fs — hardcoded, scipy unavailable on Cora
    BANDWIDTH = 1e6
    RX_GAIN = 40

    # --- Array geometry ---
    ANTENNA_SPACING_NORM = 0.5
    NUM_ELEMENTS = 2
    NUM_SOURCES = 1

    # --- Processing ---
    SNAPSHOT_SIZE = 1024     # MUST match doa_pipeline SNAPSHOT_LEN parameter
    NUM_SNAPSHOTS = 100      # snapshots to average per AoA output
    MUSIC_SPECTRUM_POINTS = 181

    # --- Output cadence ---
    UPDATE_INTERVAL = 0.1
    CONTINUOUS = True

    # --- Calibration ---
    PHASE_CAL_DEG = 0.0

    # --- Algorithm ---
    ALGORITHM = "ROOTMUSIC"

    # --- Filtering (hardware FIR presets) ---
    # The hardware FIR is 48 taps symmetric = 24 unique Q1.15 coefficients.
    # Shape determined by FILTER_TYPE; passband edges in Hz (baseband).
    FILTER_TYPE = "none"     # "none", "bandpass", or "lowpass"
    TONE_FREQ = 50e3         # bandpass center (Hz)
    BPF_HALF_BW = 10e3       # bandpass half-bandwidth (Hz)
    LPF_CUTOFF = 50e3        # lowpass cutoff (Hz)

    # --- FPGA base addresses (match v2, unchanged in Phase A) ---
    XCORR_BASE   = 0x40000000
    DMA_BASE     = 0x40400000
    DESC_PHYS    = 0x1F000000
    DMA_BUF_PHYS = 0x1F001000

    DEBUG = False

    @classmethod
    def from_args(cls, args):
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
        if getattr(args, 'filter', None):
            cls.FILTER_TYPE = args.filter.lower()
        if getattr(args, 'tone_freq', None) is not None:
            cls.TONE_FREQ = float(args.tone_freq)
        if getattr(args, 'lpf_cutoff', None) is not None:
            cls.LPF_CUTOFF = float(args.lpf_cutoff)
        return cls


# =============================================================================
# Register map constants (doa_pipeline)
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

STATUS_VALID_BIT = 0x1
FILTER_CTRL_EN_BIT     = 0x1
FILTER_CTRL_LOADED_BIT = 0x2

# Hardware FIR: 48 total taps, symmetric → 24 unique coefficients to load.
NUM_UNIQUE_TAPS = 24
NUM_HW_TAPS = 48

# DMA MM2S (Scatter Gather, unchanged from v2)
PAGE_SIZE = 0x1000
MM2S_DMACR    = 0x00
MM2S_DMASR    = 0x04
MM2S_CURDESC  = 0x08
MM2S_TAILDESC = 0x10

SG_NXTDESC     = 0x00
SG_NXTDESC_MSB = 0x04
SG_BUFFER      = 0x08
SG_BUFFER_MSB  = 0x0C
SG_CONTROL     = 0x18
SG_STATUS      = 0x1C
SG_SOF = (1 << 26)
SG_EOF = (1 << 27)


# =============================================================================
# Snapshot result dataclass
# =============================================================================

@dataclass
class Snapshot:
    """One batch of hardware-accumulated results (48-bit registers)."""
    xcorr_re:   int      # signed
    xcorr_im:   int      # signed
    r00:        int      # unsigned
    r11:        int      # unsigned
    snap_count: int

    def covariance(self) -> np.ndarray:
        """Build the 2x2 covariance matrix R from this snapshot.

        All four entries must be in the same units (SC16^2 accumulated over
        SNAPSHOT_SIZE samples). The hardware guarantees this.
        """
        r01 = complex(self.xcorr_re, self.xcorr_im)
        return np.array([
            [self.r00,       r01],
            [np.conj(r01),   self.r11],
        ], dtype=np.complex128)


# =============================================================================
# Hardware abstraction — PhaseAPipeline
# =============================================================================

class PhaseAPipeline:
    """Low-level /dev/mem interface to the Phase A doa_pipeline IP.

    Owns the AXI-Lite register window, the DMA controller registers, and
    the DMA descriptor/buffer pages. Used as a context manager so the
    mmap regions and /dev/mem fd are always released cleanly on exit.

    Usage:
        with PhaseAPipeline(config) as pipe:
            pipe.write_calibration(cal_deg=16.33)
            pipe.load_fir_taps(taps_q15)
            pipe.set_filter_enable(True)
            snap = pipe.run_snapshot(ch0, ch1)
    """

    def __init__(self, config: PhaseAConfig):
        self.config = config
        self.fd = None
        self.xcorr_m = None
        self.dma_m = None
        self.desc_m = None
        self.buf_m = None

    # ------ context manager plumbing ------

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # don't suppress exceptions

    def open(self) -> None:
        """Map /dev/mem windows for registers, DMA, descriptor, and buffer.

        Raises OSError if /dev/mem cannot be opened (typically means we're
        not running as root)."""
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.xcorr_m = mmap.mmap(
            self.fd, PAGE_SIZE, offset=self.config.XCORR_BASE
        )
        self.dma_m = mmap.mmap(
            self.fd, PAGE_SIZE, offset=self.config.DMA_BASE
        )
        self.desc_m = mmap.mmap(
            self.fd, PAGE_SIZE, offset=self.config.DESC_PHYS
        )

        # Two beats per sample, 4 bytes per beat.
        buf_size = self.config.SNAPSHOT_SIZE * 2 * 4
        buf_pages = ((buf_size + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
        self.buf_m = mmap.mmap(
            self.fd, buf_pages, offset=self.config.DMA_BUF_PHYS
        )

        # Sanity check — any successful read confirms AXI-Lite decode.
        _ = self._read32(REG_STATUS)

    def close(self) -> None:
        for m in (self.xcorr_m, self.dma_m, self.desc_m, self.buf_m):
            if m is not None:
                m.close()
        self.xcorr_m = self.dma_m = self.desc_m = self.buf_m = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    # ------ raw 32-bit accessors ------

    def _read32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.xcorr_m, offset)[0]

    def _read32_signed(self, offset: int) -> int:
        return struct.unpack_from("<i", self.xcorr_m, offset)[0]

    def _write32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.xcorr_m, offset, value & 0xFFFFFFFF)

    # ------ 48-bit result readback ------
    #
    # The RTL sign-extends XCORR_{RE,IM}_HI to 32 bits already, but we
    # rebuild the 48-bit int manually so unsigned (R00/R11) and signed
    # (XCORR) paths share the same assembly — the sign fix is applied
    # after combining, not during each read. This is easier to audit
    # than juggling two different read helpers.

    def _read_48(self, lo_off: int, hi_off: int, signed: bool) -> int:
        lo = self._read32(lo_off)
        hi = self._read32(hi_off) & 0xFFFF   # upper 16 bits of 48-bit reg
        combined = (hi << 32) | lo
        if signed and (combined & (1 << 47)):
            combined -= (1 << 48)
        return combined

    # ------ calibration registers ------

    def write_calibration(self, cal_deg: float) -> None:
        """Push a new calibration angle to the hardware phase rotator.

        The rotator computes (I + jQ) * (cos_cal - j*sin_cal), i.e. a
        rotation by -phi where phi is the written angle. v2's software
        convention was `ch1 * exp(-j*deg2rad(cal_deg))`, which is
        exactly a rotation by -cal_deg — so we write
            cos_cal = cos(cal_rad)
            sin_cal = sin(cal_rad)
        with NO sign flip. Verified against phase_rotate_sc16.v header.
        """
        phi = math.radians(cal_deg)
        cos_q15 = int(round(math.cos(phi) * 32767.0))
        sin_q15 = int(round(math.sin(phi) * 32767.0))
        # Clamp into signed 16-bit range, just in case cal_deg is pathological
        cos_q15 = max(-32768, min(32767, cos_q15)) & 0xFFFF
        sin_q15 = max(-32768, min(32767, sin_q15)) & 0xFFFF
        self._write32(REG_COS_CAL, cos_q15)
        self._write32(REG_SIN_CAL, sin_q15)

    def read_calibration(self) -> Tuple[int, int]:
        """Return (cos_cal, sin_cal) as signed 32-bit ints (sign-extended by RTL)."""
        return (
            self._read32_signed(REG_COS_CAL),
            self._read32_signed(REG_SIN_CAL),
        )

    # ------ FIR coefficient load ------

    def load_fir_taps(self, taps_q15: np.ndarray) -> None:
        """Write 24 symmetric-half Q1.15 coefficients into the hardware FIR.

        The hardware stores only the unique 24 taps — symmetry is
        exploited by fir_filter_sc16's pair-add tree. Taps must be
        already quantized to int16 Q1.15.

        After loading, sets FILTER_CTRL[1] (loaded flag) so subsequent
        enables can verify coefficients are fresh.
        """
        if len(taps_q15) != NUM_UNIQUE_TAPS:
            raise ValueError(
                f"Expected {NUM_UNIQUE_TAPS} unique taps, got {len(taps_q15)}"
            )
        for idx in range(NUM_UNIQUE_TAPS):
            tap = int(taps_q15[idx])
            # Clamp to signed 16-bit just in case
            tap = max(-32768, min(32767, tap)) & 0xFFFF
            self._write32(REG_COEFF_ADDR, idx)
            self._write32(REG_COEFF_DATA, tap)

        # Leave filter disabled until set_filter_enable; just mark as loaded.
        cur = self._read32(REG_FILTER_CTRL)
        self._write32(REG_FILTER_CTRL, (cur & FILTER_CTRL_EN_BIT) | FILTER_CTRL_LOADED_BIT)

    def set_filter_enable(self, enable: bool) -> None:
        """Toggle the FIR filter bypass in fabric (bit 0 of FILTER_CTRL)."""
        cur = self._read32(REG_FILTER_CTRL)
        if enable:
            new = cur | FILTER_CTRL_EN_BIT
        else:
            new = cur & ~FILTER_CTRL_EN_BIT
        self._write32(REG_FILTER_CTRL, new)

    # ------ DMA transfer + result readback ------

    def _setup_sg_descriptor(self, nbytes: int) -> None:
        """Point the single-descriptor SG ring at our DMA buffer."""
        self._write_desc(SG_NXTDESC, self.config.DESC_PHYS)
        self._write_desc(SG_NXTDESC_MSB, 0)
        self._write_desc(SG_BUFFER, self.config.DMA_BUF_PHYS)
        self._write_desc(SG_BUFFER_MSB, 0)
        self._write_desc(0x10, 0)
        self._write_desc(0x14, 0)
        self._write_desc(SG_CONTROL, SG_SOF | SG_EOF | (nbytes & 0x7FFFFF))
        self._write_desc(SG_STATUS, 0)

    def _write_desc(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.desc_m, offset, value & 0xFFFFFFFF)

    def _read_desc(self, offset: int) -> int:
        return struct.unpack_from("<I", self.desc_m, offset)[0]

    def _write_dma(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.dma_m, offset, value & 0xFFFFFFFF)

    def _read_dma(self, offset: int) -> int:
        return struct.unpack_from("<I", self.dma_m, offset)[0]

    def run_snapshot(self, ch0: np.ndarray, ch1: np.ndarray) -> Optional[Snapshot]:
        """Stream one snapshot through the pipeline and read all results.

        Args:
            ch0, ch1: complex64 arrays, each of length SNAPSHOT_SIZE,
                      in BladeRF CF32 range (approximately [-1, 1]).

        Returns:
            Snapshot dataclass with all 4 result fields, or None on
            DMA/timeout failure.

        Note: calibration and FIR filtering happen in hardware. The
        caller must NOT pre-apply rotation or filtering in software —
        pass raw ch0/ch1 as read from BladeRF.
        """
        n = self.config.SNAPSHOT_SIZE

        # Convert CF32 → SC16 interleaved {Q[31:16], I[15:0]} per channel.
        # Same scaling factor as v2; BladeRF CF32 is nominally [-1, 1].
        scale = 32767.0
        ch0_i = np.clip(np.real(ch0[:n]) * scale, -32768, 32767).astype(np.int16)
        ch0_q = np.clip(np.imag(ch0[:n]) * scale, -32768, 32767).astype(np.int16)
        ch1_i = np.clip(np.real(ch1[:n]) * scale, -32768, 32767).astype(np.int16)
        ch1_q = np.clip(np.imag(ch1[:n]) * scale, -32768, 32767).astype(np.int16)

        buf = np.empty(n * 2, dtype=np.uint32)
        ch0_beat = (ch0_q.astype(np.uint16).astype(np.uint32) << 16) \
                   | ch0_i.astype(np.uint16).astype(np.uint32)
        ch1_beat = (ch1_q.astype(np.uint16).astype(np.uint32) << 16) \
                   | ch1_i.astype(np.uint16).astype(np.uint32)
        buf[0::2] = ch0_beat
        buf[1::2] = ch1_beat

        data_bytes = buf.tobytes()
        nbytes = len(data_bytes)

        # Clear sticky valid before kicking off — any STATUS read triggers
        # clear_valid in the RTL, so this is purely a pre-arm.
        _ = self._read32(REG_STATUS)

        # Reset DMA
        self._write_dma(MM2S_DMACR, 0x0004)
        for _ in range(100):
            if not (self._read_dma(MM2S_DMACR) & 0x0004):
                break
            time.sleep(0.0001)

        # Stage samples
        self.buf_m.seek(0)
        self.buf_m.write(data_bytes)

        # Descriptor + DMA startup (same ordering as v2)
        self._setup_sg_descriptor(nbytes)
        self._write_dma(MM2S_CURDESC, self.config.DESC_PHYS)
        self._write_dma(MM2S_DMACR, 0x0001)
        time.sleep(0.0001)
        self._write_dma(MM2S_TAILDESC, self.config.DESC_PHYS)

        # Wait for DMA completion (descriptor status bit 31 = completed)
        for _ in range(2000):
            if self._read_desc(SG_STATUS) & 0x80000000:
                break
            time.sleep(0.0001)
        else:
            return None

        # Wait for pipeline STATUS.valid. With filter_en=1 the FIR
        # decimates the sample stream (~1/50), so most DMAs won't
        # produce a result — xcorr_acc accumulates across DMAs until
        # SNAPSHOT_LEN filtered samples arrive. Short timeout (0.5 ms)
        # keeps the loop fast; None returns are expected and harmless.
        for _ in range(5):
            if self._read32(REG_STATUS) & STATUS_VALID_BIT:
                break
            time.sleep(0.0001)
        else:
            return None

        # Read all 8 result words as fast as possible, then snap_count.
        # The RTL latches update atomically on xcorr_valid, so as long
        # as the next snapshot doesn't arrive during this read burst
        # (~3 μs << 1 ms snapshot), we get a self-consistent view.
        xcorr_re = self._read_48(REG_XCORR_RE_LO, REG_XCORR_RE_HI, signed=True)
        xcorr_im = self._read_48(REG_XCORR_IM_LO, REG_XCORR_IM_HI, signed=True)
        r00      = self._read_48(REG_R00_LO,      REG_R00_HI,      signed=False)
        r11      = self._read_48(REG_R11_LO,      REG_R11_HI,      signed=False)
        snap_count = self._read32(REG_SNAP_COUNT)

        return Snapshot(
            xcorr_re=xcorr_re,
            xcorr_im=xcorr_im,
            r00=r00,
            r11=r11,
            snap_count=snap_count,
        )


# =============================================================================
# FIR tap design — NumPy only (scipy unavailable on Cora PetaLinux image)
# =============================================================================
#
# The hardware FIR is 48 taps symmetric, Q1.15 signed. Only the unique 24
# taps (taps[0..23]) are stored in BRAM; the symmetry tree folds taps[0]
# with taps[47], taps[1] with taps[46], etc.
#
# design_phase_a_fir() returns the 24 unique-half taps in Q1.15 int16
# format, ready to feed to PhaseAPipeline.load_fir_taps().
#
# Filter shapes match the v2 software presets (windowed-sinc, Hamming),
# just with NUM_HW_TAPS=48 instead of 201. Passband edges are driven by
# the same config fields so a unified calibration matches the software
# path modulo FIR-length-induced transition bandwidth.

def _sinc_lowpass_48(cutoff_hz: float, fs: float) -> np.ndarray:
    """48-tap windowed-sinc lowpass, normalized to unity DC gain."""
    fc = cutoff_hz / fs
    n = np.arange(NUM_HW_TAPS)
    mid = (NUM_HW_TAPS - 1) / 2.0
    h = np.sinc(2 * fc * (n - mid))
    h *= np.hamming(NUM_HW_TAPS)
    h /= np.sum(h)
    return h


def design_phase_a_fir(config: PhaseAConfig) -> Optional[np.ndarray]:
    """Design Phase A FIR taps. Returns 24 Q1.15 int16 values, or None.

    Returns None when FILTER_TYPE == 'none' — caller should then call
    set_filter_enable(False) to bypass the FIR in fabric.
    """
    if config.FILTER_TYPE == "none":
        return None

    fs = config.SAMPLE_RATE

    if config.FILTER_TYPE == "lowpass":
        taps = _sinc_lowpass_48(config.LPF_CUTOFF, fs)
    elif config.FILTER_TYPE == "bandpass":
        f_low  = config.TONE_FREQ - config.BPF_HALF_BW
        f_high = config.TONE_FREQ + config.BPF_HALF_BW
        taps = _sinc_lowpass_48(f_high, fs) - _sinc_lowpass_48(f_low, fs)
        # Normalize peak gain to 1 so quantization headroom is maximized.
        peak = np.max(np.abs(np.fft.fft(taps, 512)))
        if peak > 0:
            taps /= peak
    else:
        return None

    # The windowed-sinc construction above is symmetric by design, but
    # tiny numerical asymmetry can sneak in. Force exact symmetry so the
    # hardware's pair-add assumption holds.
    taps = 0.5 * (taps + taps[::-1])

    # Scale to Q1.15 and quantize. Using 32767 (not 32768) keeps +1.0
    # representable as the max positive value.
    taps_scaled = taps * 32767.0
    taps_q15 = np.clip(np.round(taps_scaled), -32768, 32767).astype(np.int16)

    # Return only the unique first half (taps[0..23]) — the hardware
    # reconstructs the full 48-tap response via symmetry.
    return taps_q15[:NUM_UNIQUE_TAPS]


# =============================================================================
# DoA algorithms — unchanged from v2 (numerics verified against headless)
# =============================================================================

def steering_vector(theta_deg: float, d_lambda: float, n_elements: int) -> np.ndarray:
    theta_rad = np.deg2rad(theta_deg)
    n = np.arange(n_elements)
    phase = 2 * np.pi * d_lambda * (n - (n_elements - 1) / 2) * np.cos(theta_rad)
    return np.exp(1j * phase)


def phase_difference_doa_fpga(xcorr_re: float, xcorr_im: float, d_lambda: float) -> float:
    phase_diff = math.atan2(xcorr_im, xcorr_re)
    cos_theta = phase_diff / (2 * math.pi * d_lambda)
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return math.degrees(math.acos(cos_theta))


def root_music_doa(R: np.ndarray, d_lambda: float, num_sources: int = 1) -> float:
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]
    En = eigenvectors[:, :R.shape[0] - num_sources]
    C = En @ En.conj().T
    # 2-element ULA closed-form: z-polynomial coefficients from C
    coeffs = [C[0, 1], C[0, 0] + C[1, 1], C[1, 0]]
    roots = np.roots(coeffs)
    unit_circle_dist = np.abs(np.abs(roots) - 1)
    best_root = roots[np.argmin(unit_circle_dist)]
    phase = np.angle(best_root)
    cos_theta = phase / (2 * np.pi * d_lambda)
    cos_theta = np.clip(cos_theta, -1, 1)
    return float(np.rad2deg(np.arccos(cos_theta)))


def music_doa(R: np.ndarray, d_lambda: float,
              num_sources: int = 1, num_points: int = 181) -> float:
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]
    noise_subspace = eigenvectors[:, :R.shape[0] - num_sources]
    angles = np.linspace(0, 180, num_points)
    spectrum = np.zeros(num_points)
    for i, theta in enumerate(angles):
        a = steering_vector(theta, d_lambda, R.shape[0])
        proj = a.conj() @ noise_subspace
        spectrum[i] = 1.0 / (np.abs(proj @ proj.conj()) + 1e-10)
    return float(angles[np.argmax(spectrum)])


def mvdr_doa(R: np.ndarray, d_lambda: float, num_points: int = 181) -> float:
    R_reg = R + 1e-6 * np.eye(R.shape[0])
    try:
        R_inv = np.linalg.inv(R_reg)
    except np.linalg.LinAlgError:
        R_inv = np.linalg.pinv(R_reg)
    angles = np.linspace(0, 180, num_points)
    spectrum = np.zeros(num_points)
    for i, theta in enumerate(angles):
        a = steering_vector(theta, d_lambda, R.shape[0])
        spectrum[i] = 1.0 / (np.abs(a.conj() @ R_inv @ a) + 1e-10)
    return float(angles[np.argmax(spectrum)])


# =============================================================================
# SDR sources
# =============================================================================

class BladeRFSource:
    """BladeRF via SoapySDR, 2-channel CF32 RX (matches v2)."""

    def __init__(self, config: PhaseAConfig):
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
            self.rx_stream = self.sdr.setupStream(
                SOAPY_SDR_RX, SOAPY_SDR_CF32, [0, 1]
            )
            self.sdr.activateStream(self.rx_stream)
            return True
        except Exception as e:
            print(f"ERROR:BladeRF setup failed: {e}")
            return False

    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        buffers = [np.zeros(num_samples, dtype=np.complex64) for _ in range(2)]
        read = 0
        while read < num_samples:
            chunk = min(65536, num_samples - read)
            views = [b[read:read + chunk] for b in buffers]
            sr = self.sdr.readStream(self.rx_stream, views, chunk, timeoutUs=1_000_000)
            if sr.ret > 0:
                read += sr.ret
            elif sr.ret < 0:
                break
        return buffers[0], buffers[1]

    def cleanup(self):
        if self.rx_stream is not None:
            self.sdr.deactivateStream(self.rx_stream)
            self.sdr.closeStream(self.rx_stream)
        self.sdr = None


class SimulatedSource:
    """Synthetic source for host-side debug runs (no SoapySDR)."""

    def __init__(self, config: PhaseAConfig):
        self.config = config
        self._true_angle = 45.0
        self._drift = 0.0

    def setup(self) -> bool:
        print(f"# SIMULATED: true angle = {self._true_angle}°")
        return True

    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        t = np.arange(num_samples) / self.config.SAMPLE_RATE
        self._drift += np.random.randn() * 0.1
        self._drift = np.clip(self._drift, -5, 5)
        angle = self._true_angle + self._drift
        a = steering_vector(angle, self.config.ANTENNA_SPACING_NORM, 2)
        signal = np.exp(1j * 2 * np.pi * 1000 * t)
        ch0 = a[0] * signal
        ch1 = a[1] * signal
        snr_db = 20
        noise_power = 10 ** (-snr_db / 10)
        ch0 += np.sqrt(noise_power / 2) * (
            np.random.randn(num_samples) + 1j * np.random.randn(num_samples)
        )
        ch1 += np.sqrt(noise_power / 2) * (
            np.random.randn(num_samples) + 1j * np.random.randn(num_samples)
        )
        return ch0.astype(np.complex64), ch1.astype(np.complex64)

    def cleanup(self):
        pass


# =============================================================================
# Estimation layer — PhaseAEstimator
# =============================================================================

class PhaseAEstimator:
    """DoA estimation loop that sits on top of a PhaseAPipeline.

    Owns the SDR source, the calibration hot-reload logic, and the
    snapshot-averaging math. Not a context manager itself — the caller
    owns the PhaseAPipeline context.
    """

    def __init__(self, config: PhaseAConfig, pipe: PhaseAPipeline):
        self.config = config
        self.pipe = pipe
        self.source = None
        self._current_cal = config.PHASE_CAL_DEG
        self._cal_file = Path(__file__).parent / "data" / "calibration.json"

    # ------ setup ------

    def configure(self) -> bool:
        """Bring up SDR, design FIR, push taps + cal + filter enable."""
        # SDR first — if it fails we don't bother touching fabric state.
        if HAS_SOAPY:
            self.source = BladeRFSource(self.config)
        else:
            self.source = SimulatedSource(self.config)
        if not self.source.setup():
            return False

        # FIR design + load. None → disable filter, anything else → load + enable.
        taps = design_phase_a_fir(self.config)
        if taps is not None:
            self.pipe.load_fir_taps(taps)
            self.pipe.set_filter_enable(True)
            print(f"# Filter: {self.config.FILTER_TYPE} "
                  f"(48-tap symmetric hardware FIR, loaded)")
        else:
            self.pipe.set_filter_enable(False)
            print("# Filter: none (hardware bypass)")

        # Initial calibration write — hot-reload loop will update each iteration.
        self.pipe.write_calibration(self._current_cal)
        print(f"# Calibration: {self._current_cal:.2f}° "
              f"(hardware phase rotator)")

        print("# Phase A FPGA-accelerated DoA estimation (v3)")
        print(f"# Algorithm: {self.config.ALGORITHM}")
        print(f"# Snapshot size: {self.config.SNAPSHOT_SIZE}")
        print(f"# Snapshots/update: {self.config.NUM_SNAPSHOTS}")
        return True

    # ------ per-iteration helpers ------

    def _hot_reload_calibration(self) -> None:
        """Re-read calibration.json and push to fabric if it changed."""
        try:
            with open(self._cal_file) as f:
                cal_data = json.load(f)
            new_cal = cal_data.get("phase_offset_deg", self._current_cal)
            if new_cal != self._current_cal:
                print(f"# Calibration updated: "
                      f"{self._current_cal:.2f}° → {new_cal:.2f}°")
                self._current_cal = new_cal
                self.pipe.write_calibration(new_cal)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _accumulate_snapshots(self) -> Optional[Tuple[float, float, float, float]]:
        """Run NUM_SNAPSHOTS pipeline invocations and ARM-side average.

        Returns (xcorr_re_avg, xcorr_im_avg, r00_avg, r11_avg), normalized
        per-sample so they plug into the covariance matrix exactly like v2.
        Returns None if the source or DMA failed partway through.
        """
        samples_per_update = self.config.SNAPSHOT_SIZE * self.config.NUM_SNAPSHOTS
        ch0_all, ch1_all = self.source.read_samples(samples_per_update)
        if len(ch0_all) < samples_per_update:
            return None  # short read — skip this update

        acc_re = 0
        acc_im = 0
        acc_r00 = 0.0
        acc_r11 = 0.0
        ss = self.config.SNAPSHOT_SIZE
        good = 0

        for k in range(self.config.NUM_SNAPSHOTS):
            s = k * ss
            e = s + ss
            snap = self.pipe.run_snapshot(ch0_all[s:e], ch1_all[s:e])
            if snap is None:
                continue  # DMA or pipeline timeout — drop this snapshot
            acc_re  += snap.xcorr_re
            acc_im  += snap.xcorr_im
            acc_r00 += float(snap.r00)
            acc_r11 += float(snap.r11)
            good += 1

            if self.config.DEBUG and good <= 2:
                print(f"# DEBUG snap={good-1}: "
                      f"re={snap.xcorr_re} im={snap.xcorr_im} "
                      f"r00={snap.r00} r11={snap.r11} count={snap.snap_count}")

        if good == 0:
            return None

        # Per-sample normalization (matches v2 convention so R matrix
        # entries share units regardless of snapshot count).
        xcorr_re_avg = (acc_re / good) / ss
        xcorr_im_avg = (acc_im / good) / ss
        r00_avg = (acc_r00 / good) / ss
        r11_avg = (acc_r11 / good) / ss
        return xcorr_re_avg, xcorr_im_avg, r00_avg, r11_avg

    def _compute_doa(self, xcorr_re: float, xcorr_im: float,
                     r00: float, r11: float) -> float:
        algorithm = self.config.ALGORITHM
        d = self.config.ANTENNA_SPACING_NORM

        if algorithm == "PHASEDIFF":
            return phase_difference_doa_fpga(xcorr_re, xcorr_im, d)

        r01 = complex(xcorr_re, xcorr_im)
        R = np.array([
            [r00,          r01],
            [np.conj(r01), r11],
        ], dtype=np.complex128)

        if algorithm == "ROOTMUSIC":
            return root_music_doa(R, d, self.config.NUM_SOURCES)
        if algorithm == "MUSIC":
            return music_doa(R, d, self.config.NUM_SOURCES,
                             self.config.MUSIC_SPECTRUM_POINTS)
        if algorithm == "MVDR":
            return mvdr_doa(R, d, self.config.MUSIC_SPECTRUM_POINTS)

        # Unknown algorithm — fall back to phase diff so we still emit something.
        return phase_difference_doa_fpga(xcorr_re, xcorr_im, d)

    # ------ top-level loop ------

    def iterate(self) -> Optional[float]:
        """Run one full update cycle: cal hot-reload → DMA snapshots → AoA."""
        self._hot_reload_calibration()
        result = self._accumulate_snapshots()
        if result is None:
            return None
        xr, xi, r00, r11 = result
        return self._compute_doa(xr, xi, r00, r11)

    def run(self) -> None:
        """Continuous estimation loop (or single-shot if CONTINUOUS=False)."""
        try:
            while True:
                t0 = time.time()
                aoa = self.iterate()
                if aoa is not None:
                    print(f"AOA:{aoa:.1f}")
                    sys.stdout.flush()
                # Pace the loop
                elapsed = time.time() - t0
                if elapsed < self.config.UPDATE_INTERVAL:
                    time.sleep(self.config.UPDATE_INTERVAL - elapsed)
                if not self.config.CONTINUOUS:
                    break
        except KeyboardInterrupt:
            print("# Interrupted")

    def cleanup(self) -> None:
        if self.source is not None:
            self.source.cleanup()


# =============================================================================
# Entry point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase A FPGA-accelerated DoA estimation (v3)"
    )
    parser.add_argument("--cal", type=float, default=0.0,
                        help="Initial phase calibration (degrees)")
    parser.add_argument("--algo", type=str, default="ROOTMUSIC",
                        choices=["PHASEDIFF", "MUSIC", "ROOTMUSIC", "MVDR"],
                        help="DoA algorithm")
    parser.add_argument("--freq", type=float, help="Center frequency (Hz)")
    parser.add_argument("--gain", type=int, help="RX gain (dB)")
    parser.add_argument("--snapshot-size", type=int, dest="snapshot_size",
                        help="Samples per snapshot (must match FPGA SNAPSHOT_LEN)")
    parser.add_argument("--single", action="store_true",
                        help="Single estimate then exit")
    parser.add_argument("--debug", action="store_true",
                        help="Print per-snapshot register values (first 2 snaps)")
    parser.add_argument("--filter", type=str, default="none",
                        choices=["none", "bandpass", "lowpass"],
                        help="Hardware FIR preset (default: none)")
    parser.add_argument("--tone-freq", type=float, dest="tone_freq",
                        help="Bandpass center (Hz, default 50000)")
    parser.add_argument("--lpf-cutoff", type=float, dest="lpf_cutoff",
                        help="Lowpass cutoff (Hz, default 50000)")

    args = parser.parse_args()
    config = PhaseAConfig.from_args(args)

    print("# Phase A FPGA DoA Estimation starting (v3)")
    print(f"# Frequency: {config.CENTER_FREQ/1e9:.3f} GHz")
    print(f"# Sample rate: {config.SAMPLE_RATE/1e6:.1f} MSPS")

    try:
        with PhaseAPipeline(config) as pipe:
            estimator = PhaseAEstimator(config, pipe)
            if not estimator.configure():
                print("ERROR:Estimator configure failed")
                return
            try:
                estimator.run()
            finally:
                estimator.cleanup()
    except OSError as e:
        print(f"ERROR:Failed to open /dev/mem (run as root?): {e}")
    except Exception as e:
        print(f"ERROR:Unhandled exception: {e}")
        raise


if __name__ == "__main__":
    main()
