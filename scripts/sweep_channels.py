#!/usr/bin/env python3
"""
sweep_channels.py - WiFi Channel Sweep DoA Characterization

Sweeps across 2.4 GHz WiFi channels (1-14), estimates DoA at each using
all four algorithms, and generates comparison plots + CSV data.

The signal source (e.g., nRF5340 DK) should be at a known angle and fixed
frequency. As the receiver tunes away from the TX frequency, DoA accuracy
degrades — this characterizes the system's frequency selectivity and
per-channel interference environment.

Output:
    results/<timestamp>_sweep.csv   — raw data
    results/<timestamp>_sweep.png   — comparison plot

Usage:
    # On Cora (real hardware):
    python sweep_channels.py --true-angle 90 --cal -12.5

    # On host (simulation mode):
    python sweep_channels.py --true-angle 45

    # Custom channel range and dwell:
    python sweep_channels.py --channels 1 6 11 --estimates 50 --true-angle 90

Author: DoA Thesis Project
Date: 2026
"""

import numpy as np
import argparse
import sys
import os
import time
import csv
import json
from datetime import datetime
from typing import Tuple, List, Dict, Optional

# Try to import SoapySDR
try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    HAS_SOAPY = True
except ImportError:
    HAS_SOAPY = False
    print("# WARNING: SoapySDR not available, running in simulation mode")

# Try to import matplotlib for plotting
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless backend
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("# WARNING: matplotlib not available, skipping plot generation")


# =============================================================================
# WiFi Channel Definitions
# =============================================================================

# IEEE 802.11 2.4 GHz channel center frequencies (Hz)
WIFI_CHANNELS = {
    1:  2.412e9,
    2:  2.417e9,
    3:  2.422e9,
    4:  2.427e9,
    5:  2.432e9,
    6:  2.437e9,
    7:  2.442e9,
    8:  2.447e9,
    9:  2.452e9,
    10: 2.457e9,
    11: 2.462e9,
    12: 2.467e9,
    13: 2.472e9,
    14: 2.484e9,  # Japan only, 12 MHz gap
}

# Physical antenna spacing (meters) — λ/2 at 2.45 GHz
ANTENNA_SPACING_M = 0.0612

SPEED_OF_LIGHT = 3e8


# =============================================================================
# DoA Algorithms (same as aoa_estimation_headless.py)
# =============================================================================

def steering_vector(theta_deg: float, d_lambda: float, n_elements: int) -> np.ndarray:
    """Compute array steering vector for angle theta."""
    theta_rad = np.deg2rad(theta_deg)
    n = np.arange(n_elements)
    phase = 2 * np.pi * d_lambda * (n - (n_elements - 1) / 2) * np.cos(theta_rad)
    return np.exp(1j * phase)


def estimate_covariance(ch0: np.ndarray, ch1: np.ndarray,
                        snapshot_size: int) -> np.ndarray:
    """Estimate 2x2 spatial covariance matrix."""
    num_snapshots = len(ch0) // snapshot_size
    X = np.vstack([ch0[:num_snapshots * snapshot_size],
                   ch1[:num_snapshots * snapshot_size]])
    X = X.reshape(2, snapshot_size, num_snapshots, order='F')
    R = np.zeros((2, 2), dtype=np.complex128)
    for k in range(num_snapshots):
        snapshot = X[:, :, k]
        R += snapshot @ snapshot.conj().T
    R /= (num_snapshots * snapshot_size)
    return R


def phase_difference_doa(ch0: np.ndarray, ch1: np.ndarray,
                         d_lambda: float) -> float:
    """Simple phase-difference DoA estimation."""
    cross = ch0 * np.conj(ch1)
    phase_diff = np.angle(np.mean(cross))
    cos_theta = phase_diff / (2 * np.pi * d_lambda)
    cos_theta = np.clip(cos_theta, -1, 1)
    return np.rad2deg(np.arccos(cos_theta))


def music_doa(R: np.ndarray, d_lambda: float, num_sources: int = 1,
              num_points: int = 181) -> float:
    """MUSIC algorithm for DoA estimation."""
    n_elements = R.shape[0]
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]
    noise_subspace = eigenvectors[:, :n_elements - num_sources]
    angles = np.linspace(0, 180, num_points)
    spectrum = np.zeros(num_points)
    for i, theta in enumerate(angles):
        a = steering_vector(theta, d_lambda, n_elements)
        proj = a.conj() @ noise_subspace
        spectrum[i] = 1.0 / (np.abs(proj @ proj.conj()) + 1e-10)
    return angles[np.argmax(spectrum)]


