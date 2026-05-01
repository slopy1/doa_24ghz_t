# FPGA Expansion Design — 3-Phase Incremental Plan

**Date:** 2026-04-07
**Target:** Cora Z7 (Zynq-7000 XC7Z007S), Vivado 2025.2
**Goal:** Maximize FPGA utilization — move FIR filtering, auto-correlations, calibration, and multi-snapshot averaging into fabric. Each phase produces a working bitstream.

## Current State

**FPGA (PL):**
- `xcorr_acc` — computes r₀₁ = Σ(ch0 × conj(ch1)) per 1024-sample snapshot
- `xcorr_acc_axi` — AXI-Lite wrapper, 4 read-only registers (32-bit truncated from 48-bit accumulators)
- AXI DMA (SG mode) — ARM pushes one snapshot at a time
- ~4 DSP48 / ~2K LUTs / ~2K FFs used

**ARM (PS) — Python does all of this per update:**
1. Read 102,400 samples (100 × 1024) from BladeRF via SoapySDR
2. Apply FIR filter (201-tap lowpass/bandpass) via FFT convolution — both channels
3. Apply phase calibration rotation on ch1
4. Loop 100 times:
   a. Send 1024-sample snapshot to FPGA via DMA
   b. Read r₀₁ from AXI-Lite registers
   c. Compute r₀₀, r₁₁ in SC16 integer math (NumPy)
5. Average all 100 snapshots
6. Build 2×2 covariance matrix R
7. Eigendecomposition + Root-MUSIC → angle

**Known issues:**
- 32-bit register truncation causes MISMATCH on first 2-3 iterations (startup transient with large values)
- 100-iteration Python loop is the main latency bottleneck
- FIR filter on Cortex-A9 is slow even with FFT method

## Resource Budget (XC7Z007S)

| Resource | Total | Currently Used | Available |
|----------|-------|---------------|-----------|
| LUTs | 14,400 | ~2,000 | ~12,400 |
| FFs | 28,800 | ~2,000 | ~26,800 |
| DSP48E1 | 66 | ~4 | 62 |
| BRAM 36Kb | 50 | ~5 (DMA+FFT IP) | ~45 |
| BRAM 18Kb | 100 | ~10 | ~90 |

---

## Phase A — Enhanced Datapath (keep current DMA model)

**Goal:** Move FIR filtering, calibration rotation, and auto-correlations into fabric. ARM still loops 100×, but each iteration does almost no computation — just DMA kick + register read.

### A.1 New RTL Modules

#### `fir_filter_sc16` — FIR filter for one SC16 channel

```
Inputs:  s_axis_tdata[31:0] (SC16: {Q[31:16], I[15:0]})
         s_axis_tvalid, s_axis_tready
Outputs: m_axis_tdata[31:0] (filtered SC16)
         m_axis_tvalid, m_axis_tready
Config:  AXI-Lite writable coefficient RAM (up to 64 taps)
```

- Symmetric FIR (halves the multipliers needed for real-coefficient lowpass/bandpass)
- 64 taps max (vs 201 in Python — shorter but at line rate, and we can increase snapshot count to compensate)
- Filter I and Q components independently (real-coefficient FIR on complex data)
- Resource estimate: ~32 DSP48 for 64-tap symmetric (16 unique coefficients × 2 for I/Q), ~2K LUTs, 2 BRAM for coefficient storage

**Why 64 taps instead of 201:** At 1 Msps with 64 taps, the transition bandwidth is wider (~15 kHz vs ~5 kHz), but the stopband rejection is still >40 dB — sufficient for our SNR improvement goal. Going to 201 taps would consume all 66 DSP48s on just the filter.

**Alternative: 32 taps** if we need DSP headroom. 32-tap symmetric = 16 multipliers × 2 (I/Q) = 32 DSP48. Trade-off: ~30 dB stopband rejection.

**Recommended: 48 taps** — 24 unique coefficients × 2 = 48 DSP48. Leaves 14 DSP48 for xcorr + auto-corr. Good balance of rejection (~38 dB) and resource usage.

#### `phase_rotate_sc16` — Calibration phase rotation

```
Inputs:  s_axis_tdata[31:0] (SC16)
         s_axis_tvalid, s_axis_tready
Outputs: m_axis_tdata[31:0] (rotated SC16)
         m_axis_tvalid, m_axis_tready
Config:  AXI-Lite writable registers: cos_cal[15:0], sin_cal[15:0] (Q1.15 fixed-point)
```

- Complex multiply: (I + jQ) × (cos_cal - j·sin_cal)
  - I' = I·cos_cal + Q·sin_cal
  - Q' = Q·cos_cal - I·sin_cal
- Resource estimate: 4 DSP48, ~200 LUTs
- ARM writes cos/sin of calibration angle as Q1.15 values via AXI-Lite

