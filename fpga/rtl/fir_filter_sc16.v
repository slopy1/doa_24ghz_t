// fir_filter_sc16.v — Time-shared symmetric FIR filter for SC16 data
//
// WHAT:
//   48-tap linear-phase FIR applied to both ch0 and ch1. Coefficients are
//   Q1.15 signed, loadable at runtime over a simple addr/data port (the
//   doa_pipeline wrapper maps this onto AXI-Lite registers).
//
// ARCHITECTURE:
//   * 48 taps → 24 unique coefficients (symmetric, coeff[k] = coeff[47-k]).
//   * Time-shared: one state machine processes ch0 taps 0..23, then ch1
//     taps 0..23, then latches both outputs. Total = ~50 cycles per sample
//     pair, dominated by the 48 MAC ops. At 100 MHz vs 1 Msps, we have
//     100 cycles available per sample — ~50% headroom.
//   * Separate delay lines for ch0 I/Q and ch1 I/Q (4 × 48-deep shift regs).
//
// FIXED POINT:
//   * Input: s16 I, s16 Q
//   * Coefficient: Q1.15 s16
//   * Symmetric pair sum: 17 bits (adds 1 bit of headroom)
//   * Product of pair-sum × coeff: 33 bits
//   * 24 products summed: +5 bits → ~38 bits peak
//   * Accumulator: 48 bits (10 bits of headroom past peak)
//   * Output: take bits [30:15] of accumulator → s16 integer.
//
// BYPASS MODE (filter_en=0):
//   Pass the input sample through with 0 latency contribution (1 clk
//   through the OUTPUT state). Coefficients and delay line still shift —
//   that way toggling filter_en while running doesn't reset the pipeline.
//
// SPEC DEVIATION:
//   The spec's §6.2 shows `{ch0_acc_q[47:15], ch0_acc_i[47:15]}` for the
//   output, which is 66 bits jammed into a 32-bit register. That's wrong.
//   This implementation uses [30:15] on both — 16 bits each — which is the
//   correct Q17.15 → s16 truncation point.

