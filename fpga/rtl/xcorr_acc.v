// xcorr_acc.v — Streaming cross-correlation accumulator for 2-channel DoA
//
// Computes r_01 = (1/N) * sum( ch0[n] * conj(ch1[n]) ) over a snapshot.
//
// Interface:
//   - AXI-Stream slave: 32-bit TDATA, two beats per sample:
//     Beat 0 (beat_phase=0): {ch0_q[31:16], ch0_i[15:0]}
//     Beat 1 (beat_phase=1): {ch1_q[31:16], ch1_i[15:0]}
//     After both beats arrive, the MAC fires.
//   - Result outputs: xcorr_re, xcorr_im, result_valid
//
// Fixed-point: SC16 input (signed 16-bit I/Q), 48-bit accumulators.
// Target: Zynq-7000 XC7Z007S @ 100 MHz (Cora Z7)

`timescale 1ns / 1ps

module xcorr_acc #(
    parameter SNAPSHOT_LEN = 1024,  // samples per snapshot
    parameter ACC_WIDTH    = 48     // accumulator bit width
)(
    input  wire        clk,
    input  wire        rst_n,

    // AXI-Stream input (32-bit, two beats per sample)
    input  wire [31:0] s_axis_tdata,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,

    // Result output (active for one cycle at snapshot boundary)
    output reg  [ACC_WIDTH-1:0] xcorr_re,   // real part of r_01
    output reg  [ACC_WIDTH-1:0] xcorr_im,   // imag part of r_01
    output reg                  result_valid
);

    // ---------------------------------------------------------------
    // Beat phase: alternates 0/1 to track ch0 vs ch1 beats
    // ---------------------------------------------------------------
    reg beat_phase;

    // ---------------------------------------------------------------
    // Registered ch0 sample (captured on beat 0)
    // ---------------------------------------------------------------
    reg signed [15:0] ch0_i;
    reg signed [15:0] ch0_q;

    // ---------------------------------------------------------------
    // Unpack current beat from TDATA
    // ---------------------------------------------------------------
    wire signed [15:0] beat_i = s_axis_tdata[15:0];
    wire signed [15:0] beat_q = s_axis_tdata[31:16];

    // ---------------------------------------------------------------
    // Sample counter
    // ---------------------------------------------------------------
    reg [$clog2(SNAPSHOT_LEN)-1:0] sample_cnt;

    // ---------------------------------------------------------------
    // Accumulator registers
    // ---------------------------------------------------------------
    reg signed [ACC_WIDTH-1:0] acc_re;
    reg signed [ACC_WIDTH-1:0] acc_im;

    // ---------------------------------------------------------------
    // Two-beat capture + MAC datapath
    // ---------------------------------------------------------------
    //
    // Beat 0: capture ch0_i, ch0_q from TDATA
    // Beat 1: TDATA has ch1_i, ch1_q — compute cross-correlation
    //
    // Cross-correlation with conjugate of ch1:
    //   re(r_01) += ch0_i*ch1_i + ch0_q*ch1_q
    //   im(r_01) += ch0_q*ch1_i - ch0_i*ch1_q
    //
    always @(posedge clk) begin
        if (!rst_n) begin
            beat_phase   <= 0;
            ch0_i        <= 0;
            ch0_q        <= 0;
            acc_re       <= 0;
            acc_im       <= 0;
            sample_cnt   <= 0;
            xcorr_re     <= 0;
            xcorr_im     <= 0;
            result_valid <= 0;
        end else if (s_axis_tvalid) begin
            if (beat_phase == 0) begin
                // Beat 0: capture ch0, advance to beat 1
                ch0_i      <= beat_i;
                ch0_q      <= beat_q;
                beat_phase <= 1;
                result_valid <= 0;
            end else begin
                // Beat 1: ch1 arrives — compute MAC
                // beat_i = ch1_i, beat_q = ch1_q
                acc_re <= acc_re + (ch0_i * beat_i) + (ch0_q * beat_q);
                acc_im <= acc_im + (ch0_q * beat_i) - (ch0_i * beat_q);

                if (sample_cnt == SNAPSHOT_LEN - 1) begin
                    // Snapshot complete — latch final accumulated value
                    xcorr_re     <= acc_re + (ch0_i * beat_i) + (ch0_q * beat_q);
                    xcorr_im     <= acc_im + (ch0_q * beat_i) - (ch0_i * beat_q);
                    result_valid <= 1;
                    acc_re       <= 0;
                    acc_im       <= 0;
                    sample_cnt   <= 0;
                end else begin
                    result_valid <= 0;
                    sample_cnt   <= sample_cnt + 1;
                end

                beat_phase <= 0;
            end
        end else begin
            result_valid <= 0;
        end
    end

    // ---------------------------------------------------------------
    // Backpressure: always ready (streaming, no stalls)
    // ---------------------------------------------------------------
    assign s_axis_tready = 1'b1;

endmodule
