#!/usr/bin/env python3
"""
ARM vs FPGA DoA precision comparison.

Loads CSVs from data/ using data/runs.yaml as the source of truth for which
runs to include and what the nominal source angle was. Computes per-run stats
using a policy function that the user fills in (see compute_run_stats below),
then pairs ARM/FPGA runs by `group` and reports bias, spread, and error vs
the nominal angle.

Outputs:
    results/arm_vs_fpga/stats.csv           — one row per kept run
    results/arm_vs_fpga/pairs.csv           — one row per (ARM, FPGA) pair
    results/arm_vs_fpga/hist_<group>.png    — histogram overlay per group
    results/arm_vs_fpga/timeseries_<group>.png — time series per group

Usage:
    python3 scripts/analyze_arm_vs_fpga.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
OUT_DIR = REPO / "results" / "arm_vs_fpga"
RUNS_YAML = DATA_DIR / "runs.yaml"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@dataclass
class Run:
    filename: str
    mode: str            # "ARM" or "FPGA"
    algo: str            # "MUSIC" or "ROOTMUSIC"
    group: str | None
    true_angle_deg: float
    true_angle_uncertainty_deg: float
    warmup_seconds: float
    calibration_deg: float | None = None  # from sidecar JSON, if present
    source: str = "yaml"                  # "yaml" (in runs.yaml) or "auto" (discovered via sidecar)
    timestamps: np.ndarray = field(default_factory=lambda: np.array([]))
    angles_deg: np.ndarray = field(default_factory=lambda: np.array([]))

    @property
    def seconds_from_start(self) -> np.ndarray:
        if self.timestamps.size == 0:
            return np.array([])
        t0 = self.timestamps[0]
        return np.array([(t - t0).total_seconds() for t in self.timestamps])


def parse_mode_algo(filename: str) -> tuple[str, str]:
    """Extract (mode, algo) from a CSV filename.

    Two formats are supported:
        aoa_<MODE>_<ALGO>_<YYYYMMDD>_<HHMMSS>.csv           — legacy (5 parts)
        aoa_<LABEL>_<MODE>_<ALGO>_<YYYYMMDD>_<HHMMSS>.csv   — labeled (6 parts)

    Timestamp is always the last two underscore-separated parts, so MODE is
    at index -4 and ALGO is at index -3 in both cases.
    """
    parts = filename.removesuffix(".csv").split("_")
    if len(parts) < 5:
        raise ValueError(f"unexpected filename format: {filename}")
    return parts[-4], parts[-3]


def load_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    ts_list: list[datetime] = []
    ang_list: list[float] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_list.append(datetime.fromisoformat(row["timestamp"]))
            ang_list.append(float(row["aoa_deg"]))
    return np.array(ts_list), np.array(ang_list, dtype=float)


def load_sidecar(csv_name: str) -> dict | None:
    """Load the sidecar JSON metadata for a CSV, if present.

    Sidecar naming: aoa_foo.csv → aoa_foo.json (same stem, .json suffix).
    Returns None if the sidecar doesn't exist or can't be parsed.
    """
    json_path = DATA_DIR / (csv_name[:-4] + ".json")
    if not json_path.exists():
        return None
    try:
        with json_path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def angle_from_label(label: str | None) -> float | None:
    """Parse a campaign label like '50deg' or '50-degrees' into a float angle.

    Returns None if the label doesn't start with a number. Used to populate
    true_angle_deg automatically for auto-discovered runs.
    """
    if not label:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)", label)
    return float(m.group(1)) if m else None


def load_runs() -> list[Run]:
    with RUNS_YAML.open() as f:
        meta = yaml.safe_load(f)
    defaults = meta.get("defaults", {})
    runs_meta = meta.get("runs", {}) or {}

    kept: list[Run] = []

    # 1. Explicit entries from runs.yaml. YAML fields take precedence over
    #    sidecar JSON fields (so manual overrides keep working).
    for filename, cfg in runs_meta.items():
        if not cfg.get("keep", False):
            continue
        mode, algo = parse_mode_algo(filename)
        ts, ang = load_csv(DATA_DIR / filename)
        sidecar = load_sidecar(filename) or {}
        group = cfg.get("group") or sidecar.get("label") or None
        run = Run(
            filename=filename,
            mode=mode,
            algo=algo,
            group=group,
            true_angle_deg=cfg.get("true_angle_deg", defaults.get("true_angle_deg")),
            true_angle_uncertainty_deg=cfg.get(
                "true_angle_uncertainty_deg",
                defaults.get("true_angle_uncertainty_deg", 0.0),
            ),
            warmup_seconds=cfg.get(
                "warmup_seconds", defaults.get("warmup_seconds", 0.0)
            ),
            calibration_deg=sidecar.get("calibration_deg"),
            source="yaml",
            timestamps=ts,
            angles_deg=ang,
        )
        kept.append(run)

    # 2. Auto-discover campaign runs not in runs.yaml.
    #    A CSV is auto-included iff:
    #      - it is not already listed in runs.yaml (explicit keep:false stays respected)
    #      - it has a sidecar JSON
    #      - the sidecar has a non-empty `label` (the whole point of auto-discovery
    #        is to pick up runs the operator deliberately tagged)
    #      - row count >= 10 (reject smoketest scraps and hardware-failure stubs)
    #    If the label looks like "<N>deg", true_angle_deg is set from the label.
    #    Otherwise it falls back to the YAML default.
    yaml_files = set(runs_meta.keys())
    for csv_path in sorted(DATA_DIR.glob("aoa_*.csv")):
        if csv_path.name in yaml_files:
            continue
        sidecar = load_sidecar(csv_path.name)
        if not sidecar or not sidecar.get("label"):
            continue
        if int(sidecar.get("rows", 0)) < 10:
            continue
        try:
            mode, algo = parse_mode_algo(csv_path.name)
            ts, ang = load_csv(csv_path)
        except (IndexError, ValueError) as e:
            print(f"[warn] skipping auto-discovered {csv_path.name}: {e}")
            continue
        label = sidecar["label"]
        inferred_angle = angle_from_label(label)
        run = Run(
            filename=csv_path.name,
            mode=mode,
            algo=algo,
            group=label,
            true_angle_deg=(
                inferred_angle
                if inferred_angle is not None
                else defaults.get("true_angle_deg", 90.0)
            ),
            true_angle_uncertainty_deg=defaults.get("true_angle_uncertainty_deg", 0.0),
            warmup_seconds=defaults.get("warmup_seconds", 0.0),
            calibration_deg=sidecar.get("calibration_deg"),
            source="auto",
            timestamps=ts,
            angles_deg=ang,
        )
        kept.append(run)

    return kept


# ---------------------------------------------------------------------------
# USER CONTRIBUTION POINT — stats policy
# ---------------------------------------------------------------------------
#
# This is the one function where your judgment shapes every downstream number
# in the thesis. The decisions you make here are:
#
#   1. WARMUP TRIM. BladeRF AGC / PLL settles in the first few seconds.
#      run.warmup_seconds is set to 5.0 in runs.yaml — should stats discard
#      all samples before that mark? Keep them and flag them? The trade-off:
#      trimming makes std/bias honest but shrinks small runs further.
#
#   2. OUTLIER REJECTION. Post-v2-fix ROOTMUSIC has occasional spikes from
#      noise eigenvalue flips. Options:
#        - none (most honest, messiest)
#        - ±N°-from-median clip (simple, robust)
#        - M-sigma rejection (assumes Gaussian — DoA angles often aren't)
#        - IQR-based (distribution-free)
#      For a thesis, being able to JUSTIFY the choice matters more than
#      picking the "best" one. Pick one and document why in the return dict.
#
#   3. CENTRAL TENDENCY. Mean vs median vs circular mean. Circular mean
#      matters only if your angles wrap across 0°/360° or 180°. For this
#      dataset, everything is between ~30° and ~160°, well away from wrap —
#      so linear mean is defensible, but state that assumption.
#
#   4. SPREAD. std vs MAD (median absolute deviation) vs IQR. std is what
#      thesis readers expect; MAD is more robust to the ROOTMUSIC spikes.
#      You can return both.
#
# Return a dict with AT LEAST: n_used, n_total, mean_deg, std_deg, bias_deg.
# Add whatever other fields you want (median, mad, p5, p95, outlier_count...).
# bias_deg is (mean_deg - run.true_angle_deg) — signed.
#
# Keep it to ~8-12 lines of real logic. If you find yourself writing more,
# you're probably over-engineering.


def compute_run_stats(run: Run) -> dict:
    """Reduce a run's raw angle samples to a stats dict.

    Policy (user-chosen):
      1. Trim samples from the first `run.warmup_seconds` (default 1s) to drop
         AGC/PLL transients. Keep everything after.
      2. No outlier rejection — keep messy steady-state as-is.
      3. Linear mean (angles stay between ~30° and ~160°, no wrap concerns).
      4. Report both std (reader intuition) and MAD (robust to the spikes).

    Also reports *folded* stats for 2-element ULA front-back ambiguity.
    Angles θ and 180°−θ produce identical phase differences on a 2-element
    array, so the estimator flips between mirror modes near broadside. Folding
    `θ_folded = θ if θ ≤ 90° else 180° − θ` collapses both lobes onto [0°, 90°]
    and reports "angular offset from broadside." Raw stats kept alongside so
    the bimodality is still visible in the data.
    """
    t_sec = run.seconds_from_start
    angles = run.angles_deg
    n_total = len(angles)

    mask = t_sec >= run.warmup_seconds
    used = angles[mask]
    n_used = len(used)

    # Raw (unfolded) stats — exposes the bimodality honestly.
    mean = float(np.mean(used))
    std = float(np.std(used, ddof=1)) if n_used > 1 else 0.0
    mad = float(np.median(np.abs(used - np.median(used)))) if n_used > 0 else 0.0

    # Folded stats — resolves ULA ambiguity, meaningful central tendency.
    folded = np.where(used <= 90.0, used, 180.0 - used)
    true_folded = run.true_angle_deg if run.true_angle_deg <= 90.0 else 180.0 - run.true_angle_deg
    mean_f = float(np.mean(folded))
    std_f = float(np.std(folded, ddof=1)) if n_used > 1 else 0.0
    mad_f = float(np.median(np.abs(folded - np.median(folded)))) if n_used > 0 else 0.0

    return {
        "n_total": n_total,
        "n_used": n_used,
        # raw
        "mean_deg": mean,
        "median_deg": float(np.median(used)) if n_used > 0 else 0.0,
        "std_deg": std,
        "mad_deg": mad,
        "bias_deg": mean - run.true_angle_deg,
        # folded (ULA-ambiguity-aware)
        "mean_folded_deg": mean_f,
        "std_folded_deg": std_f,
        "mad_folded_deg": mad_f,
        "bias_folded_deg": mean_f - true_folded,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_stats_csv(runs_with_stats: list[tuple[Run, dict]]) -> Path:
    path = OUT_DIR / "stats.csv"
    # Union of keys so extra fields the user adds all show up.
    extra_keys: list[str] = []
    seen: set[str] = set()
    for _, s in runs_with_stats:
        for k in s:
            if k not in seen:
                seen.add(k)
                extra_keys.append(k)
    base_cols = [
        "filename", "mode", "algo", "group", "true_angle_deg",
        "calibration_deg", "source",
    ]
    cols = base_cols + extra_keys
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for run, stats in runs_with_stats:
            row = [
                run.filename,
                run.mode,
                run.algo,
                run.group or "",
                run.true_angle_deg,
                run.calibration_deg if run.calibration_deg is not None else "",
                run.source,
            ]
            row += [stats.get(k, "") for k in extra_keys]
            w.writerow(row)
    return path


def pair_runs(runs_with_stats: list[tuple[Run, dict]]) -> list[dict]:
    by_group: dict[str, dict[str, tuple[Run, dict]]] = {}
    for run, stats in runs_with_stats:
        if not run.group:
            continue
        by_group.setdefault(run.group, {})[run.mode] = (run, stats)

    pairs = []
    for group, members in by_group.items():
        if "ARM" not in members or "FPGA" not in members:
            print(f"[warn] group {group!r} missing ARM or FPGA — skipping pair")
            continue
        arm_run, arm_stats = members["ARM"]
        fpga_run, fpga_stats = members["FPGA"]
        pairs.append(
            {
                "group": group,
                "algo": arm_run.algo,
                "true_angle_deg": arm_run.true_angle_deg,
                "arm_mean_raw": arm_stats["mean_deg"],
                "fpga_mean_raw": fpga_stats["mean_deg"],
                "arm_std_raw": arm_stats["std_deg"],
                "fpga_std_raw": fpga_stats["std_deg"],
                "arm_mean_folded": arm_stats["mean_folded_deg"],
                "fpga_mean_folded": fpga_stats["mean_folded_deg"],
                "arm_std_folded": arm_stats["std_folded_deg"],
                "fpga_std_folded": fpga_stats["std_folded_deg"],
                "delta_mean_folded": fpga_stats["mean_folded_deg"]
                - arm_stats["mean_folded_deg"],
                "spread_ratio_folded": (
                    fpga_stats["std_folded_deg"] / arm_stats["std_folded_deg"]
                    if arm_stats["std_folded_deg"] > 0
                    else float("inf")
                ),
            }
        )
    return pairs


def write_pairs_csv(pairs: list[dict]) -> Path:
    path = OUT_DIR / "pairs.csv"
    if not pairs:
        path.write_text("no pairs\n")
        return path
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pairs[0].keys()))
        w.writeheader()
        w.writerows(pairs)
    return path


def plot_multi_algo_summary(pairs: list[dict], threshold_deg: float = 5.0) -> Path | None:
    """Headline figure: ARM vs FPGA agreement across all pair groups.

    One bar cluster per pair (typically one per algorithm × position). Top
    panel shows folded mean ± std for ARM and FPGA side-by-side. Bottom panel
    shows |Δmean| with a horizontal "acceptable agreement" threshold line.

    When Path B data is collected for the other algorithms (MVDR, PhaseDiff),
    new rows automatically appear here with no script changes.
    """
    if not pairs:
        return None

    labels = [f"{p['algo']}\n({p['group']})" for p in pairs]
    x = np.arange(len(pairs))
    width = 0.38

    arm_mean = np.array([p["arm_mean_folded"] for p in pairs])
    fpga_mean = np.array([p["fpga_mean_folded"] for p in pairs])
    arm_std = np.array([p["arm_std_folded"] for p in pairs])
    fpga_std = np.array([p["fpga_std_folded"] for p in pairs])
    delta = np.abs(np.array([p["delta_mean_folded"] for p in pairs]))

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(max(6, 1.8 * len(pairs) + 2), 7),
        gridspec_kw={"height_ratios": [2, 1]}, sharex=True,
    )

    ax_top.bar(
        x - width / 2, arm_mean, width, yerr=arm_std, capsize=4,
        label="ARM", color="#1f77b4", alpha=0.85,
    )
    ax_top.bar(
        x + width / 2, fpga_mean, width, yerr=fpga_std, capsize=4,
        label="FPGA", color="#ff7f0e", alpha=0.85,
    )
    ax_top.set_ylabel("Folded angle — offset from broadside (deg)")
    ax_top.set_title("ARM vs FPGA DoA estimation — ULA-ambiguity-folded mean ± std")
    ax_top.legend(loc="upper right")
    ax_top.grid(axis="y", alpha=0.3)

    colors = ["#2ca02c" if d <= threshold_deg else "#d62728" for d in delta]
    ax_bot.bar(x, delta, width * 1.4, color=colors, alpha=0.85)
    ax_bot.axhline(
        threshold_deg, linestyle="--", color="k", alpha=0.5,
        label=f"{threshold_deg:.0f}° agreement threshold",
    )
    ax_bot.set_ylabel("|Δmean|  (deg)")
    ax_bot.set_xticks(x)
    ax_bot.set_xticklabels(labels)
    ax_bot.legend(loc="upper right")
    ax_bot.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    out = OUT_DIR / "multi_algo_summary.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def write_summary_md(pairs: list[dict]) -> Path:
    """Render a markdown summary table for easy thesis paste."""
    path = OUT_DIR / "summary.md"
    lines = [
        "# ARM vs FPGA DoA estimation — summary",
        "",
        "All values are folded to resolve 2-element ULA front-back ambiguity",
        "(θ → min(θ, 180°−θ)), i.e. angular offset from broadside in [0°, 90°].",
        "",
        "| Algo | Group | μ ARM | μ FPGA | \\|Δμ\\| | σ ARM | σ FPGA | σ ratio |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in pairs:
        lines.append(
            f"| {p['algo']} | {p['group']} | "
            f"{p['arm_mean_folded']:.2f}° | {p['fpga_mean_folded']:.2f}° | "
            f"{abs(p['delta_mean_folded']):.2f}° | "
            f"{p['arm_std_folded']:.2f}° | {p['fpga_std_folded']:.2f}° | "
            f"{p['spread_ratio_folded']:.2f} |"
        )
    lines.append("")
    path.write_text("\n".join(lines))
    return path


def plot_group(group: str, members: list[tuple[Run, dict]]) -> None:
    # Histogram overlay
    fig, ax = plt.subplots(figsize=(7, 4))
    for run, _stats in members:
        ax.hist(
            run.angles_deg,
            bins=30,
            alpha=0.5,
            label=f"{run.mode} (n={len(run.angles_deg)})",
        )
    true_ang = members[0][0].true_angle_deg
    ax.axvline(true_ang, linestyle="--", color="k", label=f"nominal {true_ang:.0f}°")
    ax.set_xlabel("Estimated angle (deg)")
    ax.set_ylabel("Count")
    ax.set_title(f"{group} — ARM vs FPGA histogram")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / f"hist_{group}.png", dpi=150)
    plt.close(fig)

    # Time series
    fig, ax = plt.subplots(figsize=(8, 4))
    for run, _stats in members:
        ax.plot(
            run.seconds_from_start,
            run.angles_deg,
            marker=".",
            linestyle="-",
            alpha=0.6,
            label=f"{run.mode}",
        )
    ax.axhline(true_ang, linestyle="--", color="k")
    ax.set_xlabel("Time since run start (s)")
    ax.set_ylabel("Estimated angle (deg)")
    ax.set_title(f"{group} — ARM vs FPGA time series")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / f"timeseries_{group}.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = load_runs()
    n_yaml = sum(1 for r in runs if r.source == "yaml")
    n_auto = sum(1 for r in runs if r.source == "auto")
    print(f"Loaded {len(runs)} kept runs  ({n_yaml} from runs.yaml, {n_auto} auto-discovered via sidecar)")

    runs_with_stats: list[tuple[Run, dict]] = []
    for run in runs:
        try:
            stats = compute_run_stats(run)
        except NotImplementedError as e:
            print(f"[error] {e}")
            return 1
        runs_with_stats.append((run, stats))
        cal_str = f"cal={run.calibration_deg:+.2f}" if run.calibration_deg is not None else "cal=?"
        print(
            f"  [{run.source}] {run.filename}  group={run.group or '-'}  {cal_str}\n"
            f"    raw    mean={stats['mean_deg']:6.2f}  "
            f"std={stats['std_deg']:5.2f}  mad={stats['mad_deg']:5.2f}  "
            f"bias={stats['bias_deg']:+6.2f}  n={stats['n_used']}/{stats['n_total']}\n"
            f"    folded mean={stats['mean_folded_deg']:6.2f}  "
            f"std={stats['std_folded_deg']:5.2f}  mad={stats['mad_folded_deg']:5.2f}  "
            f"bias={stats['bias_folded_deg']:+6.2f}"
        )

    stats_path = write_stats_csv(runs_with_stats)
    print(f"Wrote {stats_path}")

    pairs = pair_runs(runs_with_stats)
    pairs_path = write_pairs_csv(pairs)
    print(f"Wrote {pairs_path}")
    for p in pairs:
        print(
            f"  [{p['group']}] {p['algo']} (folded, offset from broadside)\n"
            f"    ARM  = {p['arm_mean_folded']:6.2f}° ± {p['arm_std_folded']:5.2f}°\n"
            f"    FPGA = {p['fpga_mean_folded']:6.2f}° ± {p['fpga_std_folded']:5.2f}°\n"
            f"    Δ    = {p['delta_mean_folded']:+.2f}°   "
            f"spread(FPGA/ARM) = {p['spread_ratio_folded']:.2f}"
        )

    # Per-group diagnostic plots (hist + time series).
    by_group: dict[str, list[tuple[Run, dict]]] = {}
    for rs in runs_with_stats:
        if rs[0].group:
            by_group.setdefault(rs[0].group, []).append(rs)
    for group, members in by_group.items():
        plot_group(group, members)
        print(f"Wrote plots for group {group!r}")

    # Headline multi-algo summary figure + markdown table.
    summary_path = plot_multi_algo_summary(pairs)
    if summary_path:
        print(f"Wrote {summary_path}")
    md_path = write_summary_md(pairs)
    print(f"Wrote {md_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
