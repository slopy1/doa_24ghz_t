#!/usr/bin/env python3
"""
aoa_estimation_fpga_v2.py - FPGA-Accelerated DoA (r00/r11 SC16 fix)

Identical to aoa_estimation_fpga.py EXCEPT for how r00 and r11 are computed:

  v1 (fpga.py):    r00/r11 = CF32 float power x 32767^2   (mixed units)
  v2 (this file):  r00/r11 = SC16 int16 power directly    (same units as FPGA xcorr)

This ensures all 4 entries of the covariance matrix R are in SC16^2 units,
matching the FPGA's int16 x int16 cross-correlation output for r01.

Output Protocol (same as ARM-only version):
    AOA:<value>     - Estimated angle in degrees (0-180, broadside=90)
    ERROR:<msg>     - Error message

Usage:
    sudo python3 aoa_estimation_fpga_v2.py --cal=-12.5 --algo=ROOTMUSIC

Requires: root access for /dev/mem (DMA + register access)
"""

import numpy as np
import mmap
import os
import struct
import argparse
import sys
import time
import math
from typing import Tuple

# Try to import SoapySDR
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

class FPGAConfig:
    """FPGA + estimation parameters."""

    # RF Settings (same as ARM-only version)
    CENTER_FREQ = 2.42e9
    SAMPLE_RATE = 1e6
    BANDWIDTH = 1e6
    RX_GAIN = 40

    # Array Geometry
    ANTENNA_SPACING_NORM = 0.5  # d/lambda
    NUM_ELEMENTS = 2

    # Processing
    SNAPSHOT_SIZE = 1024      # Must match FPGA SNAPSHOT_LEN parameter
    NUM_SNAPSHOTS = 100       # Snapshots to average (ARM-side averaging)
    NUM_SOURCES = 1

    # Output
    UPDATE_INTERVAL = 0.1
    CONTINUOUS = True

    # Calibration
    PHASE_CAL_DEG = 0.0

    # Algorithm
    ALGORITHM = "ROOTMUSIC"

    # FPGA addresses
    XCORR_BASE = 0x40000000
    DMA_BASE   = 0x40400000

    # DMA buffer in high DDR
    DESC_PHYS    = 0x1F000000
    DMA_BUF_PHYS = 0x1F001000

    # MUSIC specific
    MUSIC_SPECTRUM_POINTS = 181

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
        if hasattr(args, 'debug') and args.debug:
            cls.DEBUG = True
        return cls


# =============================================================================
# FPGA / DMA Interface
# =============================================================================

PAGE_SIZE = 0x1000

# DMA MM2S registers (Scatter Gather mode)
MM2S_DMACR    = 0x00
MM2S_DMASR    = 0x04
MM2S_CURDESC  = 0x08
MM2S_TAILDESC = 0x10

# SG descriptor offsets
SG_NXTDESC     = 0x00
SG_NXTDESC_MSB = 0x04
SG_BUFFER      = 0x08
SG_BUFFER_MSB  = 0x0C
SG_CONTROL     = 0x18
SG_STATUS      = 0x1C
SG_SOF = (1 << 26)
SG_EOF = (1 << 27)


def reg_read(m, offset):
    return struct.unpack_from("<I", m, offset)[0]

def reg_read_signed(m, offset):
    return struct.unpack_from("<i", m, offset)[0]

def reg_write(m, offset, value):
    struct.pack_into("<I", m, offset, value & 0xFFFFFFFF)


