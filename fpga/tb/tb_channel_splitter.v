// tb_channel_splitter.v — Testbench for channel_splitter
//
// Test cases:
//   1. Single sample (2 beats)           → ch0_tvalid then ch1_tvalid, data matches
//   2. Back-to-back 4 samples (8 beats)  → phase stays aligned across samples
//   3. tvalid gap mid-stream              → beat_phase doesn't advance on gap
//   4. Known SC16 payload (I=100, Q=-50) → unpacking is bit-exact

`timescale 1ns / 1ps

module tb_channel_splitter;

    localparam CLK_PERIOD = 10;  // 100 MHz

    reg         clk;
    reg         rst_n;
    reg  [31:0] s_axis_tdata;
    reg         s_axis_tvalid;
    wire        s_axis_tready;

    wire [31:0] ch0_tdata;
    wire        ch0_tvalid;
    wire [31:0] ch1_tdata;
    wire        ch1_tvalid;

    // DUT
    channel_splitter dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .s_axis_tdata (s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .ch0_tdata    (ch0_tdata),
        .ch0_tvalid   (ch0_tvalid),
        .ch1_tdata    (ch1_tdata),
        .ch1_tvalid   (ch1_tvalid)
    );

    // Clock
    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // Observers — latch last seen ch0/ch1 data for comparison
    reg [31:0] last_ch0_data;
    reg [31:0] last_ch1_data;
    integer    ch0_pulses;
    integer    ch1_pulses;

    always @(posedge clk) begin
        if (!rst_n) begin
            last_ch0_data <= 32'd0;
            last_ch1_data <= 32'd0;
            ch0_pulses    <= 0;
            ch1_pulses    <= 0;
        end else begin
            if (ch0_tvalid) begin
                last_ch0_data <= ch0_tdata;
                ch0_pulses    <= ch0_pulses + 1;
            end
            if (ch1_tvalid) begin
                last_ch1_data <= ch1_tdata;
                ch1_pulses    <= ch1_pulses + 1;
            end
        end
    end

    // Stream one beat with optional tvalid
    task drive_beat;
        input [31:0] data;
        input        valid;
        begin
            @(posedge clk);
            s_axis_tdata  <= data;
            s_axis_tvalid <= valid;
        end
    endtask

    integer test_pass;

    initial begin
        $dumpfile("tb_channel_splitter.vcd");
        $dumpvars(0, tb_channel_splitter);

        test_pass = 1;

        rst_n         = 0;
        s_axis_tdata  = 32'd0;
        s_axis_tvalid = 0;
        #(CLK_PERIOD * 5);
        rst_n = 1;
        #(CLK_PERIOD * 2);

        // ---------------------------------------------------------------
        // Test 1: Single sample (2 beats)
        // Beat 0: I=100 (0x0064), Q=-50 (0xFFCE) → 0xFFCE0064
        // Beat 1: I=200 (0x00C8), Q=-100 (0xFF9C) → 0xFF9C00C8
        // ---------------------------------------------------------------
        $display("\n=== Test 1: Single sample, bit-exact unpacking ===");
        drive_beat(32'hFFCE_0064, 1);  // ch0
        drive_beat(32'hFF9C_00C8, 1);  // ch1
        @(posedge clk);
        s_axis_tvalid <= 0;
        #(CLK_PERIOD * 2);

        if (ch0_pulses != 1 || ch1_pulses != 1) begin
            $display("  FAIL: Expected 1 pulse each, got ch0=%0d ch1=%0d", ch0_pulses, ch1_pulses);
            test_pass = 0;
        end
        if (last_ch0_data !== 32'hFFCE_0064) begin
            $display("  FAIL: ch0_tdata expected FFCE0064, got %08X", last_ch0_data);
            test_pass = 0;
        end
        if (last_ch1_data !== 32'hFF9C_00C8) begin
            $display("  FAIL: ch1_tdata expected FF9C00C8, got %08X", last_ch1_data);
            test_pass = 0;
        end
        $display("  ch0 pulses=%0d data=%08X", ch0_pulses, last_ch0_data);
        $display("  ch1 pulses=%0d data=%08X", ch1_pulses, last_ch1_data);

        // ---------------------------------------------------------------
        // Test 2: Back-to-back 4 samples (8 beats, no gaps)
        // ---------------------------------------------------------------
        $display("\n=== Test 2: 4 back-to-back samples ===");
        ch0_pulses = 0;
        ch1_pulses = 0;
        drive_beat(32'h0001_0001, 1);  // sample0 ch0
        drive_beat(32'h0002_0002, 1);  // sample0 ch1
        drive_beat(32'h0003_0003, 1);  // sample1 ch0
        drive_beat(32'h0004_0004, 1);  // sample1 ch1
        drive_beat(32'h0005_0005, 1);  // sample2 ch0
        drive_beat(32'h0006_0006, 1);  // sample2 ch1
        drive_beat(32'h0007_0007, 1);  // sample3 ch0
        drive_beat(32'h0008_0008, 1);  // sample3 ch1
        @(posedge clk);
        s_axis_tvalid <= 0;
        #(CLK_PERIOD * 2);

        if (ch0_pulses != 4 || ch1_pulses != 4) begin
            $display("  FAIL: Expected 4 pulses each, got ch0=%0d ch1=%0d", ch0_pulses, ch1_pulses);
            test_pass = 0;
        end
        if (last_ch0_data !== 32'h0007_0007) begin
            $display("  FAIL: last ch0_tdata expected 00070007, got %08X", last_ch0_data);
            test_pass = 0;
        end
        if (last_ch1_data !== 32'h0008_0008) begin
            $display("  FAIL: last ch1_tdata expected 00080008, got %08X", last_ch1_data);
            test_pass = 0;
        end
        $display("  ch0 pulses=%0d last=%08X", ch0_pulses, last_ch0_data);
        $display("  ch1 pulses=%0d last=%08X", ch1_pulses, last_ch1_data);

        // ---------------------------------------------------------------
        // Test 3: tvalid gap mid-stream
        // Send ch0 beat, drop tvalid for 3 cycles, then ch1 beat.
        // Phase must stay on "expecting ch1" across the gap.
        // ---------------------------------------------------------------
        $display("\n=== Test 3: tvalid gap mid-stream ===");
        ch0_pulses = 0;
        ch1_pulses = 0;
        drive_beat(32'hDEAD_BEEF, 1);  // ch0
        drive_beat(32'd0, 0);           // gap
        drive_beat(32'd0, 0);           // gap
        drive_beat(32'd0, 0);           // gap
        drive_beat(32'hCAFE_F00D, 1);  // ch1 (phase should still expect this)
        @(posedge clk);
        s_axis_tvalid <= 0;
        #(CLK_PERIOD * 2);

        if (ch0_pulses != 1 || ch1_pulses != 1) begin
            $display("  FAIL: Expected 1 pulse each across gap, got ch0=%0d ch1=%0d", ch0_pulses, ch1_pulses);
            test_pass = 0;
        end
        if (last_ch0_data !== 32'hDEAD_BEEF) begin
            $display("  FAIL: ch0_tdata expected DEADBEEF, got %08X", last_ch0_data);
            test_pass = 0;
        end
        if (last_ch1_data !== 32'hCAFE_F00D) begin
            $display("  FAIL: ch1_tdata expected CAFEF00D, got %08X", last_ch1_data);
            test_pass = 0;
        end
        $display("  ch0 pulses=%0d data=%08X", ch0_pulses, last_ch0_data);
        $display("  ch1 pulses=%0d data=%08X", ch1_pulses, last_ch1_data);

        // ---------------------------------------------------------------
        // Test 4: Reset mid-stream clears beat_phase
        // Send one ch0 beat, assert reset, then send a ch0 beat and
        // verify it lands on ch0 (not ch1).
        // ---------------------------------------------------------------
        $display("\n=== Test 4: Reset mid-stream realigns phase ===");
        ch0_pulses = 0;
        ch1_pulses = 0;
        drive_beat(32'h1111_1111, 1);  // ch0 (leaves phase=1)
        @(posedge clk);
        s_axis_tvalid <= 0;
        rst_n <= 0;
        #(CLK_PERIOD * 3);
        rst_n <= 1;
        @(posedge clk);

        // After reset, counters cleared, so re-init observers manually
        ch0_pulses = 0;
        ch1_pulses = 0;

        drive_beat(32'h2222_2222, 1);  // should land on ch0
        drive_beat(32'h3333_3333, 1);  // should land on ch1
        @(posedge clk);
        s_axis_tvalid <= 0;
        #(CLK_PERIOD * 2);

        if (ch0_pulses != 1 || ch1_pulses != 1) begin
            $display("  FAIL: Expected 1 pulse each post-reset, got ch0=%0d ch1=%0d", ch0_pulses, ch1_pulses);
            test_pass = 0;
        end
        if (last_ch0_data !== 32'h2222_2222) begin
            $display("  FAIL: post-reset ch0 expected 22222222, got %08X", last_ch0_data);
            test_pass = 0;
        end
        if (last_ch1_data !== 32'h3333_3333) begin
            $display("  FAIL: post-reset ch1 expected 33333333, got %08X", last_ch1_data);
            test_pass = 0;
        end
        $display("  ch0 pulses=%0d data=%08X", ch0_pulses, last_ch0_data);
        $display("  ch1 pulses=%0d data=%08X", ch1_pulses, last_ch1_data);

        #(CLK_PERIOD * 5);
        $display("\n========================================");
        if (test_pass)
            $display("  ALL TESTS PASSED");
        else
            $display("  SOME TESTS FAILED");
        $display("========================================\n");
        $finish;
    end

    // Timeout
    initial begin
        #(CLK_PERIOD * 2000);
        $display("TIMEOUT");
        $finish;
    end

endmodule
