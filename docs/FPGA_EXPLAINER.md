# FPGA Cross-Correlation Accelerator — Full Explainer

> For the Cora Z7 (Zynq-7000 XC7Z007S) 2.4 GHz DoA system.
> Reference files: `fpga/rtl/xcorr_acc.v`, `fpga/rtl/xcorr_acc_axi.v`, `cora_headless/aoa_estimation_fpga_v2.py`

---

## 1. What Problem Does the FPGA Solve?

Direction of Arrival (DoA) estimation boils down to one key math operation:

```
r₀₁ = (1/N) × Σ ch0[n] · conj(ch1[n])     for n = 0 .. N-1
```

This is the **cross-correlation** between the two antenna channels. It's the off-diagonal entry of the 2×2 covariance matrix R:

```
R = | r₀₀   r₀₁ |
    | r₁₀   r₁₁ |
```

Where:
- **r₀₀** = power of channel 0 (auto-correlation)
- **r₁₁** = power of channel 1 (auto-correlation)
- **r₀₁** = cross-correlation (encodes phase difference → angle)
- **r₁₀** = conj(r₀₁)

On the ARM Cortex-A9 (650 MHz, no FPU for complex math), computing this over 1024 samples with 4 multiplies per sample is the bottleneck. The FPGA does the same computation in hardware at 100 MHz, one sample per clock cycle, using dedicated DSP48 multiply-accumulate units.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Zynq-7000 SoC                             │
│                                                                  │
│  ┌─────────────────────┐        ┌──────────────────────────────┐ │
│  │   ARM Cortex-A9     │        │        FPGA Fabric (PL)      │ │
│  │   (Processing       │        │                              │ │
│  │    System / PS)     │        │  ┌────────┐   ┌───────────┐  │ │
│  │                     │        │  │AXI DMA │──▶│xcorr_acc  │  │ │
│  │  Python script      │        │  │(MM2S)  │   │_axi       │  │ │
│  │  ┌───────────────┐  │        │  │        │   │           │  │ │
│  │  │aoa_estimation │  │        │  │scatter │   │┌─────────┐│  │ │
│  │  │_fpga_v2.py    │  │        │  │gather  │   ││xcorr_acc││  │ │
│  │  │               │  │AXI-Lite│  │        │   ││(MAC     ││  │ │
│  │  │ read results ◀├──┼────────┼──┤        │   ││ engine) ││  │ │
│  │  │               │  │(regs)  │  └────────┘   │└─────────┘│  │ │
│  │  │ send samples ─┼──┼────────┼──▶  DDR buf   │  reg map: │  │ │
│  │  │  via DMA      │  │        │               │  0x00 RE  │  │ │
│  │  └───────────────┘  │        │               │  0x04 IM  │  │ │
│  │                     │        │               │  0x08 STAT│  │ │
│  └─────────────────────┘        │               │  0x0C CNT │  │ │
│                                 └──────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
         │                                        ▲
         │ USB                                    │ SoapySDR
         ▼                                        │
    ┌──────────┐                            ┌──────────┐
    │BladeRF   │  2 RX channels ──────────▶ │ IQ data  │
    │2.0 xA4   │  (2.4 GHz, SC16)          │ ch0, ch1 │
    └──────────┘                            └──────────┘
```

### Data Flow (step by step)

1. **BladeRF** captures IQ samples on 2 channels at 2.4 GHz
2. **Python** reads samples via SoapySDR (CF32 float format)
3. **Python** converts CF32 → SC16 (multiply by 32767, clip to int16)
4. **Python** interleaves ch0/ch1 beats into a DMA buffer in DDR
5. **Python** programs AXI DMA scatter-gather descriptor
6. **DMA** streams the buffer to the FPGA as AXI-Stream beats
7. **xcorr_acc** computes the MAC in real-time, accumulates over 1024 samples
8. **xcorr_acc_axi** latches the result into AXI-Lite registers
9. **Python** reads the registers via `/dev/mem` to get (xcorr_re, xcorr_im)
10. **Python** builds the full 2×2 covariance matrix R
11. **Python** runs Root-MUSIC / MUSIC on R to estimate the angle

---

## 3. The Compute Core: `xcorr_acc.v`

**File:** `fpga/rtl/xcorr_acc.v` (123 lines)

This is the heart of the accelerator. It's a **streaming multiply-accumulate (MAC)** engine.

### 3.1 Parameters

```verilog
parameter SNAPSHOT_LEN = 1024,  // how many sample pairs to accumulate
parameter ACC_WIDTH    = 48     // accumulator width (prevents overflow)
```

- **SNAPSHOT_LEN = 1024**: Matches the Python config. After 1024 sample pairs, the result is latched and accumulators reset.
- **ACC_WIDTH = 48**: Each multiply produces a 32-bit result (16×16). Summing 1024 of them needs log2(1024)=10 extra bits → 42 bits minimum. 48 bits gives 6 bits of headroom.

### 3.2 Interface

```verilog
// AXI-Stream input: 32-bit, two beats per sample pair
input  wire [31:0] s_axis_tdata,
input  wire        s_axis_tvalid,
output wire        s_axis_tready,      // always 1 (never stalls)

