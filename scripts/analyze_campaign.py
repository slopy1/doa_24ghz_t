#!/usr/bin/env python3
"""Analyze the 2026-04-26 multi-angle campaign.

Per-angle adaptive trim → mean/std → ULA cal fit (deg-linear AND sin-space) →
ARM-vs-FPGA delta. Saves stats CSVs and figures under results/campaign_20260426/.

Usage:
    python3 scripts/analyze_campaign.py
    python3 scripts/analyze_campaign.py --run-dir data/run_20260427_090000
    python3 scripts/analyze_campaign.py --run-dir data/run_20260427_090000 \\
        --trim-from docs/trims/run_20260427_090000.json
    python3 scripts/analyze_campaign.py --no-plots   # stats only
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

DEFAULT_RUN_DIR = Path("~/doa_24ghz_thesis/data/run_20260426_182257").expanduser()
DEFAULT_OUT_DIR = Path("~/doa_24ghz_thesis/results/campaign_20260426").expanduser()

# Per-run trim windows in row indices, derived from the time-windowed
# diagnosis in the previous session. Edit if you want to widen/narrow a window
# after seeing the time-series plot. (start, end) — end=None means "to end".
DEFAULT_TRIM = {
    # angle: { path: (start, end) }
    50:  {"arm": (100, 400), "fpga": (12, 50)},   # bumped early AND late
    70:  {"arm": (126, None), "fpga": (16, None)},  # 15s blanket warmup
    90:  {"arm": (126, None), "fpga": (16, None)},
    110: {"arm": (126, None), "fpga": (16, 60)},   # FPGA tail blew up
    130: {"arm": (400, None), "fpga": (16, None)},  # ARM drifted, settled late
}

ANGLES = [50, 70, 90, 110, 130]
PATHS = ["arm", "fpga"]

RUN_DIR = DEFAULT_RUN_DIR
OUT_DIR = DEFAULT_OUT_DIR
TRIM = DEFAULT_TRIM

# 90° anchor used a different cal value (cal=51.96, before-the-break gold).
# Other angles used cal=53.19 (after-the-break recal). Per-run cal is folded
# into the angle estimate already by the driver, so this is informational only.
DEFAULT_CAL_BY_ANGLE = {90: 51.96, 50: 53.19, 70: 53.19, 110: 53.19, 130: 53.19}
CAL_BY_ANGLE = DEFAULT_CAL_BY_ANGLE


def load_csv(path: Path) -> np.ndarray:
    if not path.exists():
        return np.array([])
    return np.loadtxt(path)


def default_out_dir_for(run_dir: Path) -> Path:
    if run_dir == DEFAULT_RUN_DIR:
        return DEFAULT_OUT_DIR
    name = run_dir.name
    suffix = name.removeprefix("run_")
    return Path("~/doa_24ghz_thesis/results").expanduser() / f"campaign_{suffix}"


def load_trim_file(path: Path) -> dict[int, dict[str, tuple[int, int | None]]]:
    """Load trim windows from JSON: {"50": {"arm": [100, 400], ...}, ...}."""
    raw = json.loads(path.read_text())
    trims: dict[int, dict[str, tuple[int, int | None]]] = {}
    for angle, paths in raw.items():
        trims[int(angle)] = {}
        for p, window in paths.items():
            if len(window) != 2:
                raise ValueError(f"trim for angle {angle} path {p} must have [start, end]")
            start, end = window
            trims[int(angle)][p] = (int(start), None if end is None else int(end))
    return trims


def cal_by_angle_for(run_dir: Path, cal_used: float | None) -> dict[int, float | None]:
    if cal_used is not None:
        return {angle: cal_used for angle in ANGLES}
    if run_dir == DEFAULT_RUN_DIR:
        return DEFAULT_CAL_BY_ANGLE
    cal_file = run_dir / "cal_value_resume.txt"
    if cal_file.exists():
        try:
            value = float(cal_file.read_text().strip())
            return {angle: value for angle in ANGLES}
        except ValueError:
            pass
    return {angle: None for angle in ANGLES}


def trim_window(angle: int, path: str) -> tuple[int, int | None]:
    return TRIM.get(angle, {}).get(path, (0, None))


def trimmed(vals: np.ndarray, window: tuple[int, int | None]) -> np.ndarray:
    s, e = window
    return vals[s:e] if vals.size else vals


def per_run_stats() -> list[dict]:
    rows = []
    for ang in ANGLES:
        for p in PATHS:
            raw = load_csv(RUN_DIR / f"{p}_{ang}deg.csv")
            kept = trimmed(raw, trim_window(ang, p))
            if kept.size < 5:
                rows.append({"angle": ang, "path": p, "n_raw": raw.size,
                             "n_used": kept.size, "mean": None, "std": None})
                continue
            rows.append({
                "angle": ang, "path": p,
                "n_raw": int(raw.size), "n_used": int(kept.size),
                "mean": float(np.mean(kept)),
                "std":  float(np.std(kept, ddof=1)),
                "min":  float(np.min(kept)),
                "max":  float(np.max(kept)),
                "cal_used": CAL_BY_ANGLE.get(ang),
            })
    return rows


def fold_to_broadside(theta_deg: float) -> float:
    """2-element ULA front-back ambiguity: only |sin(θ−90°)| is observable.
    Fold both truth and measured to [0°, 90°] off broadside."""
    return 90.0 - abs(theta_deg - 90.0)


def fit_linear_folded(stats: list[dict], path: str) -> dict:
    """fold(measured) = m·fold(true) + b. Perfect cal → m=1, b=0.
    Folded so 50/130 collapse to one point, 70/110 to one point."""
    pts = [(r["angle"], r["mean"]) for r in stats
           if r["path"] == path and r["mean"] is not None]
    x = np.array([fold_to_broadside(a) for a, _ in pts], dtype=float)
    y = np.array([fold_to_broadside(m) for _, m in pts], dtype=float)
    m, b = np.polyfit(x, y, 1)
    yhat = m * x + b
    resid = y - yhat
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - np.mean(y))**2) or float("nan")
    r2 = 1 - ss_res / ss_tot if ss_tot == ss_tot else float("nan")
    return {"slope": float(m), "intercept": float(b), "r2": float(r2),
            "per_angle_error_deg": {int(a): float(fold_to_broadside(mn) - fold_to_broadside(a))
                                    for a, mn in pts}}


def fit_sin_folded(stats: list[dict], path: str) -> dict:
    """sin(fold(measured)) = m·sin(fold(true)) + b. The honest ULA model
    once front-back ambiguity is acknowledged."""
    pts = [(r["angle"], r["mean"]) for r in stats
           if r["path"] == path and r["mean"] is not None]
    x = np.sin(np.deg2rad([fold_to_broadside(a) for a, _ in pts]))
    y = np.sin(np.deg2rad([fold_to_broadside(m) for _, m in pts]))
    m, b = np.polyfit(x, y, 1)
    yhat = m * x + b
    resid = y - yhat
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - np.mean(y))**2) or float("nan")
    r2 = 1 - ss_res / ss_tot if ss_tot == ss_tot else float("nan")
    return {"slope": float(m), "intercept": float(b), "r2": float(r2)}


def write_stats_csv(stats: list[dict], path: Path) -> None:
    fields = ["angle", "path", "n_raw", "n_used", "mean", "std", "min", "max", "cal_used"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in stats:
            w.writerow({k: r.get(k) for k in fields})


def make_plots(stats: list[dict], fits: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 1. Time-series per angle with trim window shaded
    fig, axes = plt.subplots(len(ANGLES), 2, figsize=(13, 2.4 * len(ANGLES)),
                              sharex=False)
    for i, ang in enumerate(ANGLES):
        for j, p in enumerate(PATHS):
            ax = axes[i, j]
            raw = load_csv(RUN_DIR / f"{p}_{ang}deg.csv")
            if raw.size == 0:
                ax.set_title(f"{ang}° {p.upper()} — missing"); continue
            ax.plot(raw, ".", ms=2, alpha=0.6)
            s, e = trim_window(ang, p)
            e_eff = raw.size if e is None else e
            ax.axvspan(s, e_eff, alpha=0.15, color="green", label="kept")
            ax.axhline(ang, color="red", lw=0.7, ls="--", label="truth")
            ax.set_title(f"{ang}° {p.upper()}  (n={e_eff - s} kept)")
            ax.set_ylabel("AOA [deg]")
            ax.set_xlabel("sample idx")
            ax.legend(fontsize=7, loc="best")
    fig.suptitle("Per-angle raw time-series + trim windows", y=1.001)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "time_series_per_angle.png", dpi=130)
    plt.close(fig)

    # 2. Folded measured vs folded truth (handles front-back ambiguity)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    truth = np.array(ANGLES, dtype=float)
    truth_folded = np.array([fold_to_broadside(a) for a in truth])
    def _as_float(v):
        if v is None:
            return np.nan
        try:
            return float(v)
        except (TypeError, ValueError):
            return np.nan
    for p, color in [("arm", "tab:blue"), ("fpga", "tab:orange")]:
        means = np.array([_as_float(next((r["mean"] for r in stats
                                if r["angle"] == a and r["path"] == p), np.nan))
                          for a in ANGLES])
        stds  = np.array([_as_float(next((r["std"] for r in stats
                                if r["angle"] == a and r["path"] == p), np.nan))
                          for a in ANGLES])
        means_folded = np.array([fold_to_broadside(m) if np.isfinite(m) else np.nan
                                  for m in means])
        ax.errorbar(truth_folded, means_folded, yerr=stds, fmt="o", color=color,
                    label=f"{p.upper()} (slope={fits[p]['linear_folded']['slope']:+.3f}, "
                          f"int={fits[p]['linear_folded']['intercept']:+.2f}°, "
                          f"R²={fits[p]['linear_folded']['r2']:.4f})",
                    capsize=4, markersize=8)
        # annotate which truth angle each point came from
        for x_, y_, a_ in zip(truth_folded, means_folded, ANGLES):
            ax.annotate(f"{a_}°", (x_, y_), xytext=(6, 4),
                        textcoords="offset points", fontsize=8, color=color)
    ax.plot([0, 90], [0, 90], "k--", lw=0.7, label="ideal y=x")
    ax.set_xlabel("|θ_true − 90°| (off-broadside, deg)")
    ax.set_ylabel("|θ_measured − 90°| (off-broadside, deg)")
    ax.set_title("Folded measured vs truth (2-element ULA front-back ambiguity)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "folded_measured_vs_truth.png", dpi=130)
    plt.close(fig)

    # 3. Per-angle precision bar chart (the actual headline result)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    width = 0.35
    x = np.arange(len(ANGLES))
    arm_sigmas  = [_as_float(next((r["std"] for r in stats
                          if r["angle"] == a and r["path"] == "arm"),  np.nan))
                    for a in ANGLES]
    fpga_sigmas = [_as_float(next((r["std"] for r in stats
                          if r["angle"] == a and r["path"] == "fpga"), np.nan))
                    for a in ANGLES]
    ax.bar(x - width/2, arm_sigmas,  width, label="ARM",  color="tab:blue")
    ax.bar(x + width/2, fpga_sigmas, width, label="FPGA", color="tab:orange")
    ax.axhline(3.4, color="gray", ls="--", lw=0.7, label="Cora baseline σ=3.4°")
    ax.set_xticks(x); ax.set_xticklabels([f"{a}°" for a in ANGLES])
    ax.set_xlabel("True angle"); ax.set_ylabel("σ of measured AOA [deg]")
    ax.set_title("Per-angle precision (lower = better)")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "precision_per_angle.png", dpi=130)
    plt.close(fig)

    # 4. ARM minus FPGA delta vs truth
    fig, ax = plt.subplots(figsize=(7, 4.5))
    deltas = []
    for a in ANGLES:
        arm  = next((r["mean"] for r in stats if r["angle"] == a and r["path"] == "arm"),  None)
        fpga = next((r["mean"] for r in stats if r["angle"] == a and r["path"] == "fpga"), None)
        if arm is not None and fpga is not None:
            deltas.append((a, arm - fpga))
    xa, ya = zip(*deltas)
    ax.plot(xa, ya, "o-", color="tab:purple", markersize=8)
    ax.axhline(np.mean(ya), color="gray", ls="--", lw=0.7,
               label=f"mean Δ = {np.mean(ya):+.2f}°  (σ = {np.std(ya, ddof=1):.2f}°)")
    ax.set_xlabel("True angle θ [deg]")
    ax.set_ylabel("ARM − FPGA mean [deg]")
    ax.set_title("Cal-application asymmetry: ARM − FPGA per angle")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "arm_minus_fpga_delta.png", dpi=130)
    plt.close(fig)


def main():
    global RUN_DIR, OUT_DIR, TRIM, CAL_BY_ANGLE

    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR,
                    help="campaign run directory with arm_50deg.csv style files")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="output directory for stats/plots")
    ap.add_argument("--trim-from", type=Path, default=None,
                    help="JSON trim windows; defaults to the 2026-04-26 trims")
    ap.add_argument("--cal-used", type=float, default=None,
                    help="calibration value to record for all angles")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()

    RUN_DIR = args.run_dir.expanduser()
    OUT_DIR = args.out_dir.expanduser() if args.out_dir else default_out_dir_for(RUN_DIR)
    if args.trim_from:
        trim_path = args.trim_from.expanduser()
        if not trim_path.exists():
            ap.error(f"--trim-from file not found: {trim_path}")
        try:
            TRIM = load_trim_file(trim_path)
        except (json.JSONDecodeError, ValueError) as exc:
            ap.error(f"--trim-from invalid: {exc}")
    else:
        TRIM = DEFAULT_TRIM
    CAL_BY_ANGLE = cal_by_angle_for(RUN_DIR, args.cal_used)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stats = per_run_stats()
    write_stats_csv(stats, OUT_DIR / "per_angle_stats.csv")

    fits = {p: {"linear_folded": fit_linear_folded(stats, p),
                 "sin_folded":    fit_sin_folded(stats, p)}
            for p in PATHS}
    with open(OUT_DIR / "fit_summary.json", "w") as f:
        json.dump(fits, f, indent=2)

    print(f"\n=== Per-angle stats (adaptive trim per CONFIG) ===")
    print(f"{'truth':>5} {'fold':>4} {'path':<5} {'n':>5} "
          f"{'mean':>7} {'σ':>6} {'fold(mean)':>10} {'err_deg':>8}")
    for r in stats:
        if r["mean"] is None:
            continue
        ft = fold_to_broadside(r["angle"])
        fm = fold_to_broadside(r["mean"])
        print(f"{r['angle']:>4}° {ft:>3.0f}° {r['path']:<5} {r['n_used']:>5} "
              f"{r['mean']:>6.2f}° {r['std']:>5.2f}° {fm:>9.2f}° {fm-ft:>+7.2f}°")

    print(f"\n=== Folded ULA fits (front-back ambiguity acknowledged) ===")
    for p in PATHS:
        L = fits[p]["linear_folded"]; S = fits[p]["sin_folded"]
        print(f"  {p.upper()}  fold-deg:  slope={L['slope']:+.4f}  "
              f"intercept={L['intercept']:+.3f}°  R²={L['r2']:.4f}")
        print(f"        fold-sin:  slope={S['slope']:+.4f}  "
              f"intercept={S['intercept']:+.4f}    R²={S['r2']:.4f}")

    # Headline summary: precision (good) vs accuracy (limited by ULA)
    print(f"\n=== Headline result ===")
    for p in PATHS:
        sigmas = [r["std"] for r in stats if r["path"] == p and r["std"] is not None]
        if sigmas:
            print(f"  {p.upper()}  mean σ across angles = {np.mean(sigmas):.2f}°  "
                  f"(min {min(sigmas):.2f}°, max {max(sigmas):.2f}°)")
    deltas = []
    for a in ANGLES:
        arm  = next((r["mean"] for r in stats if r["angle"] == a and r["path"] == "arm"),  None)
        fpga = next((r["mean"] for r in stats if r["angle"] == a and r["path"] == "fpga"), None)
        if arm is not None and fpga is not None:
            deltas.append(arm - fpga)
    if deltas:
        print(f"  ARM−FPGA mean Δ = {np.mean(deltas):+.2f}° "
              f"(σ {np.std(deltas, ddof=1):.2f}°)  — cal-application asymmetry")

    if not args.no_plots:
        try:
            make_plots(stats, fits)
            print(f"\nPlots → {OUT_DIR}/")
        except ImportError:
            print("\n(matplotlib not available — skipping plots)")

    print(f"Stats → {OUT_DIR}/per_angle_stats.csv")
    print(f"Fits  → {OUT_DIR}/fit_summary.json")


if __name__ == "__main__":
    main()
