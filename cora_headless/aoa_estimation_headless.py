#!/usr/bin/env python3
"""
aoa_estimation_headless.py - Headless DoA Estimation for BladeRF System

This script performs Direction of Arrival estimation using captured IQ data
from the BladeRF 2.0 two-element antenna array. It supports multiple algorithms:
- PHASEDIFF: Simple phase difference (fastest, least accurate)
- MUSIC: MUltiple SIgnal Classification spectral search
- ROOTMUSIC: Root-MUSIC polynomial method (default)
- MVDR: Minimum Variance Distortionless Response beamformer

Output Protocol:
    AOA:<value>     - Estimated angle in degrees (0-180, broadside=90)
    ERROR:<msg>     - Error message
    STATS:<json>    - Statistics in JSON format

Usage:
    python aoa_estimation_headless.py --cal=-12.5 --algo=ROOTMUSIC

Based on:
    - Wachowiak & Kryszkiewicz (2022) - Root-MUSIC for 2-element ULA
    - Schmidt (1986) - MUSIC algorithm
    - Capon (1969) - MVDR beamformer

Author: DoA Thesis Project
Date: 2026
"""

import numpy as np
import argparse
import sys
import time
from typing import Tuple
from enum import Enum

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

class EstimationConfig:
    """Estimation parameters."""
    
    # RF Settings
    CENTER_FREQ = 2.42e9      # Hz
    SAMPLE_RATE = 1e6         # Hz (USB 2.0 limited)
    BANDWIDTH = 1e6           # Hz
    RX_GAIN = 40              # dB
    
    # Array Geometry
    ANTENNA_SPACING_NORM = 0.5  # d/lambda (half wavelength)
    NUM_ELEMENTS = 2
    
    # Processing
    SNAPSHOT_SIZE = 1024      # Samples per covariance estimate
    NUM_SNAPSHOTS = 100       # Snapshots to average
    NUM_SOURCES = 1           # Expected number of signal sources
    
    # Output
    UPDATE_INTERVAL = 0.1     # Seconds between AoA reports
    CONTINUOUS = True         # Run continuously until stopped
    
    # Calibration
    PHASE_CAL_DEG = 0.0       # Phase calibration coefficient
    
    # Algorithm
    ALGORITHM = "ROOTMUSIC"   # Default algorithm
    
    # MUSIC specific
    MUSIC_SPECTRUM_POINTS = 181  # 0-180 degrees
    
    @classmethod
    def from_args(cls, args):
        """Update config from command line arguments."""
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
        return cls


class Algorithm(Enum):
    PHASEDIFF = "PHASEDIFF"
    MUSIC = "MUSIC"
    ROOTMUSIC = "ROOTMUSIC"
    MVDR = "MVDR"


# =============================================================================
# DoA Algorithms
# =============================================================================

def steering_vector(theta_deg: float, d_lambda: float, n_elements: int) -> np.ndarray:
    """
    Compute array steering vector for angle theta.
    
    Args:
        theta_deg: Angle in degrees (0=endfire, 90=broadside, 180=endfire)
        d_lambda: Antenna spacing normalized by wavelength
        n_elements: Number of array elements
    
    Returns:
        Complex steering vector of shape (n_elements,)
    """
    theta_rad = np.deg2rad(theta_deg)
    n = np.arange(n_elements)
    # Phase progression across array
    # For ULA: phase = 2*pi*d/lambda * (n - (N-1)/2) * cos(theta)
    # Centered at array midpoint
    phase = 2 * np.pi * d_lambda * (n - (n_elements - 1) / 2) * np.cos(theta_rad)
    return np.exp(1j * phase)


def estimate_covariance(ch0: np.ndarray, ch1: np.ndarray, 
                        snapshot_size: int) -> np.ndarray:
    """
    Estimate spatial covariance matrix from two-channel data.
    
    Args:
        ch0: Complex samples from channel 0
        ch1: Complex samples from channel 1
        snapshot_size: Number of samples per snapshot
    
    Returns:
        2x2 complex covariance matrix
    """
    num_snapshots = len(ch0) // snapshot_size
    
    # Stack channels: shape (2, num_samples)
    X = np.vstack([ch0[:num_snapshots * snapshot_size],
                   ch1[:num_snapshots * snapshot_size]])
    
    # Reshape to (2, snapshot_size, num_snapshots)
    X = X.reshape(2, snapshot_size, num_snapshots, order='F')
    
    # Compute sample covariance: R = (1/K) * sum(x * x^H)
    R = np.zeros((2, 2), dtype=np.complex128)
    for k in range(num_snapshots):
        snapshot = X[:, :, k]  # (2, snapshot_size)
        R += snapshot @ snapshot.conj().T
    R /= (num_snapshots * snapshot_size)
    
    return R


