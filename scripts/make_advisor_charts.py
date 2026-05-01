#!/usr/bin/env python3
"""Generate clean, presentation-style charts for the advisor update.

Outputs to results/advisor_summary/:
  1. arm_vs_fpga_per_angle.png  — bar chart of mean ± σ vs truth, ARM and FPGA
  2. arm_vs_fpga_delta.png      — FPGA−ARM mean delta per angle
  3. broadside_anchor.png       — 90° unfiltered ARM vs FPGA (the negative-control point)
  4. methodology_r2.png         — Apr-26 vs Apr-27 R² jump headline
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

OUT = "/home/mau/doa_24ghz_thesis/results/advisor_summary"

# Final-config (Apr-27 174414) per-angle stats
truths    = np.array([50,  70,  110,  130])
arm_mean  = np.array([55.16, 75.04, 101.35, 121.93])
arm_sigma = np.array([1.01,  0.16,  0.36,   4.44])
fpga_mean = np.array([62.50, 78.82, 105.91,  99.76])
fpga_sigma= np.array([1.40,  1.22,  0.39,  33.55])

# 90° broadside anchor (Apr-26, --filter=none, cal=51.96)
arm90_mean,  arm90_sigma  = 89.61, 0.32
fpga90_mean, fpga90_sigma = 70.92, 0.29

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 160,
    "font.size": 11,
    "axes.grid": True,
    "grid.alpha": 0.3,
})

# ---- 1. ARM vs FPGA per-angle bar chart -----------------------------------
fig, ax = plt.subplots(figsize=(9, 5.5))
x = np.arange(len(truths))
w = 0.35
ax.bar(x - w/2, arm_mean,  w, yerr=arm_sigma,  capsize=5,
       label="ARM (reference)", color="#2b6cb0", edgecolor="black")
ax.bar(x + w/2, fpga_mean, w, yerr=fpga_sigma, capsize=5,
       label="FPGA (hybrid)",   color="#dd6b20", edgecolor="black")
for xi, t in zip(x, truths):
    ax.axhline(t, xmin=(xi-0.45)/len(truths), xmax=(xi+0.45)/len(truths),
               color="green", linestyle="--", linewidth=1.2)
ax.plot([], [], "g--", label="Truth angle")
ax.set_xticks(x)
ax.set_xticklabels([f"{t}°" for t in truths])
ax.set_xlabel("Truth angle")
ax.set_ylabel("Estimated angle (°)")
ax.set_title("ARM vs FPGA hybrid — per-angle mean ± σ\n"
             "Final config (Apr-27 174414, --filter=arm_bandpass, cal=+57.14°)")
ax.legend(loc="upper left")
plt.tight_layout()
plt.savefig(f"{OUT}/arm_vs_fpga_per_angle.png")
plt.close()

# ---- 2. FPGA - ARM delta --------------------------------------------------
delta = fpga_mean - arm_mean
fig, ax = plt.subplots(figsize=(8, 4.8))
colors = ["#dd6b20" if abs(d) < 10 else "#c53030" for d in delta]
bars = ax.bar([f"{t}°" for t in truths], delta, color=colors, edgecolor="black")
ax.axhline(0, color="black", linewidth=0.8)
ax.axhspan(-7, 7, alpha=0.15, color="green",
           label="Calibration-asymmetry band (±7°)")
for b, d in zip(bars, delta):
    ax.text(b.get_x() + b.get_width()/2,
            d + (1.5 if d > 0 else -2.5),
            f"{d:+.2f}°", ha="center", fontsize=10)
ax.set_ylabel("FPGA mean − ARM mean (°)")
ax.set_xlabel("Truth angle")
ax.set_title("Path-to-path mean offset\n"
             "Constant +4° to +7° at clean angles; 130° outlier from array-geometry limit")
ax.legend()
plt.tight_layout()
plt.savefig(f"{OUT}/arm_vs_fpga_delta.png")
plt.close()

# ---- 3. 90° broadside negative control ------------------------------------
fig, ax = plt.subplots(figsize=(8, 4.8))
ax.bar(["ARM"],  [arm90_mean],  yerr=[arm90_sigma],  capsize=8,
       color="#2b6cb0", edgecolor="black", width=0.5)
ax.bar(["FPGA (unfiltered)"], [fpga90_mean], yerr=[fpga90_sigma], capsize=8,
       color="#dd6b20", edgecolor="black", width=0.5)
ax.axhline(90, color="green", linestyle="--", linewidth=1.5,
           label="Broadside truth = 90°")
ax.text(0, arm90_mean+2,  f"{arm90_mean:.2f}°\nσ={arm90_sigma:.2f}°",
        ha="center", fontsize=10)
ax.text(1, fpga90_mean-7, f"{fpga90_mean:.2f}°\nσ={fpga90_sigma:.2f}°",
        ha="center", fontsize=10)
ax.set_ylabel("Estimated angle (°)")
ax.set_ylim(60, 100)
ax.set_title("90° broadside negative control (Apr-26, --filter=none, cal=+51.96°)\n"
             "ARM accurate & tight; FPGA equally tight but ~19° offset")
ax.legend()
plt.tight_layout()
plt.savefig(f"{OUT}/broadside_anchor.png")
plt.close()

# ---- 4. Methodology dominance — R² jump -----------------------------------
fig, ax = plt.subplots(figsize=(7.5, 4.5))
labels = ["Apr-26\n(unfiltered, mixed cal,\nroom occupied)",
          "Apr-27 174414\n(hybrid filter, single cal,\nroom empty)"]
r2 = [0.103, 0.9744]
bars = ax.bar(labels, r2, color=["#c53030", "#2f855a"], edgecolor="black")
ax.set_ylim(0, 1.05)
ax.set_ylabel("ARM fold-deg fit R²")
ax.set_title("Same hardware, same algorithm — methodology dominates\n"
             "R² jump from 0.10 → 0.97 with controlled filter, cal, and environment")
for b, v in zip(bars, r2):
    ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"R² = {v:.2f}",
            ha="center", fontsize=11, fontweight="bold")
plt.tight_layout()
plt.savefig(f"{OUT}/methodology_r2.png")
plt.close()

# ---- 5. Filter-regime comparison at 50° -----------------------------------
import csv
def load_csv(path):
    with open(path) as f:
        return np.array([float(r[0]) for r in csv.reader(f) if r and r[0].strip()])

unfilt   = load_csv("/home/mau/doa_24ghz_thesis/data/run_20260426_182257/fpga_50deg.csv")
fabricfir= load_csv("/home/mau/doa_24ghz_thesis/data/run_20260427_002020/fpga_50deg.csv")
hybrid   = load_csv("/home/mau/doa_24ghz_thesis/data/run_20260427_174414/fpga_50deg.csv")
hybrid   = hybrid[12:50]  # apply trim

fig, ax = plt.subplots(figsize=(9.5, 5))
groups = [
    ("Unfiltered\n(--filter=none)\nApr-26",         unfilt,    "#c53030"),
    ("Fabric FIR 20 kHz\n(--filter=bandpass)\nApr-27 002020", fabricfir, "#dd6b20"),
    ("Hybrid 500 kHz ARM\n(--filter=arm_bandpass)\nApr-27 174414", hybrid, "#2f855a"),
]
for i, (label, data, color) in enumerate(groups):
    jitter = np.random.default_rng(i).uniform(-0.12, 0.12, size=len(data))
    ax.scatter(np.full_like(data, i, dtype=float) + jitter, data,
               s=22, alpha=0.6, color=color, edgecolor="black", linewidth=0.3,
               label=f"{label}  (n={len(data)})")
    ax.hlines(np.mean(data), i-0.25, i+0.25, color="black", linewidth=2)

ax.axhline(50, color="green", linestyle="--", linewidth=1.5, label="Truth = 50°")
ax.set_xticks(range(len(groups)))
ax.set_xticklabels([g[0] for g in groups], fontsize=9)
ax.set_ylabel("FPGA AOA estimate (°)")
ax.set_title("Same 50° truth, three filter regimes — FPGA path only\n"
             "Fabric FIR is multimodal on BLE (occupied BW ~500 kHz vs filter 20 kHz)")
ax.legend(loc="upper right", fontsize=8)
ax.set_ylim(-10, 200)
plt.tight_layout()
plt.savefig(f"{OUT}/filter_regime_comparison.png")
plt.close()

print("Wrote charts to", OUT)
