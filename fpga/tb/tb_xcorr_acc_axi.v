// tb_xcorr_acc_axi.v — Testbench for xcorr_acc_axi (32-bit stream version)

`timescale 1ns / 1ps

module tb_xcorr_acc_axi;

    localparam SNAPSHOT_LEN = 64;
    localparam ACC_WIDTH    = 48;
    localparam CLK_PERIOD   = 10;

    // DUT signals
    reg         clk;
    reg         resetn;

    // AXI-Lite
    reg  [3:0]  araddr;
    reg         arvalid;
    wire        arready;
    wire [31:0] rdata;
    wire [1:0]  rresp;
    wire        rvalid;
    reg         rready;

    reg  [3:0]  awaddr;
    reg         awvalid;
    wire        awready;
    reg  [31:0] wdata;
    reg  [3:0]  wstrb;
    reg         wvalid;
    wire        wready;
    wire [1:0]  bresp;
    wire        bvalid;
    reg         bready;

    // AXI-Stream (32-bit)
    reg  [31:0] tdata;
    reg         tvalid;
    wire        tready;

    // DUT
    xcorr_acc_axi #(
        .SNAPSHOT_LEN(SNAPSHOT_LEN),
        .ACC_WIDTH(ACC_WIDTH)
    ) dut (
        .s_axi_aclk(clk),
        .s_axi_aresetn(resetn),
        .s_axi_araddr(araddr),
        .s_axi_arprot(3'b000),
        .s_axi_arvalid(arvalid),
        .s_axi_arready(arready),
        .s_axi_rdata(rdata),
        .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid),
        .s_axi_rready(rready),
        .s_axi_awaddr(awaddr),
        .s_axi_awprot(3'b000),
        .s_axi_awvalid(awvalid),
        .s_axi_awready(awready),
        .s_axi_wdata(wdata),
        .s_axi_wstrb(wstrb),
        .s_axi_wvalid(wvalid),
        .s_axi_wready(wready),
        .s_axi_bresp(bresp),
        .s_axi_bvalid(bvalid),
        .s_axi_bready(bready),
        .s_axis_tdata(tdata),
        .s_axis_tvalid(tvalid),
        .s_axis_tready(tready)
    );

    // Clock
    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // LUT
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

    // AXI-Lite read task
    reg [31:0] read_result;
    task axi_read;
        input [3:0] addr;
        begin
            @(posedge clk);
            araddr  <= addr;
            arvalid <= 1;
            rready  <= 1;
            @(posedge clk);
            while (!arready) @(posedge clk);
            arvalid <= 0;
            while (!rvalid) @(posedge clk);
            read_result = rdata;
            @(posedge clk);
            rready <= 0;
        end
    endtask

    // Feed snapshot (32-bit, two beats per sample)
    integer n;
    task feed_snapshot;
        input integer phase_steps;
        begin
            for (n = 0; n < SNAPSHOT_LEN; n = n + 1) begin
                @(posedge clk);
                tvalid <= 1;
                tdata  <= {sin_lut[n % 8], cos_lut[n % 8]};
                @(posedge clk);
                tdata  <= {sin_lut[(n + phase_steps) % 8],
                           cos_lut[(n + phase_steps) % 8]};
            end
            @(posedge clk);
            tvalid <= 0;
            tdata  <= 32'd0;
        end
    endtask

    // Main test
    integer test_pass;
    initial begin
        $dumpfile("tb_xcorr_acc_axi.vcd");
        $dumpvars(0, tb_xcorr_acc_axi);
        test_pass = 1;

        resetn  <= 0;
        tvalid  <= 0;
        tdata   <= 0;
        arvalid <= 0;
        araddr  <= 0;
        rready  <= 0;
        awvalid <= 0;
        awaddr  <= 0;
        wvalid  <= 0;
        wdata   <= 0;
        wstrb   <= 0;
        bready  <= 1;

        #(CLK_PERIOD * 5);
        resetn <= 1;
        #(CLK_PERIOD * 2);

        // Test 1: Feed 0-degree, read via AXI-Lite
        $display("\n=== Test 1: Feed snapshot, read via AXI-Lite ===");
        feed_snapshot(0);
        #(CLK_PERIOD * 5);

        axi_read(4'h0);
        $display("  XCORR_RE (0x00) = %0d", $signed(read_result));
        if ($signed(read_result) <= 0) begin
            $display("  FAIL: Expected xcorr_re > 0");
            test_pass = 0;
        end

        axi_read(4'h4);
        $display("  XCORR_IM (0x04) = %0d", $signed(read_result));

        // Test 2: Sticky valid
        $display("\n=== Test 2: Sticky valid bit ===");
        axi_read(4'h8);
        $display("  STATUS (0x08)  = %0d (expect 1)", read_result);
        if (read_result != 1) begin
            $display("  FAIL: Expected valid=1");
            test_pass = 0;
        end
        #(CLK_PERIOD * 3);
        axi_read(4'h8);
        $display("  STATUS re-read = %0d (expect 0)", read_result);
        if (read_result != 0) begin
            $display("  FAIL: Expected valid=0 after clear-on-read");
            test_pass = 0;
        end

        // Test 3: Snapshot counter
        $display("\n=== Test 3: Snapshot counter ===");
        axi_read(4'hC);
        $display("  SNAP_COUNT = %0d (expect 1)", read_result);
        if (read_result != 1) begin
            $display("  FAIL: Expected snap_count=1");
            test_pass = 0;
        end

        feed_snapshot(4);
        #(CLK_PERIOD * 5);
        axi_read(4'hC);
        $display("  SNAP_COUNT = %0d (expect 2)", read_result);
        if (read_result != 2) begin
            $display("  FAIL: Expected snap_count=2");
            test_pass = 0;
        end

        axi_read(4'h0);
        $display("  XCORR_RE (180-deg) = %0d (expect < 0)", $signed(read_result));
        if ($signed(read_result) >= 0) begin
            $display("  FAIL: Expected xcorr_re < 0");
            test_pass = 0;
        end

        #(CLK_PERIOD * 10);
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
