// phase_rotate_sc16.v — Calibration phase rotation for one SC16 channel
//
// Applies (I + jQ) * (cos - j*sin) to rotate one antenna stream by a
// fixed calibration angle. This matches the ARM's apply_calibration()
// step in aoa_estimation_fpga_v2.py, moved into fabric.
//
// Expanded:
//   I' = I*cos + Q*sin
//   Q' = Q*cos - I*sin
//
// Fixed-point scaling:
//   * cos_cal, sin_cal are Q1.15 signed 16-bit (value = reg / 32768).
//   * I, Q are s16 integers (SC16 from BladeRF).
//   * Each product is Q17.15 (s32): sign bit [31], integer bits [30:15],
//     fractional bits [14:0].
//   * After the add/subtract we still have Q17.15 (maybe +1 bit headroom,
//     held in a 33-bit intermediate to be safe).
//   * To get a 16-bit integer back, take bits [30:15] of the Q17.15 result.
//     Bit 30 is the MSB of the integer part (bit 31 is the sign, which
//     we'll sign-extend implicitly through $signed).
//
// Uses 4 DSP48E1 slices (I*cos, I*sin, Q*cos, Q*sin).
// 1-cycle registered output for timing slack on the Zynq-7000 @ 100 MHz.

`timescale 1ns / 1ps

module phase_rotate_sc16 (
    input  wire               clk,
    input  wire               rst_n,

    // Calibration (Q1.15 signed), written by ARM via AXI-Lite
    input  wire signed [15:0] cos_cal,
    input  wire signed [15:0] sin_cal,

    // Input SC16 {Q, I}
    input  wire        [31:0] s_tdata,
    input  wire               s_tvalid,

    // Output rotated SC16 {Q', I'}, 1-cycle latency
    output reg         [31:0] m_tdata,
    output reg                m_tvalid
);

    // Extract signed I/Q from packed input
    wire signed [15:0] in_i = s_tdata[15:0];
    wire signed [15:0] in_q = s_tdata[31:16];

    // Four partial products (s32 each, will map to DSP48 in synthesis)
    wire signed [31:0] i_cos = in_i * cos_cal;
    wire signed [31:0] q_sin = in_q * sin_cal;
    wire signed [31:0] q_cos = in_q * cos_cal;
    wire signed [31:0] i_sin = in_i * sin_cal;

    // Rotated components (33-bit intermediate for overflow headroom)
    wire signed [32:0] rot_i_full = i_cos + q_sin;   // I' = I*cos + Q*sin
    wire signed [32:0] rot_q_full = q_cos - i_sin;   // Q' = Q*cos - I*sin

    // Convert Q17.15 back to s16 integer — bits [30:15]
    wire signed [15:0] rot_i = rot_i_full[30:15];
    wire signed [15:0] rot_q = rot_q_full[30:15];

    always @(posedge clk) begin
        if (!rst_n) begin
            m_tdata  <= 32'd0;
            m_tvalid <= 1'b0;
        end else begin
            m_tvalid <= s_tvalid;
            if (s_tvalid) begin
                m_tdata <= {rot_q, rot_i};
            end
        end
    end

endmodule
