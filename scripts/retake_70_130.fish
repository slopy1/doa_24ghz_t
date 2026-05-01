#!/usr/bin/env fish
# retake_70_130.fish - Re-capture only the 70 and 130 deg angles into the
# current run dir, reusing the same CAL value from cal_value_resume.txt.
#
# Why: the first pass of those two angles was contaminated by the nRF being
# held by hand (tilted off-perpendicular) and rotated 90 deg on its long axis
# (buttons facing the array instead of nRF tip up). 50 and 110 deg from the
# same session are clean and stay; this script preserves the bad files with a
# .bad-handheld suffix and writes fresh canonical files in their place.
#
# Run from this PC. Expects /tmp/doa_session.txt to exist (set by an earlier
# resume_campaign.fish run) and cal_value_resume.txt to exist in that run dir.

set -l RUN_BASE ~/doa_24ghz_thesis/data

if not test -f /tmp/doa_session.txt
    echo "No /tmp/doa_session.txt — run resume_campaign.fish first to mint a session."
    exit 1
end

set -gx SESSION (cat /tmp/doa_session.txt)
set -gx RUN_DIR $RUN_BASE/run_$SESSION

if not test -d $RUN_DIR
    echo "Run dir not found: $RUN_DIR"
    exit 1
end

if not test -f $RUN_DIR/cal_value_resume.txt
    echo "No cal_value_resume.txt in $RUN_DIR — re-run resume_campaign.fish from cal step."
    exit 1
end

set -gx CAL (cat $RUN_DIR/cal_value_resume.txt | string trim)

set -q FREQ;     or set -gx FREQ     2.41895e9
set -q CAL_FREQ; or set -gx CAL_FREQ 2.41895e9
set -q GAIN;     or set -gx GAIN     50
set -q DUR;      or set -gx DUR      70
set -q KRIA;     or set -gx KRIA     ubuntu@192.168.1.101

echo "=== Retake 70 and 130 deg ==="
echo "  SESSION   = $SESSION"
echo "  RUN_DIR   = $RUN_DIR"
echo "  CAL       = $CAL  (reused from first pass)"
echo "  FREQ      = $FREQ"
echo "  GAIN      = $GAIN dB"
echo "  DUR       = $DUR sec"
echo

# --- Sanity check Kria ---
echo "=== Sanity check on $KRIA ==="
ssh $KRIA "ls /sys/class/uio/ | wc -l; for u in /sys/class/uio/uio*/name; do cat \"\$u\"; done; ls /sys/class/u-dma-buf/ 2>&1"
echo
read -P "Looks ok (need 5 UIO incl. dma_safe_ctrl_regs + udmabuf)? [y/N] " ok
if test "$ok" != "y"
    echo "Bail. Re-run bench bring-up:"
    echo "  ssh $KRIA 'sudo bash ~/doa/bench_bringup.sh'"
    exit 1
end

# --- Preserve bad data ---
echo
echo "=== Archiving handheld-orientation data ==="
for ANGLE in 70 130
    for PATH_ in arm fpga
        for EXT in csv log
            set -l f $RUN_DIR/{$PATH_}_{$ANGLE}deg.$EXT
            if test -f $f
                mv -v $f $f.bad-handheld
            end
        end
    end
end

# --- nRF placement guidance ---
echo
echo "=== nRF placement reminder ==="
echo "Place the nRF the same way as the 50 and 110 deg captures from this run:"
echo "  - Antenna tip pointing UP (away from ground, NOT buttons-facing-array)"
echo "  - On a fixed mount (tape, stand, anything non-handheld)"
echo "  - Long axis perpendicular to the ground"
echo "  - nRF on start_tx_modulated_carrier, channel 19"
read -P "Ready? [y/N] " ready
if test "$ready" != "y"
    echo "Aborting before captures."
    exit 1
end

# --- Re-capture ---
set ANGLES 70 130

for ANGLE in $ANGLES
    echo
    echo "=========================================="
    echo "  Angle: $ANGLE deg  (retake)"
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

    grep -oE 'AOA:-?[0-9]+([.][0-9]+)?' $RUN_DIR/arm_{$ANGLE}deg.log  | sed 's/AOA://' > $RUN_DIR/arm_{$ANGLE}deg.csv
    grep -oE 'AOA:-?[0-9]+([.][0-9]+)?' $RUN_DIR/fpga_{$ANGLE}deg.log | sed 's/AOA://' > $RUN_DIR/fpga_{$ANGLE}deg.csv
    set -l n_arm  (wc -l < $RUN_DIR/arm_{$ANGLE}deg.csv)
    set -l n_fpga (wc -l < $RUN_DIR/fpga_{$ANGLE}deg.csv)
    echo "Captured $n_arm ARM / $n_fpga FPGA readings at $ANGLE deg (retake)"
end

echo
echo "=========================================="
echo "  Retake complete — re-run analysis:"
echo "=========================================="
echo "python3 ~/doa_24ghz_thesis/scripts/analyze_campaign.py --run-dir $RUN_DIR"