#### `autocorr_acc` — Auto-correlation accumulator for r₀₀ and r₁₁

```
Inputs:  ch0_tdata[31:0], ch1_tdata[31:0] (SC16, after filtering)
         tvalid
Outputs: r00[47:0], r11[47:0], result_valid
```

- r₀₀ += I₀² + Q₀² (power of ch0)
- r₁₁ += I₁² + Q₁² (power of ch1)
- Same snapshot boundary logic as xcorr_acc (counter, latch, reset)
- Resource estimate: 4 DSP48, ~500 LUTs
- Can share the same AXI wrapper or be added to xcorr_acc_axi

### A.2 Modified `xcorr_acc_axi` — Expanded Register Map

Expand from 4 to 12 registers. Use full 48-bit readback (split into low/high words):

| Offset | Name | Width | Access | Description |
|--------|------|-------|--------|-------------|
| 0x00 | XCORR_RE_LO | 32 | R | r₀₁ real, bits [31:0] |
| 0x04 | XCORR_RE_HI | 32 | R | r₀₁ real, bits [47:32] (sign-extended) |
| 0x08 | XCORR_IM_LO | 32 | R | r₀₁ imag, bits [31:0] |
| 0x0C | XCORR_IM_HI | 32 | R | r₀₁ imag, bits [47:32] (sign-extended) |
| 0x10 | R00_LO | 32 | R | r₀₀ auto-corr, bits [31:0] |
| 0x14 | R00_HI | 32 | R | r₀₀ auto-corr, bits [47:32] |
| 0x18 | R11_LO | 32 | R | r₁₁ auto-corr, bits [31:0] |
| 0x1C | R11_HI | 32 | R | r₁₁ auto-corr, bits [47:32] |
| 0x20 | STATUS | 32 | R | bit 0 = result_valid (sticky, clear-on-read) |
| 0x24 | SNAP_COUNT | 32 | R | completed snapshot counter |
| 0x28 | COS_CAL | 16 | R/W | calibration cos(θ) in Q1.15 |
| 0x2C | SIN_CAL | 16 | R/W | calibration sin(θ) in Q1.15 |
| 0x30 | FILTER_COEFF_ADDR | 8 | W | coefficient index to write |
| 0x34 | FILTER_COEFF_DATA | 16 | W | coefficient value (Q1.15) |
| 0x38 | FILTER_CTRL | 8 | R/W | bit 0 = filter enable, bit 1 = coefficients loaded |

Need C_S_AXI_ADDR_WIDTH ≥ 8 (currently 12, so no change needed).

### A.3 Block Design Changes (Vivado)

Current path:
```
DMA MM2S → xcorr_acc_axi (s_axis)
```

New path:
```
DMA MM2S → channel_splitter → fir_filter_sc16 (ch0) → ┐
                             → fir_filter_sc16 (ch1) → phase_rotate_sc16 → channel_merger
                                                                              ↓
                                                              xcorr_acc_axi (expanded, includes autocorr)
```

**channel_splitter:** Demuxes the interleaved 2-beat stream into two separate SC16 streams (ch0, ch1). Simple FSM toggling on beat_phase.

**channel_merger:** Re-interleaves the two filtered/calibrated SC16 streams back into the 2-beat format expected by xcorr_acc.

Alternatively: modify xcorr_acc to accept two separate input ports instead of interleaved. This avoids the split/merge overhead.

### A.4 Python Driver Changes (`aoa_estimation_fpga_v3.py`)

```python
# Phase A: ARM still loops, but registers provide full covariance per snapshot

# At startup — write filter coefficients and calibration
fpga.write_filter_coefficients(taps)  # AXI-Lite writes to coeff RAM
fpga.write_calibration(cal_deg)       # Write cos/sin to registers

# Per-update loop (100 snapshots)
for k in range(n_snap):
    fpga.dma_transfer(ch0_snap, ch1_snap)  # Push raw SC16 data
    r01_re, r01_im = fpga.read_xcorr_48bit()  # Full 48-bit read
    r00 = fpga.read_r00_48bit()
    r11 = fpga.read_r11_48bit()
    # Accumulate on ARM (simple addition, no DSP)
    acc_re += r01_re
    acc_im += r01_im
    acc_r00 += r00
    acc_r11 += r11

# Build R and run Root-MUSIC (same as before)
```

**What ARM no longer does:**
- FIR filtering (moved to FPGA)
- Phase calibration rotation (moved to FPGA)
- SC16 quantization for r₀₀/r₁₁ (FPGA computes directly)
- The Python loop is now: DMA kick → read 6 registers → add to accumulators

### A.5 Resource Estimate (Phase A)