def phase_difference_doa(ch0: np.ndarray, ch1: np.ndarray, 
                         d_lambda: float) -> float:
    """
    Simple phase-difference DoA estimation.
    
    Fastest but least robust to noise and multipath.
    
    Args:
        ch0, ch1: Complex samples from both channels
        d_lambda: Normalized antenna spacing
    
    Returns:
        Estimated angle in degrees (0-180)
    """
    # Compute phase difference via conjugate multiplication
    cross = ch0 * np.conj(ch1)
    phase_diff = np.angle(np.mean(cross))
    
    # Convert phase to angle
    # phase_diff = 2*pi*d/lambda * cos(theta)
    cos_theta = phase_diff / (2 * np.pi * d_lambda)
    cos_theta = np.clip(cos_theta, -1, 1)  # Handle numerical errors
    
    theta_rad = np.arccos(cos_theta)
    return np.rad2deg(theta_rad)


def music_doa(R: np.ndarray, d_lambda: float, num_sources: int = 1,
              num_points: int = 181) -> Tuple[float, np.ndarray]:
    """
    MUSIC algorithm for DoA estimation.
    
    Args:
        R: Spatial covariance matrix (2x2)
        d_lambda: Normalized antenna spacing
        num_sources: Number of signal sources
        num_points: Number of spectrum points
    
    Returns:
        (estimated_angle, spectrum) tuple
    """
    n_elements = R.shape[0]
    
    # Eigendecomposition
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    
    # Sort by eigenvalue (ascending)
    idx = np.argsort(eigenvalues)
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    
    # Noise subspace: eigenvectors corresponding to smallest eigenvalues
    noise_subspace = eigenvectors[:, :n_elements - num_sources]
    
    # Compute MUSIC spectrum
    angles = np.linspace(0, 180, num_points)
    spectrum = np.zeros(num_points)
    
    for i, theta in enumerate(angles):
        a = steering_vector(theta, d_lambda, n_elements)
        # MUSIC spectrum: 1 / (a^H * En * En^H * a)
        proj = a.conj() @ noise_subspace
        spectrum[i] = 1.0 / (np.abs(proj @ proj.conj()) + 1e-10)
    
    # Convert to dB
    spectrum_db = 10 * np.log10(spectrum / np.max(spectrum) + 1e-10)
    
    # Find peak
    peak_idx = np.argmax(spectrum)
    estimated_angle = angles[peak_idx]
    
    return estimated_angle, spectrum_db


def root_music_doa(R: np.ndarray, d_lambda: float, num_sources: int = 1) -> float:
    """
    Root-MUSIC algorithm for DoA estimation.
    
    More computationally efficient than spectral MUSIC for ULA.
    Finds angle by solving polynomial roots.
    
    Args:
        R: Spatial covariance matrix (2x2)
        d_lambda: Normalized antenna spacing
        num_sources: Number of signal sources
    
    Returns:
        Estimated angle in degrees
    """
    n_elements = R.shape[0]
    
    # Eigendecomposition
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    
    # Sort by eigenvalue (ascending)
    idx = np.argsort(eigenvalues)
    eigenvectors = eigenvectors[:, idx]
    
    # Noise subspace
    En = eigenvectors[:, :n_elements - num_sources]
    
    # Form the noise subspace projection matrix
    C = En @ En.conj().T
    
    # For 2-element ULA, we can solve directly
    # The MUSIC polynomial has coefficients from C
    # For 2x2: polynomial is C[0,0]*z^2 + (C[0,1]+C[1,0])*z + C[1,1]
    # But actually we need: a(z)^H * C * a(z) where a(z) = [1, z]^T
    # This gives: C[0,0] + C[0,1]*z + C[1,0]*z^(-1) + C[1,1]
    # Multiply by z: C[0,0]*z + C[0,1]*z^2 + C[1,0] + C[1,1]*z
    # Rearrange: C[0,1]*z^2 + (C[0,0]+C[1,1])*z + C[1,0]
    
    coeffs = [C[0, 1], C[0, 0] + C[1, 1], C[1, 0]]
    roots = np.roots(coeffs)
    
    # Find root closest to unit circle
    unit_circle_dist = np.abs(np.abs(roots) - 1)
    best_root = roots[np.argmin(unit_circle_dist)]
    
    # Convert root to angle
    # z = exp(j * 2*pi*d/lambda * cos(theta))
    phase = np.angle(best_root)
    cos_theta = phase / (2 * np.pi * d_lambda)
    cos_theta = np.clip(cos_theta, -1, 1)
    
    theta_rad = np.arccos(cos_theta)
    return np.rad2deg(theta_rad)


