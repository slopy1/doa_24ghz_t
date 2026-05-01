// tb_autocorr_acc.v — Testbench for autocorr_acc
//
// Test cases:
//   1. DC input at ±1000 on both channels → known power sum
//   2. Sinusoid input (same LUT as xcorr testbench) → matches NumPy reference
//   3. Back-to-back snapshots → accumulators clear cleanly
//   4. Unaligned valids (ch0 or ch1 alone) → NOT accumulated (single-cycle pulse rule)

`timescale 1ns / 1ps

module tb_autocorr_acc;

    localparam SNAPSHOT_LEN = 64;
    localparam ACC_WIDTH    = 48;
    localparam CLK_PERIOD   = 10;

    reg                     clk;
    reg                     rst_n;
    reg  [31:0]             ch0_tdata;
    reg                     ch0_tvalid;
    reg  [31:0]             ch1_tdata;
    reg                     ch1_tvalid;
    wire [ACC_WIDTH-1:0]    r00;
    wire [ACC_WIDTH-1:0]    r11;
    wire                    result_valid;

    autocorr_acc #(
        .SNAPSHOT_LEN(SNAPSHOT_LEN),
        .ACC_WIDTH(ACC_WIDTH)
    ) dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .ch0_tdata   (ch0_tdata),
        .ch0_tvalid  (ch0_tvalid),
        .ch1_tdata   (ch1_tdata),
        .ch1_tvalid  (ch1_tvalid),
        .r00         (r00),
        .r11         (r11),
        .result_valid(result_valid)
    );

    // Clock
    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // Sinusoid LUT (matches tb_xcorr_acc.v, amp=1000)
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

    // Task: feed a snapshot of constant I/Q on both channels
    task feed_dc_snapshot;
        input signed [15:0] i0;
        input signed [15:0] q0;
        input signed [15:0] i1;
        input signed [15:0] q1;
        integer n;
        begin
            for (n = 0; n < SNAPSHOT_LEN; n = n + 1) begin
                @(posedge clk);
                ch0_tdata  <= {q0, i0};
                ch0_tvalid <= 1'b1;
                ch1_tdata  <= {q1, i1};
                ch1_tvalid <= 1'b1;
                @(posedge clk);
                // Valid is a one-cycle pulse — matches channel_splitter
                ch0_tvalid <= 1'b0;
                ch1_tvalid <= 1'b0;
            end
        end
    endtask

    // Task: feed sinusoid snapshot
    task feed_sin_snapshot;
        integer n;
        begin
            for (n = 0; n < SNAPSHOT_LEN; n = n + 1) begin
                @(posedge clk);
                ch0_tdata  <= {sin_lut[n % 8], cos_lut[n % 8]};
                ch0_tvalid <= 1'b1;
                ch1_tdata  <= {sin_lut[n % 8], cos_lut[n % 8]};
                ch1_tvalid <= 1'b1;
                @(posedge clk);
                ch0_tvalid <= 1'b0;
                ch1_tvalid <= 1'b0;
            end
        end
    endtask

    task wait_result;
        begin
            @(posedge result_valid);
            @(posedge clk);
        end
    endtask

    // Expected: sinusoid LUT power = cos^2 + sin^2 per sample
    // cos=1000,sin=0     → 1_000_000
    // cos=707,sin=707    → 499_849 + 499_849 = 999_698
    // cos=0,sin=1000     → 1_000_000
    // cos=-707,sin=707   → 999_698
    // cos=-1000,sin=0    → 1_000_000
    // cos=-707,sin=-707  → 999_698
    // cos=0,sin=-1000    → 1_000_000
    // cos=707,sin=-707   → 999_698
    // Average over 8 = 999_849. Over 64 samples = 63_990_336 (exactly).

    integer test_pass;

    initial begin
        $dumpfile("tb_autocorr_acc.vcd");
        $dumpvars(0, tb_autocorr_acc);

        test_pass = 1;

        rst_n      = 0;
        ch0_tdata  = 32'd0;
        ch0_tvalid = 0;
        ch1_tdata  = 32'd0;
        ch1_tvalid = 0;
        #(CLK_PERIOD * 5);
        rst_n = 1;
        #(CLK_PERIOD * 2);

        // ---------------------------------------------------------------
        // Test 1: DC input (I=1000, Q=0) on both channels
        // Expected: 1000^2 * 64 = 64_000_000 for both r00 and r11
        // ---------------------------------------------------------------
        $display("\n=== Test 1: DC input I=1000 Q=0 ===");
        fork
            feed_dc_snapshot(16'sd1000, 16'sd0, 16'sd1000, 16'sd0);
            wait_result;
        join
        $display("  r00 = %0d (expected 64000000)", r00);
        $display("  r11 = %0d (expected 64000000)", r11);
        if (r00 !== 64_000_000 || r11 !== 64_000_000) begin
            $display("  FAIL");
            test_pass = 0;
        end
        #(CLK_PERIOD * 5);

        // ---------------------------------------------------------------
        // Test 2: DC input with different powers per channel
        // ch0: I=500 Q=-500 → 250000+250000 = 500000/sample → 32000000 total
        // ch1: I=2000 Q=0  → 4000000/sample → 256000000 total
        // ---------------------------------------------------------------
        $display("\n=== Test 2: Asymmetric DC ===");
        fork
            feed_dc_snapshot(16'sd500, -16'sd500, 16'sd2000, 16'sd0);
            wait_result;
        join
        $display("  r00 = %0d (expected 32000000)", r00);
        $display("  r11 = %0d (expected 256000000)", r11);
        if (r00 !== 32_000_000 || r11 !== 256_000_000) begin
            $display("  FAIL");
            test_pass = 0;
        end
        #(CLK_PERIOD * 5);

        // ---------------------------------------------------------------
        // Test 3: Sinusoid — matches LUT expected value
        // 8 samples of LUT power sum = 7_999_020 (see comment above)
        // Wait — recomputing: (1e6 + 999698 + 1e6 + 999698 + 1e6 + 999698 + 1e6 + 999698)
        //                   = 4_000_000 + 3_998_792 = 7_998_792
        // Per sample average = 999_849.   64 samples = 63_990_336
        // ---------------------------------------------------------------
        $display("\n=== Test 3: Sinusoid, power sum ===");
        fork
            feed_sin_snapshot;
            wait_result;
        join
        $display("  r00 = %0d (expected 63990336)", r00);
        $display("  r11 = %0d (expected 63990336)", r11);
        if (r00 !== 63_990_336 || r11 !== 63_990_336) begin
            $display("  FAIL");
            test_pass = 0;
        end
        #(CLK_PERIOD * 5);

        // ---------------------------------------------------------------
        // Test 4: Back-to-back — DC followed immediately by different DC
        // ---------------------------------------------------------------
        $display("\n=== Test 4: Back-to-back snapshots ===");
        fork
            begin
                feed_dc_snapshot(16'sd100, 16'sd0, 16'sd100, 16'sd0);
                feed_dc_snapshot(16'sd200, 16'sd0, 16'sd300, 16'sd0);
            end
            begin
                wait_result;
                $display("  Snap A: r00=%0d r11=%0d (expected 640000 both)", r00, r11);
                if (r00 !== 640_000 || r11 !== 640_000) begin
                    $display("  FAIL on snap A");
                    test_pass = 0;
                end
                wait_result;
                $display("  Snap B: r00=%0d (expected 2560000) r11=%0d (expected 5760000)", r00, r11);
                if (r00 !== 2_560_000 || r11 !== 5_760_000) begin
                    $display("  FAIL on snap B");
                    test_pass = 0;
                end
            end
        join
        #(CLK_PERIOD * 5);

        // ---------------------------------------------------------------
        // Test 5: Unaligned valids — ch0 alone should NOT accumulate
        // After 10 ch0-only pulses, the snapshot counter should still be 0.
        // Then 64 aligned pulses should complete one snapshot normally.
        // ---------------------------------------------------------------
        $display("\n=== Test 5: Unaligned ch0 valids are ignored ===");
        begin : unaligned
            integer n;
            for (n = 0; n < 10; n = n + 1) begin
                @(posedge clk);
                ch0_tdata  <= 32'h0000_7FFF;  // I=max, Q=0
                ch0_tvalid <= 1'b1;
                ch1_tvalid <= 1'b0;
                @(posedge clk);
                ch0_tvalid <= 1'b0;
            end
        end
        fork
            feed_dc_snapshot(16'sd100, 16'sd0, 16'sd100, 16'sd0);
            wait_result;
        join
        $display("  r00=%0d r11=%0d (expected 640000 both)", r00, r11);
        if (r00 !== 640_000 || r11 !== 640_000) begin
            $display("  FAIL — ch0-alone pulses leaked into accumulator");
            test_pass = 0;
        end
        #(CLK_PERIOD * 5);

        $display("\n========================================");
        if (test_pass)
            $display("  ALL TESTS PASSED");
        else
            $display("  SOME TESTS FAILED");
        $display("========================================\n");
        $finish;
    end

    initial begin
        #(CLK_PERIOD * 20000);
        $display("TIMEOUT");
        $finish;
    end

endmodule
