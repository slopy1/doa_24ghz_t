# FPGA Implementation

This directory contains FPGA-related code and notes for accelerating the DOA pipeline on Zynq-7000.

## Target Platform

**Cora Z7-07S** (Xilinx Zynq-7000 XC7Z007S)

## Vivado Project

**Location:** `/home/vmau/tools/projects/cora-linux/cora_doa_hw/cora_doa_hw.xpr` (Vivado 2025.2)

**Block design (system):**
- ZYNQ7 Processing System (processing_system7_0)
- AXI DMA (axi_dma_0)
- Xilinx FFT IP (xfft_0)
- AXI Interconnect (axi_interconnect_0)
- Processor System Reset (rst_ps7_0_50M)
- xlconstant_0, xlconstant_1 (tieoffs, marked Discontinued)

Bitstream successfully generated. See `notes/vivado_block_design_2026-03-25.png` for screenshot.

## Directory Structure

```
fpga/
├── README.md              ← This file
├── GETTING_STARTED.md     ← Step-by-step implementation guide
├── rtl/
│   └── xcorr_acc.v        ← Cross-correlation module (skeleton, MAC TODO)
├── tb/
│   └── (testbench, next step)
├── constraints/
│   └── (timing .xdc if needed)
└── notes/
    └── vivado_block_design_2026-03-25.png
```

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Vivado block design | Done | FFT + DMA + AXI Interconnect wired |
| Bitstream (infrastructure) | Done | Generated successfully |
| Cross-correlation IP | In progress | Module skeleton in `rtl/xcorr_acc.v`, MAC datapath TODO |
| Power estimation | Designed | Same accumulator pattern as xcorr |
| Phase extraction | Pending | CORDIC or LUT, may stay on PS |
| AXI-Lite wrapper | Pending | After xcorr_acc simulation passes |
| Block design integration | Pending | Wire xcorr_acc into existing design |

## Architecture: Time-Domain Approach

Chosen over frequency-domain (FFT) for simplicity. The FFT block remains in the design for future use.

### What runs on PL (FPGA fabric)

1. **Streaming cross-correlation** (`xcorr_acc.v`)
   - Complex multiply-accumulate: `r_01 = Σ ch0[n] × conj(ch1[n])`
   - AXI-Stream input (64-bit, both channels packed)
   - AXI-Lite output registers for ARM to read results
   - ~4 DSP48 slices, ~500 LUTs

2. **Power estimation** (future, same accumulator structure)
   - `P_0 = Σ|ch0[n]|²`, `P_1 = Σ|ch1[n]|²`

### What runs on PS (ARM cores)

1. Phase extraction (atan2)
2. Grid search over angles
3. Kalman filter for drift tracking
4. Posterior computation

## Resource Budget

| Resource | Available | xcorr_acc | FFT (existing) | Remaining |
|----------|-----------|-----------|----------------|-----------|
| DSP48    | 66        | 4         | ~10-15         | ~47       |
| BRAM     | 50        | 0         | ~8-10          | ~30       |
| LUTs     | 14,400    | ~500      | ~2000          | ~11,900   |
| FFs      | 28,800    | ~1000     | ~2000          | ~25,800   |

## Next Steps

See [GETTING_STARTED.md](GETTING_STARTED.md) for the full walkthrough.

## References

- [docs/fpga_mapping.md](../docs/fpga_mapping.md) — Full architecture document
- Xilinx UG585 — Zynq-7000 TRM
- Xilinx UG1399 — Vitis HLS User Guide
