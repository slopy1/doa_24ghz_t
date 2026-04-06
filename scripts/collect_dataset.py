#!/usr/bin/env python3
"""
Dataset Collection Script for Thesis Experiments

Collects labeled DOA captures using BladeRF 2.0 MIMO receiver.

Usage:
    python scripts/collect_dataset.py --angle 30 --distance 2 --snr high
    python scripts/collect_dataset.py --angle -45 --distance 5 --snr low --reps 10

See docs/experiment_spec.md for the full experiment matrix.
"""

import argparse
import sys
import os
import time
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
from doa24.io_hdf5 import save_capture
from doa24.calibration import apply_calibration, compute_phase_offset, compute_coherence
from doa24.config import load_receiver_calibration


def collect_capture(angle_deg, distance_m, snr_label, notes="",
                    duration=1.0, fs=5e6, fc=2.45e9, gain=30, output_dir='data'):
    """
    Collect one labeled capture.
    
    Args:
        angle_deg: Nominal DOA angle in degrees
        distance_m: Distance to transmitter in meters
        snr_label: 'high' or 'low'
        notes: Additional notes
        duration: Recording duration in seconds
        fs: Sample rate in Hz
        fc: Center frequency in Hz
        gain: RX gain in dB
        output_dir: Output directory for HDF5 files
        
    Returns:
        Path to saved file
    """
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/capture_{timestamp}_angle{angle_deg:+03d}_dist{distance_m}m_{snr_label}.h5"
    
    print(f"\n{'='*60}")
    print(f"COLLECTING: angle={angle_deg}°, distance={distance_m}m, SNR={snr_label}")
    print(f"{'='*60}")
    
    try:
        # Import BladeRF
        from bladerf import _bladerf
        
        print("  Opening BladeRF...")
        device = _bladerf.BladeRF()
        
        # Configure channels
        ch0 = device.Channel(_bladerf.CHANNEL_RX(0))
        ch1 = device.Channel(_bladerf.CHANNEL_RX(1))
        
        for ch in [ch0, ch1]:
            ch.frequency = int(fc)
            ch.sample_rate = int(fs)
            ch.bandwidth = int(fs * 0.75)
            ch.gain = gain
            ch.gain_mode = _bladerf.GainMode.Manual
        
        print(f"  Configured: {fc/1e9:.3f} GHz, {fs/1e6:.1f} MS/s, {gain} dB gain")
        
        # Setup MIMO sync
        device.sync_config(
            layout=_bladerf.ChannelLayout.RX_X2,
            fmt=_bladerf.Format.SC16_Q11,
            num_buffers=32,
            buffer_size=16384,
            num_transfers=16,
            stream_timeout=5000
        )
        
        ch0.enable = True
        ch1.enable = True
        
        # Capture
        n_samples = int(duration * fs)
        print(f"  Recording {n_samples:,} samples ({duration}s)...")
        
        buf = np.zeros(n_samples * 4, dtype=np.int16)
        device.sync_rx(buf, n_samples)
        
        ch0.enable = False
        ch1.enable = False
        device.close()
        
        # Deinterleave: [I0, Q0, I1, Q1, ...]
        ch0_data = (buf[0::4].astype(np.float32) + 1j * buf[1::4].astype(np.float32)).astype(np.complex64)
        ch1_data = (buf[2::4].astype(np.float32) + 1j * buf[3::4].astype(np.float32)).astype(np.complex64)
        
        print(f"  ✓ Recorded {len(ch0_data):,} samples")
        device_name = 'BladeRF 2.0'
        
    except Exception as e:
        print(f"  ⚠️ Hardware error: {e}")
        print("  Generating synthetic data for testing...")
        
        n_samples = int(duration * fs)
        t = np.arange(n_samples) / fs
        
        # Synthetic signal at specified angle
        phi_geom = np.pi * np.sin(np.deg2rad(angle_deg))
        signal = np.exp(1j * 2 * np.pi * 100e3 * t)
        
        ch0_data = signal.astype(np.complex64)
        ch1_data = (signal * np.exp(1j * phi_geom)).astype(np.complex64)
        
        noise_power = 0.3 if snr_label == 'low' else 0.05
        ch0_data += (np.sqrt(noise_power/2) * (np.random.randn(n_samples) + 1j*np.random.randn(n_samples))).astype(np.complex64)
        ch1_data += (np.sqrt(noise_power/2) * (np.random.randn(n_samples) + 1j*np.random.randn(n_samples))).astype(np.complex64)
        
        device_name = 'Synthetic (no hardware)'
    
    # Save with full metadata
    cal = load_receiver_calibration()
    metadata = {
        'fc': fc,
        'fs': fs,
        'bw': fs * 0.75,
        'gain': gain,
        'antenna_spacing': 0.061,  # λ/2 at 2.45 GHz
        'angle': angle_deg,
        'distance': distance_m,
        'snr_label': snr_label,
        'environment': 'indoor_lab',
        'notes': notes,
        'device': device_name,
        'phase_cal_deg': cal.phase_offset_deg,
        'gain_ratio': cal.gain_ratio,
    }
    
    save_capture(filename, ch0_data, ch1_data, metadata)
    
    # Sanity checks
    coherence = compute_coherence(ch0_data, ch1_data)
    phase_raw = compute_phase_offset(ch0_data, ch1_data)
    # Apply static calibration for an informative quick-look DOA estimate.
    ch0_cal, ch1_cal = apply_calibration(ch0_data, ch1_data, cal.phase_offset_rad, cal.gain_ratio)
    phase_cal = compute_phase_offset(ch0_cal, ch1_cal)
    doa_est = np.rad2deg(np.arcsin(np.clip(phase_cal / np.pi, -1, 1)))
    
    print(f"\n✓ Saved: {filename}")
    print(f"  Coherence: {coherence:.3f}")
    print(f"  Raw phase: {np.rad2deg(phase_raw):.1f}°")
    print(f"  Using phase_cal_deg: {cal.phase_offset_deg:.2f}°  (source: {cal.source})")
    print(f"  Calibrated phase: {np.rad2deg(phase_cal):.1f}°")
    print(f"  Estimated DOA (calibrated): {doa_est:.1f}° (target: {angle_deg}°)")
    
    if coherence < 0.1:
        print("  ⚠️ WARNING: Low coherence! Check antenna/signal")
    
    return filename