def root_music_doa(R: np.ndarray, d_lambda: float, num_sources: int = 1) -> float:
    """Root-MUSIC algorithm for DoA estimation."""
    n_elements = R.shape[0]
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]
    En = eigenvectors[:, :n_elements - num_sources]
    C = En @ En.conj().T
    coeffs = [C[0, 1], C[0, 0] + C[1, 1], C[1, 0]]
    roots = np.roots(coeffs)
    unit_circle_dist = np.abs(np.abs(roots) - 1)
    best_root = roots[np.argmin(unit_circle_dist)]
    phase = np.angle(best_root)
    cos_theta = phase / (2 * np.pi * d_lambda)
    cos_theta = np.clip(cos_theta, -1, 1)
    return np.rad2deg(np.arccos(cos_theta))


def mvdr_doa(R: np.ndarray, d_lambda: float, num_points: int = 181) -> float:
    """MVDR (Capon) beamformer for DoA estimation."""
    n_elements = R.shape[0]
    R_reg = R + 1e-6 * np.eye(n_elements)
    try:
        R_inv = np.linalg.inv(R_reg)
    except np.linalg.LinAlgError:
        R_inv = np.linalg.pinv(R_reg)
    angles = np.linspace(0, 180, num_points)
    spectrum = np.zeros(num_points)
    for i, theta in enumerate(angles):
        a = steering_vector(theta, d_lambda, n_elements)
        spectrum[i] = 1.0 / (np.abs(a.conj() @ R_inv @ a) + 1e-10)
    return angles[np.argmax(spectrum)]


def apply_calibration(ch1: np.ndarray, phase_cal_deg: float) -> np.ndarray:
    """Apply phase calibration to channel 1."""
    return ch1 * np.exp(-1j * np.deg2rad(phase_cal_deg))


def compute_d_lambda(freq_hz: float) -> float:
    """Compute normalized antenna spacing d/λ for given frequency."""
    wavelength = SPEED_OF_LIGHT / freq_hz
    return ANTENNA_SPACING_M / wavelength


# =============================================================================
# SDR Interface
# =============================================================================

class BladeRFSweeper:
    """BladeRF interface with frequency retuning support."""

    def __init__(self, sample_rate: float = 1e6, bandwidth: float = 1e6,
                 rx_gain: int = 40):
        self.sample_rate = sample_rate
        self.bandwidth = bandwidth
        self.rx_gain = rx_gain
        self.sdr = None
        self.rx_stream = None

    def setup(self) -> bool:
        """Initialize BladeRF device."""
        if not HAS_SOAPY:
            return False
        try:
            results = SoapySDR.Device.enumerate("driver=bladerf")
            if not results:
                print("ERROR: No BladeRF device found")
                return False
            self.sdr = SoapySDR.Device(results[0])
            for ch in [0, 1]:
                self.sdr.setSampleRate(SOAPY_SDR_RX, ch, self.sample_rate)
                self.sdr.setBandwidth(SOAPY_SDR_RX, ch, self.bandwidth)
                self.sdr.setGain(SOAPY_SDR_RX, ch, self.rx_gain)
            self.rx_stream = self.sdr.setupStream(
                SOAPY_SDR_RX, SOAPY_SDR_CF32, [0, 1])
            self.sdr.activateStream(self.rx_stream)
            return True
        except Exception as e:
            print(f"ERROR: Failed to setup BladeRF: {e}")
            return False

    def set_frequency(self, freq_hz: float):
        """Retune both RX channels."""
        for ch in [0, 1]:
            self.sdr.setFrequency(SOAPY_SDR_RX, ch, freq_hz)

    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """Read samples from both RX channels."""
        buffers = [np.zeros(num_samples, dtype=np.complex64) for _ in range(2)]
        samples_read = 0
        while samples_read < num_samples:
            chunk_size = min(65536, num_samples - samples_read)
            chunk_buffers = [b[samples_read:samples_read + chunk_size]
                             for b in buffers]
            sr = self.sdr.readStream(self.rx_stream, chunk_buffers,
                                     chunk_size, timeoutUs=1000000)
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