| Resource | Phase A Usage | Total Available | % Used |
|----------|--------------|----------------|--------|
| DSP48E1 | ~56 (48 FIR + 4 phase_rot + 4 xcorr + 4 autocorr, but xcorr reuses) | 66 | ~85% |
| LUTs | ~6,000 | 14,400 | ~42% |
| FFs | ~5,000 | 28,800 | ~17% |
| BRAM 18Kb | ~4 (coeff storage) | 100 | ~4% |

**Note:** 48-tap FIR uses 48 DSP48 if we filter both channels. If resources are too tight, reduce to 32 taps (32 DSP48) or use a single time-shared FIR for both channels (halves DSP48 but doubles latency — fine at 1 Msps since the clock is 100 MHz, giving 100× oversampling).

**Recommended: Time-shared single FIR** — processes ch0, then ch1, using the same multiplier array. Uses 24 DSP48 for a 48-tap symmetric filter. Total DSP48: 24 + 4 + 4 + 4 = 36 (~55%).

### A.6 Testing Strategy

1. **Simulation (iverilog):**
   - `tb_fir_filter_sc16.v` — impulse response test, known sinusoid filtering
   - `tb_phase_rotate_sc16.v` — verify rotation angles (0°, 45°, 90°, 180°)
   - `tb_autocorr_acc.v` — known-power input, verify r₀₀/r₁₁
   - `tb_full_pipeline.v` — end-to-end: raw SC16 → filter → rotate → xcorr + autocorr

2. **Hardware test (on Cora):**
   - `test_fpga_pipeline.py` — synthetic DMA test similar to existing `test_fpga_xcorr.py`
   - Compare FPGA pipeline output vs NumPy reference for known phase/amplitude inputs

3. **Live comparison:**
   - `--debug` flag prints FPGA vs ARM reference for first N iterations with real BladeRF data

---

## Phase B — Autonomous Streaming (rework DMA)

**Goal:** Eliminate the 100-iteration Python loop. FPGA accumulates N snapshots autonomously. ARM reads the final averaged covariance matrix once per update.

### B.1 DMA Changes

Replace single-shot SG DMA with **cyclic DMA** (ring buffer):
- ARM sets up a circular SG descriptor ring
- DMA streams continuously from a shared DDR buffer
- BladeRF → SoapySDR writes to buffer, DMA reads from it
- FPGA consumes at line rate

Alternative (simpler): ARM still pushes data, but sends all 100 snapshots in one large DMA transfer (102,400 × 2 channels × 4 bytes = 819,200 bytes). Single SG descriptor chain, FPGA processes the entire batch.

**Recommended: Large single transfer** — simpler than true ring buffer, still eliminates the per-snapshot DMA setup overhead. ARM calls `readStream` once for all samples, packs them into the DMA buffer, kicks one transfer, waits for completion.

### B.2 New RTL: `multi_snapshot_acc`

Wraps xcorr_acc + autocorr_acc with an outer counter:
```
Parameter: NUM_SNAPSHOTS (writable via AXI-Lite, default 100)

For each snapshot (1024 samples):
  - Accumulate r01, r00, r11 as before
  - At snapshot boundary: add to outer accumulator
  - After NUM_SNAPSHOTS: latch final averaged values, assert result_valid
```

Register map adds:
| Offset | Name | Width | Access | Description |
|--------|------|-------|--------|-------------|
| 0x3C | NUM_SNAPSHOTS | 16 | R/W | Snapshots to average before signaling result |
| 0x40 | AVG_R01_RE_LO | 32 | R | Averaged r₀₁ real |
| ... | | | | (6 more averaged registers) |

### B.3 Python Driver Changes

```python
# Phase B: single DMA transfer, single register read
fpga.write_num_snapshots(100)
fpga.dma_transfer_bulk(ch0_all, ch1_all)  # One big transfer
fpga.wait_for_result()                     # Poll STATUS register
R = fpga.read_covariance_matrix()          # Read 6 values → build 2x2 R
aoa = root_music_doa(R, ...)               # Only computation ARM does
```

### B.4 Resource Estimate (Phase B, incremental over A)

Additional ~500 LUTs, ~500 FFs for outer accumulator and control. DSP48 unchanged.

---

## Phase C — Full FPGA DoA (angle output)

**Goal:** FPGA outputs the DoA angle directly. ARM just reads one register.

### C.1 2×2 Eigendecomposition in Fixed-Point

For a 2×2 Hermitian matrix R = [[r₀₀, r₀₁], [r₀₁*, r₁₁]], the noise eigenvector has a closed-form:

```
The noise subspace eigenvector for a 2×2 matrix is:
  e_noise = [-r₀₁, r₀₀ - λ_min]  (unnormalized)

where λ_min = (r₀₀ + r₁₁)/2 - sqrt((r₀₀ - r₁₁)²/4 + |r₀₁|²)
```

This requires:
- Fixed-point square root (iterative, ~16 cycles for 48-bit)
- Basic arithmetic (add, subtract, shift)

