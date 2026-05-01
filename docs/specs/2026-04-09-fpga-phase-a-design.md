# FPGA Phase A — Enhanced Datapath Design Spec

**Date:** 2026-04-09
**Parent spec:** `2026-04-07-fpga-expansion-design.md`
**Target:** Cora Z7 (Zynq-7000 XC7Z007S), Vivado 2025.2
**Goal:** Move FIR filtering, phase calibration rotation, and auto-correlations (r00/r11) into the FPGA fabric. ARM still loops 100 snapshots via DMA, but each iteration is reduced to: DMA kick + read 3 register pairs.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FIR tap count | 48 (symmetric -> 24 unique) | ~38 dB stopband rejection, fits DSP48 budget |
| FIR architecture | Time-shared single filter | Processes ch0 then ch1 on same multiplier array. 100 MHz / 1 Msps = 100x clock headroom |
| Coefficient loading | Runtime-loadable via AXI-Lite | Supports bandpass/lowpass/none switching from Python without resynthesis |
| Accumulator width | 48-bit | Matches existing xcorr_acc, 6 bits headroom over worst case |
| Register readback | 48-bit split (LO/HI pairs) | Fixes the 32-bit truncation bug seen in v2 debug output |
| Cal rotation format | Q1.15 cos/sin | 15-bit fractional precision = ~0.002 deg angular resolution |
| Phase rotation | ch1 only | Matches ARM code's apply_calibration() behavior |

## 2. Resource Estimate

| Resource | Phase A Usage | Total Available | % Used |
|----------|--------------|----------------|--------|
| DSP48E1 | ~36 (24 FIR + 4 phase_rot + 4 xcorr + 4 autocorr) | 66 | ~55% |
| LUTs | ~6,000 | 14,400 | ~42% |
| FFs | ~5,000 | 28,800 | ~17% |
| BRAM 18Kb | ~4 (coeff storage + FIR delay lines) | 100 | ~4% |

## 3. Datapath Architecture

```
DMA MM2S (raw SC16, interleaved ch0/ch1 beats)
    |
    v
channel_splitter --- demux beat 0 -> ch0, beat 1 -> ch1
    |           |
    v           v
 FIR(ch0)    FIR(ch1)    <-- time-shared single multiplier array
    |           |
    |           v
    |     phase_rotate    <-- complex multiply by (cos_cal - j*sin_cal)
    |     (ch1 only)
    |           |
    v           v
xcorr_acc (r01 = ch0 * conj(ch1))   <-- existing math, unchanged
autocorr_acc (r00 = |ch0|^2, r11 = |ch1|^2)   <-- new
    |
    v
AXI-Lite registers (48-bit split readback)
ARM reads r01_re, r01_im, r00, r11
```

## 4. New RTL Modules

### 4.1 `channel_splitter`

Demuxes the interleaved 2-beat AXI-Stream into two separate SC16 streams.

- Input: 32-bit AXI-Stream (beat 0 = ch0, beat 1 = ch1)
- Output: two 32-bit SC16 streams with valid signals
- Simple FSM toggling on beat_phase (same logic currently inside xcorr_acc)

### 4.2 `fir_filter_sc16`

Time-shared symmetric FIR filter processing both channels.

- 48 taps, symmetric -> 24 unique coefficients
- Processes I and Q independently (real-coefficient FIR on complex data)
- Coefficient RAM writable via simple addr/data interface
- Filter enable/bypass control bit
- Time-sharing: processes ch0 samples first, then ch1, using same multiplier array

### 4.3 `phase_rotate_sc16`

Complex multiply for calibration phase rotation on ch1.

- (I + jQ) x (cos_cal - j*sin_cal)
- I' = I*cos_cal + Q*sin_cal
- Q' = Q*cos_cal - I*sin_cal
- cos_cal and sin_cal are Q1.15 fixed-point, writable via AXI-Lite

### 4.4 `autocorr_acc`

Auto-correlation accumulator computing power for both channels.

- r00 += I0^2 + Q0^2 (power of ch0)
- r11 += I1^2 + Q1^2 (power of ch1)
- Same snapshot boundary logic as xcorr_acc (counter, latch, reset)
- 48-bit accumulators

## 5. Register Map

Base address: `0x4000_0000` (unchanged). C_S_AXI_ADDR_WIDTH = 12 (unchanged).

### Read-only registers (result values):

| Offset | Name | Width | Description |
|--------|------|-------|-------------|
| 0x00 | XCORR_RE_LO | 32 | r01 real, bits [31:0] |
| 0x04 | XCORR_RE_HI | 32 | r01 real, bits [47:32] (sign-extended) |
| 0x08 | XCORR_IM_LO | 32 | r01 imag, bits [31:0] |
| 0x0C | XCORR_IM_HI | 32 | r01 imag, bits [47:32] (sign-extended) |
| 0x10 | R00_LO | 32 | r00 auto-corr ch0, bits [31:0] |
| 0x14 | R00_HI | 32 | r00 auto-corr ch0, bits [47:32] |
| 0x18 | R11_LO | 32 | r11 auto-corr ch1, bits [31:0] |
| 0x1C | R11_HI | 32 | r11 auto-corr ch1, bits [47:32] |
| 0x20 | STATUS | 32 | bit 0 = result_valid (sticky, clear-on-read) |
| 0x24 | SNAP_COUNT | 32 | completed snapshot counter |

### Read/write registers (configuration):

| Offset | Name | Width | Description |
|--------|------|-------|-------------|
| 0x28 | COS_CAL | 16 | cos(cal_angle) in Q1.15 signed fixed-point |
| 0x2C | SIN_CAL | 16 | sin(cal_angle) in Q1.15 signed fixed-point |
| 0x30 | COEFF_ADDR | 8 | Coefficient index to write (0-23) |
| 0x34 | COEFF_DATA | 16 | Coefficient value in Q1.15 -- write triggers storage |
| 0x38 | FILTER_CTRL | 8 | bit 0 = filter enable, bit 1 = coefficients loaded |

Address decode: `axi_araddr[5:2]` gives 16 register slots (0x00-0x3C).

## 6. Annotated Verilog Reference

The following Verilog is annotated line-by-line for study. This represents the target RTL for Phase A.

### 6.1 `channel_splitter.v`

