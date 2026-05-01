#!/usr/bin/env fish
# calshift_test.fish — Fresh-cal + 90°-only falsification of the
# cal-application asymmetry hypothesis (thesis ch5:14).
#
# Flow:
#   1. Sanity check Kria UIO/udmabuf/EMIO chip names.
#   2. Two back-to-back 10s cals on the wired splitter (extends the
#      Apr-27 → Apr-29 → today time series in ch5:34, and bounds today's
#      within-session reproducibility).
#   3. Typed CAL value pinned via --cal (CAL_FROM_CLI gate).
#   4. Single 90° capture, ARM + FPGA, --filter=none (matches v2 data).
#   5. Parse CSVs, print ARM mean / FPGA mean / Δ so the result is
#      readable on the terminal before you leave the bench.
#
# Decision rule:
#   - Δ ≈ +7° → cal-application asymmetry confirmed; ch5:14 stands.
#   - Δ near 0° → asymmetry interpretation is wrong; cal staleness
#     was driving the v2 offset; ch5 needs revision.

set -l RUN_BASE ~/doa_24ghz_thesis/data
set -l SESSION (date +"%Y%m%d_%H%M%S")_calshift
set -gx RUN_DIR $RUN_BASE/run_$SESSION
mkdir -p $RUN_DIR
echo "RUN_DIR = $RUN_DIR"

# Defaults — same as resume_campaign.fish, --filter=none for v2 parity.
set -q FREQ;     or set -gx FREQ     2.41895e9
set -q CAL_FREQ; or set -gx CAL_FREQ 2.41895e9
set -q GAIN;     or set -gx GAIN     50
set -q DUR;      or set -gx DUR      70
set -q KRIA;     or set -gx KRIA     ubuntu@192.168.1.101

echo "  FREQ      = $FREQ"
echo "  CAL_FREQ  = $CAL_FREQ"
echo "  GAIN      = $GAIN dB"
echo "  DUR       = $DUR sec (single 90° capture, ARM + FPGA)"
echo "  KRIA      = $KRIA"

# --- 1. Sanity check ---
echo
echo "=== Sanity check on $KRIA ==="
ssh $KRIA "uptime; echo '--- UIO ---'; ls /sys/class/uio/; echo '--- udmabuf ---'; ls /sys/class/u-dma-buf/ 2>&1; echo '--- chip names ---'; for u in /sys/class/uio/uio*/name; do cat \"\$u\"; done"
echo
read -P "Looks ok (dma_safe_ctrl_regs present, u-dma-buf alive)? [y/N] " ok
if test "$ok" != "y"
    echo "Bail. Re-run bench_bringup.sh on Kria first:"
    echo "  ssh $KRIA 'sudo bash ~/doa/bench_bringup.sh'"
    exit 1
end

# --- 2. Two back-to-back cals on wired splitter ---
echo
echo "=== Back-to-back wired-splitter cals ==="
echo "Swap RX cables to splitter (ZX10-2-42-S+ + 2× 30 dB attenuators)."
echo "Set nRF to start_tx_carrier (UNMODULATED tone), channel 19 = 2419 MHz."
read -P "Splitter cabled, nRF on tone? [y/N] " ready
if test "$ready" != "y"; exit 1; end

ssh $KRIA "sudo python3 ~/doa/phase_calibration_headless.py --duration 10 --freq $CAL_FREQ --gain $GAIN --tone 0" 2>&1 \
    | tee $RUN_DIR/calibration_a.log
echo
echo "--- second pass (no movement) ---"
ssh $KRIA "sudo python3 ~/doa/phase_calibration_headless.py --duration 10 --freq $CAL_FREQ --gain $GAIN --tone 0" 2>&1 \
    | tee $RUN_DIR/calibration_b.log

read -P "Enter the typed CAL value to pin for the 90° capture (e.g. 53.72): " CAL
set -gx CAL $CAL
echo "$CAL" > $RUN_DIR/cal_value.txt
echo "CAL = $CAL  (saved to $RUN_DIR/cal_value.txt)"

# --- 3. 90° capture ---
echo
echo "=== 90° broadside capture, --filter=none ==="
echo "Swap RX back to antennas. Set nRF to start_tx_modulated_carrier (BLE GFSK)."
read -P "Antennas connected, nRF transmitting modulated, board placed at 90° broadside? [y/N] " ready
if test "$ready" != "y"; exit 1; end

ssh $KRIA "echo '90deg' > ~/doa/data/current_label.txt"

read -P "Press enter to BEGIN ARM capture (3 s settle) " __junk
sleep 3
echo "--- ARM, $DUR sec, --filter=none ---"
ssh $KRIA "sudo timeout --signal=INT $DUR python3 ~/doa/aoa_estimation_headless.py \
    --algo ROOTMUSIC --freq $FREQ --gain $GAIN --filter none --cal $CAL" 2>&1 \
  | tee $RUN_DIR/arm_90deg.log

read -P "Press enter to BEGIN FPGA capture (3 s settle) " __junk
sleep 3
echo "--- FPGA, $DUR sec, --filter=none ---"
ssh $KRIA "sudo timeout --signal=INT $DUR python3 ~/doa/aoa_estimation_fpga_kv260.py \
    --algo ROOTMUSIC --freq $FREQ --gain $GAIN --filter none --cal $CAL" 2>&1 \
  | tee $RUN_DIR/fpga_90deg.log

# --- 4. Parse + headline result ---
grep -oE 'AOA:-?[0-9]+([.][0-9]+)?' $RUN_DIR/arm_90deg.log  | sed 's/AOA://' > $RUN_DIR/arm_90deg.csv
grep -oE 'AOA:-?[0-9]+([.][0-9]+)?' $RUN_DIR/fpga_90deg.log | sed 's/AOA://' > $RUN_DIR/fpga_90deg.csv

set -l n_arm  (wc -l < $RUN_DIR/arm_90deg.csv)
set -l n_fpga (wc -l < $RUN_DIR/fpga_90deg.csv)
echo
echo "=========================================="
echo "  Captured $n_arm ARM / $n_fpga FPGA at 90°"
echo "=========================================="

# Headline numbers via python (same logic as analyze_campaign.py: trim 6%/edge).
python3 -c "
import numpy as np
arm  = np.loadtxt('$RUN_DIR/arm_90deg.csv')
fpga = np.loadtxt('$RUN_DIR/fpga_90deg.csv')
def stats(x):
    x = np.sort(x); k = max(1, int(0.06*len(x)))
    x = x[k:-k] if len(x) > 2*k else x
    return len(x), float(np.mean(x)), float(np.std(x))
n_a, m_a, s_a = stats(arm)
n_f, m_f, s_f = stats(fpga)
print(f'ARM  n={n_a:4d}  mean={m_a:7.3f}°  σ={s_a:5.3f}°')
print(f'FPGA n={n_f:4d}  mean={m_f:7.3f}°  σ={s_f:5.3f}°')
print(f'Δ (FPGA − ARM) = {m_f - m_a:+.3f}°')
print()
delta = m_f - m_a
if abs(delta - 7.5) < 2.0:
    print('→ Δ within ±2° of v2 +7.5°: cal-application asymmetry hypothesis HOLDS.')
elif abs(delta) < 1.5:
    print('→ Δ near 0°: asymmetry hypothesis FALSIFIED — v2 offset was cal staleness.')
else:
    print('→ Δ in neither band: needs interpretation. Check cal value drift vs Apr-29 (53.72°).')
"

echo
echo "Data in: $RUN_DIR"
ls $RUN_DIR