def mvdr_doa(R: np.ndarray, d_lambda: float, num_points: int = 181) -> Tuple[float, np.ndarray]:
    """
    MVDR (Capon) beamformer for DoA estimation.
    
    Args:
        R: Spatial covariance matrix
        d_lambda: Normalized antenna spacing
        num_points: Number of spectrum points
    
    Returns:
        (estimated_angle, spectrum) tuple
    """
    n_elements = R.shape[0]
    
    # Regularize covariance matrix
    R_reg = R + 1e-6 * np.eye(n_elements)
    
    try:
        R_inv = np.linalg.inv(R_reg)
    except np.linalg.LinAlgError:
        R_inv = np.linalg.pinv(R_reg)
    
    # Compute MVDR spectrum
    angles = np.linspace(0, 180, num_points)
    spectrum = np.zeros(num_points)
    
    for i, theta in enumerate(angles):
        a = steering_vector(theta, d_lambda, n_elements)
        # MVDR spectrum: 1 / (a^H * R^-1 * a)
        spectrum[i] = 1.0 / (np.abs(a.conj() @ R_inv @ a) + 1e-10)
    
    # Convert to dB
    spectrum_db = 10 * np.log10(spectrum / np.max(spectrum) + 1e-10)
    
    # Find peak
    peak_idx = np.argmax(spectrum)
    estimated_angle = angles[peak_idx]
    
    return estimated_angle, spectrum_db


# =============================================================================
# SDR Interface
# =============================================================================

class BladeRFEstimator:
    """Interface to BladeRF for DoA estimation."""
    
    def __init__(self, config: EstimationConfig):
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


class SimulatedEstimator:
    """Simulated estimator for testing."""
    
    def __init__(self, config: EstimationConfig):
        self.config = config
        self._true_angle = 45.0  # Simulated source at 45 degrees
        self._angle_drift = 0.0
    
    def setup(self) -> bool:
        print(f"# SIMULATED: True angle = {self._true_angle}°")
        return True
    
    def read_samples(self, num_samples: int) -> Tuple[np.ndarray, np.ndarray]:
        """Generate simulated samples from source at known angle."""
        t = np.arange(num_samples) / self.config.SAMPLE_RATE
        
        # Simulate slow angle drift
        self._angle_drift += np.random.randn() * 0.1
        self._angle_drift = np.clip(self._angle_drift, -5, 5)
        angle = self._true_angle + self._angle_drift
        
        # Steering vector for this angle
        a = steering_vector(angle, self.config.ANTENNA_SPACING_NORM, 2)
        
        # Signal: tone with some modulation
        signal = np.exp(1j * 2 * np.pi * 1000 * t)  # 1kHz tone
        
        # Received signals at each antenna
        ch0 = a[0] * signal
        ch1 = a[1] * signal
        
        # Add noise
        snr_db = 20
        noise_power = 10 ** (-snr_db / 10)
        ch0 += np.sqrt(noise_power/2) * (np.random.randn(num_samples) + 
                                          1j * np.random.randn(num_samples))
        ch1 += np.sqrt(noise_power/2) * (np.random.randn(num_samples) + 
                                          1j * np.random.randn(num_samples))
        
        return ch0.astype(np.complex64), ch1.astype(np.complex64)
    
    def cleanup(self):
        pass


