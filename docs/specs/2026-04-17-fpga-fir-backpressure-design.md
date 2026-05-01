# FPGA Phase A — FIR Backpressure & Pipeline AXI-Stream Compliance

**Date:** 2026-04-17
**Status:** Draft — brainstorming in progress
**Related:** `docs/specs/2026-04-09-fpga-phase-a-design.md`, the project notes "Current Blockers — FIR throughput bottleneck"

---

## TL;DR (one-paragraph elevator pitch for later)

The Phase A `doa_pipeline` accepts DMA samples at ~25 MSPS but the 48-tap time-shared FIR can only produce output pairs every ~50 cycles (~1 MSPS when `filter_en=1`). Because `channel_splitter.s_axis_tready` is tied high, the DMA has no way to know the FIR is busy, so ~98% of samples are lost — and worse, the FIR's delay-line shift registers advance *during* its own MAC computation, causing each accumulator to be computed against a mutating snapshot of the delay line (a silent correctness bug, visible as noisier bandpass-mode DoA estimates). This change wires proper AXI-Stream backpressure end-to-end through the pipeline, making every stage honestly handshake-compliant rather than relying on a "downstream is faster than upstream" timing guarantee. The win is twofold: bandpass/lowpass throughput recovers toward the DMA-limited rate (no more 50× sparsification), and the FIR MACs now operate on a frozen delay line so the arithmetic matches the fixed-point reference.

---

## Problem context (for the thesis chapter)

### Current pipeline

```
DMA (~25 MSPS) ──► channel_splitter ──► fir_filter_sc16 ──► phase_rotate (ch1) ──► interleaver ──► xcorr_acc
                      │                     │                                      │             └► autocorr_acc
                      │                     └─ 48-tap time-shared, ~50 cyc/pair    │
                      │                        (~1 MSPS when filter_en=1,          │
                      │                         1 cyc/pair in bypass)              │
                      └─ s_axis_tready = 1'b1 (CONSTANT — no backpressure)         └─ 2 cyc/pair
```

### Two observed symptoms, one root cause

1. **Throughput:** bandpass/lowpass run at ~3 Hz iteration rate vs bypass's ~10 Hz. The v3 driver works around part of this by polling STATUS at 2 kHz instead of 50 Hz, but the underlying FPGA throughput loss is ~50×.
2. **Noise in filtered mode:** bypass gives <2° std-dev on a static source; bandpass shows visibly noisier angle estimates even after the v3 driver's fixes.

Both symptoms stem from the same RTL decision in `channel_splitter.v:51` — `assign s_axis_tready = 1'b1` — inherited from the original `xcorr_acc_axi` which had no multi-cycle stage downstream.

### Why the delay-line corruption matters even more than raw throughput

In `fir_filter_sc16.v`, the delay-line shift (`always @(posedge clk) if (ch0_tvalid) ...`) is outside the MAC FSM. While the FSM is in `COMP_CH0` or `COMP_CH1`, any new `tvalid` still shifts the delay line. The combinational symmetric-pair wires (`ch0_sym_i`, etc.) read whatever is currently in the array. So over ~50 MAC cycles, the FIR is summing `coeff[k] * (delay_now[k] + delay_now[47-k])` where `delay_now` is mutating under it — each tap's contribution comes from a different snapshot.

In bypass, output is latched in one cycle, so no mutation window exists. That matches the field observation: bypass clean, filter noisy.

---

## Design decisions log

> Each decision below is recorded with **Choice**, **Why**, **Alternatives considered**, **Trade-off accepted**. This log is appended during brainstorming so the rationale is preserved for thesis writeup and future maintenance.

### D1 — Scope: fix the bug, not just the throughput

