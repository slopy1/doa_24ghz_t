#!/bin/bash
# One-command reproducer for thesis results
#
# Usage:
#   ./run.sh              # Generate figures from existing data
#   ./run.sh collect      # Collect new dataset
#   ./run.sh analyze      # Run analysis only
#   ./run.sh test         # Run with synthetic data

set -e
cd "$(dirname "$0")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "DOA-24GHz Thesis Pipeline"
echo "=========================================="

case "${1:-analyze}" in
    collect)
        echo -e "${YELLOW}Collecting dataset...${NC}"
        echo "This will run the full experiment matrix."
        echo "Make sure TX is running and positioned correctly."
        read -p "Continue? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            for angle in -60 -45 -30 -15 0 15 30 45 60; do
                echo -e "${GREEN}Collecting angle=${angle}°, distance=2m, SNR=high${NC}"
                python scripts/collect_dataset.py --angle $angle --distance 2 --snr high --reps 10
                echo -e "${GREEN}Collecting angle=${angle}°, distance=5m, SNR=low${NC}"
                python scripts/collect_dataset.py --angle $angle --distance 5 --snr low --reps 10
            done
        fi
        ;;
    
    analyze)
        echo -e "${GREEN}Running analysis pipeline...${NC}"
        python scripts/analyze_dataset.py
        ;;
    
    test)
        echo -e "${YELLOW}Running with synthetic data...${NC}"
        # Generate some synthetic captures for testing
        for angle in -30 0 30; do
            python scripts/collect_dataset.py --angle $angle --distance 2 --snr high --reps 3
        done
        python scripts/analyze_dataset.py
        ;;
    
    figures)
        echo -e "${GREEN}Regenerating figures...${NC}"
        python scripts/make_figures.py
        ;;
    
    *)
        echo "Usage: ./run.sh [collect|analyze|test|figures]"
        echo ""
        echo "Commands:"
        echo "  collect  - Run full data collection"
        echo "  analyze  - Run analysis on existing data"
        echo "  test     - Generate synthetic data and analyze"
        echo "  figures  - Regenerate figures only"
        ;;
esac

echo ""
echo -e "${GREEN}Done!${NC}"
echo "Results in: results/figures/ and results/tables/"

