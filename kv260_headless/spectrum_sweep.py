#!/usr/bin/env python3
"""Spectrum sweep at the campaign tuning. Diagnostic for multipath/interference.

Captures N seconds of CH0 IQ from BladeRF at --freq, computes a Welch PSD,
emits CSV (baseband_freq_hz, power_dbfs) and prints the top spectral peaks.
Saves a quick PNG if matplotlib is installed.

Usage:
    sudo python3 spectrum_sweep.py --freq 2.41895e9 --gain 50 --duration 5 \\
        --out /tmp/sweep.csv
"""
import argparse
import sys
import time

import numpy as np

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
except ImportError:
    print("SoapySDR not installed. Run on the Kria.", file=sys.stderr)
    sys.exit(1)


def capture(freq_hz, gain_db, sample_rate, n_samples):
    stream = None
    try:
        sdr = SoapySDR.Device({"driver": "bladerf"})
    except Exception as exc:
        raise RuntimeError(f"failed to open BladeRF via SoapySDR: {exc}") from exc

    try:
        sdr.setSampleRate(SOAPY_SDR_RX, 0, sample_rate)
        sdr.setFrequency(SOAPY_SDR_RX, 0, freq_hz)
        sdr.setGain(SOAPY_SDR_RX, 0, gain_db)
        sdr.setBandwidth(SOAPY_SDR_RX, 0, sample_rate * 0.8)

        stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0])
        sdr.activateStream(stream)

        buf = np.empty(n_samples, dtype=np.complex64)
        chunk = np.empty(8192, dtype=np.complex64)
        got = 0
        retries = 0
        while got < n_samples and retries < 200:
            sr = sdr.readStream(stream, [chunk], chunk.size, timeoutUs=int(1e6))
            if sr.ret > 0:
                n = min(sr.ret, n_samples - got)
                buf[got:got + n] = chunk[:n]
                got += n
                retries = 0
            elif sr.ret == -4:  # SOAPY_SDR_OVERFLOW is advisory.
                continue
            else:
                retries += 1

        if got == 0:
            raise RuntimeError("BladeRF capture returned zero samples")
        return buf[:got]
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"BladeRF spectrum capture failed: {exc}") from exc
    finally:
        if stream is not None:
            try:
                sdr.deactivateStream(stream)
                sdr.closeStream(stream)
            except Exception:
                pass


def welch_psd(samples, sample_rate, nfft=8192):
    n_segments = max(1, samples.size // nfft)
    psd = np.zeros(nfft, dtype=np.float64)
    win = np.hanning(nfft)
    win_norm = (win ** 2).sum()
    for i in range(n_segments):
        seg = samples[i * nfft:(i + 1) * nfft] * win
        spec = np.fft.fftshift(np.fft.fft(seg, nfft))
        psd += np.abs(spec) ** 2
    psd /= (n_segments * win_norm * sample_rate)
    psd = 10 * np.log10(psd + 1e-20)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / sample_rate))
    return freqs, psd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=float, default=2.41895e9)
    ap.add_argument("--gain", type=float, default=50)
    ap.add_argument("--rate", type=float, default=1e6)
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--out", default="/tmp/sweep.csv")
    args = ap.parse_args()

    n = int(args.rate * args.duration)
    print(f"# Capturing {args.duration} s @ {args.rate/1e6} MSPS, "
          f"freq={args.freq/1e9:.5f} GHz, gain={args.gain} dB")
    t0 = time.monotonic()
    try:
        iq = capture(args.freq, args.gain, args.rate, n)
    except RuntimeError as exc:
        print(f"ERROR:{exc}")
        sys.exit(1)
    print(f"# Got {iq.size} samples in {time.monotonic()-t0:.1f} s")

    freqs, psd = welch_psd(iq, args.rate)

    # Save CSV (baseband Hz, power dBFS/Hz)
    with open(args.out, "w") as f:
        f.write("# baseband_freq_hz,power_dbfs_per_hz\n")
        for fr, p in zip(freqs, psd):
            f.write(f"{fr:.1f},{p:.3f}\n")
    print(f"# CSV → {args.out}")

    # Top 5 peaks above noise floor (sample dense regions)
    noise_floor = np.median(psd)
    peak_threshold = noise_floor + 6  # 6 dB above median
    peaks = np.argsort(psd)[-12:][::-1]
    print(f"# Noise floor (median): {noise_floor:.1f} dB")
    print(f"# Top spectral peaks (within ±{args.rate/2/1e3:.0f} kHz baseband):")
    seen = []
    for idx in peaks:
        f_baseband = freqs[idx]
        # Suppress duplicates within 5 kHz
        if any(abs(f_baseband - s) < 5e3 for s in seen): continue
        seen.append(f_baseband)
        f_rf = args.freq + f_baseband
        in_band = "<-- IN 40-60 kHz BANDPASS" if 40e3 <= f_baseband <= 60e3 else ""
        if -60e3 <= f_baseband <= -40e3:
            in_band = "<-- mirror image of bandpass"
        print(f"  baseband={f_baseband/1e3:+7.1f} kHz  "
              f"RF={f_rf/1e9:.6f} GHz  power={psd[idx]:+6.1f} dB  {in_band}")
        if len(seen) >= 5: break


if __name__ == "__main__":
    main()
