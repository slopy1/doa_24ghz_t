# Dataset Directory

This directory contains HDF5 captures for DOA experiments.

## File Naming Convention

```
capture_YYYYMMDD_HHMMSS_angle+XX_distY.Ym_SNR.h5
```

Example: `capture_20241221_153000_angle+30_dist2.0m_high.h5`

## Collecting Data

```bash
# Single capture
python scripts/collect_dataset.py --angle 30 --distance 2 --snr high

# Multiple repetitions
python scripts/collect_dataset.py --angle 30 --distance 2 --snr high --reps 10

# Full experiment matrix (run for each angle/distance)
for angle in -60 -45 -30 -15 0 15 30 45 60; do
    python scripts/collect_dataset.py --angle $angle --distance 2 --snr high --reps 10
    python scripts/collect_dataset.py --angle $angle --distance 5 --snr low --reps 10
done
```

## File Format

Each HDF5 file contains:

### Datasets
- `channel_0`: Complex64 array (RX0 samples)
- `channel_1`: Complex64 array (RX1 samples)

### Attributes
| Attribute | Type | Description |
|-----------|------|-------------|
| `timestamp_utc` | string | ISO timestamp |
| `center_frequency_hz` | float | 2.45e9 |
| `sample_rate_hz` | float | 5e6 |
| `nominal_angle_deg` | int | Ground truth angle |
| `distance_m` | float | TX-RX distance |
| `snr_label` | string | "high" or "low" |

## Data Size Estimate

- 1 second capture: ~40 MB (2 channels × 5M samples × 4 bytes)
- Full matrix (180 captures): ~7.2 GB

## Note on Large Files

Large HDF5 files are NOT committed to git. If you need to share data:

1. Use Git LFS: `git lfs track "*.h5"`
2. Use external storage (Dropbox, Google Drive, etc.)
3. Store a manifest file listing available captures

