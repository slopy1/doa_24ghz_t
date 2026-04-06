#!/usr/bin/env python3
"""
View Raw IQ Data (.32fc)

Usage:
    python3 scripts/view_iq_data.py data/aoa_ch0.32fc
    python3 scripts/view_iq_data.py data/cal_ch1.32fc --fs 5e6

"""

import argparse
import numpy as np
import matplotlib.pyplot as plt

def main():
    parser = argparse.ArgumentParser(description="Plot raw IQ data from binary file")
    parser.add_argument("filename", help="Path to .32fc file")
    parser.add_argument("--fs", type=float, default=1e6, help="Sample rate (Hz)")
    parser.add_argument("--samples", type=int, default=1000, help="Number of samples to plot in time domain")
    args = parser.parse_args()

    try:
        # Read data
        # .32fc in GNU Radio is standard complex64 (2x float32)
        data = np.fromfile(args.filename, dtype=np.complex64)
        print(f"Loaded {len(data)} samples from {args.filename}")
        
        if len(data) == 0:
            print("Error: File is empty.")
            return

        # Calculate duration
        duration = len(data) / args.fs
        print(f"Loaded {len(data)} samples from {args.filename}")
        print(f"Total Duration: {duration:.3f} seconds (at {args.fs/1e6:.1f} MHz)")

        # Time vector
        t = np.arange(len(data)) / args.fs

        # Create plots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

        # 1. Time Domain (I and Q)
        subset_len = min(args.samples, len(data))
        subset = data[:subset_len]
        t_subset = t[:subset_len] * 1000 # ms
        
        ax1.plot(t_subset, subset.real, label='I (Real)', alpha=0.8)
        ax1.plot(t_subset, subset.imag, label='Q (Imag)', alpha=0.8)
        ax1.set_title(f"Time Domain (Showing first {subset_len} samples of {len(data)})")
        ax1.set_xlabel("Time (ms)")
        ax1.set_ylabel("Amplitude")
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        # 2. Frequency Domain (PSD)
        # Use simple FFT or Welch's method
        ax2.psd(data, NFFT=1024, Fs=args.fs, window=np.hanning(1024))
        ax2.set_title("Power Spectral Density")
        
        plt.tight_layout()
        print("Displaying plot...")
        plt.show()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
