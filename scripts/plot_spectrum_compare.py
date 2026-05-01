#!/usr/bin/env python3
"""Plot two spectrum_sweep CSVs (off vs on) with bandpass region shaded."""
import os
import sys

import numpy as np


def load(p):
    a = np.loadtxt(p, delimiter=",", comments="#")
    return a[:, 0], a[:, 1]


def main():
    if len(sys.argv) != 2:
        print("usage: plot_spectrum_compare.py <out_dir>")
        sys.exit(2)
    out_dir = sys.argv[1]

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"matplotlib not available; CSVs are in {out_dir}")
        sys.exit(0)

    f_off, p_off = load(os.path.join(out_dir, "sweep_off.csv"))
    f_on,  p_on  = load(os.path.join(out_dir, "sweep_on.csv"))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(f_off / 1e3, p_off, label="nRF OFF (background)",
            color="gray", lw=0.7)
    ax.plot(f_on / 1e3, p_on, label="nRF ON (mod carrier)",
            color="tab:blue", lw=0.9)
    ax.axvspan(40, 60, color="tab:orange", alpha=0.25,
               label="bandpass +40 to +60 kHz")
    ax.axvspan(-60, -40, color="tab:red", alpha=0.10,
               label="mirror image -60 to -40 kHz")
    ax.axvline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_xlabel("Baseband frequency [kHz] (RF = 2.41895 GHz + this)")
    ax.set_ylabel("Power [dBFS/Hz]")
    ax.set_title("Spectrum at campaign tuning: nRF OFF vs ON")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_xlim(-500, 500)
    fig.tight_layout()
    out_path = os.path.join(out_dir, "spectrum_compare.png")
    fig.savefig(out_path, dpi=130)
    print(f"plot → {out_path}")


if __name__ == "__main__":
    main()
