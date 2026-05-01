// channel_splitter.v — Demux interleaved 2-beat AXI-Stream into ch0/ch1 streams
//
// The AXI DMA delivers raw SC16 samples as alternating beats on a single
// 32-bit stream:
//
//   Beat 0 (beat_phase=0): {ch0_q[31:16], ch0_i[15:0]}
//   Beat 1 (beat_phase=1): {ch1_q[31:16], ch1_i[15:0]}
//   Beat 0 (next sample):  ch0 again, ...
//
// Downstream blocks (FIR, phase_rotate, autocorr) want two independent
// streams, one per channel, so they can operate on both in parallel
// (or time-share, in the FIR's case).
//
// Design notes:
//   * s_axis_tready is tied high — we match the existing xcorr_acc's
//     streaming-no-backpressure philosophy. The DMA is the timing master.
//   * Output valids are one-cycle pulses so downstream shift-registers
//     and MACs can use them as clock enables without extra edge detection.
//   * beat_phase recovery: if the DMA were to drop the first beat, we'd
//     be misaligned forever. The AXI DMA's SG descriptors guarantee
//     atomic 2-beat transfers, so this isn't a concern in the real system.
//
// Target: Zynq-7000 XC7Z007S @ 100 MHz (Cora Z7)

`timescale 1ns / 1ps

module channel_splitter (
    input  wire        clk,
    input  wire        rst_n,

    // AXI-Stream input (interleaved ch0/ch1 beats from DMA)
    input  wire [31:0] s_axis_tdata,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,

    // Channel 0 output
    output reg  [31:0] ch0_tdata,
    output reg         ch0_tvalid,

    // Channel 1 output
    output reg  [31:0] ch1_tdata,
    output reg         ch1_tvalid
);

    // ---------------------------------------------------------------
    // Beat phase: 0 = next valid beat is ch0, 1 = next valid beat is ch1
    // ---------------------------------------------------------------
    reg beat_phase;

    // Never stall — DMA is timing master
    assign s_axis_tready = 1'b1;

    always @(posedge clk) begin
        if (!rst_n) begin
            beat_phase <= 1'b0;
            ch0_tdata  <= 32'd0;
            ch0_tvalid <= 1'b0;
            ch1_tdata  <= 32'd0;
            ch1_tvalid <= 1'b0;
        end else begin
            // Default: outputs are one-cycle pulses
            ch0_tvalid <= 1'b0;
            ch1_tvalid <= 1'b0;

            if (s_axis_tvalid) begin
                if (beat_phase == 1'b0) begin
                    // Beat 0 → ch0
                    ch0_tdata  <= s_axis_tdata;
                    ch0_tvalid <= 1'b1;
                    beat_phase <= 1'b1;
                end else begin
                    // Beat 1 → ch1
                    ch1_tdata  <= s_axis_tdata;
                    ch1_tvalid <= 1'b1;
                    beat_phase <= 1'b0;
                end
            end
        end
    end

endmodule
