#!/usr/bin/env fish
# Capture a spectrum at the campaign tuning, both with nRF off and with nRF on.
# Plot locally so you can see what's actually in the bandpass.

set -l KRIA ubuntu@192.168.1.101
set -l OUT_DIR ~/doa_24ghz_thesis/results/spectrum_sweep_(date +%Y%m%d_%H%M%S)
mkdir -p $OUT_DIR

# Deploy script to Kria
scp ~/doa_24ghz_thesis/kv260_headless/spectrum_sweep.py $KRIA:~/doa/

echo
echo "=== Sweep 1: nRF OFF (background only) ==="
echo "Make sure the nRF is in stop_tx state."
read -P "nRF off and quiet? Press enter " __junk

ssh $KRIA "sudo python3 ~/doa/spectrum_sweep.py --freq 2.41895e9 --gain 50 --duration 5 --out /tmp/sweep_off.csv" \
  | tee $OUT_DIR/sweep_off.log
scp $KRIA:/tmp/sweep_off.csv $OUT_DIR/sweep_off.csv

echo
echo "=== Sweep 2: nRF ON (modulated carrier ch 19) ==="
echo "Set nRF: start_channel 19, then start_tx_modulated_carrier."
read -P "nRF transmitting? Press enter " __junk

ssh $KRIA "sudo python3 ~/doa/spectrum_sweep.py --freq 2.41895e9 --gain 50 --duration 5 --out /tmp/sweep_on.csv" \
  | tee $OUT_DIR/sweep_on.log
scp $KRIA:/tmp/sweep_on.csv $OUT_DIR/sweep_on.csv

# Plot locally
python3 ~/doa_24ghz_thesis/scripts/plot_spectrum_compare.py $OUT_DIR

echo
echo "Done. Files in $OUT_DIR/"
/usr/bin/ls -la $OUT_DIR
