#!/usr/bin/env python3
"""
phase_calibration_headless.py - Headless Phase Calibration for BladeRF System

This script measures the phase offset between the two RX channels of the
BladeRF 2.0 using a wired calibration setup (signal source → splitter →
matched cables → both RX inputs).

The phase offset is computed by conjugate-multiplying the two channel signals,
averaging, and extracting the argument (phase angle). This replicates the
GNU Radio flowgraph logic in pure Python/SoapySDR.

Output Protocol (parsed by main.py):
    PHASE:<value>   - Phase offset in degrees
    ERROR:<msg>     - Error message
    PROGRESS:<pct>  - Progress percentage (0-100)

Usage:
    python phase_calibration_headless.py [--duration=10] [--freq=2.42e9] [--gain=40]

Based on:
    - Wachowiak & Kryszkiewicz (2022)
    - GNU Radio phase_calibration_bladerf_headless.py flowgraph

Author: DoA Thesis Project
Date: 2026
"""

import numpy as np
import argparse
import sys
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

class CalibrationConfig:
    """Calibration parameters."""

    # RF Settings
    CENTER_FREQ = 2.42e9      # Hz
    SAMPLE_RATE = 1e6         # Hz (USB 2.0 limited)
    BANDWIDTH = 1e6           # Hz
    RX_GAIN = 40              # dB

    # Calibration
    DURATION = 10             # seconds of data to collect
    AVG_LENGTH = 100000       # samples for moving average (matches GR flowgraph)

    # Tone filter (bandpass around expected calibration tone)
    TONE_FREQ = 50e3          # Hz offset from center
    TONE_BW = 10e3            # Hz bandwidth around tone

    @classmethod
    def from_args(cls, args):
        """Update config from command line arguments."""
        if args.duration is not None:
            cls.DURATION = float(args.duration)
        if args.freq is not None:
            cls.CENTER_FREQ = float(args.freq)
        if args.gain is not None:
            cls.RX_GAIN = int(args.gain)
        if args.tone is not None:
            cls.TONE_FREQ = float(args.tone)
        return cls


# =============================================================================
# SDR Interface
# =============================================================================

class BladeRFCalibrator:
    """Interface to BladeRF for phase calibration."""

    def __init__(self, config: CalibrationConfig):
        self.config = config
        self.sdr = None
        self.rx_stream = None

    def setup(self) -> bool:
        """Initialize BladeRF device."""
        if not HAS_SOAPY:
            print("ERROR:SoapySDR not available")
            return False

        try:
            results = SoapySDR.Device.enumerate("driver=bladerf")
            if not results:
                print("ERROR:No BladeRF device found")
                return False

            self.sdr = SoapySDR.Device(results[0])

            # Configure both RX channels
            for ch in [0, 1]:
                self.sdr.setSampleRate(SOAPY_SDR_RX, ch, self.config.SAMPLE_RATE)
                self.sdr.setFrequency(SOAPY_SDR_RX, ch, self.config.CENTER_FREQ)
                self.sdr.setBandwidth(SOAPY_SDR_RX, ch, self.config.BANDWIDTH)
                self.sdr.setGain(SOAPY_SDR_RX, ch, self.config.RX_GAIN)

            self.rx_stream = self.sdr.setupStream(
                SOAPY_SDR_RX,
                SOAPY_SDR_CF32,
                [0, 1]
            )

            self.sdr.activateStream(self.rx_stream)
            return True

        except Exception as e:
            print(f"ERROR:Failed to setup BladeRF: {e}")
            return False

    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """Read samples from both RX channels."""
        buffers = [np.zeros(num_samples, dtype=np.complex64) for _ in range(2)]

        samples_read = 0
        while samples_read < num_samples:
            chunk_size = min(65536, num_samples - samples_read)
            chunk_buffers = [b[samples_read:samples_read+chunk_size] for b in buffers]

            sr = self.sdr.readStream(
                self.rx_stream,
                chunk_buffers,
                chunk_size,
                timeoutUs=1000000
            )

            if sr.ret > 0:
                samples_read += sr.ret
            elif sr.ret < 0:
                break

        return buffers[0], buffers[1]

    def cleanup(self):
        """Release SDR resources."""
        if self.rx_stream:
            self.sdr.deactivateStream(self.rx_stream)
            self.sdr.closeStream(self.rx_stream)
        self.sdr = None


class SimulatedCalibrator:
    """Simulated calibrator for testing without hardware."""

    def __init__(self, config: CalibrationConfig):
        self.config = config
        self._true_offset = -12.5  # Simulated phase offset in degrees

    def setup(self) -> bool:
        print(f"# SIMULATED: True phase offset = {self._true_offset} deg")
        return True

    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """Generate simulated samples with known phase offset."""
        t = np.arange(num_samples) / self.config.SAMPLE_RATE

        # Simulated tone at TONE_FREQ offset
        tone = np.exp(1j * 2 * np.pi * self.config.TONE_FREQ * t)

        # Channel 0: reference
        ch0 = tone.copy()

        # Channel 1: same signal with phase offset + small noise
        offset_rad = np.deg2rad(self._true_offset)
        ch1 = tone * np.exp(1j * offset_rad)

        # Add noise (SNR ~30 dB)
        noise_power = 10 ** (-30 / 10)
        for ch in [ch0, ch1]:
            ch += np.sqrt(noise_power / 2) * (
                np.random.randn(num_samples) + 1j * np.random.randn(num_samples)
            )

        return ch0.astype(np.complex64), ch1.astype(np.complex64)

    def cleanup(self):
        pass


