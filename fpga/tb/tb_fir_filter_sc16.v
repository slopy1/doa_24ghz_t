// tb_fir_filter_sc16.v — Testbench for fir_filter_sc16
//
// Test cases:
//   1. Bypass mode (filter_en=0) — output should match newest delay-line sample
//   2. Kronecker delta → coefficient sequence readout (impulse response)
//   3. DC input through a normalized lowpass → output converges to input * sum(coeffs)
//   4. Two back-to-back samples — state machine resets cleanly between them
//
// The FIR processing takes ~50 cycles per sample (24 MAC cycles per channel
// + transitions), so we space input samples with a `WAIT_FIR` delay.

`timescale 1ns / 1ps

module tb_fir_filter_sc16;

    localparam NUM_TAPS   = 48;
    localparam NUM_UNIQUE = 24;
    localparam CLK_PERIOD = 10;
    localparam WAIT_FIR   = 80;  // cycles between input samples (safe > 50)

    reg                clk;
    reg                rst_n;
    reg  [4:0]         coeff_addr;
    reg  signed [15:0] coeff_data;
    reg                coeff_wr_en;
    reg                filter_en;
    reg  [31:0]        ch0_tdata;
    reg                ch0_tvalid;
    reg  [31:0]        ch1_tdata;
    reg                ch1_tvalid;
    wire [31:0]        ch0_out_tdata;
    wire               ch0_out_tvalid;
    wire [31:0]        ch1_out_tdata;
    wire               ch1_out_tvalid;

    fir_filter_sc16 #(
        .NUM_TAPS(NUM_TAPS)
    ) dut (
        .clk           (clk),
        .rst_n         (rst_n),
        .coeff_addr    (coeff_addr),
        .coeff_data    (coeff_data),
        .coeff_wr_en   (coeff_wr_en),
        .filter_en     (filter_en),
        .ch0_tdata     (ch0_tdata),
        .ch0_tvalid    (ch0_tvalid),
        .ch0_out_tdata (ch0_out_tdata),
        .ch0_out_tvalid(ch0_out_tvalid),
        .ch1_tdata     (ch1_tdata),
        .ch1_tvalid    (ch1_tvalid),
        .ch1_out_tdata (ch1_out_tdata),
        .ch1_out_tvalid(ch1_out_tvalid)
    );

    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // Observe last output for each channel
    reg signed [15:0] last_ch0_i;
    reg signed [15:0] last_ch0_q;
    reg signed [15:0] last_ch1_i;
    reg signed [15:0] last_ch1_q;
    integer ch0_out_cnt;
    integer ch1_out_cnt;

    always @(posedge clk) begin
        if (!rst_n) begin
            last_ch0_i  <= 0;
            last_ch0_q  <= 0;
            last_ch1_i  <= 0;
            last_ch1_q  <= 0;
            ch0_out_cnt <= 0;
            ch1_out_cnt <= 0;
        end else begin
            if (ch0_out_tvalid) begin
                last_ch0_i  <= ch0_out_tdata[15:0];
                last_ch0_q  <= ch0_out_tdata[31:16];
                ch0_out_cnt <= ch0_out_cnt + 1;
            end
            if (ch1_out_tvalid) begin
                last_ch1_i  <= ch1_out_tdata[15:0];
                last_ch1_q  <= ch1_out_tdata[31:16];
                ch1_out_cnt <= ch1_out_cnt + 1;
            end
        end
    end

    integer test_pass;
    integer k;

    // Task: write one coefficient
    task write_coeff;
        input [4:0]          addr;
        input signed [15:0]  data;
        begin
            @(posedge clk);
            coeff_addr  <= addr;
            coeff_data  <= data;
            coeff_wr_en <= 1'b1;
            @(posedge clk);
            coeff_wr_en <= 1'b0;
        end
    endtask

    // Task: drive one sample pair (ch0 and ch1, both valid for 1 cycle)
    task drive_sample;
        input [31:0] d0;
        input [31:0] d1;
        begin
            @(posedge clk);
            ch0_tdata  <= d0;
            ch0_tvalid <= 1'b1;
            ch1_tdata  <= d1;
            ch1_tvalid <= 1'b1;
            @(posedge clk);
            ch0_tvalid <= 1'b0;
            ch1_tvalid <= 1'b0;
        end
    endtask

    // Task: drive one sample and wait for filter result
    task drive_and_wait;
        input [31:0] d0;
        input [31:0] d1;
        begin
            drive_sample(d0, d1);
            // Wait for ch1 output (ch1 completes last in the FIR state machine)
            @(posedge ch1_out_tvalid);
            @(posedge clk);
        end
    endtask

    initial begin
        $dumpfile("tb_fir_filter_sc16.vcd");
        $dumpvars(0, tb_fir_filter_sc16);

        test_pass   = 1;
        rst_n       = 0;
        coeff_addr  = 0;
        coeff_data  = 0;
        coeff_wr_en = 0;
        filter_en   = 0;
        ch0_tdata   = 32'd0;
        ch0_tvalid  = 0;
        ch1_tdata   = 32'd0;
        ch1_tvalid  = 0;
        #(CLK_PERIOD * 5);
        rst_n = 1;
        #(CLK_PERIOD * 2);

        // ---------------------------------------------------------------
        // Test 1: Bypass mode — output should equal newest input sample
        // ---------------------------------------------------------------
        $display("\n=== Test 1: Bypass mode (filter_en=0) ===");
        filter_en = 1'b0;
        drive_sample(32'h0000_1234, 32'h0000_5678);
        @(posedge ch1_out_tvalid);
        @(posedge clk);
        $display("  ch0_out=%08X (expected 00001234)", ch0_out_tdata);
        $display("  ch1_out=%08X (expected 00005678)", ch1_out_tdata);
        if (ch0_out_tdata !== 32'h0000_1234 || ch1_out_tdata !== 32'h0000_5678) begin
            $display("  FAIL");
            test_pass = 0;
        end
        #(CLK_PERIOD * WAIT_FIR);

        // ---------------------------------------------------------------
        // Test 2: Impulse response — single coefficient non-zero
        // Load coeff[0] = 16384 (Q1.15 = 0.5).
        // Because of symmetry, coeff[0] also applies to tap[47].
        // With input = Kronecker delta (large I, then zeros), the first
        // filter output is: coeff[0] * delay[0] + coeff[0] * delay[47].
        // After first impulse, delay[47] is still 0, so output_i = 0.5 * I.
        // Q17.15 → s16 truncation: bits [30:15] of the accumulator.
        // Input I=32000 → product = 32000 * 16384 = 524_288_000 = 0x1F40_0000
        // Add once: acc = 524_288_000 (Q17.15). Bits [30:15] = 16000.
        // ---------------------------------------------------------------
        $display("\n=== Test 2: Impulse response, single non-zero coeff ===");
        // Clear all coefficients
        for (k = 0; k < NUM_UNIQUE; k = k + 1) begin
            write_coeff(k[4:0], 16'sd0);
        end
        // Load coeff[0] = 16384 (= 0.5 in Q1.15)
        write_coeff(5'd0, 16'sd16384);
        filter_en = 1'b1;
        // Drive impulse (I=32000)
        drive_and_wait(32'h0000_7D00, 32'h0000_7D00);  // 0x7D00 = 32000
        $display("  ch0_out_i=%0d (expected ~16000)", $signed(ch0_out_tdata[15:0]));
        $display("  ch1_out_i=%0d (expected ~16000)", $signed(ch1_out_tdata[15:0]));
        // Allow ±2 LSB for truncation
        if ($signed(ch0_out_tdata[15:0]) < 16000 - 2 || $signed(ch0_out_tdata[15:0]) > 16000 + 2) begin
            $display("  FAIL ch0");
            test_pass = 0;
        end
        if ($signed(ch1_out_tdata[15:0]) < 16000 - 2 || $signed(ch1_out_tdata[15:0]) > 16000 + 2) begin
            $display("  FAIL ch1");
            test_pass = 0;
        end

        // Second sample: zero input. Now delay[1] has the impulse, coeff[0]*0 = 0.
        // But coeff[0] is symmetric (also tap 47), so delay[47] is still 0 → 0.
        drive_and_wait(32'h0000_0000, 32'h0000_0000);
        $display("  after zero: ch0_out_i=%0d (expected 0)", $signed(ch0_out_tdata[15:0]));
        if ($signed(ch0_out_tdata[15:0]) !== 0) begin
            $display("  FAIL — impulse leaked into next output");
            test_pass = 0;
        end

        // ---------------------------------------------------------------
        // Test 3: DC gain — uniform rectangular window
        // Load all 24 coeffs to 16384/24 ≈ 683 (so sum ≈ 16383 ≈ 0.5)
        // Actually, easier: set each unique coeff to 683 (int).
        // Symmetric pair sum = 2*683 = 1366 per tap.
        // After filling the delay line with DC=1000, each pair contributes:
        //   1366 * 1000 = 1_366_000 per coefficient
        //   * 24 coeffs = 32_784_000 total (Q17.15)
        // Truncate [30:15]: 32_784_000 >> 15 = 1000 (approx).
        // ---------------------------------------------------------------
        $display("\n=== Test 3: DC gain with uniform window ===");
        // Reset accumulators by toggling rst_n
        rst_n = 1'b0;
        #(CLK_PERIOD * 3);
        rst_n = 1'b1;
        #(CLK_PERIOD * 2);

        for (k = 0; k < NUM_UNIQUE; k = k + 1) begin
            write_coeff(k[4:0], 16'sd683);
        end
        filter_en = 1'b1;

        // Fill delay line with 48 DC samples (I=1000 Q=0)
        for (k = 0; k < NUM_TAPS; k = k + 1) begin
            drive_and_wait(32'h0000_03E8, 32'h0000_03E8);  // 0x03E8 = 1000
        end

        $display("  ch0_out_i=%0d (expected ~1000)",  $signed(ch0_out_tdata[15:0]));
        $display("  ch1_out_i=%0d (expected ~1000)",  $signed(ch1_out_tdata[15:0]));
        // Expected ~1000 ± a few LSB (683 vs 682.67 rounding drift)
        if ($signed(ch0_out_tdata[15:0]) < 995 || $signed(ch0_out_tdata[15:0]) > 1005) begin
            $display("  FAIL ch0");
            test_pass = 0;
        end
        if ($signed(ch1_out_tdata[15:0]) < 995 || $signed(ch1_out_tdata[15:0]) > 1005) begin
            $display("  FAIL ch1");
            test_pass = 0;
        end

        // ---------------------------------------------------------------
        // Test 4: Non-zero Q component passes through
        // Same uniform window, DC input I=500 Q=-300
        // ---------------------------------------------------------------
        $display("\n=== Test 4: I+Q DC passthrough ===");
        // Fill with new DC value
        for (k = 0; k < NUM_TAPS; k = k + 1) begin
            drive_and_wait(32'hFED4_01F4, 32'hFED4_01F4);  // I=500, Q=-300
        end
        $display("  ch0_out_i=%0d (expected ~500)",  $signed(ch0_out_tdata[15:0]));
        $display("  ch0_out_q=%0d (expected ~-300)", $signed(ch0_out_tdata[31:16]));
        if ($signed(ch0_out_tdata[15:0]) < 495 || $signed(ch0_out_tdata[15:0]) > 505) begin
            $display("  FAIL I");
            test_pass = 0;
        end
        if ($signed(ch0_out_tdata[31:16]) < -305 || $signed(ch0_out_tdata[31:16]) > -295) begin
            $display("  FAIL Q");
            test_pass = 0;
        end

        #(CLK_PERIOD * 20);
        $display("\n========================================");
        if (test_pass)
            $display("  ALL TESTS PASSED");
        else
            $display("  SOME TESTS FAILED");
        $display("========================================\n");
        $finish;
    end

    initial begin
        #(CLK_PERIOD * 100000);
        $display("TIMEOUT");
        $finish;
    end

endmodule