class SimulatedSweeper:
    """Simulated sweeper for testing without hardware."""

    def __init__(self, true_angle: float = 90.0, tx_freq: float = 2.418e9,
                 sample_rate: float = 1e6, **kwargs):
        self.true_angle = true_angle
        self.tx_freq = tx_freq
        self.sample_rate = sample_rate
        self.current_freq = tx_freq

    def setup(self) -> bool:
        print(f"# SIMULATED: True angle = {self.true_angle}°, "
              f"TX freq = {self.tx_freq / 1e6:.0f} MHz")
        return True

    def set_frequency(self, freq_hz: float):
        self.current_freq = freq_hz

    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """Generate simulated samples with frequency-dependent SNR."""
        t = np.arange(num_samples) / self.sample_rate

        # SNR degrades as receiver tunes away from TX frequency
        freq_offset = abs(self.current_freq - self.tx_freq)
        # ~30 dB on-channel, drops off with distance
        snr_db = max(30 - freq_offset / 1e6 * 3, -5)

        d_lambda = compute_d_lambda(self.current_freq)
        a = steering_vector(self.true_angle, d_lambda, 2)

        # Signal: tone at offset
        signal = np.exp(1j * 2 * np.pi * 50e3 * t)

        # Received signals
        signal_power = 10 ** (snr_db / 20)
        ch0 = signal_power * a[0] * signal
        ch1 = signal_power * a[1] * signal

        # Add noise (unit power)
        noise_scale = np.sqrt(0.5)
        ch0 += noise_scale * (np.random.randn(num_samples) +
                               1j * np.random.randn(num_samples))
        ch1 += noise_scale * (np.random.randn(num_samples) +
                               1j * np.random.randn(num_samples))

        return ch0.astype(np.complex64), ch1.astype(np.complex64)

    def cleanup(self):
        pass


# =============================================================================
# Sweep Engine
# =============================================================================

ALGORITHMS = ["ROOTMUSIC", "MUSIC", "MVDR", "PHASEDIFF"]


def estimate_snr(ch0: np.ndarray) -> float:
    """Rough SNR estimate from power statistics (dB)."""
    power = np.abs(ch0) ** 2
    # Use ratio of peak to median as rough SNR proxy
    median_power = np.median(power)
    if median_power < 1e-20:
        return -np.inf
    return 10 * np.log10(np.mean(power) / median_power + 1e-10)


def run_sweep(sweeper, channels: List[int], num_estimates: int,
              phase_cal_deg: float, settle_time: float,
              snapshot_size: int, num_snapshots: int,
              true_angle: Optional[float] = None) -> List[Dict]:
    """
    Sweep across WiFi channels and collect DoA estimates.

    Returns list of result dicts, one per channel per algorithm per estimate.
    """
    results = []
    samples_per_est = snapshot_size * num_snapshots
    total_channels = len(channels)

    for ch_idx, wifi_ch in enumerate(channels):
        freq_hz = WIFI_CHANNELS[wifi_ch]
        d_lambda = compute_d_lambda(freq_hz)

        print(f"\n# === Channel {wifi_ch} ({freq_hz / 1e6:.0f} MHz) "
              f"[{ch_idx + 1}/{total_channels}] ===")
        print(f"#   d/lambda = {d_lambda:.4f}")

        # Retune
        sweeper.set_frequency(freq_hz)

        # Settle time for PLL lock
        if settle_time > 0:
            time.sleep(settle_time)
            # Flush stale samples
            sweeper.read_samples(int(sweeper.sample_rate * 0.1)
                                 if hasattr(sweeper, 'sample_rate')
                                 else 100000)

        # Collect estimates
        for est_idx in range(num_estimates):
            ch0, ch1 = sweeper.read_samples(samples_per_est)
            ch1_cal = apply_calibration(ch1, phase_cal_deg)

            # Compute covariance once (shared by ROOTMUSIC, MUSIC, MVDR)
            R = estimate_covariance(ch0, ch1_cal, snapshot_size)
            snr_est = estimate_snr(ch0)

            for algo_name in ALGORITHMS:
                if algo_name == "PHASEDIFF":
                    aoa = phase_difference_doa(ch0, ch1_cal, d_lambda)
                elif algo_name == "MUSIC":
                    aoa = music_doa(R, d_lambda)
                elif algo_name == "ROOTMUSIC":
                    aoa = root_music_doa(R, d_lambda)
                elif algo_name == "MVDR":
                    aoa = mvdr_doa(R, d_lambda)

                error = abs(aoa - true_angle) if true_angle is not None else None

                results.append({
                    "wifi_channel": wifi_ch,
                    "freq_mhz": freq_hz / 1e6,
                    "d_lambda": round(d_lambda, 4),
                    "algorithm": algo_name,
                    "estimate_idx": est_idx,
                    "aoa_deg": round(aoa, 2),
                    "error_deg": round(error, 2) if error is not None else "",
                    "snr_est_db": round(snr_est, 1),
                })

            if est_idx == 0 or (est_idx + 1) % 10 == 0:
                rm_aoa = [r["aoa_deg"] for r in results
                          if r["wifi_channel"] == wifi_ch
                          and r["algorithm"] == "ROOTMUSIC"]
                print(f"#   Estimate {est_idx + 1}/{num_estimates}: "
                      f"Root-MUSIC={rm_aoa[-1]:.1f}°  SNR≈{snr_est:.0f} dB")

    return results


