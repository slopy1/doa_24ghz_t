#!/usr/bin/env python3
"""
plot_runs.py — quick-look plots for DoA run CSVs with sidecar JSONs.

Unlike analyze_arm_vs_fpga.py (which does rigorous ARM-vs-FPGA pairing via
runs.yaml), this script is for "show me what's in these files" exploration.
Load any set of aoa_*.csv files, plot each one's time series + histogram,
and make a combined overlay for quick visual comparison.

Usage:
    python3 scripts/plot_runs.py
        - Plots every data/aoa_*.csv that has a sidecar JSON

    python3 scripts/plot_runs.py data/aoa_smoketest_*.csv
        - Plots a specific set (shell expands the glob)

    python3 scripts/plot_runs.py file1.csv file2.csv
        - Plots explicit files

Outputs (in results/quicklook/):
    <run_stem>.png   — per-run time series + histogram + metadata title
    overlay.png      — all non-empty runs overlaid on one time axis
    summary.txt      — text table of rows/mean/std/rate for every run
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
OUT_DIR = REPO / "results" / "quicklook"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@dataclass
class RunData:
    csv_path: Path
    timestamps: np.ndarray
    angles: np.ndarray
    meta: dict  # sidecar JSON contents, or {} if missing

    @property
    def name(self) -> str:
        return self.csv_path.stem

    @property
    def seconds(self) -> np.ndarray:
        if len(self.timestamps) == 0:
            return np.array([])
        t0 = self.timestamps[0]
        return np.array([(t - t0).total_seconds() for t in self.timestamps])


def angle_from_label(label: str | None) -> float | None:
    """Parse a label like '50deg' or '90' into a float angle. None if no match."""
    if not label:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)", str(label))
    return float(m.group(1)) if m else None


def load_run(csv_path: Path) -> RunData | None:
    ts_list: list[datetime] = []
    ang_list: list[float] = []
    try:
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_list.append(datetime.fromisoformat(row["timestamp"]))
                ang_list.append(float(row["aoa_deg"]))
    except (OSError, ValueError, KeyError) as e:
        print(f"[warn] cannot load {csv_path.name}: {e}")
        return None

    meta: dict = {}
    json_path = csv_path.with_suffix(".json")
    if json_path.exists():
        try:
            with json_path.open() as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    return RunData(
        csv_path=csv_path,
        timestamps=np.array(ts_list),
        angles=np.array(ang_list, dtype=float),
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def _title_line(run: RunData) -> str:
    parts = [run.name]
    meta = run.meta
    if meta:
        cal = meta.get("calibration_deg")
        if isinstance(cal, (int, float)):
            parts.append(f"cal={cal:+.2f}°")
        parts.append(f"{meta.get('rows', len(run.angles))} rows")
        rate = meta.get("rate_hz")
        if isinstance(rate, (int, float)) and rate > 0:
            parts.append(f"{rate:.2f} Hz")
        dur = meta.get("duration_s")
        if isinstance(dur, (int, float)) and dur > 0:
            parts.append(f"{dur:.1f}s")
        label = meta.get("label")
        if label:
            parts.append(f"label={label}")
    return "  ·  ".join(parts)


def plot_single_run(run: RunData) -> Path | None:
    """Time series (top) + histogram (bottom) for one run. Skips empty runs."""
    n = len(run.angles)
    if n == 0:
        return None

    mean = float(np.mean(run.angles))
    std = float(np.std(run.angles, ddof=1)) if n > 1 else 0.0
    median = float(np.median(run.angles))

    fig, (ax_ts, ax_hist) = plt.subplots(
        2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [2, 1]}
    )

    # --- Time series ---
    t = run.seconds
    ax_ts.plot(
        t, run.angles, marker=".", linestyle="-", markersize=4,
        alpha=0.7, color="#1f77b4",
    )
    ax_ts.axhline(
        mean, linestyle="--", color="#d62728", alpha=0.8,
        label=f"mean = {mean:.1f}°",
    )
    if t.size > 0:
        ax_ts.fill_between(
            [t.min(), t.max()], mean - std, mean + std,
            alpha=0.15, color="#d62728", label=f"±1σ ({std:.2f}°)",
        )
    # If the label encodes a nominal angle, draw it as a reference line.
    nominal = angle_from_label(run.meta.get("label"))
    if nominal is not None:
        ax_ts.axhline(
            nominal, linestyle=":", color="#2ca02c", alpha=0.8,
            label=f"nominal = {nominal:.0f}°",
        )
    ax_ts.set_xlabel("Time since run start (s)")
    ax_ts.set_ylabel("Estimated angle (°)")
    ax_ts.legend(loc="best", fontsize=9)
    ax_ts.grid(alpha=0.3)
    ax_ts.set_title(_title_line(run), fontsize=9)

    # --- Histogram ---
    bins = min(40, max(10, n // 5))
    ax_hist.hist(run.angles, bins=bins, color="#1f77b4", alpha=0.7)
    ax_hist.axvline(mean, linestyle="--", color="#d62728", alpha=0.8, label=f"mean {mean:.1f}°")
    ax_hist.axvline(median, linestyle=":", color="#9467bd", alpha=0.8, label=f"median {median:.1f}°")
    if nominal is not None:
        ax_hist.axvline(nominal, linestyle=":", color="#2ca02c", alpha=0.8)
    ax_hist.set_xlabel("Estimated angle (°)")
    ax_hist.set_ylabel("Count")
    ax_hist.legend(loc="best", fontsize=8)
    ax_hist.grid(alpha=0.3)

    fig.tight_layout()
    out = OUT_DIR / f"{run.name}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_overlay(runs: list[RunData]) -> Path | None:
    """All non-empty runs overlaid, relative to each run's own start."""
    non_empty = [r for r in runs if len(r.angles) > 0]
    if not non_empty:
        return None

    fig, ax = plt.subplots(figsize=(11, 5))
    colors = plt.cm.tab10.colors
    for i, run in enumerate(non_empty):
        meta = run.meta
        label_bits = []
        label = meta.get("label")
        if label:
            label_bits.append(str(label))
        label_bits.append(str(meta.get("mode", "?")))
        label_bits.append(str(meta.get("algorithm", "?")))
        rate = meta.get("rate_hz")
        if isinstance(rate, (int, float)) and rate > 0:
            label_bits.append(f"{rate:.2f}Hz")
        label_bits.append(f"n={len(run.angles)}")
        ax.plot(
            run.seconds, run.angles,
            marker=".", linestyle="-", markersize=3, alpha=0.6,
            color=colors[i % len(colors)],
            label=" ".join(label_bits),
        )

    ax.set_xlabel("Time since individual run start (s)")
    ax.set_ylabel("Estimated angle (°)")
    ax.set_title(f"Time series overlay — {len(non_empty)} runs")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = OUT_DIR / "overlay.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def write_summary(runs: list[RunData]) -> Path:
    lines = [
        "Quicklook summary",
        "=" * 92,
        f"{'run':<58} {'rows':>6} {'mean':>9} {'std':>8} {'rate':>9}",
        "-" * 92,
    ]
    for run in runs:
        n = len(run.angles)
        if n > 0:
            mean = float(np.mean(run.angles))
            std = float(np.std(run.angles, ddof=1)) if n > 1 else 0.0
            rate = run.meta.get("rate_hz")
            rate_str = f"{rate:.2f} Hz" if isinstance(rate, (int, float)) else "?"
            lines.append(
                f"{run.name:<58} {n:>6} {mean:>8.2f}° {std:>7.2f}° {rate_str:>9}"
            )
        else:
            lines.append(f"{run.name:<58} {'EMPTY':>6}")
    text = "\n".join(lines) + "\n"
    path = OUT_DIR / "summary.txt"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        paths = sorted(DATA_DIR.glob("aoa_*.csv"))

    if not paths:
        print("No CSVs found to plot.")
        return 1

    runs: list[RunData] = []
    for p in paths:
        if not p.exists():
            print(f"[warn] missing: {p}")
            continue
        r = load_run(p)
        if r:
            runs.append(r)

    if not runs:
        print("No runs loaded.")
        return 1

    print(f"Loaded {len(runs)} runs")
    for run in runs:
        out = plot_single_run(run)
        if out:
            print(f"  [ok ] {run.name}  ({len(run.angles)} rows) → {out.name}")
        else:
            print(f"  [empty] {run.name}  (0 rows — no plot)")

    overlay = plot_overlay(runs)
    if overlay:
        print(f"Overlay → {overlay.name}")

    summary = write_summary(runs)
    print(f"Summary → {summary}")

    print(f"\nAll outputs in: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
