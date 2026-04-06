#!/usr/bin/env python3
"""
Dataset Analysis Pipeline

Runs all DOA methods on the collected dataset and generates thesis figures/tables.

Usage:
    python scripts/analyze_dataset.py
    python scripts/analyze_dataset.py --dataset data/experiment1

Output:
    results/figures/figure1_error_cdf.png
    results/figures/figure2_true_vs_estimated.png
    results/figures/figure3_error_by_snr.png
    results/tables/table1_metrics.csv
"""

import argparse
import sys
import os
from datetime import datetime
import csv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import matplotlib
matplotlib.use('Agg')

from doa24.io_hdf5 import load_all_captures
from doa24.baselines import estimate_doa_phase_diff, estimate_doa_music, estimate_doa_mvdr
from doa24.bayesian import SimpleBayesianDOA
from doa24.calibration import apply_calibration
from doa24.config import load_receiver_calibration
from doa24.metrics import compute_metrics
from doa24.plotting import plot_error_cdf, plot_true_vs_estimated, plot_error_by_snr


def run_analysis(dataset_dir='data', output_dir='results'):
    """
    Run full analysis pipeline.
    
    Args:
        dataset_dir: Directory containing HDF5 captures
        output_dir: Output directory for figures/tables
    """
    print(f"\n{'#'*70}")
    print("# DOA ANALYSIS PIPELINE")
    print(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")
    
    # Load data
    captures = load_all_captures(dataset_dir)

    # Load static calibration (if available)
    cal = load_receiver_calibration()
    print("\nStatic calibration:")
    print(f"  phase_cal_deg: {cal.phase_offset_deg:.2f}°")
    print(f"  gain_ratio:    {cal.gain_ratio:.4f}")
    print(f"  source:        {cal.source}")
    
    if len(captures) == 0:
        print(f"\n⚠️ No captures found in {dataset_dir}/")
        print("Run 'python scripts/collect_dataset.py' first.")
        return None
    
    # Filter to labeled captures
    labeled = [c for c in captures if c['angle'] != 0 or True]  # Keep all
    print(f"\nProcessing {len(labeled)} captures...")
    
    # Angle distribution
    angles = [c['angle'] for c in labeled]
    unique_angles = sorted(set(angles))
    print(f"Angles: {unique_angles}")
    print(f"Counts: {[angles.count(a) for a in unique_angles]}")
    
    # Results storage
    results = {
        'phase_diff': [],
        'music': [],
        'mvdr': [],
        'bayesian': []
    }
    
    # Process each capture
    for i, cap in enumerate(labeled):
        true_angle = cap['angle']
        ch0, ch1 = cap['ch0'], cap['ch1']
        
        # Use subset for speed
        n_use = min(50000, len(ch0))
        ch0 = ch0[:n_use]
        ch1 = ch1[:n_use]

        # Apply static calibration once up front.
        ch0, ch1 = apply_calibration(ch0, ch1, cal.phase_offset_rad, cal.gain_ratio)
        
        # Baseline estimates
        est_phase = estimate_doa_phase_diff(ch0, ch1)
        est_music = estimate_doa_music(ch0, ch1)
        est_mvdr = estimate_doa_mvdr(ch0, ch1)
        
        # Bayesian estimate
        estimator = SimpleBayesianDOA(d_lambda=0.5, drift_std=0.01)
        streaming_results = estimator.process_streaming(ch0, ch1, snapshot_size=1024)
        est_bayesian = streaming_results[-1]['theta'] if streaming_results else 0
        
        # Store results
        snr = cap['snr_label']
        results['phase_diff'].append({'true': true_angle, 'est': est_phase, 'snr': snr})
        results['music'].append({'true': true_angle, 'est': est_music, 'snr': snr})
        results['mvdr'].append({'true': true_angle, 'est': est_mvdr, 'snr': snr})
        results['bayesian'].append({'true': true_angle, 'est': est_bayesian, 'snr': snr})
        
        if (i + 1) % 10 == 0:
            print(f"  Processed {i+1}/{len(labeled)}")
    
    # Create output directories
    fig_dir = os.path.join(output_dir, 'figures')
    table_dir = os.path.join(output_dir, 'tables')
    os.makedirs(fig_dir, exist_ok=True)
    os.makedirs(table_dir, exist_ok=True)
    
    # Generate figures
    print(f"\n{'='*70}")
    print("GENERATING FIGURES")
    print(f"{'='*70}")
    
    plot_error_cdf(results, os.path.join(fig_dir, 'figure1_error_cdf.png'))
    plot_true_vs_estimated(results, os.path.join(fig_dir, 'figure2_true_vs_estimated.png'))
    plot_error_by_snr(results, os.path.join(fig_dir, 'figure3_error_by_snr.png'))
    
    # Generate table
    print(f"\n{'='*70}")
    print("TABLE 1: DOA Estimation Performance Metrics")
    print(f"{'='*70}")
    
    labels = {
        'phase_diff': 'Phase Difference',
        'music': 'MUSIC',
        'mvdr': 'MVDR',
        'bayesian': 'Bayesian'
    }
    
    print(f"{'Method':<20} {'Median':<10} {'95th %':<10} {'Mean':<10} {'Std':<10} {'Catast.':<10}")
    print("-" * 70)
    
    table_data = []
    for method, data in results.items():
        true_vals = [d['true'] for d in data]
        est_vals = [d['est'] for d in data]
        m = compute_metrics(true_vals, est_vals)
        
        print(f"{labels[method]:<20} "
              f"{m['median_error']:<10.1f} "
              f"{m['p95_error']:<10.1f} "
              f"{m['mean_error']:<10.1f} "
              f"{m['std_error']:<10.1f} "
              f"{m['catastrophic_rate']:<10.1f}%")
        
        table_data.append({'method': labels[method], **m})
    
    print("=" * 70)
    
    # Save CSV
    csv_path = os.path.join(table_dir, 'table1_metrics.csv')
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['method', 'median_error', 'p95_error',
                                                'mean_error', 'std_error', 'max_error',
                                                'catastrophic_rate', 'n_samples'])
        writer.writeheader()
        writer.writerows(table_data)
    print(f"\n✓ Saved: {csv_path}")
    
    # Summary
    print(f"\n{'='*70}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*70}")
    print(f"Figures: {fig_dir}/")
    print(f"Tables:  {table_dir}/")
    print(f"{'='*70}")
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Analyze DOA dataset')
    parser.add_argument('--dataset', '-d', default='data',
                        help='Dataset directory (default: data)')
    parser.add_argument('--output', '-o', default='results',
                        help='Output directory (default: results)')
    
    args = parser.parse_args()
    run_analysis(args.dataset, args.output)


if __name__ == "__main__":
    main()