# =============================================================================
# Output: CSV
# =============================================================================

def save_csv(results: List[Dict], filepath: str):
    """Save sweep results to CSV."""
    if not results:
        return
    fieldnames = list(results[0].keys())
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"# Saved CSV: {filepath}")


# =============================================================================
# Output: Plot
# =============================================================================

def generate_plot(results: List[Dict], true_angle: Optional[float],
                  filepath: str):
    """Generate comparison plot: DoA accuracy vs WiFi channel."""
    if not HAS_MATPLOTLIB:
        print("# Skipping plot (matplotlib not available)")
        return

    # Aggregate: mean and std per channel per algorithm
    channels = sorted(set(r["wifi_channel"] for r in results))
    freq_labels = [f"Ch{ch}\n{WIFI_CHANNELS[ch] / 1e6:.0f}" for ch in channels]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                             gridspec_kw={'height_ratios': [2, 1]})

    colors = {
        "ROOTMUSIC": "#2196F3",
        "MUSIC": "#4CAF50",
        "MVDR": "#FF9800",
        "PHASEDIFF": "#F44336",
    }
    markers = {
        "ROOTMUSIC": "o",
        "MUSIC": "s",
        "MVDR": "^",
        "PHASEDIFF": "D",
    }

    x = np.arange(len(channels))
    width = 0.18  # bar width for std plot
    offsets = {"ROOTMUSIC": -1.5, "MUSIC": -0.5, "MVDR": 0.5, "PHASEDIFF": 1.5}

    # --- Top: Mean AoA estimate per channel ---
    ax1 = axes[0]

    for algo in ALGORITHMS:
        means = []
        stds = []
        for ch in channels:
            aoas = [r["aoa_deg"] for r in results
                    if r["wifi_channel"] == ch and r["algorithm"] == algo]
            means.append(np.mean(aoas))
            stds.append(np.std(aoas))

        ax1.errorbar(x, means, yerr=stds, label=algo,
                     color=colors[algo], marker=markers[algo],
                     markersize=6, capsize=3, linewidth=1.5,
                     linestyle='-', alpha=0.85)

    if true_angle is not None:
        ax1.axhline(y=true_angle, color='gray', linestyle='--',
                     linewidth=1.5, label=f'True angle ({true_angle}°)')

    ax1.set_ylabel('Estimated AoA (°)', fontsize=12)
    ax1.set_title('DoA Estimation vs WiFi Channel (2.4 GHz Band)', fontsize=14)
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 180)

    # --- Bottom: Std dev (precision) per channel ---
    ax2 = axes[1]

    for algo in ALGORITHMS:
        stds = []
        for ch in channels:
            aoas = [r["aoa_deg"] for r in results
                    if r["wifi_channel"] == ch and r["algorithm"] == algo]
            stds.append(np.std(aoas))

        offset = offsets[algo] * width
        ax2.bar(x + offset, stds, width, label=algo,
                color=colors[algo], alpha=0.8)

    ax2.set_xlabel('WiFi Channel / Frequency (MHz)', fontsize=12)
    ax2.set_ylabel('Std Dev (°)', fontsize=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(freq_labels, fontsize=9)
    ax2.legend(loc='best', fontsize=9)
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"# Saved plot: {filepath}")


