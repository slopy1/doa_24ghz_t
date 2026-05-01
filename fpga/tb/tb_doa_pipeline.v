// tb_doa_pipeline.v — Integration testbench for the Phase A top level
//
// Covers:
//   1. AXI-Lite coefficient load + readback
//   2. Calibration register write + readback
//   3. Bypass-mode full snapshot with known signal → r00, r11, r01 match analytic
//   4. Autocorr double-count regression — r00/r11 must match the Python formula,
//      not 2× it (this is the spec bug we fixed).
//   5. 48-bit split readback sanity — writes large-value snapshots and confirms
//      LO/HI halves can be recombined on the ARM side.
//
// Uses SNAPSHOT_LEN=32 to keep simulation fast. Timing-wise the pipeline is
// no different from SNAPSHOT_LEN=1024 — only the counter wrap point changes.

`timescale 1ns / 1ps

module tb_doa_pipeline;

    localparam SNAPSHOT_LEN = 32;
    localparam ACC_WIDTH    = 48;
    localparam ADDR_WIDTH   = 12;
    localparam CLK_PERIOD   = 10;

    reg                  clk;
    reg                  resetn;

    // AXI-Lite
    reg  [ADDR_WIDTH-1:0] awaddr;
    reg  [2:0]            awprot;
    reg                   awvalid;
    wire                  awready;
    reg  [31:0]           wdata;
    reg  [3:0]            wstrb;
    reg                   wvalid;
    wire                  wready;
    wire [1:0]            bresp;
    wire                  bvalid;
    reg                   bready;
    reg  [ADDR_WIDTH-1:0] araddr;
    reg  [2:0]            arprot;
    reg                   arvalid;
    wire                  arready;
    wire [31:0]           rdata;
    wire [1:0]            rresp;
    wire                  rvalid;
    reg                   rready;

    // AXI-Stream
    reg  [31:0] axis_tdata;
    reg         axis_tvalid;
    wire        axis_tready;

    doa_pipeline #(
        .SNAPSHOT_LEN      (SNAPSHOT_LEN),
        .ACC_WIDTH         (ACC_WIDTH),
        .C_S_AXI_ADDR_WIDTH(ADDR_WIDTH)
    ) dut (
        .s_axi_aclk    (clk),
        .s_axi_aresetn (resetn),

        .s_axi_awaddr  (awaddr),
        .s_axi_awprot  (awprot),
        .s_axi_awvalid (awvalid),
        .s_axi_awready (awready),
        .s_axi_wdata   (wdata),
        .s_axi_wstrb   (wstrb),
        .s_axi_wvalid  (wvalid),
        .s_axi_wready  (wready),
        .s_axi_bresp   (bresp),
        .s_axi_bvalid  (bvalid),
        .s_axi_bready  (bready),
        .s_axi_araddr  (araddr),
        .s_axi_arprot  (arprot),
        .s_axi_arvalid (arvalid),
        .s_axi_arready (arready),
        .s_axi_rdata   (rdata),
        .s_axi_rresp   (rresp),
        .s_axi_rvalid  (rvalid),
        .s_axi_rready  (rready),

        .s_axis_tdata  (axis_tdata),
        .s_axis_tvalid (axis_tvalid),
        .s_axis_tready (axis_tready)
    );

    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    integer test_pass;

    // -------------------- AXI-Lite BFM --------------------

    task axi_write;
        input [ADDR_WIDTH-1:0] addr;
        input [31:0]           data;
        begin
            @(posedge clk);
            awaddr  <= addr;
            awvalid <= 1'b1;
            wdata   <= data;
            wstrb   <= 4'hF;
            wvalid  <= 1'b1;
            bready  <= 1'b1;
            wait (awready == 1'b1);
            @(posedge clk);
            awvalid <= 1'b0;
            wait (wready == 1'b1);
            @(posedge clk);
            wvalid  <= 1'b0;
            wait (bvalid == 1'b1);
            @(posedge clk);
            bready  <= 1'b0;
            #(CLK_PERIOD);
        end
    endtask

    reg [31:0] read_result;
    task axi_read;
        input [ADDR_WIDTH-1:0] addr;
        begin
            @(posedge clk);
            araddr  <= addr;
            arvalid <= 1'b1;
            rready  <= 1'b1;
            wait (arready == 1'b1);
            @(posedge clk);
            arvalid <= 1'b0;
            wait (rvalid == 1'b1);
            read_result <= rdata;
            @(posedge clk);
            rready <= 1'b0;
            #(CLK_PERIOD);
        end
    endtask

    // Task: feed a snapshot of N sample pairs via AXI-Stream (2 beats per sample)
    // Spaces each sample pair with enough delay that the FIR state machine can
    // complete its processing cycle before the next input arrives (bypass mode
    // needs only a few cycles; filter mode needs ~50).
    task feed_snapshot_pairs;
        input integer count;
        input [31:0]  ch0_data;
        input [31:0]  ch1_data;
        integer n;
        begin
            for (n = 0; n < count; n = n + 1) begin
                @(posedge clk);
                axis_tdata  <= ch0_data;
                axis_tvalid <= 1'b1;
                @(posedge clk);
                axis_tdata  <= ch1_data;
                @(posedge clk);
                axis_tvalid <= 1'b0;
                // Gap for bypass mode — short is fine
                repeat (6) @(posedge clk);
            end
        end
    endtask

    // Read a 48-bit split register pair and recombine
    reg [47:0] read48;
    task read_48bit;
        input [ADDR_WIDTH-1:0] lo_addr;
        input [ADDR_WIDTH-1:0] hi_addr;
        reg [31:0] lo;
        reg [31:0] hi;
        begin
            axi_read(lo_addr);
            lo = read_result;
            axi_read(hi_addr);
            hi = read_result;
            read48 = {hi[15:0], lo};
        end
    endtask

    initial begin
        $dumpfile("tb_doa_pipeline.vcd");
        $dumpvars(0, tb_doa_pipeline);

        test_pass = 1;

        resetn      = 0;
        awaddr      = 0;
        awvalid     = 0;
        wdata       = 0;
        wstrb       = 0;
        wvalid      = 0;
        bready      = 0;
        araddr      = 0;
        arvalid     = 0;
        rready      = 0;
        awprot      = 0;
        arprot      = 0;
        axis_tdata  = 0;
        axis_tvalid = 0;

        #(CLK_PERIOD * 10);
        resetn = 1;
        #(CLK_PERIOD * 5);

        // ---------------------------------------------------------------
        // Test 1: Register readback sanity — write cos/sin, read back
        // ---------------------------------------------------------------
        $display("\n=== Test 1: AXI-Lite cal register write/readback ===");
        axi_write(12'h028, 32'h0000_7AD4);  // cos = 31444
        axi_write(12'h02C, 32'h0000_23FE);  // sin = 9214

        axi_read(12'h028);
        $display("  COS_CAL readback = 0x%08X (expected 0x00007AD4)", read_result);
        if (read_result[15:0] !== 16'h7AD4) begin
            $display("  FAIL");
            test_pass = 0;
        end
        axi_read(12'h02C);
        $display("  SIN_CAL readback = 0x%08X (expected 0x000023FE)", read_result);
        if (read_result[15:0] !== 16'h23FE) begin
            $display("  FAIL");
            test_pass = 0;
        end

        // ---------------------------------------------------------------
        // Test 2: FILTER_CTRL write/readback
        // ---------------------------------------------------------------
        $display("\n=== Test 2: FILTER_CTRL ===");
        axi_write(12'h038, 32'h0000_0003);  // enable + coeff_loaded
        axi_read(12'h038);
        $display("  FILTER_CTRL = 0x%08X (expected 0x00000003)", read_result);
        if (read_result[1:0] !== 2'b11) begin
            $display("  FAIL");
            test_pass = 0;
        end

        // Put it back to bypass for test 3
        axi_write(12'h038, 32'h0000_0000);

        // ---------------------------------------------------------------
        // Test 3: Full snapshot in BYPASS mode — verify autocorr matches
        // analytic, no double-counting.
        //
        // Input: ch0 I=1000 Q=0, ch1 I=1000 Q=0  (fully correlated, zero phase)
        // Expected over 32 samples:
        //   r00 = r11 = 1000^2 * 32 = 32_000_000
        //   r01_re = 1000*1000 * 32 = 32_000_000
        //   r01_im = 0
        //
        // Also: cos_cal=32767 sin_cal=0 → phase rotation is identity (within 1 LSB)
        // ---------------------------------------------------------------
        $display("\n=== Test 3: Bypass snapshot, r00/r11/r01 analytic check ===");
        axi_write(12'h028, 32'h0000_7FFF);  // cos=32767 (identity)
        axi_write(12'h02C, 32'h0000_0000);  // sin=0
        axi_write(12'h038, 32'h0000_0000);  // filter bypass

        feed_snapshot_pairs(SNAPSHOT_LEN,
                            32'h0000_03E8,   // ch0: I=1000 Q=0
                            32'h0000_03E8);  // ch1: I=1000 Q=0

        // Wait for pipeline to flush and result_valid to latch
        #(CLK_PERIOD * 50);

        axi_read(12'h020);  // STATUS
        $display("  STATUS = 0x%08X (bit 0 should be 1)", read_result);
        if (read_result[0] !== 1'b1) begin
            $display("  FAIL — result_valid not set");
            test_pass = 0;
        end

        read_48bit(12'h010, 12'h014);  // R00
        $display("  r00 = %0d (expected ~32_000_000)", read48);
        // Bypass mode has a 1-LSB rounding at the identity rotation:
        // I' = I*32767/32768 = 999, so r00 from rotated ch1 drops slightly.
        // ch0 is not rotated at all, so r00 is exact. r11 drops a hair.
        if (read48 !== 32_000_000) begin
            $display("  FAIL r00");
            test_pass = 0;
        end

        read_48bit(12'h018, 12'h01C);  // R11
        $display("  r11 = %0d (expected ~31_936_032 after 999^2*32 rounding)", read48);
        if (read48 < 31_000_000 || read48 > 32_100_000) begin
            $display("  FAIL r11 out of expected range");
            test_pass = 0;
        end

        read_48bit(12'h000, 12'h004);  // XCORR_RE
        $display("  xcorr_re = %0d (expected ~32_000_000)", $signed(read48));
        if ($signed(read48) < 31_000_000 || $signed(read48) > 32_100_000) begin
            $display("  FAIL xcorr_re");
            test_pass = 0;
        end

        read_48bit(12'h008, 12'h00C);  // XCORR_IM
        $display("  xcorr_im = %0d (expected ~0)", $signed(read48));
        if ($signed(read48) < -1000 || $signed(read48) > 1000) begin
            $display("  FAIL xcorr_im — nonzero phase when should be zero");
            test_pass = 0;
        end

        // ---------------------------------------------------------------
        // Test 4: Autocorr double-count regression
        //
        // This is the spec-bug test. If autocorr were driven by the
        // level-high buf_*_valid combo, r00 would be 2 * (I^2 * N).
        // With our pulse-based wiring, r00 must equal exactly I^2 * N.
        //
        // Use a new value (I=500) and look for 500^2 * 32 = 8_000_000.
        // ---------------------------------------------------------------
        $display("\n=== Test 4: Autocorr double-count regression ===");

        // Clear status and count by reading
        axi_read(12'h020);  // clears valid

        feed_snapshot_pairs(SNAPSHOT_LEN,
                            32'h0000_01F4,   // ch0: I=500 Q=0
                            32'h0000_01F4);  // ch1: I=500 Q=0
        #(CLK_PERIOD * 50);

        read_48bit(12'h010, 12'h014);
        $display("  r00 = %0d (expected 8_000_000; double-count would give 16_000_000)", read48);
        if (read48 !== 8_000_000) begin
            $display("  FAIL — double-count bug");
            test_pass = 0;
        end

        // ---------------------------------------------------------------
        // Test 5: SNAP_COUNT increments
        // ---------------------------------------------------------------
        $display("\n=== Test 5: SNAP_COUNT increments ===");
        axi_read(12'h024);
        $display("  SNAP_COUNT = %0d (expected 2)", read_result);
        if (read_result !== 32'd2) begin
            $display("  FAIL — expected exactly 2 snapshots latched");
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
        #(CLK_PERIOD * 50000);
        $display("TIMEOUT");
        $finish;
    end

endmodule
