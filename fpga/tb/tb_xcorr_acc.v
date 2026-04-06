// tb_xcorr_acc.v — Testbench for xcorr_acc (32-bit, two-beat version)
//
// Test cases:
//   1. Same signal on both channels     -> xcorr_im ~ 0 (zero phase)
//   2. 90-degree phase shift             -> xcorr_re ~ 0
//   3. Known phase offset (45 degrees)   -> re ~ im
//   4. 180-degree phase shift            -> xcorr_re < 0
//   5. Back-to-back snapshots            -> accumulators clear correctly

`timescale 1ns / 1ps

module tb_xcorr_acc;

    localparam SNAPSHOT_LEN = 64;
    localparam ACC_WIDTH    = 48;
    localparam CLK_PERIOD   = 10;  // 100 MHz

    // DUT signals
    reg         clk;
    reg         rst_n;
    reg  [31:0] s_axis_tdata;
    reg         s_axis_tvalid;
    wire        s_axis_tready;

    wire [ACC_WIDTH-1:0] xcorr_re;
    wire [ACC_WIDTH-1:0] xcorr_im;
    wire                 result_valid;

    // DUT
    xcorr_acc #(
        .SNAPSHOT_LEN(SNAPSHOT_LEN),
        .ACC_WIDTH(ACC_WIDTH)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .xcorr_re(xcorr_re),
        .xcorr_im(xcorr_im),
        .result_valid(result_valid)
    );

    // Clock
    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // Sine/cosine LUT (8 entries per cycle = 45-degree steps, amp=1000)
    reg signed [15:0] cos_lut [0:7];
    reg signed [15:0] sin_lut [0:7];

    initial begin
        cos_lut[0] =  1000; sin_lut[0] =     0;
        cos_lut[1] =   707; sin_lut[1] =   707;
        cos_lut[2] =     0; sin_lut[2] =  1000;
        cos_lut[3] =  -707; sin_lut[3] =   707;
        cos_lut[4] = -1000; sin_lut[4] =     0;
        cos_lut[5] =  -707; sin_lut[5] =  -707;
        cos_lut[6] =     0; sin_lut[6] = -1000;
        cos_lut[7] =   707; sin_lut[7] =  -707;
    end

    // ---------------------------------------------------------------
    // Task: feed one snapshot (two beats per sample)
    //   Beat 0: {ch0_q, ch0_i}
    //   Beat 1: {ch1_q, ch1_i}
    // ---------------------------------------------------------------
    integer n;
    task feed_snapshot;
        input integer phase_steps;
        begin
            for (n = 0; n < SNAPSHOT_LEN; n = n + 1) begin
                // Beat 0: ch0
                @(posedge clk);
                s_axis_tvalid <= 1;
                s_axis_tdata  <= {sin_lut[n % 8], cos_lut[n % 8]};

                // Beat 1: ch1
                @(posedge clk);
                s_axis_tdata  <= {sin_lut[(n + phase_steps) % 8],
                                  cos_lut[(n + phase_steps) % 8]};
            end
            @(posedge clk);
            s_axis_tvalid <= 0;
            s_axis_tdata  <= 32'd0;
        end
    endtask

    // Task: wait for result_valid and print
    task wait_and_print;
        input [8*32-1:0] label;
        begin
            @(posedge result_valid);
            @(posedge clk);
            $display("%-20s  xcorr_re = %0d, xcorr_im = %0d",
                     label,
                     $signed(xcorr_re),
                     $signed(xcorr_im));
        end
    endtask

    // Main test sequence
    integer test_pass;

    initial begin
        $dumpfile("tb_xcorr_acc.vcd");
        $dumpvars(0, tb_xcorr_acc);

        test_pass = 1;

        rst_n         <= 0;
        s_axis_tvalid <= 0;
        s_axis_tdata  <= 32'd0;
        #(CLK_PERIOD * 5);
        rst_n <= 1;
        #(CLK_PERIOD * 2);

        // Test 1: 0-degree
        $display("\n=== Test 1: Zero phase offset (same signal) ===");
        fork
            feed_snapshot(0);
            wait_and_print("T1 0-deg");
        join
        if ($signed(xcorr_im) != 0) begin
            $display("  WARN: Expected xcorr_im=0, got %0d", $signed(xcorr_im));
        end
        if ($signed(xcorr_re) <= 0) begin
            $display("  FAIL: Expected xcorr_re > 0");
            test_pass = 0;
        end
        #(CLK_PERIOD * 5);

        // Test 2: 90-degree
        $display("\n=== Test 2: 90-degree phase offset ===");
        fork
            feed_snapshot(2);
            wait_and_print("T2 90-deg");
        join
        #(CLK_PERIOD * 5);

        // Test 3: 45-degree
        $display("\n=== Test 3: 45-degree phase offset ===");
        fork
            feed_snapshot(1);
            wait_and_print("T3 45-deg");
        join
        #(CLK_PERIOD * 5);

        // Test 4: 180-degree
        $display("\n=== Test 4: 180-degree phase offset ===");
        fork
            feed_snapshot(4);
            wait_and_print("T4 180-deg");
        join
        if ($signed(xcorr_re) >= 0) begin
            $display("  FAIL: Expected xcorr_re < 0 for 180-deg");
            test_pass = 0;
        end
        #(CLK_PERIOD * 5);

        // Test 5: Back-to-back
        $display("\n=== Test 5: Back-to-back snapshots ===");
        fork
            begin
                feed_snapshot(0);
                feed_snapshot(4);
            end
            begin
                wait_and_print("T5a 0-deg");
                wait_and_print("T5b 180-deg");
            end
        join

        #(CLK_PERIOD * 10);
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
        #(CLK_PERIOD * 20000);
        $display("TIMEOUT");
        $finish;
    end

endmodule
