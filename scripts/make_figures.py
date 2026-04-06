#!/usr/bin/env python3
"""
Figure Generation Script

Regenerates all thesis figures from the analysis results.
This is the "one command reproducer" for thesis figures.

Usage:
    python scripts/make_figures.py
    python scripts/make_figures.py --dataset data --output results

This script:
1. Loads all captures from data/
2. Runs all DOA methods
3. Generates Figure 1-3 and Table 1
4. Saves outputs to results/figures/ and results/tables/
"""

import argparse
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import the full pipeline from analyze_dataset
from analyze_dataset import run_analysis


def main():
    parser = argparse.ArgumentParser(
        description='Generate thesis figures',
        epilog="""
This is the canonical "reproduce results" script.
Run this after collecting data to regenerate all thesis figures.
        """
    )
    parser.add_argument('--dataset', '-d', default='data',
                        help='Dataset directory')
    parser.add_argument('--output', '-o', default='results',
                        help='Output directory')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("THESIS FIGURE GENERATION")
    print("=" * 60)
    print(f"\nInput:  {args.dataset}/")
    print(f"Output: {args.output}/figures/ and {args.output}/tables/")
    print()
    
    results = run_analysis(args.dataset, args.output)
    
    if results:
        print("\n✓ All figures generated successfully.")
        print("\nGenerated outputs:")
        print(f"  • {args.output}/figures/figure1_error_cdf.png")
        print(f"  • {args.output}/figures/figure2_true_vs_estimated.png")
        print(f"  • {args.output}/figures/figure3_error_by_snr.png")
        print(f"  • {args.output}/tables/table1_metrics.csv")
    else:
        print("\n⚠️ No data to process. Collect data first:")
        print("  python scripts/collect_dataset.py --angle 0 --distance 2 --snr high")


if __name__ == "__main__":
    main()