def generate_error_plot(results: List[Dict], true_angle: float,
                        filepath: str):
    """Generate error-focused plot when true angle is known."""
    if not HAS_MATPLOTLIB or true_angle is None:
        return

    channels = sorted(set(r["wifi_channel"] for r in results))

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                             gridspec_kw={'height_ratios': [1, 1]})

    colors = {
        "ROOTMUSIC": "#2196F3",
        "MUSIC": "#4CAF50",
        "MVDR": "#FF9800",
        "PHASEDIFF": "#F44336",
    }
    markers = {"ROOTMUSIC": "o", "MUSIC": "s", "MVDR": "^", "PHASEDIFF": "D"}

    x = np.arange(len(channels))
    freq_labels = [f"Ch{ch}\n{WIFI_CHANNELS[ch] / 1e6:.0f}" for ch in channels]

    # --- Top: Mean absolute error ---
    ax1 = axes[0]
    for algo in ALGORITHMS:
        mae = []
        for ch in channels:
            errors = [abs(r["aoa_deg"] - true_angle) for r in results
                      if r["wifi_channel"] == ch and r["algorithm"] == algo]
            mae.append(np.mean(errors))

        ax1.plot(x, mae, label=algo, color=colors[algo],
                 marker=markers[algo], markersize=6, linewidth=1.5)

    ax1.set_ylabel('Mean Absolute Error (°)', fontsize=12)
    ax1.set_title(f'DoA Error vs WiFi Channel (true angle = {true_angle}°)',
                  fontsize=14)
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3)

    # --- Bottom: RMSE ---
    ax2 = axes[1]
    for algo in ALGORITHMS:
        rmse = []
        for ch in channels:
            errors = [(r["aoa_deg"] - true_angle) ** 2 for r in results
                      if r["wifi_channel"] == ch and r["algorithm"] == algo]
            rmse.append(np.sqrt(np.mean(errors)))

        ax2.plot(x, rmse, label=algo, color=colors[algo],
                 marker=markers[algo], markersize=6, linewidth=1.5)

    ax2.set_xlabel('WiFi Channel / Frequency (MHz)', fontsize=12)
    ax2.set_ylabel('RMSE (°)', fontsize=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(freq_labels, fontsize=9)
    ax2.legend(loc='best', fontsize=10)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"# Saved error plot: {filepath}")


# =============================================================================
# Summary
# =============================================================================