`timescale 1ns / 1ps

module fir_filter_sc16 #(
    parameter NUM_TAPS    = 64,    // was 48 — bumped per plan A.2 (sharper transition band, ~36% timing-budget headroom retained)
    parameter NUM_UNIQUE  = NUM_TAPS/2,   // = 32
    parameter COEFF_WIDTH = 16,
    parameter DATA_WIDTH  = 16,
    parameter ACC_WIDTH   = 48
)(
    input  wire        clk,
    input  wire        rst_n,

    // Coefficient load port (synchronous)
    input  wire [$clog2(NUM_UNIQUE)-1:0] coeff_addr,
    input  wire signed [COEFF_WIDTH-1:0] coeff_data,
    input  wire                          coeff_wr_en,

    // Bypass control
    input  wire        filter_en,

    // Channel 0
    input  wire [31:0] ch0_tdata,
    input  wire        ch0_tvalid,
    output reg  [31:0] ch0_out_tdata,
    output reg         ch0_out_tvalid,

    // Channel 1
    input  wire [31:0] ch1_tdata,
    input  wire        ch1_tvalid,
    output reg  [31:0] ch1_out_tdata,
    output reg         ch1_out_tvalid
);

    // ---------------------------------------------------------------
    // Coefficient RAM (24 x 16 registers)
    // ---------------------------------------------------------------
    reg signed [COEFF_WIDTH-1:0] coeffs [0:NUM_UNIQUE-1];

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
    // Delay lines — 4 separate shift registers
    // ---------------------------------------------------------------
    reg signed [DATA_WIDTH-1:0] ch0_delay_i [0:NUM_TAPS-1];
    reg signed [DATA_WIDTH-1:0] ch0_delay_q [0:NUM_TAPS-1];
    reg signed [DATA_WIDTH-1:0] ch1_delay_i [0:NUM_TAPS-1];
    reg signed [DATA_WIDTH-1:0] ch1_delay_q [0:NUM_TAPS-1];

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
            if (ch0_tvalid) begin
                for (di = NUM_TAPS-1; di > 0; di = di - 1) begin
                    ch0_delay_i[di] <= ch0_delay_i[di-1];
                    ch0_delay_q[di] <= ch0_delay_q[di-1];
                end
                ch0_delay_i[0] <= $signed(ch0_tdata[15:0]);
                ch0_delay_q[0] <= $signed(ch0_tdata[31:16]);
            end
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
    // MAC state machine (time-shared ch0 → ch1)
    // ---------------------------------------------------------------
    localparam IDLE     = 2'd0;
    localparam COMP_CH0 = 2'd1;
    localparam COMP_CH1 = 2'd2;
    localparam OUTPUT   = 2'd3;

    reg [1:0] state;
    reg [$clog2(NUM_UNIQUE)-1:0] tap_idx;
    reg ch0_pending;
    reg ch1_pending;

    reg signed [ACC_WIDTH-1:0] ch0_acc_i;
    reg signed [ACC_WIDTH-1:0] ch0_acc_q;
    reg signed [ACC_WIDTH-1:0] ch1_acc_i;
    reg signed [ACC_WIDTH-1:0] ch1_acc_q;

    // Symmetric pair sums (17 bits to preserve add headroom)
    wire signed [DATA_WIDTH:0] ch0_sym_i =
        ch0_delay_i[tap_idx] + ch0_delay_i[NUM_TAPS-1-tap_idx];
    wire signed [DATA_WIDTH:0] ch0_sym_q =
        ch0_delay_q[tap_idx] + ch0_delay_q[NUM_TAPS-1-tap_idx];
    wire signed [DATA_WIDTH:0] ch1_sym_i =
        ch1_delay_i[tap_idx] + ch1_delay_i[NUM_TAPS-1-tap_idx];
    wire signed [DATA_WIDTH:0] ch1_sym_q =
        ch1_delay_q[tap_idx] + ch1_delay_q[NUM_TAPS-1-tap_idx];

    always @(posedge clk) begin
        if (!rst_n) begin
            state          <= IDLE;
            tap_idx        <= 0;
            ch0_pending    <= 1'b0;
            ch1_pending    <= 1'b0;
            ch0_acc_i      <= 0;
            ch0_acc_q      <= 0;
            ch1_acc_i      <= 0;
            ch1_acc_q      <= 0;
            ch0_out_tdata  <= 32'd0;
            ch0_out_tvalid <= 1'b0;
            ch1_out_tdata  <= 32'd0;
            ch1_out_tvalid <= 1'b0;
        end else begin
            // Default: outputs are one-cycle pulses
            ch0_out_tvalid <= 1'b0;
            ch1_out_tvalid <= 1'b0;

            // Latch pending flags on new sample arrivals
            if (ch0_tvalid) ch0_pending <= 1'b1;
            if (ch1_tvalid) ch1_pending <= 1'b1;

            case (state)
                IDLE: begin
                    if (ch0_pending && ch1_pending) begin
                        if (!filter_en) begin
                            // BYPASS: pass the most recent sample straight through
                            ch0_out_tdata  <= {ch0_delay_q[0], ch0_delay_i[0]};
                            ch0_out_tvalid <= 1'b1;
                            ch1_out_tdata  <= {ch1_delay_q[0], ch1_delay_i[0]};
                            ch1_out_tvalid <= 1'b1;
                            ch0_pending    <= 1'b0;
                            ch1_pending    <= 1'b0;
                        end else begin
                            ch0_acc_i <= 0;
                            ch0_acc_q <= 0;
                            tap_idx   <= 0;
                            state     <= COMP_CH0;
                        end
                    end
                end

                COMP_CH0: begin
                    ch0_acc_i <= ch0_acc_i + ($signed(coeffs[tap_idx]) * ch0_sym_i);
                    ch0_acc_q <= ch0_acc_q + ($signed(coeffs[tap_idx]) * ch0_sym_q);
                    if (tap_idx == NUM_UNIQUE - 1) begin
                        ch1_acc_i <= 0;
                        ch1_acc_q <= 0;
                        tap_idx   <= 0;
                        state     <= COMP_CH1;
                    end else begin
                        tap_idx <= tap_idx + 1;
                    end
                end

                COMP_CH1: begin
                    ch1_acc_i <= ch1_acc_i + ($signed(coeffs[tap_idx]) * ch1_sym_i);
                    ch1_acc_q <= ch1_acc_q + ($signed(coeffs[tap_idx]) * ch1_sym_q);
                    if (tap_idx == NUM_UNIQUE - 1) begin
                        state <= OUTPUT;
                    end else begin
                        tap_idx <= tap_idx + 1;
                    end
                end

                OUTPUT: begin
                    // Q17.15 → s16: take bits [30:15]
                    // FIX vs spec §6.2: was [ACC_WIDTH-1:15], should be [30:15]
                    ch0_out_tdata  <= {ch0_acc_q[30:15], ch0_acc_i[30:15]};
                    ch0_out_tvalid <= 1'b1;
                    ch1_out_tdata  <= {ch1_acc_q[30:15], ch1_acc_i[30:15]};
                    ch1_out_tvalid <= 1'b1;
                    ch0_pending    <= 1'b0;
                    ch1_pending    <= 1'b0;
                    state          <= IDLE;
                end
            endcase
        end
    end

endmodule
