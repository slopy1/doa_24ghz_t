#!/usr/bin/env fish
# resume_campaign.fish - Resume the multi-angle DoA campaign after a break.
#
# Picks up from the 90deg anchor that was already captured. Walks through:
#   1. Sanity check Kria + UIO + udmabuf
#   2. Recalibrate (wired splitter path)
#   3. Capture remaining angles ARM + FPGA back-to-back
#   4. Pull/parse logs locally
#
# Run from this PC (host), not the Kria. Expects fish shell.

set -l SCRIPT_DIR (dirname (status -f))
set -l RUN_BASE ~/doa_24ghz_thesis/data

# --- Session ID ---
if test -f /tmp/doa_session.txt
    set -gx SESSION (cat /tmp/doa_session.txt)
    echo "Reusing session: $SESSION"
else
    set -gx SESSION (date +"%Y%m%d_%H%M%S")
    echo $SESSION > /tmp/doa_session.txt
    echo "New session: $SESSION"
end

set -gx RUN_DIR $RUN_BASE/run_$SESSION
mkdir -p $RUN_DIR

# --- Defaults (override before running if needed) ---
# AOA FREQ must equal CAL_FREQ for bandpass to work: BladeRF tunes 50 kHz below
# the nRF carrier (2.419 GHz on ch 19) so the signal lands at +50 kHz baseband,
# inside the 40-60 kHz bandpass. On-carrier tuning (2.419e9) puts signal at DC,
# which the bandpass rejects — produces noise-only ARM and lucky-frame FPGA.
set -q FREQ;     or set -gx FREQ     2.41895e9
set -q CAL_FREQ; or set -gx CAL_FREQ 2.41895e9
set -q GAIN;     or set -gx GAIN     50
set -q DUR;      or set -gx DUR      70
set -q KRIA;     or set -gx KRIA     ubuntu@192.168.1.101

# Loud surfacing — a stale FREQ universal variable bit us once already.
echo "  FREQ      = $FREQ  (BladeRF AOA tune)"
echo "  CAL_FREQ  = $CAL_FREQ  (BladeRF cal tune)"
echo "  GAIN      = $GAIN dB"
echo "  DUR       = $DUR sec"
if test "$FREQ" != "$CAL_FREQ"
    echo
    echo "  !! WARNING: FREQ != CAL_FREQ. Bandpass mode requires both to be"
    echo "  !! 50 kHz off-carrier (typically 2.41895e9 for ch 19). The bandpass"
    echo "  !! at +50 kHz baseband will not admit the carrier if FREQ is on-carrier."
    echo "  !! Clear stale env var:  set -e FREQ; set -eU FREQ"
    read -P "Continue anyway? [y/N] " ok
    if test "$ok" != "y"; exit 1; end
end

# --- 1. Sanity check ---
echo
echo "=== Sanity check on $KRIA ==="
ssh $KRIA "uptime; echo '--- UIO ---'; ls /sys/class/uio/; echo '--- udmabuf ---'; ls /sys/class/u-dma-buf/ 2>&1; echo '--- chip names ---'; for u in /sys/class/uio/uio*/name; do cat \"\$u\"; done"
echo
read -P "Looks ok? [y/N] " ok
if test "$ok" != "y"
    echo "Bail. Re-run bench_bringup.sh on Kria first:"
    echo "  ssh $KRIA 'sudo bash ~/doa/bench_bringup.sh'"
    exit 1
end

# --- 2. Recalibrate ---
echo
echo "=== Recalibrate ==="
echo "Swap RX cables to splitter (Mini-Circuits ZX10-2-42-S+ + 2x 30dB attenuators)."
echo "Set nRF to start_tx_carrier (unmodulated tone), channel 19 = 2419 MHz."
read -P "Cables on splitter, nRF on tone? [y/N] " ready
if test "$ready" = "y"
    ssh $KRIA "sudo python3 ~/doa/phase_calibration_headless.py --duration 10 --freq $CAL_FREQ --gain $GAIN --tone 0" 2>&1 \
        | tee $RUN_DIR/calibration_resume.log
    echo
    echo "Run a second cal back-to-back to verify reproducibility:"
    ssh $KRIA "sudo python3 ~/doa/phase_calibration_headless.py --duration 10 --freq $CAL_FREQ --gain $GAIN --tone 0" 2>&1 \
        | tee $RUN_DIR/calibration_resume_b.log
end

read -P "Enter the new CAL value (e.g. 51.96): " CAL
set -gx CAL $CAL
echo "$CAL" > $RUN_DIR/cal_value_resume.txt
echo "CAL = $CAL  (saved to $RUN_DIR/cal_value_resume.txt)"

# --- 3. Capture angles ---
echo
echo "=== Multi-angle captures ==="
echo "Swap RX back to antennas. nRF on start_tx_modulated_carrier."
read -P "Antennas connected, nRF transmitting? [y/N] " ready
if test "$ready" != "y"
    echo "Aborting before captures."
    exit 1
end

# Angles still to capture (90 already done in earlier session)
# Edit this list if you want a different order or to skip an angle.
set ANGLES 50 70 110 130

for ANGLE in $ANGLES
    echo
    echo "=========================================="
    echo "  Angle: $ANGLE deg"
    echo "=========================================="
    read -P "Move nRF to $ANGLE deg, press enter when board is placed " __junk
    ssh $KRIA "echo \"$ANGLE""deg\" > ~/doa/data/current_label.txt"

    read -P "Press enter to BEGIN ARM capture (3s settle delay starts on enter) " __junk
    sleep 3
    echo "--- ARM, $DUR sec, one-sided ARM bandpass ---"
    ssh $KRIA "sudo timeout --signal=INT $DUR python3 ~/doa/aoa_estimation_headless.py \
        --algo ROOTMUSIC --freq $FREQ --gain $GAIN --filter arm_bandpass --cal $CAL" 2>&1 \
      | tee $RUN_DIR/arm_{$ANGLE}deg.log

    read -P "Press enter to BEGIN FPGA capture (3s settle delay starts on enter) " __junk
    sleep 3
    echo "--- FPGA, $DUR sec, hybrid (fabric xcorr + ARM bandpass) ---"
    ssh $KRIA "sudo timeout --signal=INT $DUR python3 ~/doa/aoa_estimation_fpga_kv260.py \
        --algo ROOTMUSIC --freq $FREQ --gain $GAIN --filter arm_bandpass --cal $CAL" 2>&1 \
      | tee $RUN_DIR/fpga_{$ANGLE}deg.log

    # Quick parse to CSV
    grep -oE 'AOA:-?[0-9]+([.][0-9]+)?' $RUN_DIR/arm_{$ANGLE}deg.log  | sed 's/AOA://' > $RUN_DIR/arm_{$ANGLE}deg.csv
    grep -oE 'AOA:-?[0-9]+([.][0-9]+)?' $RUN_DIR/fpga_{$ANGLE}deg.log | sed 's/AOA://' > $RUN_DIR/fpga_{$ANGLE}deg.csv
    set -l n_arm  (wc -l < $RUN_DIR/arm_{$ANGLE}deg.csv)
    set -l n_fpga (wc -l < $RUN_DIR/fpga_{$ANGLE}deg.csv)
    echo "Captured $n_arm ARM / $n_fpga FPGA readings at $ANGLE deg"
end

echo
echo "=========================================="
echo "  Campaign complete"
echo "=========================================="
echo "Data in: $RUN_DIR"
ls $RUN_DIR