### C.2 Root-MUSIC for 2 Elements

For a 2-element ULA with 1 source, Root-MUSIC reduces to:
```
phase = atan2(imag(r₀₁), real(r₀₁)) - cal_phase
angle = arccos(phase / (2π × d/λ))
```

Wait — for 2 elements and 1 source, Root-MUSIC simplifies to essentially the phase-difference method applied to the noise subspace. The polynomial is degree 1. This means:

- **CORDIC** for atan2 (~16 iterations, ~200 LUTs)
- **CORDIC** for arccos (same unit, different mode)
- Fixed-point division (or shift if d/λ = 0.5)

### C.3 Register Map Addition

| Offset | Name | Width | Access | Description |
|--------|------|-------|--------|-------------|
| 0x50 | DOA_ANGLE | 16 | R | Estimated angle × 10 (e.g., 854 = 85.4°) |
| 0x54 | DOA_VALID | 1 | R | New angle available |

### C.4 Resource Estimate (Phase C, incremental over B)

Additional ~2K LUTs for CORDIC + sqrt + control. No additional DSP48.

**Total Phase C estimate:**

| Resource | Total Usage | Available | % Used |
|----------|------------|-----------|--------|
| DSP48E1 | ~36 | 66 | ~55% |
| LUTs | ~9,000 | 14,400 | ~63% |
| FFs | ~7,000 | 28,800 | ~24% |
| BRAM 18Kb | ~4 | 100 | ~4% |

---

## Implementation Order (Tomorrow's Plan)

### Day 1 — Phase A Foundation

**Morning (RTL + Simulation):**

1. **Write `fir_filter_sc16.v`** — time-shared symmetric FIR, 48 taps
   - Coefficient loading via simple interface (not AXI-Lite yet — test first)
   - Testbench: impulse response, known sinusoid at 50 kHz, verify stopband rejection

2. **Write `phase_rotate_sc16.v`** — complex multiply with cos/sin registers
   - Testbench: 0°, 45°, 90°, 180° rotation, verify against NumPy

3. **Write `autocorr_acc.v`** — power accumulator for both channels
   - Testbench: known-amplitude input, verify r₀₀/r₁₁ match

4. **Run all simulations with iverilog** — all tests must pass before Vivado

**Afternoon (Integration):**

5. **Expand `xcorr_acc_axi.v`** — new register map (48-bit readback, cal registers, filter ctrl)
   - Testbench: AXI-Lite read/write verification

6. **Write `doa_pipeline.v`** — top-level wrapper connecting:
   `s_axis → fir_filter (time-shared) → phase_rotate (ch1 only) → xcorr_acc + autocorr_acc → registers`

7. **Full pipeline testbench** — synthetic SC16 data through entire chain, compare with NumPy

### Day 2 — Vivado + Hardware

8. **Package IP in Vivado** — add `doa_pipeline` as custom IP
9. **Update block design** — replace `xcorr_acc_axi_0` with new `doa_pipeline`
10. **Synthesis + Implementation** — check timing, utilization
11. **Generate bitstream** — save as `BOOT_phaseA.BIN`
12. **Write `aoa_estimation_fpga_v3.py`** — new driver using expanded registers
13. **Hardware test** — run `test_fpga_pipeline.py` with synthetic data
14. **Live test** — compare Phase A output vs current v2 with real BladeRF data

### Day 3+ — Phase B

15. Rework DMA to bulk transfer
16. Add multi-snapshot accumulator
17. New bitstream + driver
18. Benchmark: update rate comparison (Phase A vs Phase B vs pure ARM)

---

## Fallback Strategy

- **Current bitstream** saved as `BOOT_current.BIN` before any changes
- Each phase produces a named bitstream: `BOOT_phaseA.BIN`, `BOOT_phaseB.BIN`
- Python scripts versioned: `v2` (current), `v3` (Phase A), `v4` (Phase B)
- If Phase A synthesis fails timing: reduce FIR to 32 taps
- If Phase B DMA rework is too complex: stay on Phase A (still a major improvement)

## Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FIR tap count | 48 (symmetric → 24 unique) | Balances rejection (~38 dB) vs DSP48 budget |
| FIR architecture | Time-shared (1 filter, 2 channels) | Halves DSP48 usage, 100 MHz clock gives 100× margin at 1 Msps |
| Accumulator width | 48-bit | Matches existing xcorr_acc, 6 bits headroom over worst case |
| Register readback | 48-bit split (LO/HI) | Fixes 32-bit truncation bug seen in debug |
| Cal rotation | Q1.15 cos/sin | 15-bit fractional precision ≈ 0.002° angular resolution |
| Phase A→B transition | Large single DMA transfer | Simpler than ring buffer, eliminates per-snapshot overhead |
| Phase C eigen | Closed-form 2×2 | No iterative solver needed for 2-element array |
