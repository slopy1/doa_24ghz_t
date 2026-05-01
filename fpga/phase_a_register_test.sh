#!/bin/sh
# phase_a_register_test.sh — standalone Phase A register-map sanity check.
#
# Run as root on the Cora after Phase A bitstream is loaded:
#   sudo /tmp/phase_a_register_test.sh
#
# No signal source required — this only probes AXI-Lite registers, never
# triggers DMA. Safe to run at any time.

BASE=0x40000000

echo "=== A.1 Baseline reads (all should be 0x00000000) ==="
printf "%-24s " "XCORR_RE_LO (0x00):"; devmem 0x40000000
printf "%-24s " "XCORR_RE_HI (0x04):"; devmem 0x40000004
printf "%-24s " "XCORR_IM_LO (0x08):"; devmem 0x40000008
printf "%-24s " "XCORR_IM_HI (0x0C):"; devmem 0x4000000C
printf "%-24s " "R00_LO      (0x10):"; devmem 0x40000010
printf "%-24s " "R00_HI      (0x14):"; devmem 0x40000014
printf "%-24s " "R11_LO      (0x18):"; devmem 0x40000018
printf "%-24s " "R11_HI      (0x1C):"; devmem 0x4000001C
printf "%-24s " "STATUS      (0x20):"; devmem 0x40000020
printf "%-24s " "SNAP_COUNT  (0x24):"; devmem 0x40000024
printf "%-24s " "FILTER_CTRL (0x38):"; devmem 0x40000038

echo
echo "=== A.2 COS_CAL / SIN_CAL write-read ==="

devmem 0x40000028 32 0x00007FFF
printf "COS_CAL wrote 0x00007FFF -> read: "; devmem 0x40000028

devmem 0x40000028 32 0x00008000
printf "COS_CAL wrote 0x00008000 -> read: "; devmem 0x40000028
echo "  (expect 0xFFFF8000 - sign-extended from 16-bit negative)"

devmem 0x4000002C 32 0x00004000
printf "SIN_CAL wrote 0x00004000 -> read: "; devmem 0x4000002C

devmem 0x40000028 32 0x00000000
devmem 0x4000002C 32 0x00000000
echo "COS_CAL and SIN_CAL reset to 0"

echo
echo "=== A.3 FIR coefficient slot write-read ==="

devmem 0x40000030 32 0x00000000
devmem 0x40000034 32 0x00001111
printf "COEFF_ADDR wrote 0      -> read: "; devmem 0x40000030
printf "COEFF_DATA wrote 0x1111 -> read: "; devmem 0x40000034

devmem 0x40000030 32 0x00000005
devmem 0x40000034 32 0x00002222
printf "COEFF_ADDR wrote 5      -> read: "; devmem 0x40000030
printf "COEFF_DATA wrote 0x2222 -> read: "; devmem 0x40000034

echo
echo "=== A.4 FILTER_CTRL write-read ==="

devmem 0x40000038 32 0x00000003
printf "FILTER_CTRL wrote 0x3 -> read: "; devmem 0x40000038

devmem 0x40000038 32 0x00000000
printf "FILTER_CTRL wrote 0x0 -> read: "; devmem 0x40000038

echo
echo "=== DONE ==="