- **Choice:** Treat this as a correctness + throughput fix, not a throughput-only optimization. Verify the delay-line corruption via iverilog comparison against a NumPy golden reference first, then land backpressure + write regression tests that catch both failure modes.
- **Why:** the project notes's Known Issues entry describes this as a throughput-only problem ("FIR output quality is correct, just throughput-limited"). Reading the RTL carefully shows that framing is incomplete — the delay line mutates mid-MAC whenever the FIR is throttled upstream, so filtered-mode output is off. Catching this now means the backpressure fix also explains the "filter noisy vs bypass clean" asymmetry, which is useful thesis material.
- **Alternatives considered:** (A) ship backpressure alone and keep the Known-Issues framing; (C) treat FIR output as good-enough per v3 driver observations and leave it.
- **Trade-off accepted:** +~20 min of iverilog sim work up front, in exchange for a cleaner narrative and a regression test that prevents this specific failure mode from ever silently reappearing.

### D2 — Backpressure depth: propagate AXI-Stream ready end-to-end

- **Choice:** Make every stage of the pipeline honest-AXI-Stream: `channel_splitter`, `fir_filter_sc16`, `phase_rotate_sc16`, and the wrapper's interleaver all declare `tready` as a real input, and the DMA-facing `s_axis_tready` is the logical AND of all downstream readiness signals (with any needed pipeline-aware buffering).
- **Why:** Today the xcorr/autocorr path only works because the FIR is ~25× slower than the 2-cycle interleaver — it's a timing guarantee, not an architectural one. After adding FIR backpressure we'd still be one optimization away (parallel MACs, shorter taps, DSP block use) from silently overwriting `buf_ch0/buf_ch1`. Making every stage self-defending removes that landmine for the next person (thesis reviewer, future maintainer, future me).
- **Alternatives considered:** (a) only fix the DMA↔splitter↔FIR boundary; rely on timing math to prove the interleaver stays safe.
- **Trade-off accepted:** Touch one more module (`xcorr_acc` handshake) and add one extra "interleaver busy" gate. ~10 additional lines, a few more testbench cases. Worth it for explainability — "the pipeline uses standard AXI-Stream flow control everywhere" is a one-sentence thesis claim; the alternative needs a timing-analysis footnote.

### D3 — Readiness expression lives inside the FIR module

- **Choice:** `fir_filter_sc16` exports its own `m_tready_for_pair` (or equivalent) output. The expression `(state == IDLE) && !ch0_pending && !ch1_pending` is computed inside the module, not by the wrapper.
- **Why:** The readiness condition is a pure function of FIR-internal FSM state. Exposing internals to the wrapper couples two files that should be independent. If the FSM is ever refactored (e.g., to a pipelined MAC with shorter critical path), the ready expression updates in the same file — the wrapper doesn't move. This also matches standard Xilinx/ARM AXI-Stream slave convention: every stream port publishes its own `tready`.
- **Alternatives considered:** (b) expose raw `busy` and compute ready in the wrapper; (c) let `channel_splitter` peek at FIR state directly.
- **Trade-off accepted:** One extra output wire per AXI-Stream slave port in the FIR. Essentially free; the cost is all in the naming/interface design, which we do once.

### D4 — Handshake style at the DMA↔splitter boundary: Xilinx `axis_register_slice`

- **Choice:** Insert Xilinx's stock `axis_register_slice` IP in the Vivado block design between `AXI DMA M_AXIS_MM2S` and `doa_pipeline.s_axis`. `channel_splitter.s_axis_tready` becomes a real input driven combinationally from FIR ready; the register-slice IP registers the handshake toward the DMA.
- **Why:** The RTL change in `channel_splitter.v` is the same size as the pure-combinational approach (~5–8 lines), but routing through Xilinx's certified IP breaks the FIR→DMA combinational path with a registered stage. Benefits:
  - **Zero timing risk** — registered `tready` guarantees no long combinational path from FIR FSM state to the DMA interface, regardless of future clock upgrades or fanout changes.
  - **Zero debug risk on the skid behavior itself** — Xilinx IP has a formal spec and is widely battle-tested; hand-rolled skid buffers have a reputation for off-by-one replay bugs.
  - **Thesis-friendly** — one-sentence description: "an `axis_register_slice` inserts a registered handshake between DMA and the pipeline, standard Xilinx AXI-Stream reference pattern."
  - **Marginal cost** — since we already need a Vivado respin for every other RTL change here, adding one IP block is ~3–5 minutes of block-design editing.