// Result output: pulses for one clock cycle per snapshot
output reg  [47:0] xcorr_re,           // real part of r₀₁
output reg  [47:0] xcorr_im,           // imaginary part of r₀₁
output reg         result_valid
```

The input uses the **AXI-Stream** protocol (industry standard for streaming data in FPGAs). Each IQ sample pair arrives as two 32-bit beats:

```
Beat 0 (beat_phase=0):  |  ch0_Q [31:16]  |  ch0_I [15:0]  |
Beat 1 (beat_phase=1):  |  ch1_Q [31:16]  |  ch1_I [15:0]  |
```

This is the SC16 format — signed 16-bit integers for I (in-phase) and Q (quadrature) components.

### 3.3 Internal Registers

```verilog
reg beat_phase;                              // 0 = expecting ch0, 1 = expecting ch1
reg signed [15:0] ch0_i, ch0_q;             // captured ch0 from beat 0
reg [$clog2(SNAPSHOT_LEN)-1:0] sample_cnt;  // counts 0..1023
reg signed [47:0] acc_re, acc_im;            // running accumulator
```

### 3.4 The State Machine (annotated)

The entire engine is one `always @(posedge clk)` block with a 1-bit state (`beat_phase`):

```
                    ┌──────────────────┐
                    │    RESET         │
                    │ (all regs = 0)   │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
              ┌────▶│  beat_phase = 0   │ ◀── waiting for ch0
              │     │  (capture ch0)    │
              │     └────────┬─────────┘
              │              │ tvalid=1: save ch0_i, ch0_q
              │     ┌────────▼─────────┐
              │     │  beat_phase = 1   │ ◀── waiting for ch1
              │     │  (compute MAC)    │
              │     └────────┬─────────┘
              │              │ tvalid=1: fire MAC
              │              ├─── sample_cnt < 1023: increment counter
              │              └─── sample_cnt == 1023: latch result, reset
              └──────────────┘
```

### 3.5 The MAC Equations (lines 95-96)

This is the complex conjugate multiplication expanded into real arithmetic:

```
Given:  ch0 = a + jb    (ch0_i = a, ch0_q = b)
        ch1 = c + jd    (ch1_i = c, ch1_q = d)

We want: ch0 × conj(ch1) = (a + jb)(c - jd)

Expanding:
    Real part:  ac + bd    =  ch0_i × ch1_i  +  ch0_q × ch1_q
    Imag part:  bc - ad    =  ch0_q × ch1_i  -  ch0_i × ch1_q
```

In Verilog:
```verilog
acc_re <= acc_re + (ch0_i * beat_i) + (ch0_q * beat_q);   // ac + bd
acc_im <= acc_im + (ch0_q * beat_i) - (ch0_i * beat_q);   // bc - ad
```

**Why conjugate of ch1 (not ch0)?** By convention, the cross-correlation r₀₁ is defined as E[ch0 · conj(ch1)]. The conjugate flips the sign of ch1's imaginary part, which makes the resulting phase angle represent the direction the signal arrives from relative to the array.

### 3.6 Snapshot Boundary (lines 98-109)

```verilog
if (sample_cnt == SNAPSHOT_LEN - 1) begin
    // Latch the FINAL accumulated value (including this cycle's MAC)
    xcorr_re     <= acc_re + (ch0_i * beat_i) + (ch0_q * beat_q);
    xcorr_im     <= acc_im + (ch0_q * beat_i) - (ch0_i * beat_q);
    result_valid <= 1;     // one-cycle pulse
    acc_re       <= 0;     // reset for next snapshot
    acc_im       <= 0;
    sample_cnt   <= 0;