```verilog
// channel_splitter.v -- Demux interleaved 2-beat AXI-Stream into separate ch0/ch1
//
// The DMA sends data as alternating "beats":
//   Beat 0: {ch0_Q[31:16], ch0_I[15:0]}   (channel 0, I and Q packed into 32 bits)
//   Beat 1: {ch1_Q[31:16], ch1_I[15:0]}   (channel 1, I and Q packed into 32 bits)
//
// This module splits that single interleaved stream into two independent streams,
// one for each channel. Downstream modules (FIR, phase rotate) work on one
// channel at a time, so they need separated data.

`timescale 1ns / 1ps  // simulation time unit = 1 ns, precision = 1 ps

module channel_splitter (
    input  wire        clk,          // system clock (100 MHz on Cora Z7)
    input  wire        rst_n,        // active-low reset (0 = reset, 1 = running)

    // --- AXI-Stream input (interleaved ch0/ch1 beats from DMA) ---
    input  wire [31:0] s_axis_tdata,  // 32-bit data: {Q[31:16], I[15:0]}
    input  wire        s_axis_tvalid, // high when data on tdata is valid
    output wire        s_axis_tready, // we assert this to say "ready to accept"

    // --- Channel 0 output ---
    output reg  [31:0] ch0_tdata,     // ch0 sample: {Q[31:16], I[15:0]}
    output reg         ch0_tvalid,    // high for one cycle when ch0_tdata is valid

    // --- Channel 1 output ---
    output reg  [31:0] ch1_tdata,     // ch1 sample: {Q[31:16], I[15:0]}
    output reg         ch1_tvalid     // high for one cycle when ch1_tdata is valid
);

    // beat_phase tracks which beat we're on:
    //   0 = expecting ch0 data (beat 0)
    //   1 = expecting ch1 data (beat 1)
    reg beat_phase;

    // We're always ready to accept data -- no backpressure (streaming design)
    assign s_axis_tready = 1'b1;

    always @(posedge clk) begin          // execute on every rising clock edge
        if (!rst_n) begin                // RESET: clear everything
            beat_phase <= 0;             // start expecting ch0
            ch0_tdata  <= 32'd0;
            ch0_tvalid <= 1'b0;
            ch1_tdata  <= 32'd0;
            ch1_tvalid <= 1'b0;
        end else begin
            // Default: both outputs invalid this cycle (pulse behavior)
            ch0_tvalid <= 1'b0;
            ch1_tvalid <= 1'b0;

            if (s_axis_tvalid) begin     // new beat arrived from DMA
                if (beat_phase == 1'b0) begin
                    // Beat 0: this is channel 0 data
                    ch0_tdata  <= s_axis_tdata;   // capture the 32-bit sample
                    ch0_tvalid <= 1'b1;           // signal "ch0 data ready"
                    beat_phase <= 1'b1;           // next beat will be ch1
                end else begin
                    // Beat 1: this is channel 1 data
                    ch1_tdata  <= s_axis_tdata;   // capture the 32-bit sample
                    ch1_tvalid <= 1'b1;           // signal "ch1 data ready"
                    beat_phase <= 1'b0;           // next beat will be ch0 again
                end
            end
        end
    end

endmodule
```

### 6.2 `fir_filter_sc16.v`

```verilog
// fir_filter_sc16.v -- Time-shared symmetric FIR filter for SC16 data
//
// WHAT THIS DOES:
//   Takes raw SC16 samples (16-bit signed I + 16-bit signed Q) and applies
//   a FIR (Finite Impulse Response) filter. The filter smooths the signal
//   by computing a weighted sum of the current and past samples. The weights
//   are the "coefficients" (aka "taps") loaded at startup by the ARM.
//
// TIME-SHARING:
//   We have two channels to filter (ch0 and ch1), but only one set of
//   multipliers. The FPGA clock (100 MHz) is 100x faster than the sample
//   rate (1 MHz), so we process ch0 first, then ch1, reusing the same
//   hardware. This halves our DSP48 usage.
//
// SYMMETRIC OPTIMIZATION:
//   For a linear-phase FIR, coeff[k] == coeff[N-1-k]. Instead of doing
//   48 multiplies, we add the two samples that share a coefficient first:
//     result += coeff[k] * (sample[k] + sample[N-1-k])
//   This halves the multiplies again: 48 taps -> 24 multiplies per component.
//
// COMPLEX DATA:
//   SC16 = signed 16-bit I (in-phase) + signed 16-bit Q (quadrature).
//   Since our FIR coefficients are real-valued (not complex), we filter
//   I and Q independently using the same coefficients. Each "multiply"
//   is actually two multiplies (one for I, one for Q), using 2 DSP48s.
//   24 coefficient pairs x 2 (I+Q) = 48 DSP48s... but time-sharing means
//   we reuse them for both channels, so it's still 24 DSP48s total.
//
// FIXED POINT:
//   Coefficients are Q1.15 (1 sign bit, 15 fractional bits, range [-1, +1)).
//   Multiply: 16-bit sample x 16-bit coeff = 32-bit product.
//   Accumulate across 24 taps: needs ~37 bits (32 + ceil(log2(24)) = 37).
//   We use 48-bit accumulators for headroom, then truncate back to 16-bit
//   for the output.

`timescale 1ns / 1ps

module fir_filter_sc16 #(
    parameter NUM_TAPS    = 48,        // total filter length (must be even)
    parameter NUM_UNIQUE  = NUM_TAPS/2,// unique coefficients (symmetric)
    parameter COEFF_WIDTH = 16,        // Q1.15 coefficient width
    parameter DATA_WIDTH  = 16,        // SC16 component width (I or Q)
    parameter ACC_WIDTH   = 48         // internal accumulator width
)(
    input  wire        clk,
    input  wire        rst_n,

    // --- Coefficient loading interface (active at startup) ---
    input  wire [$clog2(NUM_UNIQUE)-1:0] coeff_addr,  // which coefficient (0-23)
    input  wire [COEFF_WIDTH-1:0]        coeff_data,  // the coefficient value
    input  wire                          coeff_wr_en, // pulse high to store

    // --- Filter enable (bypass when 0) ---
    input  wire        filter_en,

    // --- Channel 0 input/output ---
    input  wire [31:0] ch0_tdata,     // {Q[31:16], I[15:0]}
    input  wire        ch0_tvalid,
    output reg  [31:0] ch0_out_tdata, // filtered {Q[31:16], I[15:0]}
    output reg         ch0_out_tvalid,

    // --- Channel 1 input/output ---
    input  wire [31:0] ch1_tdata,
    input  wire        ch1_tvalid,
    output reg  [31:0] ch1_out_tdata,
    output reg         ch1_out_tvalid
);

    // ---------------------------------------------------------------
    // Coefficient storage (RAM)
    // ---------------------------------------------------------------
    // 24 coefficients stored in a small register array.
    // ARM writes these once at startup via AXI-Lite -> coeff_addr/data/wr_en.
    reg signed [COEFF_WIDTH-1:0] coeffs [0:NUM_UNIQUE-1];

    // On write-enable pulse, store the coefficient at the given address
    integer ci;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (ci = 0; ci < NUM_UNIQUE; ci = ci + 1)
                coeffs[ci] <= 0;
        end else if (coeff_wr_en) begin
            coeffs[coeff_addr] <= coeff_data;
        end
    end

    // ---------------------------------------------------------------
    // Delay line (shift register) for each channel's I and Q
    // ---------------------------------------------------------------
    // A FIR filter needs access to the current sample AND the past (NUM_TAPS-1)
    // samples. We store them in a shift register: new samples enter at index 0,
    // old samples shift toward index NUM_TAPS-1.
    //
    // We keep separate delay lines for ch0 and ch1, each with I and Q.

    reg signed [DATA_WIDTH-1:0] ch0_delay_i [0:NUM_TAPS-1];
    reg signed [DATA_WIDTH-1:0] ch0_delay_q [0:NUM_TAPS-1];
    reg signed [DATA_WIDTH-1:0] ch1_delay_i [0:NUM_TAPS-1];
    reg signed [DATA_WIDTH-1:0] ch1_delay_q [0:NUM_TAPS-1];

    // Shift new sample into delay line (oldest sample falls off the end)
    integer di;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (di = 0; di < NUM_TAPS; di = di + 1) begin
                ch0_delay_i[di] <= 0;
                ch0_delay_q[di] <= 0;
                ch1_delay_i[di] <= 0;
                ch1_delay_q[di] <= 0;
            end
        end else begin
            // Channel 0: shift when new sample arrives
            if (ch0_tvalid) begin
                for (di = NUM_TAPS-1; di > 0; di = di - 1) begin
                    ch0_delay_i[di] <= ch0_delay_i[di-1];  // shift right
                    ch0_delay_q[di] <= ch0_delay_q[di-1];
                end
                // New sample enters at position 0
                // tdata format: {Q[31:16], I[15:0]}
                ch0_delay_i[0] <= $signed(ch0_tdata[15:0]);   // I component
                ch0_delay_q[0] <= $signed(ch0_tdata[31:16]);  // Q component
            end

            // Channel 1: same logic
            if (ch1_tvalid) begin
                for (di = NUM_TAPS-1; di > 0; di = di - 1) begin
                    ch1_delay_i[di] <= ch1_delay_i[di-1];
                    ch1_delay_q[di] <= ch1_delay_q[di-1];
                end
                ch1_delay_i[0] <= $signed(ch1_tdata[15:0]);
                ch1_delay_q[0] <= $signed(ch1_tdata[31:16]);
            end
        end
    end

    // ---------------------------------------------------------------
    // FIR computation (symmetric, combinational for now)
    // ---------------------------------------------------------------
    // For each channel, compute:
    //   output_I = sum over k=0..23 of: coeff[k] * (delay_I[k] + delay_I[47-k])
    //   output_Q = sum over k=0..23 of: coeff[k] * (delay_Q[k] + delay_Q[47-k])
    //
    // The (delay[k] + delay[47-k]) exploits symmetry -- two samples that
    // share the same coefficient get added first, then multiplied once.
    // This is a standard FPGA FIR optimization.
    //
    // NOTE: In synthesis, Vivado will infer DSP48 slices for the multiplies.
    // In simulation (iverilog), these are just behavioral multiplies.

    // --- Channel 0 ---
    reg signed [ACC_WIDTH-1:0] ch0_acc_i;  // running sum for I component
    reg signed [ACC_WIDTH-1:0] ch0_acc_q;  // running sum for Q component

    // --- Channel 1 ---
    reg signed [ACC_WIDTH-1:0] ch1_acc_i;
    reg signed [ACC_WIDTH-1:0] ch1_acc_q;

    // Pipelined computation: when a valid sample arrives, compute the
    // filter output over multiple clock cycles (one coefficient per cycle).
    // With 24 coefficients and 100 MHz clock, this takes 24 cycles = 240 ns,
    // well within the ~1000 ns sample period at 1 Msps.

    // State machine for time-shared computation
    localparam IDLE    = 2'd0;   // waiting for a new sample
    localparam COMP_CH0 = 2'd1;  // computing ch0 filter output
    localparam COMP_CH1 = 2'd2;  // computing ch1 filter output
    localparam OUTPUT  = 2'd3;   // latching results

    reg [1:0] state;
    reg [$clog2(NUM_UNIQUE)-1:0] tap_idx;  // which coefficient we're processing
    reg ch0_pending;  // new ch0 sample waiting to be processed
    reg ch1_pending;  // new ch1 sample waiting to be processed

    // Pre-add results (symmetric pair sums) -- computed combinationally
    wire signed [DATA_WIDTH:0] ch0_sym_i = ch0_delay_i[tap_idx] + ch0_delay_i[NUM_TAPS-1-tap_idx];
    wire signed [DATA_WIDTH:0] ch0_sym_q = ch0_delay_q[tap_idx] + ch0_delay_q[NUM_TAPS-1-tap_idx];
    wire signed [DATA_WIDTH:0] ch1_sym_i = ch1_delay_i[tap_idx] + ch1_delay_i[NUM_TAPS-1-tap_idx];
    wire signed [DATA_WIDTH:0] ch1_sym_q = ch1_delay_q[tap_idx] + ch1_delay_q[NUM_TAPS-1-tap_idx];

    always @(posedge clk) begin
        if (!rst_n) begin
            state          <= IDLE;
            tap_idx        <= 0;
            ch0_pending    <= 0;
            ch1_pending    <= 0;
            ch0_acc_i      <= 0;
            ch0_acc_q      <= 0;
            ch1_acc_i      <= 0;
            ch1_acc_q      <= 0;
            ch0_out_tdata  <= 0;
            ch0_out_tvalid <= 0;
            ch1_out_tdata  <= 0;
            ch1_out_tvalid <= 0;
        end else begin
            // Default: output valids are pulses (high for one cycle only)
            ch0_out_tvalid <= 1'b0;
            ch1_out_tvalid <= 1'b0;

            // Capture pending flags when new samples arrive
            if (ch0_tvalid) ch0_pending <= 1'b1;
            if (ch1_tvalid) ch1_pending <= 1'b1;

            case (state)
                IDLE: begin
                    // Wait until both channels have new samples
                    // (they arrive back-to-back from the splitter)
                    if (ch0_pending && ch1_pending) begin
                        if (!filter_en) begin
                            // BYPASS: pass through unfiltered data directly
                            // Use the newest sample from the delay line
                            ch0_out_tdata  <= {ch0_delay_q[0], ch0_delay_i[0]};
                            ch0_out_tvalid <= 1'b1;
                            ch1_out_tdata  <= {ch1_delay_q[0], ch1_delay_i[0]};
                            ch1_out_tvalid <= 1'b1;
                            ch0_pending    <= 1'b0;
                            ch1_pending    <= 1'b0;
                        end else begin
                            // START FILTERING: begin with ch0
                            ch0_acc_i <= 0;   // clear accumulators
                            ch0_acc_q <= 0;
                            tap_idx   <= 0;   // start from coefficient 0
                            state     <= COMP_CH0;
                        end
                    end
                end

                COMP_CH0: begin
                    // Multiply-accumulate: acc += coeff[k] * (sample[k] + sample[47-k])
                    // The $signed() cast ensures signed multiplication in Verilog
                    ch0_acc_i <= ch0_acc_i + ($signed(coeffs[tap_idx]) * ch0_sym_i);
                    ch0_acc_q <= ch0_acc_q + ($signed(coeffs[tap_idx]) * ch0_sym_q);

                    if (tap_idx == NUM_UNIQUE - 1) begin
                        // Done with ch0 -- move to ch1
                        ch1_acc_i <= 0;
                        ch1_acc_q <= 0;
                        tap_idx   <= 0;
                        state     <= COMP_CH1;
                    end else begin
                        tap_idx <= tap_idx + 1;  // next coefficient
                    end
                end

                COMP_CH1: begin
                    // Same MAC operation, but using ch1's delay line
                    ch1_acc_i <= ch1_acc_i + ($signed(coeffs[tap_idx]) * ch1_sym_i);
                    ch1_acc_q <= ch1_acc_q + ($signed(coeffs[tap_idx]) * ch1_sym_q);

                    if (tap_idx == NUM_UNIQUE - 1) begin
                        // Done with both channels -- output results
                        state <= OUTPUT;
                    end else begin
                        tap_idx <= tap_idx + 1;
                    end
                end

                OUTPUT: begin
                    // Truncate 48-bit accumulator back to 16-bit SC16 output.
                    // Coefficients are Q1.15, so the product is Q17.15.
                    // We right-shift by 15 to get back to integer scale,
                    // then take the lower 16 bits.
                    //
                    // ch0_acc_i >>> 15 extracts the 16-bit filtered value.
                    // (>>> is arithmetic right shift -- preserves sign bit)
                    ch0_out_tdata  <= {ch0_acc_q[ACC_WIDTH-1:15], ch0_acc_i[ACC_WIDTH-1:15]};
                    ch0_out_tvalid <= 1'b1;

                    ch1_out_tdata  <= {ch1_acc_q[ACC_WIDTH-1:15], ch1_acc_i[ACC_WIDTH-1:15]};
                    ch1_out_tvalid <= 1'b1;

                    ch0_pending <= 1'b0;
                    ch1_pending <= 1'b0;
                    state       <= IDLE;
                end
            endcase
        end
    end

endmodule
```

### 6.3 `phase_rotate_sc16.v`

```verilog
// phase_rotate_sc16.v -- Calibration phase rotation for one SC16 channel
//
// WHAT THIS DOES:
//   Applies a complex rotation to compensate for the phase offset between
//   the two antenna channels. Without calibration, the measured angle is
//   wrong by a fixed amount (currently ~16.33 deg for the ARM path).
//
// THE MATH:
//   A complex sample is (I + jQ). To rotate it by angle -theta:
//     (I + jQ) * (cos(theta) - j*sin(theta))
//
//   Expanding:
//     I' = I*cos + Q*sin     (new in-phase component)
//     Q' = Q*cos - I*sin     (new quadrature component)
//
//   This is just two multiplies and an add/subtract per component.
//
// FIXED POINT:
//   cos and sin are provided as Q1.15 values by the ARM.
//   Q1.15 means: value = register_value / 32768
//   So cos(16.33 deg) = 0.9596 -> round(0.9596 * 32768) = 31444
//
//   The multiply: 16-bit sample * 16-bit cos/sin = 32-bit product.
//   We right-shift by 15 to undo the Q1.15 scaling, yielding a 16-bit result.
//   Uses 4 DSP48 slices (I*cos, I*sin, Q*cos, Q*sin).

`timescale 1ns / 1ps

module phase_rotate_sc16 (
    input  wire        clk,
    input  wire        rst_n,

    // --- Calibration angle (written by ARM via AXI-Lite) ---
    input  wire signed [15:0] cos_cal,  // cos(cal_angle) in Q1.15
    input  wire signed [15:0] sin_cal,  // sin(cal_angle) in Q1.15

    // --- Input SC16 sample ---
    input  wire [31:0] s_tdata,        // {Q[31:16], I[15:0]}
    input  wire        s_tvalid,       // input valid

    // --- Output rotated SC16 sample ---
    output reg  [31:0] m_tdata,        // {Q'[31:16], I'[15:0]}
    output reg         m_tvalid        // output valid (1-cycle latency)
);

    // Extract I and Q from the input (signed 16-bit)
    wire signed [15:0] in_i = $signed(s_tdata[15:0]);    // in-phase
    wire signed [15:0] in_q = $signed(s_tdata[31:16]);   // quadrature

    // Intermediate products (32-bit, from 16x16 multiply)
    // These will map to DSP48 slices in synthesis.
    wire signed [31:0] i_cos = in_i * cos_cal;   // I * cos(theta)
    wire signed [31:0] q_sin = in_q * sin_cal;   // Q * sin(theta)
    wire signed [31:0] q_cos = in_q * cos_cal;   // Q * cos(theta)
    wire signed [31:0] i_sin = in_i * sin_cal;   // I * sin(theta)

    // Compute rotated I' and Q':
    //   I' = I*cos + Q*sin
    //   Q' = Q*cos - I*sin
    //
    // The products are Q17.15 (32-bit). We add/subtract, then extract
    // bits [30:15] to get back to 16-bit Q1.0 (integer) scale.
    // Bit 30 (not 31) because the sign bit of Q1.15 * Q1.15 is at bit 30.
    wire signed [32:0] rot_i_full = i_cos + q_sin;  // 33-bit to handle overflow
    wire signed [32:0] rot_q_full = q_cos - i_sin;

    // Right-shift by 15 and truncate to 16 bits
    wire signed [15:0] rot_i = rot_i_full[30:15];
    wire signed [15:0] rot_q = rot_q_full[30:15];

    // Pipeline register: one clock cycle latency
    always @(posedge clk) begin
        if (!rst_n) begin
            m_tdata  <= 32'd0;
            m_tvalid <= 1'b0;
        end else begin
            m_tvalid <= s_tvalid;              // valid follows input by 1 cycle
            if (s_tvalid) begin
                m_tdata <= {rot_q, rot_i};     // repack as {Q[31:16], I[15:0]}
            end
        end
    end

endmodule
```

### 6.4 `autocorr_acc.v`

```verilog
// autocorr_acc.v -- Auto-correlation (power) accumulator for two channels
//
// WHAT THIS DOES:
//   Computes the signal power for each channel over a snapshot:
//     r00 = sum of (I0^2 + Q0^2) for all samples in ch0
//     r11 = sum of (I1^2 + Q1^2) for all samples in ch1
//
//   These are the diagonal elements of the 2x2 covariance matrix R.
//   Together with r01 (from xcorr_acc), the ARM has the full matrix:
//     R = [[r00, r01],
//          [conj(r01), r11]]
//
// WHY IN FPGA:
//   The v2 Python code computes r00/r11 on the ARM by converting CF32->SC16
//   and doing NumPy integer math. Moving this to fabric means the ARM's
//   inner loop has zero computation -- just DMA + register reads.
//
// FIXED POINT:
//   Input: 16-bit signed I, 16-bit signed Q
//   I^2 + Q^2: max value per sample = 32767^2 + 32767^2 = ~2.15 * 10^9
//   Over 1024 samples: max = ~2.2 * 10^12, needs 42 bits.
//   We use 48-bit accumulators for headroom (same as xcorr_acc).
//   Uses 4 DSP48 slices (I0^2, Q0^2, I1^2, Q1^2).

`timescale 1ns / 1ps

module autocorr_acc #(
    parameter SNAPSHOT_LEN = 1024,   // samples per snapshot
    parameter ACC_WIDTH    = 48      // accumulator bit width
)(
    input  wire        clk,
    input  wire        rst_n,

    // --- Channel 0 input (filtered SC16) ---
    input  wire [31:0] ch0_tdata,    // {Q[31:16], I[15:0]}
    input  wire        ch0_tvalid,

    // --- Channel 1 input (filtered + rotated SC16) ---
    input  wire [31:0] ch1_tdata,
    input  wire        ch1_tvalid,

    // --- Results (latched at snapshot boundary) ---
    output reg  [ACC_WIDTH-1:0] r00,           // auto-corr of ch0 (unsigned)
    output reg  [ACC_WIDTH-1:0] r11,           // auto-corr of ch1 (unsigned)
    output reg                  result_valid    // pulse high for one cycle
);

    // Extract signed I and Q from each channel
    wire signed [15:0] ch0_i = $signed(ch0_tdata[15:0]);
    wire signed [15:0] ch0_q = $signed(ch0_tdata[31:16]);
    wire signed [15:0] ch1_i = $signed(ch1_tdata[15:0]);
    wire signed [15:0] ch1_q = $signed(ch1_tdata[31:16]);

    // Power per sample: I^2 + Q^2
    // 16-bit * 16-bit = 32-bit, both terms positive, sum fits in 33 bits
    wire [32:0] ch0_power = (ch0_i * ch0_i) + (ch0_q * ch0_q);
    wire [32:0] ch1_power = (ch1_i * ch1_i) + (ch1_q * ch1_q);

    // Running accumulators (48-bit, reset each snapshot)
    reg [ACC_WIDTH-1:0] acc_r00;
    reg [ACC_WIDTH-1:0] acc_r11;

    // Sample counter -- counts how many samples we've seen in this snapshot
    reg [$clog2(SNAPSHOT_LEN)-1:0] sample_cnt;

    // We accumulate when BOTH channels have valid data on the same cycle.
    // Since they come from the FIR (which outputs ch0 and ch1 together
    // in the OUTPUT state), they should be aligned.
    wire both_valid = ch0_tvalid & ch1_tvalid;

    always @(posedge clk) begin
        if (!rst_n) begin
            acc_r00      <= 0;
            acc_r11      <= 0;
            r00          <= 0;
            r11          <= 0;
            sample_cnt   <= 0;
            result_valid <= 0;
        end else if (both_valid) begin
            // Accumulate power for this sample
            acc_r00 <= acc_r00 + ch0_power;
            acc_r11 <= acc_r11 + ch1_power;

            if (sample_cnt == SNAPSHOT_LEN - 1) begin
                // End of snapshot: latch the final values (including this sample)
                r00          <= acc_r00 + ch0_power;
                r11          <= acc_r11 + ch1_power;
                result_valid <= 1'b1;

                // Reset for next snapshot
                acc_r00    <= 0;
                acc_r11    <= 0;
                sample_cnt <= 0;
            end else begin
                result_valid <= 0;
                sample_cnt   <= sample_cnt + 1;
            end
        end else begin
            result_valid <= 0;   // no valid data this cycle, no pulse
        end
    end

endmodule
```

### 6.5 `doa_pipeline.v` (Top-level wrapper)

```verilog
// doa_pipeline.v -- Top-level Phase A DoA processing pipeline
//
// This is the module that replaces xcorr_acc_axi in the Vivado block design.
// It connects all the Phase A modules together:
//
//   DMA input -> splitter -> FIR filter -> phase rotate (ch1) ->
//   -> xcorr_acc (r01) + autocorr_acc (r00, r11) -> AXI-Lite registers
//
// From the ARM's perspective, this looks like a single AXI-Lite peripheral
// at base address 0x4000_0000 with an AXI-Stream slave port for DMA data.
//
// The ARM:
//   1. Writes filter coefficients (0x30/0x34) and calibration (0x28/0x2C) at startup
//   2. Enables the filter (0x38 bit 0)
//   3. For each snapshot: DMA 2048 beats -> read r01, r00, r11 from registers
//   4. Averages 100 snapshots, runs Root-MUSIC

`timescale 1ns / 1ps

module doa_pipeline #(
    parameter SNAPSHOT_LEN        = 1024,
    parameter ACC_WIDTH           = 48,
    parameter NUM_TAPS            = 48,
    parameter C_S_AXI_DATA_WIDTH  = 32,
    parameter C_S_AXI_ADDR_WIDTH  = 12
)(
    // --- Clock and reset ---
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:s_axis, ASSOCIATED_RESET s_axi_aresetn" *)
    input  wire        s_axi_aclk,
    input  wire        s_axi_aresetn,

    // --- AXI-Lite Slave (register access from ARM) ---
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_awaddr,
    input  wire [2:0]                     s_axi_awprot,
    input  wire                           s_axi_awvalid,
    output reg                            s_axi_awready,

    input  wire [C_S_AXI_DATA_WIDTH-1:0] s_axi_wdata,
    input  wire [3:0]                     s_axi_wstrb,
    input  wire                           s_axi_wvalid,
    output reg                            s_axi_wready,

    output reg  [1:0]                     s_axi_bresp,
    output reg                            s_axi_bvalid,
    input  wire                           s_axi_bready,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_araddr,
    input  wire [2:0]                     s_axi_arprot,
    input  wire                           s_axi_arvalid,
    output reg                            s_axi_arready,

    output reg  [C_S_AXI_DATA_WIDTH-1:0] s_axi_rdata,
    output reg  [1:0]                     s_axi_rresp,
    output reg                            s_axi_rvalid,
    input  wire                           s_axi_rready,

    // --- AXI-Stream Slave (DMA data input) ---
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TDATA" *)
    (* X_INTERFACE_PARAMETER = "CLK_DOMAIN s_axi_aclk, FREQ_HZ 50000000, HAS_TKEEP 0, HAS_TLAST 0, HAS_TREADY 1, HAS_TSTRB 0, TDATA_NUM_BYTES 4" *)
    input  wire [31:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TVALID" *)
    input  wire        s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TREADY" *)
    output wire        s_axis_tready
);

    // ===============================================================
    // Internal wires connecting the pipeline stages
    // ===============================================================

    // Splitter outputs
    wire [31:0] split_ch0_tdata;
    wire        split_ch0_tvalid;
    wire [31:0] split_ch1_tdata;
    wire        split_ch1_tvalid;

    // FIR filter outputs
    wire [31:0] fir_ch0_tdata;
    wire        fir_ch0_tvalid;
    wire [31:0] fir_ch1_tdata;
    wire        fir_ch1_tvalid;

    // Phase rotate output (ch1 only; ch0 passes through)
    wire [31:0] rot_ch1_tdata;
    wire        rot_ch1_tvalid;

    // xcorr_acc results
    wire [ACC_WIDTH-1:0] xcorr_re_raw;
    wire [ACC_WIDTH-1:0] xcorr_im_raw;
    wire                 xcorr_valid;

    // autocorr_acc results
    wire [ACC_WIDTH-1:0] r00_raw;
    wire [ACC_WIDTH-1:0] r11_raw;
    wire                 autocorr_valid;

    // ===============================================================
    // Writable configuration registers (ARM writes via AXI-Lite)
    // ===============================================================

    reg signed [15:0] reg_cos_cal;    // 0x28: cos(cal_angle) Q1.15
    reg signed [15:0] reg_sin_cal;    // 0x2C: sin(cal_angle) Q1.15
    reg [4:0]         reg_coeff_addr; // 0x30: coefficient index (0-23)
    reg signed [15:0] reg_coeff_data; // 0x34: coefficient value
    reg               coeff_wr_pulse; // triggers one-cycle write to FIR
    reg               reg_filter_en;  // 0x38 bit 0: enable filter
    reg               reg_coeff_loaded; // 0x38 bit 1: coefficients loaded

    // ===============================================================
    // Read-only result registers (latched at snapshot boundary)
    // ===============================================================

    reg [ACC_WIDTH-1:0] reg_xcorr_re;   // 0x00/0x04
    reg [ACC_WIDTH-1:0] reg_xcorr_im;   // 0x08/0x0C
    reg [ACC_WIDTH-1:0] reg_r00;        // 0x10/0x14
    reg [ACC_WIDTH-1:0] reg_r11;        // 0x18/0x1C
    reg                 reg_valid;      // 0x20 bit 0 (sticky, clear-on-read)
    reg [31:0]          reg_snap_count; // 0x24

    reg clear_valid;  // signal from read logic to clear valid bit

    // Latch results when xcorr_acc signals completion
    // (xcorr and autocorr should fire on the same cycle since they
    // share the same data stream and snapshot length)
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            reg_xcorr_re  <= 0;
            reg_xcorr_im  <= 0;
            reg_r00       <= 0;
            reg_r11       <= 0;
            reg_valid     <= 0;
            reg_snap_count <= 0;
        end else begin
            if (clear_valid)
                reg_valid <= 0;

            if (xcorr_valid) begin
                reg_xcorr_re   <= xcorr_re_raw;
                reg_xcorr_im   <= xcorr_im_raw;
                reg_r00        <= r00_raw;
                reg_r11        <= r11_raw;
                reg_valid      <= 1;
                reg_snap_count <= reg_snap_count + 1;
            end
        end
    end

    // ===============================================================
    // Pipeline instantiation
    // ===============================================================

    // --- Stage 1: Split interleaved stream into ch0 and ch1 ---
    channel_splitter u_splitter (
        .clk           (s_axi_aclk),
        .rst_n         (s_axi_aresetn),
        .s_axis_tdata  (s_axis_tdata),
        .s_axis_tvalid (s_axis_tvalid),
        .s_axis_tready (s_axis_tready),
        .ch0_tdata     (split_ch0_tdata),
        .ch0_tvalid    (split_ch0_tvalid),
        .ch1_tdata     (split_ch1_tdata),
        .ch1_tvalid    (split_ch1_tvalid)
    );

    // --- Stage 2: FIR filter (both channels, time-shared) ---
    fir_filter_sc16 #(
        .NUM_TAPS  (NUM_TAPS),
        .ACC_WIDTH (ACC_WIDTH)
    ) u_fir (
        .clk            (s_axi_aclk),
        .rst_n          (s_axi_aresetn),
        .coeff_addr     (reg_coeff_addr),
        .coeff_data     (reg_coeff_data),
        .coeff_wr_en    (coeff_wr_pulse),
        .filter_en      (reg_filter_en),
        .ch0_tdata      (split_ch0_tdata),
        .ch0_tvalid     (split_ch0_tvalid),
        .ch0_out_tdata  (fir_ch0_tdata),
        .ch0_out_tvalid (fir_ch0_tvalid),
        .ch1_tdata      (split_ch1_tdata),
        .ch1_tvalid     (split_ch1_tvalid),
        .ch1_out_tdata  (fir_ch1_tdata),
        .ch1_out_tvalid (fir_ch1_tvalid)
    );

    // --- Stage 3: Phase rotation on ch1 only ---
    phase_rotate_sc16 u_rotate (
        .clk      (s_axi_aclk),
        .rst_n    (s_axi_aresetn),
        .cos_cal  (reg_cos_cal),
        .sin_cal  (reg_sin_cal),
        .s_tdata  (fir_ch1_tdata),
        .s_tvalid (fir_ch1_tvalid),
        .m_tdata  (rot_ch1_tdata),
        .m_tvalid (rot_ch1_tvalid)
    );

    // --- Stage 4a: Cross-correlation (r01 = ch0 * conj(ch1)) ---
    // We need to re-interleave ch0 and ch1 for xcorr_acc, which expects
    // the 2-beat format. We use a small FSM for this.
    //
    // ch0 comes from FIR directly (no rotation).
    // ch1 comes from phase_rotate.
    // xcorr_acc needs: beat0=ch0, beat1=ch1, beat0=ch0, beat1=ch1, ...

    reg [31:0] xcorr_axis_tdata;
    reg        xcorr_axis_tvalid;
    reg        interleave_phase;  // 0=send ch0, 1=send ch1

    // Buffer the ch0 and ch1 samples to align them for interleaving
    reg [31:0] buf_ch0;
    reg        buf_ch0_valid;
    reg [31:0] buf_ch1;
    reg        buf_ch1_valid;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            buf_ch0       <= 0;
            buf_ch0_valid <= 0;
            buf_ch1       <= 0;
            buf_ch1_valid <= 0;
            xcorr_axis_tdata  <= 0;
            xcorr_axis_tvalid <= 0;
            interleave_phase  <= 0;
        end else begin
            xcorr_axis_tvalid <= 0;  // default: no output this cycle

            // Capture filtered ch0 (straight from FIR, not rotated)
            if (fir_ch0_tvalid) begin
                buf_ch0       <= fir_ch0_tdata;
                buf_ch0_valid <= 1;
            end

            // Capture rotated ch1
            if (rot_ch1_tvalid) begin
                buf_ch1       <= rot_ch1_tdata;
                buf_ch1_valid <= 1;
            end

            // When both are ready, emit interleaved beats
            if (buf_ch0_valid && buf_ch1_valid) begin
                if (interleave_phase == 0) begin
                    // Beat 0: ch0
                    xcorr_axis_tdata  <= buf_ch0;
                    xcorr_axis_tvalid <= 1;
                    interleave_phase  <= 1;
                end else begin
                    // Beat 1: ch1
                    xcorr_axis_tdata  <= buf_ch1;
                    xcorr_axis_tvalid <= 1;
                    interleave_phase  <= 0;
                    // Both consumed
                    buf_ch0_valid <= 0;
                    buf_ch1_valid <= 0;
                end
            end
        end
    end

    // xcorr_acc core (existing module, unchanged)
    xcorr_acc #(
        .SNAPSHOT_LEN (SNAPSHOT_LEN),
        .ACC_WIDTH    (ACC_WIDTH)
    ) u_xcorr (
        .clk            (s_axi_aclk),
        .rst_n          (s_axi_aresetn),
        .s_axis_tdata   (xcorr_axis_tdata),
        .s_axis_tvalid  (xcorr_axis_tvalid),
        .s_axis_tready  (),  // xcorr is always ready
        .xcorr_re       (xcorr_re_raw),
        .xcorr_im       (xcorr_im_raw),
        .result_valid   (xcorr_valid)
    );

    // --- Stage 4b: Auto-correlation (r00, r11) in parallel ---
    // Uses filtered ch0 and rotated ch1, same data as xcorr_acc
    autocorr_acc #(
        .SNAPSHOT_LEN (SNAPSHOT_LEN),
        .ACC_WIDTH    (ACC_WIDTH)
    ) u_autocorr (
        .clk          (s_axi_aclk),
        .rst_n        (s_axi_aresetn),
        .ch0_tdata    (buf_ch0),     // filtered ch0
        .ch0_tvalid   (buf_ch0_valid && buf_ch1_valid),
        .ch1_tdata    (buf_ch1),     // filtered + rotated ch1
        .ch1_tvalid   (buf_ch0_valid && buf_ch1_valid),
        .r00          (r00_raw),
        .r11          (r11_raw),
        .result_valid (autocorr_valid)
    );

    // ===============================================================
    // AXI-Lite Read Logic
    // ===============================================================
    // The ARM reads registers by sending an address on the AR channel,
    // then we respond with data on the R channel.

    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_araddr;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 0;
            axi_araddr    <= 0;
        end else if (s_axi_arvalid && !s_axi_arready) begin
            s_axi_arready <= 1;           // accept the read address
            axi_araddr    <= s_axi_araddr;// latch it
        end else begin
            s_axi_arready <= 0;
        end
    end

    // Decode address and return the appropriate register value
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_rdata  <= 0;
            s_axi_rresp  <= 0;
            s_axi_rvalid <= 0;
            clear_valid  <= 0;
        end else if (s_axi_arready && s_axi_arvalid && !s_axi_rvalid) begin
            s_axi_rvalid <= 1;
            s_axi_rresp  <= 2'b00;  // OKAY

            // Decode using bits [5:2] -> 16 register slots
            case (axi_araddr[5:2])
                4'h0: s_axi_rdata <= reg_xcorr_re[31:0];                        // 0x00
                4'h1: s_axi_rdata <= {{16{reg_xcorr_re[ACC_WIDTH-1]}},           // 0x04
                                      reg_xcorr_re[ACC_WIDTH-1:32]};             // sign-extend
                4'h2: s_axi_rdata <= reg_xcorr_im[31:0];                         // 0x08
                4'h3: s_axi_rdata <= {{16{reg_xcorr_im[ACC_WIDTH-1]}},           // 0x0C
                                      reg_xcorr_im[ACC_WIDTH-1:32]};
                4'h4: s_axi_rdata <= reg_r00[31:0];                              // 0x10
                4'h5: s_axi_rdata <= {{16{1'b0}}, reg_r00[ACC_WIDTH-1:32]};      // 0x14 (unsigned)
                4'h6: s_axi_rdata <= reg_r11[31:0];                              // 0x18
                4'h7: s_axi_rdata <= {{16{1'b0}}, reg_r11[ACC_WIDTH-1:32]};      // 0x1C (unsigned)
                4'h8: s_axi_rdata <= {31'b0, reg_valid};                         // 0x20
                4'h9: s_axi_rdata <= reg_snap_count;                             // 0x24
                4'hA: s_axi_rdata <= {{16{reg_cos_cal[15]}}, reg_cos_cal};       // 0x28
                4'hB: s_axi_rdata <= {{16{reg_sin_cal[15]}}, reg_sin_cal};       // 0x2C
                4'hC: s_axi_rdata <= {27'b0, reg_coeff_addr};                    // 0x30
                4'hD: s_axi_rdata <= {{16{reg_coeff_data[15]}}, reg_coeff_data}; // 0x34
                4'hE: s_axi_rdata <= {30'b0, reg_coeff_loaded, reg_filter_en};   // 0x38
                default: s_axi_rdata <= 32'hDEADBEEF;
            endcase
        end else if (s_axi_rvalid && s_axi_rready) begin
            s_axi_rvalid <= 0;
            // Clear-on-read for STATUS register (0x20 = slot 0x8)
            if (axi_araddr[5:2] == 4'h8)
                clear_valid <= 1;
            else
                clear_valid <= 0;
        end else begin
            clear_valid <= 0;
        end
    end

    // ===============================================================
    // AXI-Lite Write Logic
    // ===============================================================
    // The ARM writes configuration registers (cal angles, FIR coefficients).

    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_awaddr;
    reg                           aw_ready;
    reg                           w_ready;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready   <= 0;
            s_axi_wready    <= 0;
            s_axi_bvalid    <= 0;
            s_axi_bresp     <= 0;
            axi_awaddr      <= 0;
            aw_ready         <= 0;
            w_ready          <= 0;
            reg_cos_cal      <= 0;
            reg_sin_cal      <= 0;
            reg_coeff_addr   <= 0;
            reg_coeff_data   <= 0;
            coeff_wr_pulse   <= 0;
            reg_filter_en    <= 0;
            reg_coeff_loaded <= 0;
        end else begin
            coeff_wr_pulse <= 0;  // default: no write pulse

            // Capture write address
            if (s_axi_awvalid && !s_axi_awready) begin
                s_axi_awready <= 1;
                axi_awaddr    <= s_axi_awaddr;
                aw_ready      <= 1;
            end else begin
                s_axi_awready <= 0;
            end

            // Capture write data
            if (s_axi_wvalid && !s_axi_wready) begin
                s_axi_wready <= 1;
                w_ready      <= 1;
            end else begin
                s_axi_wready <= 0;
            end

            // When both address and data are captured, decode and store
            if (aw_ready && w_ready) begin
                aw_ready <= 0;
                w_ready  <= 0;

                case (axi_awaddr[5:2])
                    4'hA: reg_cos_cal    <= s_axi_wdata[15:0];    // 0x28
                    4'hB: reg_sin_cal    <= s_axi_wdata[15:0];    // 0x2C
                    4'hC: reg_coeff_addr <= s_axi_wdata[4:0];     // 0x30
                    4'hD: begin
                        reg_coeff_data <= s_axi_wdata[15:0];      // 0x34
                        coeff_wr_pulse <= 1;  // trigger FIR coeff write
                    end
                    4'hE: begin
                        reg_filter_en    <= s_axi_wdata[0];       // 0x38 bit 0
                        reg_coeff_loaded <= s_axi_wdata[1];       // 0x38 bit 1
                    end
                    default: ; // ignore writes to read-only registers
                endcase
            end

            // Write response
            if (s_axi_awready && s_axi_awvalid &&
                s_axi_wready && s_axi_wvalid && !s_axi_bvalid) begin
                s_axi_bvalid <= 1;
                s_axi_bresp  <= 2'b00;  // OKAY
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 0;
            end
        end
    end

endmodule
```

## 7. Testing Strategy

### 7.1 Unit simulation (iverilog)

| Testbench | Verifies |
|-----------|----------|
| `tb_channel_splitter.v` | Interleaved in -> two separate streams, correct beat assignment |
| `tb_fir_filter_sc16.v` | Impulse response matches NumPy. 50 kHz sinusoid passband/stopband |
| `tb_phase_rotate_sc16.v` | Rotation at 0/45/90/180 deg vs NumPy reference |
| `tb_autocorr_acc.v` | Constant amplitude -> known power. Random -> matches NumPy `sum(I^2 + Q^2)` |

### 7.2 Full pipeline simulation (iverilog)

`tb_doa_pipeline.v` -- End-to-end: generate SC16 with known phase, load coefficients via AXI-Lite, stream data, read registers, compare with Python reference.

### 7.3 Hardware test (on Cora)

`test_fpga_pipeline.py` -- Extends existing `test_fpga_xcorr.py`: write coefficients + cal, DMA synthetic data, read all registers, compare vs NumPy.

Regression: run with FILTER_CTRL=0, compare against current v2 xcorr results.

### 7.4 Live validation

`aoa_estimation_fpga_v3.py --debug` -- real BladeRF data, prints FPGA vs ARM reference for first 5 iterations.

## 8. Python Driver Changes (v3)

- `FPGAXcorr` gains: `write_filter_coefficients()`, `write_calibration()`, `enable_filter()`, `read_48bit()`
- ARM inner loop: DMA raw samples -> read 3 register pairs -> integer accumulate
- ARM no longer does: FIR filtering, calibration rotation, SC16 r00/r11 computation
- `design_filter()` stays -- computes taps once, writes to FPGA
- `--filter=none` sets FILTER_CTRL=0 (bypass, data passes through unfiltered)
- v2 script stays as fallback

## 9. Fallback Strategy

- Current bitstream saved as `BOOT_current.BIN`
- Phase A bitstream saved as `BOOT_phaseA.BIN`
- If synthesis fails timing: reduce to 32-tap FIR
- If FIR output is wrong: disable filter (FILTER_CTRL=0) and debug incrementally
- v2 Python script and bitstream always available for immediate rollback