def print_summary(results: List[Dict], true_angle: Optional[float]):
    """Print summary statistics table."""
    channels = sorted(set(r["wifi_channel"] for r in results))

    print("\n# ============================================================")
    print("# SWEEP SUMMARY")
    print("# ============================================================")

    header = f"{'Channel':>8} {'Freq':>8}"
    for algo in ALGORITHMS:
        header += f"  {algo:>12}"
    print(f"# {header}")
    print(f"# {'-' * len(header)}")

    # Mean ± std per channel per algorithm
    for ch in channels:
        freq = WIFI_CHANNELS[ch] / 1e6
        row = f"{'Ch ' + str(ch):>8} {freq:>7.0f}M"
        for algo in ALGORITHMS:
            aoas = [r["aoa_deg"] for r in results
                    if r["wifi_channel"] == ch and r["algorithm"] == algo]
            mean = np.mean(aoas)
            std = np.std(aoas)
            row += f"  {mean:5.1f}±{std:4.1f}°"
        print(f"# {row}")

    if true_angle is not None:
        print(f"#\n# True angle: {true_angle}°")
        print(f"# {'':>8} {'RMSE':>8}", end="")
        for algo in ALGORITHMS:
            all_errors = [(r["aoa_deg"] - true_angle) ** 2 for r in results
                          if r["algorithm"] == algo]
            rmse = np.sqrt(np.mean(all_errors))
            print(f"  {rmse:>11.2f}°", end="")
        print()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="WiFi channel sweep DoA characterization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --true-angle 90 --cal -12.5           # Full sweep, all channels
  %(prog)s --channels 1 6 11 --estimates 50       # Quick 3-channel test
  %(prog)s --true-angle 45                        # Simulation mode (no SDR)
        """)

    parser.add_argument("--channels", type=int, nargs='+',
                        default=list(range(1, 15)),
                        help="WiFi channels to sweep (default: 1-14)")
    parser.add_argument("--estimates", type=int, default=20,
                        help="Number of estimates per channel (default: 20)")
    parser.add_argument("--cal", type=float, default=0.0,
                        help="Phase calibration offset in degrees")
    parser.add_argument("--true-angle", type=float, default=None,
                        dest="true_angle",
                        help="True source angle for error calculation")
    parser.add_argument("--gain", type=int, default=40,
                        help="RX gain in dB (default: 40)")
    parser.add_argument("--settle", type=float, default=0.5,
                        help="Settle time after retune in seconds (default: 0.5)")
    parser.add_argument("--snapshot-size", type=int, default=1024,
                        dest="snapshot_size",
                        help="Samples per covariance snapshot (default: 1024)")
    parser.add_argument("--num-snapshots", type=int, default=100,
                        dest="num_snapshots",
                        help="Snapshots to average (default: 100)")
    parser.add_argument("--tx-freq", type=float, default=2.418e9,
                        dest="tx_freq",
                        help="TX frequency for simulation mode (default: 2.418 GHz)")
    parser.add_argument("--output-dir", type=str, default=None,
                        dest="output_dir",
                        help="Output directory (default: results/)")

    args = parser.parse_args()

    # Validate channels
    for ch in args.channels:
        if ch not in WIFI_CHANNELS:
            print(f"ERROR: Invalid WiFi channel {ch}. Valid: 1-14")
            sys.exit(1)

    # Output directory
    if args.output_dir:
        out_dir = args.output_dir
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(os.path.dirname(script_dir), "results")
    os.makedirs(out_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Print configuration
    print("# ============================================================")
    print("# WiFi Channel Sweep — DoA Characterization")
    print("# ============================================================")
    print(f"# Channels: {args.channels}")
    print(f"# Estimates per channel: {args.estimates}")
    print(f"# Calibration: {args.cal}°")
    print(f"# RX gain: {args.gain} dB")
    print(f"# Snapshot: {args.snapshot_size} samples × {args.num_snapshots} averages")
    if args.true_angle is not None:
        print(f"# True angle: {args.true_angle}°")
    print(f"# Output: {out_dir}/{timestamp}_sweep.*")
    print()

    # Create sweeper
    if HAS_SOAPY:
        sweeper = BladeRFSweeper(
            sample_rate=1e6,
            bandwidth=1e6,
            rx_gain=args.gain,
        )
    else:
        sweeper = SimulatedSweeper(
            true_angle=args.true_angle or 90.0,
            tx_freq=args.tx_freq,
            sample_rate=1e6,
        )

    if not sweeper.setup():
        print("ERROR: Failed to initialize SDR")
        sys.exit(1)

    try:
        # Run sweep
        start = time.time()
        results = run_sweep(
            sweeper=sweeper,
            channels=args.channels,
            num_estimates=args.estimates,
            phase_cal_deg=args.cal,
            settle_time=args.settle,
            snapshot_size=args.snapshot_size,
            num_snapshots=args.num_snapshots,
            true_angle=args.true_angle,
        )
        elapsed = time.time() - start

        print(f"\n# Sweep completed in {elapsed:.1f}s "
              f"({len(results)} measurements)")

        # Save CSV
        csv_path = os.path.join(out_dir, f"{timestamp}_sweep.csv")
        save_csv(results, csv_path)

        # Save metadata
        meta = {
            "timestamp": timestamp,
            "channels": args.channels,
            "estimates_per_channel": args.estimates,
            "algorithms": ALGORITHMS,
            "phase_cal_deg": args.cal,
            "rx_gain_db": args.gain,
            "true_angle_deg": args.true_angle,
            "snapshot_size": args.snapshot_size,
            "num_snapshots": args.num_snapshots,
            "antenna_spacing_m": ANTENNA_SPACING_M,
            "elapsed_seconds": round(elapsed, 1),
            "hardware": "bladerf" if HAS_SOAPY else "simulated",
        }
        meta_path = os.path.join(out_dir, f"{timestamp}_sweep_meta.json")
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

        # Generate plots
        plot_path = os.path.join(out_dir, f"{timestamp}_sweep.png")
        generate_plot(results, args.true_angle, plot_path)

        if args.true_angle is not None:
            error_path = os.path.join(out_dir, f"{timestamp}_sweep_error.png")
            generate_error_plot(results, args.true_angle, error_path)

        # Print summary
        print_summary(results, args.true_angle)

    finally:
        sweeper.cleanup()


if __name__ == "__main__":
    main()