end
```

**Why is the MAC duplicated in the latch?** The accumulator update (`acc_re <= acc_re + ...`) won't be visible until the next clock edge. To include the final sample in the output, the latch computes `acc_re + (this cycle's product)` directly. Without this, the last sample would be lost.

### 3.7 Backpressure

```verilog
assign s_axis_tready = 1'b1;    // always ready
```

The core never stalls the DMA. At 100 MHz clock and ~4 MHz sample rate, the FPGA is ~25× faster than the data arrival rate, so there's no need for flow control.

### 3.8 Resource Usage

- **4 DSP48 slices** — two for the real MAC (ch0_i×ch1_i, ch0_q×ch1_q) and two for the imaginary MAC (ch0_q×ch1_i, ch0_i×ch1_q). The Zynq XC7Z007S has 66 DSP48s, so this uses ~6%.
- **Minimal LUTs/FFs** — the state machine is just a 1-bit toggle, a 10-bit counter, and two 48-bit accumulators.

---

## 4. The AXI Wrapper: `xcorr_acc_axi.v`

**File:** `fpga/rtl/xcorr_acc_axi.v` (200 lines)

This wraps the compute core with an **AXI-Lite slave** interface so the ARM processor can read results as memory-mapped registers.

### 4.1 Register Map (base address: 0x4000_0000)

| Offset | Name       | Access | Description |
|--------|-----------|--------|-------------|
| 0x00   | XCORR_RE  | Read   | Real part of cross-correlation (lower 32 of 48 bits) |
| 0x04   | XCORR_IM  | Read   | Imaginary part (lower 32 of 48 bits) |
| 0x08   | STATUS    | Read   | Bit 0 = new result ready (sticky, **cleared on read**) |
| 0x0C   | SNAP_CT   | Read   | Lifetime snapshot counter |

### 4.2 Result Latching (lines 103-120)

```verilog
if (result_valid_pulse) begin
    reg_xcorr_re  <= xcorr_re_raw[31:0];   // truncate 48→32 bits
    reg_xcorr_im  <= xcorr_im_raw[31:0];
    reg_valid     <= 1;                      // set sticky flag
    reg_snap_count <= reg_snap_count + 1;
end
```

When the core completes a snapshot, the wrapper:
1. Captures the 48-bit result into 32-bit holding registers
2. Sets the `reg_valid` sticky bit
3. Increments the snapshot counter

The ARM can then read at its leisure — the values are held stable until the next snapshot overwrites them.

### 4.3 Clear-on-Read (lines 154-163)

```verilog
if (axi_araddr[3:2] == 2'b10)    // reading STATUS register (0x08)
    clear_valid <= 1;              // clears the sticky valid bit
```

Reading the STATUS register automatically clears the valid bit. This is a common hardware pattern — the ARM doesn't need a separate "acknowledge" write. The sequence is:

1. ARM reads STATUS → gets `1` (new result ready), valid bit auto-clears
2. ARM reads XCORR_RE → gets the real part
3. ARM reads XCORR_IM → gets the imaginary part
4. FPGA computes next snapshot, sets valid again

### 4.4 AXI-Lite Read State Machine (lines 126-164)

The read side follows the standard AXI-Lite handshake:

```
ARM (master)                    FPGA (slave)
─────────────                   ────────────
ARVALID=1, ARADDR=0x00  ──▶    sees ARVALID, asserts ARREADY
                         ◀──   ARREADY=1 (address accepted)
                         ◀──   RVALID=1, RDATA=reg_xcorr_re
RREADY=1                 ──▶   sees RREADY, deasserts RVALID
```

### 4.5 AXI-Lite Write Logic (lines 167-198)

All registers are read-only, but the AXI-Lite protocol **requires** the slave to respond to writes. The write logic accepts any write, responds with OKAY, and discards the data.

### 4.6 AXI-Stream Interface Attributes (lines 61-67)

```verilog
(* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TDATA" *)
(* X_INTERFACE_PARAMETER = "CLK_DOMAIN s_axi_aclk, FREQ_HZ 50000000, ..." *)
```

These are **Vivado IP Integrator directives** — they tell the block design tool that these ports form an AXI-Stream interface so it can auto-connect them to the DMA.

---

## 5. The Python Driver: `FPGAXcorr` Class

**File:** `cora_headless/aoa_estimation_fpga_v2.py` (class at line 142)

### 5.1 Memory Mapping (setup, lines 153-169)

The driver accesses hardware through `/dev/mem` — Linux's raw physical memory device:

```python
self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
self.xcorr_m = mmap.mmap(self.fd, PAGE_SIZE, offset=0x40000000)  # xcorr registers
self.dma_m   = mmap.mmap(self.fd, PAGE_SIZE, offset=0x40400000)  # DMA registers
self.desc_m  = mmap.mmap(self.fd, PAGE_SIZE, offset=0x1F000000)  # SG descriptor
self.buf_m   = mmap.mmap(self.fd, buf_pages,  offset=0x1F001000) # DMA data buffer
```

| Region | Physical Address | Purpose |
|--------|-----------------|---------|
| xcorr regs | 0x4000_0000 | Read cross-correlation results |
| DMA regs | 0x4040_0000 | Control the AXI DMA engine |
| SG descriptor | 0x1F00_0000 | Scatter-Gather descriptor (tells DMA what to transfer) |
| DMA buffer | 0x1F00_1000 | Raw sample data written by Python, read by DMA |

### 5.2 Data Conversion: CF32 → SC16 (lines 193-205)

```python
# BladeRF gives float samples in [-1, 1] range
scale = 32767.0
ch0_i = np.clip(np.real(ch0) * scale, -32768, 32767).astype(np.int16)
ch0_q = np.clip(np.imag(ch0) * scale, -32768, 32767).astype(np.int16)
# ... same for ch1

# Interleave: [ch0_beat, ch1_beat, ch0_beat, ch1_beat, ...]
buf[0::2] = (ch0_q << 16) | ch0_i    # beat 0: ch0
buf[1::2] = (ch1_q << 16) | ch1_i    # beat 1: ch1
```

The FPGA expects SC16 (signed 16-bit integers), but SoapySDR delivers CF32 (complex float32). The driver scales, clips, and packs the data into the exact bit layout the FPGA expects: `{Q[31:16], I[15:0]}`.

### 5.3 DMA Transfer Sequence (compute_xcorr, lines 210-249)

```
Step 1:  Clear previous result by reading STATUS (clear-on-read)
Step 2:  Reset DMA (write 0x0004 to DMACR, poll until cleared)
Step 3:  Write sample data to DMA buffer in DDR
Step 4:  Program SG descriptor (source address, byte count, SOF|EOF flags)
Step 5:  Set CURDESC to descriptor address (must be done while DMA is halted)
Step 6:  Start DMA (write 0x0001 to DMACR)
Step 7:  Write TAILDESC to kick off the transfer
Step 8:  Poll descriptor STATUS bit 31 for completion
Step 9:  Read XCORR_RE (0x00) and XCORR_IM (0x04) from register map
```

### 5.4 Building the Full Covariance Matrix (v2 fix, lines 480-507)

The FPGA only computes **r₀₁** (cross-correlation). The diagonal entries r₀₀ and r₁₁ (auto-correlation / power) are still computed in Python:

```python
# v2 FIX: compute r00/r11 in SC16 units to match FPGA r01
ch0_i = np.clip(np.real(ch0_snap) * 32767, -32768, 32767).astype(np.int16)
acc_r00 += float(np.sum(ch0_i**2 + ch0_q**2))   # SC16² units

# Build the matrix
R = | r00          r01         |
    | conj(r01)    r11         |
```

**Why the v2 fix matters:** In v1, r₀₀ and r₁₁ were computed from CF32 floats (range [-1,1]) then scaled by 32767² to try to match the FPGA output. This introduced rounding errors. v2 converts to SC16 first, then computes power — ensuring all 4 matrix entries are in identical SC16² units.

---

## 6. How It All Connects in Vivado

The block design (`cora_doa_hw.xpr` on the build VM) wires everything together:

```
ZYNQ7 PS ──▶ AXI Interconnect ──┬──▶ AXI DMA (MM2S) ──▶ xcorr_acc_axi (s_axis)
                                 │
                                 └──▶ xcorr_acc_axi (s_axi)  ← register reads
                                 │
                                 └──▶ AXI DMA (s_axi_lite)   ← DMA control
```

- **MM2S** = Memory-Mapped to Stream: DMA reads from DDR (where Python wrote the samples) and streams to the FPGA's AXI-Stream input
- **Scatter-Gather** mode: the DMA reads a descriptor from memory that tells it where the data is and how much to transfer
- The FPGA clock domain is the same as the PS (`s_axi_aclk`), so no clock-domain crossing is needed

---

## 7. Similar Projects & References

These projects use the same architectural patterns and can serve as reference points:

### Cross-Correlation / Beamforming in FPGA

| Project | Similarity | Link |
|---------|-----------|------|
| **KrakenSDR** | 5-channel DoA receiver, same covariance → MUSIC pipeline | github.com/krakenrf/krakensdr_doa |
| **GNU Radio gr-aoa** | The ARM-side module your system is based on; FPGA core replicates `correlate_and_tag` | github.com/MarcinWachowiak/gr-aoa |
| **CASPER (radio astronomy)** | FPGA cross-correlators for antenna arrays, same MAC architecture at much larger scale | casper.astro.berkeley.edu |

### AXI-Stream + DMA Pattern

| Reference | What it shows |
|-----------|--------------|
| **Xilinx XAPP1209** | AXI DMA scatter-gather programming model (same as your Python driver) |
| **PYNQ overlays** | Python + `/dev/mem` + AXI-Lite register access to custom IP (identical pattern) |
| **ZipCPU AXI tutorials** | AXI-Lite slave design with the same handshake state machines | zipcpu.com |

### DoA Theory

| Reference | What it covers |
|-----------|---------------|
| **PySDR DoA chapter** | ULA, covariance matrix, MUSIC algorithm with Python code | pysdr.org/content/doa.html |
| **Van Trees, "Optimum Array Processing"** | The textbook reference for MUSIC, Root-MUSIC, MVDR |
| **Stoica & Moses, "Spectral Analysis of Signals"** | Root-MUSIC derivation and performance analysis |

---

## 8. Key Design Decisions & Trade-offs

| Decision | Rationale |
|----------|-----------|
| **Time-domain MAC** (not FFT-based) | Simpler, maps 1:1 to the existing Python cross-correlation. FFT-based would be more efficient for larger arrays but overkill for 2 elements. |
| **SC16 fixed-point** (not float) | DSP48 slices do integer multiplication natively. Float would need soft-float IP and 10× more resources. |
| **48-bit accumulators** | 16×16 = 32-bit product, summing 1024 needs 10 extra bits = 42 minimum. 48 gives 6 bits of headroom for future snapshot lengths up to 65536. |
| **Always-ready (no backpressure)** | The FPGA processes at 100 MHz, data arrives at ~4 MHz. No stall logic needed = simpler design, fewer bugs. |
| **Sticky valid + clear-on-read** | Decouples FPGA timing from ARM software timing. The ARM can read whenever it's ready without missing results. |
| **r₀₀/r₁₁ in Python** (not FPGA) | Auto-correlation is simpler math (just power = I²+Q²). Adding it to the FPGA would use 2 more DSP48s for marginal benefit. The diagonal doesn't encode angle information — it's just normalization. |
| **DMA scatter-gather** (not PIO) | Writing samples directly to FPGA registers would be too slow. DMA streams data autonomously while the ARM prepares the next batch. |

---

## 9. Summary: What the FPGA Does vs What the ARM Does

| Step | Who | What |
|------|-----|------|
| 1. Capture IQ samples | ARM (SoapySDR) | Read from BladeRF USB |
| 2. Apply calibration | ARM (Python) | Rotate ch1 by cal phase offset |
| 3. Convert CF32 → SC16 | ARM (Python) | Scale and pack for FPGA |
| 4. DMA transfer | FPGA (AXI DMA) | Stream samples to MAC engine |
| 5. Cross-correlation | **FPGA** | MAC over 1024 samples → r₀₁ |
| 6. Read result | ARM (Python) | Read registers via /dev/mem |
| 7. Build covariance R | ARM (Python) | Combine r₀₁ with r₀₀, r₁₁ |
| 8. Eigendecomposition | ARM (Python) | numpy.linalg.eigh(R) |
| 9. Root-MUSIC / MUSIC | ARM (Python) | Polynomial roots or spectral search |
| 10. Output angle | ARM (Python) | Print AOA:XX.X° |

The FPGA handles the **inner loop** (step 5) — the most compute-intensive, repetitive operation. Everything else stays in Python for flexibility.
