# Getting Started: Time-Domain Cross-Correlation IP

This guide walks through implementing the `xcorr_acc` module — your first custom IP for the Zynq PL fabric.

## What You're Building

A streaming complex cross-correlator that computes:

```
r_01 = (1/N) * Σ ch0[n] × conj(ch1[n])
```

This is the same operation your Python code does on the ARM, but in hardware at line rate.

## Prerequisites

- Vivado 2025.2 (already installed on VM)
- Existing block design at `/home/vmau/tools/projects/cora-linux/cora_doa_hw/cora_doa_hw.xpr`
- Familiarity with your block design (Zynq PS, AXI DMA, FFT, AXI Interconnect)

## Step 1: Implement the MAC Datapath

**File:** `fpga/rtl/xcorr_acc.v`

The module skeleton is ready. You need to write one `always @(posedge clk)` block that does:

```verilog
always @(posedge clk) begin
    if (!rst_n) begin
        acc_re       <= 0;
        acc_im       <= 0;
        sample_cnt   <= 0;
        xcorr_re     <= 0;
        xcorr_im     <= 0;
        result_valid <= 0;
    end else if (s_axis_tvalid) begin
        // Cross-correlation: ch0 * conj(ch1)
        //   re part: ch0_i*ch1_i + ch0_q*ch1_q
        //   im part: ch0_q*ch1_i - ch0_i*ch1_q
        acc_re <= acc_re + (ch0_i * ch1_i) + (ch0_q * ch1_q);
        acc_im <= acc_im + (ch0_q * ch1_i) - (ch0_i * ch1_q);

        if (sample_cnt == SNAPSHOT_LEN - 1) begin
            // Snapshot complete — latch results
            xcorr_re     <= acc_re + (ch0_i * ch1_i) + (ch0_q * ch1_q);
            xcorr_im     <= acc_im + (ch0_q * ch1_i) - (ch0_i * ch1_q);
            result_valid <= 1;
            acc_re       <= 0;
            acc_im       <= 0;
            sample_cnt   <= 0;
        end else begin
            result_valid <= 0;
            sample_cnt   <= sample_cnt + 1;
        end
    end else begin
        result_valid <= 0;
    end
end
```

Key points:
- The multiply expressions infer DSP48E1 slices automatically
- 48-bit accumulators handle 1024 × (16×16) without overflow
- `result_valid` pulses for exactly one cycle per snapshot

## Step 2: Write a Testbench

**File:** `fpga/tb/tb_xcorr_acc.v`

Create a testbench that:
1. Generates two known SC16 tone signals with a fixed phase offset
2. Feeds them through `xcorr_acc`
3. Checks that `xcorr_re` and `xcorr_im` give the expected phase

Test vectors to try:
- **Same signal on both channels** → `xcorr_im ≈ 0` (zero phase)
- **90° shifted** → `xcorr_re ≈ 0`, `xcorr_im` nonzero
- **Known phase offset** → compare `atan2(im, re)` against expected angle

Run with: `vivado -mode batch -source run_sim.tcl` or use Vivado GUI simulator.

## Step 3: Simulate in Vivado

```tcl
# In Vivado Tcl console:
add_files fpga/rtl/xcorr_acc.v
add_files -fileset sim_1 fpga/tb/tb_xcorr_acc.v
launch_simulation
run 100us
```

Verify the waveforms show:
- `result_valid` pulsing every 1024 clock cycles
- `xcorr_re` / `xcorr_im` matching expected values

## Step 4: Package as AXI IP

Once simulation passes, package `xcorr_acc` as a Vivado IP with:
- **AXI-Stream slave** port (64-bit, for sample input from DMA)
- **AXI-Lite slave** port (for ARM to read results)

In Vivado: Tools → Create and Package New IP → Package your current project.

You'll need to add an AXI-Lite wrapper that maps:
- `0x00` → `xcorr_re` (read-only)
- `0x04` → `xcorr_im` (read-only)
- `0x08` → `result_valid` / status (read-only)
- `0x0C` → `snapshot_len` (read-write, optional)

## Step 5: Integrate into Block Design

In your existing block design:
1. Add your packaged `xcorr_acc` IP
2. Connect AXI-Stream input from `axi_dma_0` MM2S channel
3. Connect AXI-Lite to `axi_interconnect_0`
4. Assign address in Address Editor

The FFT block can stay — it's independent. You can wire it in parallel later for spectrum visualization.

```
                    ┌──────────────┐
axi_dma_0 MM2S ──► │  xcorr_acc   │ ◄── AXI-Lite (ARM reads results)
                    └──────────────┘
```

## Step 6: Linux Driver / Userspace Access

From Linux on the ARM, read your IP's registers via `/dev/mem` or UIO:

```python
import mmap, struct

# AXI-Lite base address (from Vivado Address Editor)
BASE = 0x43C0_0000  # example, check your address map

with open("/dev/mem", "r+b") as f:
    mm = mmap.mmap(f.fileno(), 0x1000, offset=BASE)
    xcorr_re = struct.unpack("<i", mm[0x00:0x04])[0]
    xcorr_im = struct.unpack("<i", mm[0x04:0x08])[0]
    phase = math.atan2(xcorr_im, xcorr_re)
```

## File Map

```
fpga/
├── GETTING_STARTED.md    ← This file
├── rtl/
│   └── xcorr_acc.v       ← Cross-correlation module (Step 1)
├── tb/
│   └── tb_xcorr_acc.v    ← Testbench (Step 2)
├── constraints/
│   └── (timing .xdc if needed)
└── notes/
    └── vivado_block_design_2026-03-25.png
```

## Resource Budget After xcorr_acc

| Resource | Available | xcorr_acc | FFT (existing) | Remaining |
|----------|-----------|-----------|----------------|-----------|
| DSP48    | 66        | 4         | ~10-15         | ~47       |
| BRAM     | 50        | 0         | ~8-10          | ~30       |
| LUTs     | 14,400    | ~500      | ~2000          | ~11,900   |
| FFs      | 28,800    | ~1000     | ~2000          | ~25,800   |

Plenty of headroom.