# =============================================================================
# Main Estimation Loop
# =============================================================================

def apply_calibration(ch1: np.ndarray, phase_cal_deg: float) -> np.ndarray:
    """Apply phase calibration to channel 1."""
    phase_cal_rad = np.deg2rad(phase_cal_deg)
    return ch1 * np.exp(-1j * phase_cal_rad)


def run_estimation(config: EstimationConfig):
    """Execute the DoA estimation loop."""
    
    # Select hardware or simulation
    if HAS_SOAPY:
        estimator = BladeRFEstimator(config)
    else:
        estimator = SimulatedEstimator(config)
    
    if not estimator.setup():
        return
    
    # Parse algorithm
    try:
        algorithm = Algorithm[config.ALGORITHM]
    except KeyError:
        print(f"ERROR:Unknown algorithm '{config.ALGORITHM}'")
        estimator.cleanup()
        return
    
    print(f"# Algorithm: {algorithm.value}")
    print(f"# Calibration: {config.PHASE_CAL_DEG}°")
    
    samples_per_update = int(config.SNAPSHOT_SIZE * config.NUM_SNAPSHOTS)
    
    try:
        iteration = 0
        while True:
            start_time = time.time()
            
            # Read samples
            ch0, ch1 = estimator.read_samples(samples_per_update)
            
            # Apply calibration
            ch1_cal = apply_calibration(ch1, config.PHASE_CAL_DEG)
            
            # Estimate DoA based on selected algorithm
            if algorithm == Algorithm.PHASEDIFF:
                aoa = phase_difference_doa(ch0, ch1_cal, config.ANTENNA_SPACING_NORM)
                
            elif algorithm == Algorithm.MUSIC:
                R = estimate_covariance(ch0, ch1_cal, config.SNAPSHOT_SIZE)
                aoa, _ = music_doa(R, config.ANTENNA_SPACING_NORM, 
                                   config.NUM_SOURCES, config.MUSIC_SPECTRUM_POINTS)
                
            elif algorithm == Algorithm.ROOTMUSIC:
                R = estimate_covariance(ch0, ch1_cal, config.SNAPSHOT_SIZE)
                aoa = root_music_doa(R, config.ANTENNA_SPACING_NORM, config.NUM_SOURCES)
                
            elif algorithm == Algorithm.MVDR:
                R = estimate_covariance(ch0, ch1_cal, config.SNAPSHOT_SIZE)
                aoa, _ = mvdr_doa(R, config.ANTENNA_SPACING_NORM, 
                                  config.MUSIC_SPECTRUM_POINTS)
            
            # Output result
            print(f"AOA:{aoa:.1f}")
            sys.stdout.flush()
            
            # Timing
            elapsed = time.time() - start_time
            if elapsed < config.UPDATE_INTERVAL:
                time.sleep(config.UPDATE_INTERVAL - elapsed)
            
            iteration += 1
            
            # Single-shot mode
            if not config.CONTINUOUS:
                break
                
    except KeyboardInterrupt:
        print("# Interrupted")
    finally:
        estimator.cleanup()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Headless DoA estimation for BladeRF system"
    )
    parser.add_argument("--cal", type=float, default=0.0,
                        help="Phase calibration coefficient (degrees)")
    parser.add_argument("--algo", type=str, default="ROOTMUSIC",
                        choices=["PHASEDIFF", "MUSIC", "ROOTMUSIC", "MVDR"],
                        help="DoA algorithm")
    parser.add_argument("--freq", type=float, help="Center frequency (Hz)")
    parser.add_argument("--gain", type=int, help="RX gain (dB)")
    parser.add_argument("--snapshot-size", type=int, dest="snapshot_size",
                        help="Samples per covariance snapshot")
    parser.add_argument("--single", action="store_true",
                        help="Single estimate then exit")
    
    args = parser.parse_args()
    config = EstimationConfig.from_args(args)
    
    print("# DoA Estimation starting")
    print(f"# Frequency: {config.CENTER_FREQ/1e9:.3f} GHz")
    print(f"# Sample rate: {config.SAMPLE_RATE/1e6:.1f} MSPS")
    
    run_estimation(config)


if __name__ == "__main__":
    main()
