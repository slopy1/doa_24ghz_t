#!/usr/bin/env python3
"""
cal_drift_test.py - Phase Calibration Drift Diagnostic

Measures inter-channel phase offset every second for a configurable duration
and logs each measurement to CSV. Use with wired calibration setup (signal
source → splitter → matched cables → both RX inputs).

This helps answer:
  1. How fast does the phase offset drift after power-on?
  2. Does it stabilize after warmup?
  3. How much run-to-run variance is there without touching cables?

Output: data/cal_drift_<timestamp>.csv

Usage:
    python3 cal_drift_test.py [--duration=300] [--freq=2.42e9] [--gain=40]
    python3 cal_drift_test.py --duration=300   # 5-minute drift test

Author: DoA Thesis Project
Date: 2026
"""

import numpy as np
import argparse
import sys
import time
import csv
from datetime import datetime
from pathlib import Path

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

CENTER_FREQ = 2.42e9
SAMPLE_RATE = 1e6
BANDWIDTH = 1e6
RX_GAIN = 40
CHUNK_SAMPLES = int(SAMPLE_RATE)  # 1 second of data per measurement


# =============================================================================
# SDR setup / teardown
# =============================================================================

def setup_sdr(freq, rate, bw, gain):
    results = SoapySDR.Device.enumerate("driver=bladerf")
    if not results:
        raise RuntimeError("No BladeRF device found")
    sdr = SoapySDR.Device(results[0])
    for ch in [0, 1]:
        sdr.setSampleRate(SOAPY_SDR_RX, ch, rate)
        sdr.setFrequency(SOAPY_SDR_RX, ch, freq)
        sdr.setBandwidth(SOAPY_SDR_RX, ch, bw)
        sdr.setGain(SOAPY_SDR_RX, ch, gain)
    stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0, 1])
    sdr.activateStream(stream)
    return sdr, stream


def read_samples(sdr, stream, n):
    buffers = [np.zeros(n, dtype=np.complex64) for _ in range(2)]
    got = 0
    while got < n:
        chunk = min(65536, n - got)
        bufs = [b[got:got+chunk] for b in buffers]
        sr = sdr.readStream(stream, bufs, chunk, timeoutUs=1000000)
        if sr.ret > 0:
            got += sr.ret
        elif sr.ret < 0:
            break
    return buffers[0], buffers[1]


# =============================================================================
# Phase measurement
# =============================================================================

def measure_phase(ch0, ch1):
    """Conjugate-multiply and average → phase in degrees + SNR proxy."""
    cross = ch0 * np.conj(ch1)
    cross_avg = np.mean(cross)
    phase_deg = np.rad2deg(np.angle(cross_avg))

    # SNR proxy: |mean(cross)| / std(cross)
    # High value = clean tone, low value = noise-dominated
    magnitude = np.abs(cross_avg)
    spread = np.std(cross)
    snr_proxy = magnitude / spread if spread > 0 else 0.0

    # Power per channel (for gain balance check)
    p0 = float(np.mean(np.abs(ch0)**2))
    p1 = float(np.mean(np.abs(ch1)**2))

    return phase_deg, snr_proxy, p0, p1


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Phase calibration drift diagnostic")
    parser.add_argument("--duration", type=int, default=300,
                        help="Test duration in seconds (default: 300 = 5 min)")
    parser.add_argument("--freq", type=float, default=CENTER_FREQ,
                        help="Center frequency in Hz")
    parser.add_argument("--gain", type=int, default=RX_GAIN,
                        help="RX gain in dB")
    args = parser.parse_args()

    # Output file
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = data_dir / f"cal_drift_{ts}.csv"

    print(f"# Cal Drift Test — {args.duration}s @ {args.freq/1e9:.3f} GHz, gain={args.gain} dB")
    print(f"# Output: {csv_path}")
    sys.stdout.flush()

    if not HAS_SOAPY:
        print("ERROR:SoapySDR not available")
        return

    sdr, stream = setup_sdr(args.freq, SAMPLE_RATE, BANDWIDTH, args.gain)
    print("# SDR ready, starting measurements...")
    sys.stdout.flush()

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["elapsed_s", "phase_deg", "snr_proxy", "power_ch0", "power_ch1"])

        try:
            t0 = time.time()
            idx = 0
            while True:
                elapsed = time.time() - t0
                if elapsed >= args.duration:
                    break

                ch0, ch1 = read_samples(sdr, stream, CHUNK_SAMPLES)
                phase, snr, p0, p1 = measure_phase(ch0, ch1)

                writer.writerow([f"{elapsed:.1f}", f"{phase:.2f}", f"{snr:.3f}",
                                 f"{p0:.6f}", f"{p1:.6f}"])
                f.flush()

                gain_balance_db = 10 * np.log10(p0 / p1) if p1 > 0 else 0
                print(f"  [{elapsed:6.1f}s] phase={phase:+7.2f}°  snr={snr:.2f}  "
                      f"bal={gain_balance_db:+.1f}dB")
                sys.stdout.flush()

                idx += 1

        except KeyboardInterrupt:
            print("\n# Interrupted")
        finally:
            sdr.deactivateStream(stream)
            sdr.closeStream(stream)

    print(f"# Done — {idx} measurements saved to {csv_path}")

    # Quick summary
    if idx > 1:
        import csv as csv_mod
        phases = []
        with open(csv_path) as f:
            for row in csv_mod.DictReader(f):
                phases.append(float(row["phase_deg"]))
        print(f"# Summary: mean={np.mean(phases):.2f}°  std={np.std(phases):.2f}°  "
              f"range=[{min(phases):.1f}°, {max(phases):.1f}°]")


if __name__ == "__main__":
    main()