class FPGAXcorr:
    """Interface to the xcorr_acc FPGA IP via AXI DMA."""

    def __init__(self, config: FPGAConfig):
        self.config = config
        self.fd = None
        self.xcorr_m = None
        self.dma_m = None
        self.desc_m = None
        self.buf_m = None

    def setup(self) -> bool:
        try:
            self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
            self.xcorr_m = mmap.mmap(self.fd, PAGE_SIZE, offset=self.config.XCORR_BASE)
            self.dma_m = mmap.mmap(self.fd, PAGE_SIZE, offset=self.config.DMA_BASE)
            self.desc_m = mmap.mmap(self.fd, PAGE_SIZE, offset=self.config.DESC_PHYS)

            buf_size = self.config.SNAPSHOT_SIZE * 2 * 4  # two beats * 4 bytes
            buf_pages = ((buf_size + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
            self.buf_m = mmap.mmap(self.fd, buf_pages, offset=self.config.DMA_BUF_PHYS)

            # Quick sanity check — read a register
            _ = reg_read(self.xcorr_m, 0x00)
            return True
        except Exception as e:
            print(f"ERROR:FPGA setup failed: {e}")
            return False

    def _setup_sg_descriptor(self, nbytes):
        reg_write(self.desc_m, SG_NXTDESC, self.config.DESC_PHYS)
        reg_write(self.desc_m, SG_NXTDESC_MSB, 0)
        reg_write(self.desc_m, SG_BUFFER, self.config.DMA_BUF_PHYS)
        reg_write(self.desc_m, SG_BUFFER_MSB, 0)
        reg_write(self.desc_m, 0x10, 0)
        reg_write(self.desc_m, 0x14, 0)
        reg_write(self.desc_m, SG_CONTROL, SG_SOF | SG_EOF | (nbytes & 0x7FFFFF))
        reg_write(self.desc_m, SG_STATUS, 0)

    def compute_xcorr(self, ch0: np.ndarray, ch1: np.ndarray) -> Tuple[int, int]:
        """
        Send one snapshot through DMA and return FPGA cross-correlation.

        Args:
            ch0, ch1: complex64 arrays of length SNAPSHOT_SIZE

        Returns:
            (xcorr_re, xcorr_im) as signed 32-bit integers
        """
        n = self.config.SNAPSHOT_SIZE

        # Convert CF32 to SC16 (scale float [-1,1] to int16 range)
        # BladeRF CF32 samples are typically in [-1, 1] range
        scale = 32767.0
        ch0_i = np.clip(np.real(ch0[:n]) * scale, -32768, 32767).astype(np.int16)
        ch0_q = np.clip(np.imag(ch0[:n]) * scale, -32768, 32767).astype(np.int16)
        ch1_i = np.clip(np.real(ch1[:n]) * scale, -32768, 32767).astype(np.int16)
        ch1_q = np.clip(np.imag(ch1[:n]) * scale, -32768, 32767).astype(np.int16)

        # Interleave into DMA buffer: [ch0_iq, ch1_iq, ch0_iq, ch1_iq, ...]
        # Each beat is {Q[31:16], I[15:0]} as uint32
        buf = np.empty(n * 2, dtype=np.uint32)
        buf[0::2] = (ch0_q.astype(np.uint16).astype(np.uint32) << 16) | ch0_i.astype(np.uint16).astype(np.uint32)
        buf[1::2] = (ch1_q.astype(np.uint16).astype(np.uint32) << 16) | ch1_i.astype(np.uint16).astype(np.uint32)

        data_bytes = buf.tobytes()
        nbytes = len(data_bytes)

        # Clear previous result
        reg_read(self.xcorr_m, 0x08)  # clear sticky valid

        # Reset DMA
        reg_write(self.dma_m, MM2S_DMACR, 0x0004)
        for _ in range(100):
            if not (reg_read(self.dma_m, MM2S_DMACR) & 0x0004):
                break
            time.sleep(0.0001)

        # Write data to buffer
        self.buf_m.seek(0)
        self.buf_m.write(data_bytes)

        # Setup descriptor
        self._setup_sg_descriptor(nbytes)

        # Set current descriptor (while halted)
        reg_write(self.dma_m, MM2S_CURDESC, self.config.DESC_PHYS)

        # Start DMA
        reg_write(self.dma_m, MM2S_DMACR, 0x0001)
        time.sleep(0.0001)

        # Kick off by writing tail descriptor
        reg_write(self.dma_m, MM2S_TAILDESC, self.config.DESC_PHYS)

        # Wait for completion
        for _ in range(2000):
            desc_status = reg_read(self.desc_m, SG_STATUS)
            if desc_status & 0x80000000:
                break
            time.sleep(0.0001)
        else:
            return 0, 0  # DMA timeout

        # Read results
        xcorr_re = reg_read_signed(self.xcorr_m, 0x00)
        xcorr_im = reg_read_signed(self.xcorr_m, 0x04)
        return xcorr_re, xcorr_im

    def cleanup(self):
        for m in [self.xcorr_m, self.dma_m, self.desc_m, self.buf_m]:
            if m:
                m.close()
        if self.fd is not None:
            os.close(self.fd)


# =============================================================================
# DoA Algorithms (same as ARM-only version)
# =============================================================================

def steering_vector(theta_deg, d_lambda, n_elements):
    theta_rad = np.deg2rad(theta_deg)
    n = np.arange(n_elements)
    phase = 2 * np.pi * d_lambda * (n - (n_elements - 1) / 2) * np.cos(theta_rad)
    return np.exp(1j * phase)


def phase_difference_doa_fpga(xcorr_re, xcorr_im, d_lambda):
    """Phase-difference DoA directly from FPGA cross-correlation."""
    phase_diff = math.atan2(xcorr_im, xcorr_re)
    cos_theta = phase_diff / (2 * math.pi * d_lambda)
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return math.degrees(math.acos(cos_theta))


def root_music_doa(R, d_lambda, num_sources=1):
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]
    En = eigenvectors[:, :R.shape[0] - num_sources]
    C = En @ En.conj().T
    coeffs = [C[0, 1], C[0, 0] + C[1, 1], C[1, 0]]
    roots = np.roots(coeffs)
    unit_circle_dist = np.abs(np.abs(roots) - 1)
    best_root = roots[np.argmin(unit_circle_dist)]
    phase = np.angle(best_root)
    cos_theta = phase / (2 * np.pi * d_lambda)
    cos_theta = np.clip(cos_theta, -1, 1)
    return float(np.rad2deg(np.arccos(cos_theta)))


def music_doa(R, d_lambda, num_sources=1, num_points=181):
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


def mvdr_doa(R, d_lambda, num_points=181):
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
# SDR Interface
# =============================================================================

class BladeRFSource:
    def __init__(self, config):
        self.config = config
        self.sdr = None
        self.rx_stream = None

    def setup(self):
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

    def read_samples(self, num_samples):
        buffers = [np.zeros(num_samples, dtype=np.complex64) for _ in range(2)]
        samples_read = 0
        while samples_read < num_samples:
            chunk_size = min(65536, num_samples - samples_read)
            chunk_buffers = [b[samples_read:samples_read+chunk_size] for b in buffers]
            sr = self.sdr.readStream(self.rx_stream, chunk_buffers, chunk_size, timeoutUs=1000000)
            if sr.ret > 0:
                samples_read += sr.ret
            elif sr.ret < 0:
                break
        return buffers[0], buffers[1]

    def cleanup(self):
        if self.rx_stream:
            self.sdr.deactivateStream(self.rx_stream)
            self.sdr.closeStream(self.rx_stream)
        self.sdr = None


class SimulatedSource:
    def __init__(self, config):
        self.config = config
        self._true_angle = 45.0
        self._drift = 0.0

    def setup(self):
        print(f"# SIMULATED: True angle = {self._true_angle}")
        return True

    def read_samples(self, num_samples):
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
        ch0 += np.sqrt(noise_power/2) * (np.random.randn(num_samples) + 1j * np.random.randn(num_samples))
        ch1 += np.sqrt(noise_power/2) * (np.random.randn(num_samples) + 1j * np.random.randn(num_samples))
        return ch0.astype(np.complex64), ch1.astype(np.complex64)

    def cleanup(self):
        pass


# =============================================================================
# Main Estimation Loop
# =============================================================================

def apply_calibration(ch1, phase_cal_deg):
    return ch1 * np.exp(-1j * np.deg2rad(phase_cal_deg))


def run_estimation(config: FPGAConfig):
    # Setup SDR
    if HAS_SOAPY:
        source = BladeRFSource(config)
    else:
        source = SimulatedSource(config)

    if not source.setup():
        return

    # Setup FPGA
    fpga = FPGAXcorr(config)
    if not fpga.setup():
        print("ERROR:FPGA not available, cannot run FPGA-accelerated estimation")
        source.cleanup()
        return

    algorithm = config.ALGORITHM
    print(f"# FPGA-accelerated DoA estimation (v2 — SC16 r00/r11)")
    print(f"# Algorithm: {algorithm}")
    print(f"# Calibration: {config.PHASE_CAL_DEG}")
    print(f"# Snapshot size: {config.SNAPSHOT_SIZE}")

    samples_per_update = config.SNAPSHOT_SIZE * config.NUM_SNAPSHOTS

    try:
        iteration = 0
        while True:
            start_time = time.time()

            # Read all samples for this update (same amount as ARM version)
            ch0_all, ch1_all = source.read_samples(samples_per_update)

            # Apply calibration
            ch1_all_cal = apply_calibration(ch1_all, config.PHASE_CAL_DEG)

            # === FPGA PATH: average cross-correlation over multiple snapshots ===
            acc_re = 0
            acc_im = 0
            acc_r00 = 0.0
            acc_r11 = 0.0
            n_snap = config.NUM_SNAPSHOTS
            ss = config.SNAPSHOT_SIZE

            scale = 32767.0

            for k in range(n_snap):
                s = k * ss
                e = s + ss
                ch0_snap = ch0_all[s:e]
                ch1_snap = ch1_all_cal[s:e]

                # Cross-correlation on FPGA
                xr, xi = fpga.compute_xcorr(ch0_snap, ch1_snap)
                acc_re += xr
                acc_im += xi

                # --- v2 FIX: r00/r11 from SC16 (not CF32) so units match FPGA r01 ---
                ch0_i = np.clip(np.real(ch0_snap) * scale, -32768, 32767).astype(np.int16)
                ch0_q = np.clip(np.imag(ch0_snap) * scale, -32768, 32767).astype(np.int16)
                ch1_i = np.clip(np.real(ch1_snap) * scale, -32768, 32767).astype(np.int16)
                ch1_q = np.clip(np.imag(ch1_snap) * scale, -32768, 32767).astype(np.int16)
                acc_r00 += float(np.sum(ch0_i.astype(np.int64)**2 + ch0_q.astype(np.int64)**2))
                acc_r11 += float(np.sum(ch1_i.astype(np.int64)**2 + ch1_q.astype(np.int64)**2))
                # --- end v2 FIX ---

            # Average
            xcorr_re = acc_re / n_snap
            xcorr_im = acc_im / n_snap

            # Compute DoA
            if algorithm == "PHASEDIFF":
                aoa = phase_difference_doa_fpga(xcorr_re, xcorr_im,
                                                 config.ANTENNA_SPACING_NORM)
            else:
                # --- v2 FIX: no scale^2 multiply needed, r00/r11 already in SC16^2 ---
                r00 = acc_r00 / (n_snap * ss)
                r11 = acc_r11 / (n_snap * ss)
                r01 = complex(xcorr_re, xcorr_im) / ss
                # --- end v2 FIX ---

                R = np.array([
                    [r00,          r01],
                    [np.conj(r01), r11]
                ], dtype=np.complex128)

                if algorithm == "ROOTMUSIC":
                    aoa = root_music_doa(R, config.ANTENNA_SPACING_NORM,
                                          config.NUM_SOURCES)
                elif algorithm == "MUSIC":
                    aoa = music_doa(R, config.ANTENNA_SPACING_NORM,
                                     config.NUM_SOURCES,
                                     config.MUSIC_SPECTRUM_POINTS)
                elif algorithm == "MVDR":
                    aoa = mvdr_doa(R, config.ANTENNA_SPACING_NORM,
                                    config.MUSIC_SPECTRUM_POINTS)
                else:
                    aoa = phase_difference_doa_fpga(xcorr_re, xcorr_im,
                                                     config.ANTENNA_SPACING_NORM)

            print(f"AOA:{aoa:.1f}")
            sys.stdout.flush()

            elapsed = time.time() - start_time
            if elapsed < config.UPDATE_INTERVAL:
                time.sleep(config.UPDATE_INTERVAL - elapsed)

            iteration += 1
            if not config.CONTINUOUS:
                break

    except KeyboardInterrupt:
        print("# Interrupted")
    finally:
        fpga.cleanup()
        source.cleanup()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="FPGA-accelerated DoA estimation for BladeRF system (v2 — SC16 scaling fix)"
    )
    parser.add_argument("--cal", type=float, default=0.0,
                        help="Phase calibration coefficient (degrees)")
    parser.add_argument("--algo", type=str, default="ROOTMUSIC",
                        choices=["PHASEDIFF", "MUSIC", "ROOTMUSIC", "MVDR"],
                        help="DoA algorithm")
    parser.add_argument("--freq", type=float, help="Center frequency (Hz)")
    parser.add_argument("--gain", type=int, help="RX gain (dB)")
    parser.add_argument("--snapshot-size", type=int, dest="snapshot_size",
                        help="Samples per snapshot (must match FPGA)")
    parser.add_argument("--single", action="store_true",
                        help="Single estimate then exit")
    parser.add_argument("--debug", action="store_true",
                        help="Print FPGA vs ARM comparison for first 5 iterations")

    args = parser.parse_args()
    config = FPGAConfig.from_args(args)

    print("# FPGA DoA Estimation starting (v2)")
    print(f"# Frequency: {config.CENTER_FREQ/1e9:.3f} GHz")
    print(f"# Sample rate: {config.SAMPLE_RATE/1e6:.1f} MSPS")

    run_estimation(config)


if __name__ == "__main__":
    main()
