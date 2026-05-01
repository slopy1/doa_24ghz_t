// autocorr_acc.v — Auto-correlation (power) accumulator for 2 channels
//
// Computes, over a snapshot of SNAPSHOT_LEN aligned ch0/ch1 sample pairs:
//   r00 = sum_n ( I0[n]^2 + Q0[n]^2 )      // power of ch0
//   r11 = sum_n ( I1[n]^2 + Q1[n]^2 )      // power of ch1
//
// Together with r01 from xcorr_acc, these form the 2x2 covariance matrix
// the ARM hands to Root-MUSIC:
//   R = [[r00, r01], [conj(r01), r11]]
//
// Interface:
//   * Two parallel 32-bit SC16 inputs with their own tvalid pulses.
//   * A sample is accumulated when BOTH ch0_tvalid and ch1_tvalid are
//     high on the same cycle (edge, not level — see IMPORTANT note).
//   * Results latched on the SNAPSHOT_LEN-th pair, pulse result_valid
//     for one cycle.
//
// IMPORTANT — spec fix #1:
//   The spec wires autocorr's "both valid" into `buf_valid && buf_valid`
//   in doa_pipeline, where those regs stay high for *two* cycles during
//   the interleave phase. That would double-count every sample.
//   This module treats ch0_tvalid and ch1_tvalid as single-cycle pulses
//   (same convention as channel_splitter's outputs), so the fix lives
//   in doa_pipeline's wiring, not here. See tb_doa_pipeline.v for the
//   regression test that exercises it.
//
// Fixed-point: SC16 input, 48-bit unsigned accumulators, 4 DSP48 slices.
// Target: Zynq-7000 XC7Z007S @ 100 MHz (Cora Z7)

`timescale 1ns / 1ps

module autocorr_acc #(
    parameter SNAPSHOT_LEN = 1024,
    parameter ACC_WIDTH    = 48
)(
    input  wire                     clk,
    input  wire                     rst_n,

    // Channel 0 (filtered SC16 from FIR)
    input  wire [31:0]              ch0_tdata,
    input  wire                     ch0_tvalid,

    // Channel 1 (filtered + phase-rotated SC16)
    input  wire [31:0]              ch1_tdata,
    input  wire                     ch1_tvalid,

    // Latched results (one-cycle pulse on result_valid)
    output reg  [ACC_WIDTH-1:0]     r00,
    output reg  [ACC_WIDTH-1:0]     r11,
    output reg                      result_valid
);

    // Unpack signed I/Q from both channels
    wire signed [15:0] ch0_i = ch0_tdata[15:0];
    wire signed [15:0] ch0_q = ch0_tdata[31:16];
    wire signed [15:0] ch1_i = ch1_tdata[15:0];
    wire signed [15:0] ch1_q = ch1_tdata[31:16];

    // Per-sample power (I*I + Q*Q). Max value = 2 * 32767^2 ~ 2.15e9 -> 33 bits.
    // $signed ensures Vivado infers signed 16x16 DSP48 multiplies, even though
    // the final sum is non-negative.
    wire [32:0] ch0_power = (ch0_i * ch0_i) + (ch0_q * ch0_q);
    wire [32:0] ch1_power = (ch1_i * ch1_i) + (ch1_q * ch1_q);

    // Running accumulators
    reg [ACC_WIDTH-1:0] acc_r00;
    reg [ACC_WIDTH-1:0] acc_r11;

    // Sample counter (counts aligned ch0+ch1 pairs)
    reg [$clog2(SNAPSHOT_LEN)-1:0] sample_cnt;

    // A sample is counted only when both channels pulse valid in the same cycle
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
            if (sample_cnt == SNAPSHOT_LEN - 1) begin
                // Final sample of the snapshot — latch total and reset
                r00          <= acc_r00 + ch0_power;
                r11          <= acc_r11 + ch1_power;
                result_valid <= 1'b1;
                acc_r00      <= 0;
                acc_r11      <= 0;
                sample_cnt   <= 0;
            end else begin
                acc_r00      <= acc_r00 + ch0_power;
                acc_r11      <= acc_r11 + ch1_power;
                sample_cnt   <= sample_cnt + 1;
                result_valid <= 1'b0;
            end
        end else begin
            result_valid <= 1'b0;
        end
    end

endmodule