# =============================================================================
# Calibration Processing
# =============================================================================

def bandpass_filter(signal: np.ndarray, sample_rate: float,
                    center_freq: float, bandwidth: float) -> np.ndarray:
    """
    Simple frequency-domain bandpass filter around a tone.

    Args:
        signal: Complex input samples
        sample_rate: Sample rate in Hz
        center_freq: Center frequency of passband in Hz
        bandwidth: Bandwidth of passband in Hz

    Returns:
        Filtered complex samples
    """
    N = len(signal)
    freqs = np.fft.fftfreq(N, 1.0 / sample_rate)
    spectrum = np.fft.fft(signal)

    # Create bandpass mask
    mask = np.abs(np.abs(freqs) - center_freq) <= (bandwidth / 2)
    spectrum *= mask

    return np.fft.ifft(spectrum)


def compute_phase_offset(ch0: np.ndarray, ch1: np.ndarray,
                         avg_length: int) -> float:
    """
    Compute phase offset between two channels.

    Replicates the GNU Radio flowgraph:
        ch0 × conj(ch1) → moving average → arg → rad2deg

    Args:
        ch0: Complex samples from channel 0
        ch1: Complex samples from channel 1
        avg_length: Number of samples for moving average

    Returns:
        Phase offset in degrees
    """
    # Conjugate multiply
    cross = ch0 * np.conj(ch1)

    # Moving average (use last avg_length samples for stable estimate)
    if len(cross) >= avg_length:
        cross_avg = np.mean(cross[-avg_length:])
    else:
        cross_avg = np.mean(cross)

    # Extract phase and convert to degrees
    phase_rad = np.angle(cross_avg)
    phase_deg = np.rad2deg(phase_rad)

    return phase_deg


def run_calibration(config: CalibrationConfig):
    """Execute the phase calibration procedure."""

    # Select hardware or simulation
    if HAS_SOAPY:
        calibrator = BladeRFCalibrator(config)
    else:
        calibrator = SimulatedCalibrator(config)

    if not calibrator.setup():
        return

    print("# Phase Calibration starting")
    print(f"# Frequency: {config.CENTER_FREQ/1e9:.3f} GHz")
    print(f"# Duration: {config.DURATION}s")
    print(f"# Gain: {config.RX_GAIN} dB")
    sys.stdout.flush()

    total_samples = int(config.SAMPLE_RATE * config.DURATION)
    chunk_size = int(config.SAMPLE_RATE)  # 1 second chunks
    phase_estimates = []

    try:
        samples_collected = 0
        chunk_idx = 0

        while samples_collected < total_samples:
            remaining = total_samples - samples_collected
            read_size = min(chunk_size, remaining)

            # Read samples
            ch0, ch1 = calibrator.read_samples(read_size)

            # Bandpass filter around calibration tone (if tone_freq > 0)
            if config.TONE_FREQ > 0:
                ch0_filt = bandpass_filter(ch0, config.SAMPLE_RATE,
                                           config.TONE_FREQ, config.TONE_BW)
                ch1_filt = bandpass_filter(ch1, config.SAMPLE_RATE,
                                           config.TONE_FREQ, config.TONE_BW)
            else:
                ch0_filt = ch0
                ch1_filt = ch1

            # Compute phase offset for this chunk
            phase_deg = compute_phase_offset(
                ch0_filt, ch1_filt, min(config.AVG_LENGTH, read_size)
            )
            phase_estimates.append(phase_deg)

            samples_collected += read_size
            chunk_idx += 1

            # Report progress
            progress = int(100 * samples_collected / total_samples)
            print(f"PROGRESS:{progress}")
            sys.stdout.flush()

        # Final averaged phase estimate
        if phase_estimates:
            final_phase = np.mean(phase_estimates)
            std_phase = np.std(phase_estimates) if len(phase_estimates) > 1 else 0.0

            print(f"# Collected {len(phase_estimates)} chunks")
            print(f"# Std dev: {std_phase:.2f} deg")
            print(f"PHASE:{final_phase:.2f}")
            sys.stdout.flush()
        else:
            print("ERROR:No phase estimates collected")

    except KeyboardInterrupt:
        print("# Interrupted")
        # Still output what we have
        if phase_estimates:
            final_phase = np.mean(phase_estimates)
            print(f"PHASE:{final_phase:.2f}")
            sys.stdout.flush()
    finally:
        calibrator.cleanup()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Headless phase calibration for BladeRF system"
    )
    parser.add_argument("--duration", type=float, default=10,
                        help="Calibration duration in seconds (default: 10)")
    parser.add_argument("--freq", type=float,
                        help="Center frequency in Hz (default: 2.42 GHz)")
    parser.add_argument("--gain", type=int,
                        help="RX gain in dB (default: 40)")
    parser.add_argument("--tone", type=float,
                        help="Tone frequency offset in Hz (default: 50 kHz, 0=DC)")

    args = parser.parse_args()
    config = CalibrationConfig.from_args(args)

    run_calibration(config)


if __name__ == "__main__":
    main()