def main():
    parser = argparse.ArgumentParser(
        description='Collect labeled DOA dataset',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/collect_dataset.py --angle 0 --distance 2 --snr high
    python scripts/collect_dataset.py --angle 30 --distance 5 --snr low --reps 5
    
See docs/experiment_spec.md for the experiment matrix.
        """
    )
    parser.add_argument('--angle', type=int, required=True,
                        help='Nominal angle in degrees (-90 to +90)')
    parser.add_argument('--distance', type=float, required=True,
                        help='Distance in meters')
    parser.add_argument('--snr', choices=['high', 'low'], required=True,
                        help='SNR condition label')
    parser.add_argument('--notes', type=str, default='',
                        help='Additional notes')
    parser.add_argument('--reps', type=int, default=1,
                        help='Number of repetitions')
    parser.add_argument('--duration', type=float, default=1.0,
                        help='Recording duration in seconds')
    parser.add_argument('--gain', type=int, default=30,
                        help='RX gain in dB')
    parser.add_argument('--output', '-o', default='data',
                        help='Output directory')
    
    args = parser.parse_args()
    
    if not -90 <= args.angle <= 90:
        print("Error: Angle must be between -90 and +90 degrees")
        sys.exit(1)
    
    print(f"\n{'#'*60}")
    print("# THESIS DATA COLLECTION")
    print(f"# Angle: {args.angle}°, Distance: {args.distance}m, SNR: {args.snr}")
    print(f"# Repetitions: {args.reps}")
    print(f"{'#'*60}")
    
    filenames = []
    for i in range(args.reps):
        print(f"\n[Capture {i+1}/{args.reps}]")
        filename = collect_capture(
            angle_deg=args.angle,
            distance_m=args.distance,
            snr_label=args.snr,
            notes=args.notes,
            duration=args.duration,
            gain=args.gain,
            output_dir=args.output
        )
        filenames.append(filename)
        
        if i < args.reps - 1:
            print("\nWaiting 2 seconds...")
            time.sleep(2)
    
    print(f"\n{'='*60}")
    print(f"COLLECTION COMPLETE: {len(filenames)} captures saved to {args.output}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