- **Alternatives considered:**
  - **(i) Pure combinational `tready`** driven by FIR ready, no register-slice. Meets timing today (+3.74 ns slack, added AND-gate path costs ~1–2 ns) but creates a long combinational path from FSM state out to the DMA. Works, but fragile to future changes.
  - **(ii) Hand-rolled skid buffer** in Verilog (`held_beat` register + valid flag + replay logic). ~15–25 lines of RTL, reputation for subtle off-by-one bugs in the replay cycle. Pure downside vs (ii').
- **Trade-off accepted:** One extra IP instance in the block design (not in RTL), one additional connectivity validation step during synthesis, plus `axis_register_slice` itself costs a small number of FFs (~100, negligible vs our 43% FF budget). **Fallback if licensing/tool issues block this:** option (i) is a clean drop-in replacement — same `channel_splitter` RTL change, just remove the IP block and wire DMA straight to `doa_pipeline`. The RTL is designed to work in either configuration.

---

## Before/after pipeline diagrams

### Before (current — broken)

```
                                           tready = 1'b1 (hardwired)
                                         ◄────────────────────┐
                                                              │
 [AXI DMA]                                                    │
 MM2S_tdata ─────► [channel_splitter] ── ch0_tvalid ──────┐   │
 MM2S_tvalid ────►                                        │   │
                                       ── ch1_tvalid ──┐  │   │
                                                       │  │   │
                                                       ▼  ▼   │
                                             [fir_filter_sc16]│
                                             (48 taps, ~50    │
                                              cyc/pair MAC)   │
                                                       │      │
                                                       │ one-cycle tvalid pulses
                                                       │ (ch0_out, ch1_out)
                                                       ▼
                                                    [buf_ch0]   (latch w/ valid)
                                                    [buf_ch1]   (latch w/ valid)
                                                       │
                                                 2 cyc drain
                                                       │
                                                       ▼
                                           [xcorr_acc]  (tready dangling)
                                           [autocorr_acc]

 BUGS:
   ▲ DMA sends at ~25 MSPS, FIR consumes at ~1 MSPS → 98% of samples
     never enter the MAC. Throughput bottleneck.
   ▲ Delay-line shift registers in the FIR advance on EVERY tvalid —
     even while the MAC FSM is mid-computation. So each MAC sum is
     taken over a mutating snapshot of the delay line. Correctness bug,
     visible as noisy filtered-mode DoA estimates (vs clean bypass).
```

### After (proposed — fixed)

```
                              ┌──── registered tready ─────┐
                              │                            │
 [AXI DMA]                    │                            │
 MM2S_tdata ─────►[axis_register_slice]─ tdata ──►[channel_splitter]
 MM2S_tvalid ────► (Xilinx IP,            tvalid            │
                    1-deep skid,          tready ◄──────────┘ (combinational
                    registered ports)                          from fir_ready)
                                                               │
                                                               │ tready into
                                                               │ splitter =
                                                               │ FIR's published
                                                               │ ready
                                                               ▼
                                                     [fir_filter_sc16]
                                                     publishes:
                                                       m_ready (= IDLE && !pending)
                                                       m_tvalid (output pair)
                                                     expects:
                                                       m_tready (from interleaver)
                                                               │
                                                               │ FIR holds its
                                                               │ OUTPUT state
                                                               │ until interleaver
                                                               │ accepts
                                                               ▼
                                                     [interleaver]
                                                     drops m_tready when
                                                     buf_ch0_valid &&
                                                     buf_ch1_valid
                                                               │
                                                               ▼
                                                     [xcorr_acc]   (publishes
                                                                    tready = 1'b1,
                                                                    declared)
                                                     [autocorr_acc] (same)

 FIXES:
   ▲ DMA can be told "wait" — tready goes low while FIR MAC is running.
     When FIR finishes (~50 cycles later) and its output pair is drained
     by the interleaver, tready rises again. No more dropped samples.
   ▲ Because the FIR no longer accepts new samples during COMP_CH0/COMP_CH1,
     the delay lines cannot shift mid-MAC. Each accumulator sees a consistent
     snapshot. Arithmetic now matches the fixed-point reference.
   ▲ Every AXI-Stream port in the pipeline publishes its own tready.
     Implicit timing invariants ("xcorr faster than FIR") are replaced
     with explicit handshake — the RTL is honestly flow-controlled.
```

### Flow-control legend

```
  ─────►  tdata / tvalid  (data flowing downstream)
  ◄─────  tready          (backpressure flowing upstream)
  [box]   RTL module or Xilinx IP
```

---

## Design (to be filled in as we confirm each section)

### Architecture change summary

Summary of what moves where, in one paragraph per scope:

**Block design.** Insert one `axis_register_slice` IP between `axi_dma_0/M_AXIS_MM2S` and `doa_pipeline_0/s_axis`. No other BD changes; same clock, same reset, same register-map base address. All 15 AXI-Lite registers keep their current offsets and semantics.

**RTL.** Three modules gain AXI-Stream `tready` handshake ports; one module gets a correctness fix on its delay-line shift gating. Concretely:
- `channel_splitter.v` — `s_axis_tready` goes from `1'b1` to a combinational function of downstream FIR ready.
- `fir_filter_sc16.v` — publishes `m_ready` (slave-side) and `m_tready`-aware `m_tvalid` (master-side); delay-line shift gated on `state == IDLE`.
- `phase_rotate_sc16.v` — declares `s_tready` and `m_tready`, trivially always ready.
- `xcorr_acc.v` — declares `s_axis_tready = 1'b1` instead of leaving it dangling.
- `doa_pipeline.v` — wires the new handshake signals; interleaver asserts "not ready" when both `buf_ch*_valid` are set.

**Testbenches.** Five files touched (one new Python post-process script), all additive — existing test cases stay. See D5 for the full inventory.

**Driver (`cora_headless/aoa_estimation_fpga_v3.py`).** **No change** expected. Register map is identical; STATUS semantics unchanged. The current 0.5 ms STATUS poll timeout may become unnecessary once bandpass throughput recovers, but leaving it at 0.5 ms is harmless.

**Yocto / rootfs.** **No change.** Same bitstream loader, same init.d script, same udev rules. Only the `BOOT.BIN` / bitstream on the Phase A SD card changes. Phase 0 fallback card remains untouched as escape hatch.

**Measured expected impact.** Bandpass iteration rate: 3 Hz → ≥ 8 Hz (targeting closer to 10 Hz bypass rate). Filtered-mode DoA std-dev: drops to within 1.5× of bypass (currently visibly worse). No change to bypass mode, since `filter_en=0` already avoids the MAC path entirely.

### Module interface changes

All changes are **additive** — existing ports keep their names. New ports are added to carry the AXI-Stream ready signal at each stage.

#### `channel_splitter.v`
- `s_axis_tready` changes from internally-driven (`= 1'b1`) to **combinationally driven** by a new input port wired to the downstream FIR's `m_ready`.
- Add ports:
  - `input wire s_axis_tready_in` *(new — gating signal; the module's own `s_axis_tready` output is a pass-through plus the beat-phase gate)*
- Beat-phase FSM now advances only when `s_axis_tvalid && s_axis_tready` (AXI-Stream handshake).

#### `fir_filter_sc16.v`
- Add ports:
  - `output wire m_ready` — slave-side ready: asserts when the FIR can accept a new sample pair (`state == IDLE && !ch0_pending && !ch1_pending`).
  - `output reg m_tvalid` — master-side valid: rises one cycle after the OUTPUT state, **stays high until `m_tready` is asserted** (previously was a one-cycle pulse).
  - `input wire m_tready` — master-side ready, from interleaver.
- The existing `ch0_out_tvalid` / `ch1_out_tvalid` one-cycle pulses are **replaced** by the handshake-compliant `m_tvalid` / `m_tready` pair. (ch0/ch1 data emit together; no more implicit two-port semantics.)
- Delay-line shift is **gated on `state == IDLE`** — this is the correctness fix. Shifts only happen between MACs, not during.

#### `phase_rotate_sc16.v`
- Add ports:
  - `output wire s_tready` — trivially always high (single-cycle combinational rotate); declared for protocol compliance.
  - `input wire m_tready` — pass-through to the slave-side ready of the sink.
- Internal latency is 1 cycle; `m_tvalid` stays high until `m_tready`.

#### `xcorr_acc.v`
- Add port:
  - `output wire s_axis_tready` — declared and tied to `1'b1`. Formalizes what was previously dangling.

#### `doa_pipeline.v` (wrapper)
- Wire the new ready signals:
  - `splitter.s_axis_tready_in  ← fir.m_ready`
  - `fir.m_tready               ← interleaver's "not full" signal (`!(buf_ch0_valid && buf_ch1_valid)`)`
  - `rotate.m_tready            ← interleaver's "not full" signal` (same condition as FIR)
- The interleaver block (lines 178-239 of current `doa_pipeline.v`) gets a small rewrite: clear `buf_ch0_valid`/`buf_ch1_valid` at the right handshake edges, assert "not ready" while both are full.
- Block-design level: insert `axis_register_slice` between AXI DMA `M_AXIS_MM2S` and the new `doa_pipeline.s_axis` port. Both sides keep `TDATA_WIDTH=32`. Default config (1-deep skid, both `REG_CONFIG=1`).

### Testbench plan

#### D5 — Dual verification path: Verilog behavioral reference (A2) + Python NumPy diff (A1)

- **Choice:** Run both an in-simulation Verilog behavioral reference model and a Python post-process comparison, rather than pick one.
- **Why:**
  - **A2 alone** gives fast pass/fail in `vvp` — good for iterating on the RTL fix, but no visualization.
  - **A1 alone** gives thesis-quality comparison plots (delay-line-corrupted output overlaid with fixed output and golden reference) but requires a two-step flow.
  - **A1's cost is near zero** because the NumPy reference already exists in `cora_headless/aoa_estimation_fpga_v3.py` — same windowed-sinc coefficients, same convolution. We wrap it as a function and reuse.
  - **A2's cost is one-time** (~30 lines of Verilog behavioral FIR in the testbench).
  - Together you get: fast local iteration (A2) + a thesis figure that literally shows the bug and the fix side by side (A1).
- **Alternatives considered:** Pick one; skip investigation entirely and hope the fix works (rejected in D1).
- **Trade-off accepted:** One extra `$fwrite` in `tb_fir_filter_sc16` to dump input/output as CSV (~5 lines) and a Python script (~40 lines, mostly matplotlib) under `fpga/tb/plot_fir_diff.py`. Thesis figure is worth it.

#### Test case inventory

Added in this change:

1. **`tb_channel_splitter`** — new case: drop `tready` for N cycles, verify `beat_phase` does not advance until tready rises. Verify last-held beat replays on rising tready.
2. **`tb_fir_filter_sc16`** —
   - Full-rate input test (ties `s_axis_tvalid=1` every cycle) against the **in-sim Verilog behavioral reference** (A2). On the current RTL this should FAIL; after the fix, PASS.
   - `m_tready` stall test: hold `m_tready` low, verify `m_tvalid` stays high (pair held, not re-emitted) and that `m_ready` (slave-side) goes low (FIR refuses new input pairs).
   - `$fwrite` dump of input/output CSV for Python post-process (A1).
3. **`tb_doa_pipeline`** — full-rate DMA test that counts N snapshots, verifies `SNAP_COUNT` matches expected (today this test would show 1/50 the expected count).
4. **`tb_xcorr_acc`** — trivial: verify tready is now declared and stays high.
5. **`fpga/tb/plot_fir_diff.py`** (new) — reads CSV dump from #2, computes NumPy golden reference, emits max-abs-error / std-dev metrics and a 3-trace comparison plot (current-RTL, fixed-RTL, golden).

#### Regression protection

The full-rate test in `tb_fir_filter_sc16` is the one that catches this specific bug class. If a future refactor ever breaks backpressure (e.g., someone re-ties `s_axis_tready = 1'b1` in `channel_splitter`), the delay-line corruption returns and this test fails. That's exactly the regression-prevention guarantee we want.

### Vivado respin checklist

On the build VM (`vmau@192.168.122.93`), project `cora_doa_hw`:

1. **Copy updated RTL** to the VM's project source tree (same paths used in `fpga/rtl/`).
2. **Open block design** (`cora_doa_hw.xpr → design_1.bd`).
3. **Insert `axis_register_slice`** between `axi_dma_0/M_AXIS_MM2S` and `doa_pipeline_0/s_axis`. Default config. Connect `aclk` and `aresetn` to the existing 50 MHz domain.
4. **Validate design** — connectivity check should pass with no new warnings (besides the existing harmless `xfft_0 s_axis_data_tvalid` one).
5. **Run synthesis** — check LUT/FF/DSP deltas are small (expect <1% change). WNS should stay comfortably positive.
6. **Run implementation** — verify timing met (WNS still positive, TNS = 0). **If the `doa_pipeline/splitter/fir` critical path degrades below ~+1 ns slack, re-examine:** likely the interleaver "not full" signal needs a registered stage.
7. **Generate bitstream.**
8. **Export hardware** (`.xsa`) and update the Cora Phase A SD card's `BOOT.BIN` / device tree if needed (no DT change expected — same IP, same register map).

Exit criteria for the VM side: clean implementation report, positive slack, bitstream in hand.

### Verification on Cora

The pre-change Phase A SD card is preserved as the **A/B baseline** — any behavioral regression can be diagnosed by a card swap rather than a git bisect.

#### Acceptance criteria

1. **Throughput.** Bandpass/lowpass iteration rate ≥ 8 Hz (current: ~3 Hz). Bypass mode stays at ≥ 10 Hz (no regression vs pre-change card).
2. **Filtered-mode noise floor.** ROOTMUSIC std-dev on a static source with bandpass enabled ≤ 1.5× the bypass-mode std-dev on the same source. Measured against pre-change card where the gap is visibly larger.
3. **Register map.** All 15 Phase A AXI-Lite registers round-trip via `fpga/phase_a_register_test.sh` (no regressions in the slave).
4. **Calibration convergence.** ARM and FPGA cal offsets agree within ±2° on the same static source after the fix — closing out the "filter-path mismatch" theory noted in the project notes.
5. **Stability.** 5-minute run with bandpass filter enabled: no dropped snapshots, no STATUS-poll timeouts, no USB hub disruption from load changes.

#### Measurement procedure

With the pre-change card installed first:
- Capture 2 minutes of ROOTMUSIC data on a static source, bandpass enabled. Save CSV + sidecar JSON.
- Capture 2 minutes of the same source, bypass enabled. Save CSV + sidecar JSON.
- Record iteration-rate from the JSON (`rate` field).

Swap to new-bitstream card, repeat both captures.

Compare via `scripts/analyze_arm_vs_fpga.py` (or a new small script if needed) — plot std-dev, mean offset, and iteration-rate side by side. This becomes the thesis figure.

#### Rollback plan

If any acceptance criterion fails and the root cause isn't clear within ~1 hour of debugging: put the pre-change SD card back in, flag the failing criterion in the project notes's Known Issues, and return to the spec. The bitstream change is self-contained (one SD card), so rollback is trivial — no PetaLinux rebuild, no Yocto recipes.
