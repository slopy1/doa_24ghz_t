// emio_regfile_tb.v -- self-checking testbench for EMIO AXI-Lite bridge

`timescale 1ns / 1ps

module axi_lite_stub #(
    parameter ADDR_WIDTH = 12
)(
    input  wire                  clk,
    input  wire                  resetn,

    input  wire [ADDR_WIDTH-1:0] awaddr,
    input  wire [2:0]            awprot,
    input  wire                  awvalid,
    output reg                   awready,
    input  wire [31:0]           wdata,
    input  wire [3:0]            wstrb,
    input  wire                  wvalid,
    output reg                   wready,
    output reg  [1:0]            bresp,
    output reg                   bvalid,
    input  wire                  bready,

    input  wire [ADDR_WIDTH-1:0] araddr,
    input  wire [2:0]            arprot,
    input  wire                  arvalid,
    output reg                   arready,
    output reg  [31:0]           rdata,
    output reg  [1:0]            rresp,
    output reg                   rvalid,
    input  wire                  rready
);
    reg [31:0] mem [0:31];
    integer aw_delay;
    integer w_delay;
    integer b_delay;
    integer ar_delay;
    integer r_delay;
    integer i;

    initial begin
        awready = 0;
        wready  = 0;
        bresp   = 0;
        bvalid  = 0;
        arready = 0;
        rdata   = 0;
        rresp   = 0;
        rvalid  = 0;
        aw_delay = 0;
        w_delay  = 0;
        b_delay  = 0;
        ar_delay = 0;
        r_delay  = 0;
        for (i = 0; i < 32; i = i + 1)
            mem[i] = 32'h0;
    end

    reg [ADDR_WIDTH-1:0] awaddr_latched;
    reg [31:0]           wdata_latched;

    initial begin
        wait (resetn == 1'b1);
        forever begin
            wait (awvalid == 1'b1);
            repeat (aw_delay) @(posedge clk);
            awaddr_latched = awaddr;
            awready = 1'b1;
            repeat (2) @(posedge clk);
            awready = 1'b0;

            wait (wvalid == 1'b1);
            repeat (w_delay) @(posedge clk);
            wdata_latched = wdata;
            wready = 1'b1;
            repeat (2) @(posedge clk);
            wready = 1'b0;

            mem[awaddr_latched[6:2]] = wdata_latched;
            repeat (b_delay) @(posedge clk);
            bresp = 2'b00;
            bvalid = 1'b1;
            wait (bready == 1'b1);
            repeat (2) @(posedge clk);
            bvalid = 1'b0;
        end
    end

    reg [ADDR_WIDTH-1:0] araddr_latched;

    initial begin
        wait (resetn == 1'b1);
        forever begin
            wait (arvalid == 1'b1);
            repeat (ar_delay) @(posedge clk);
            araddr_latched = araddr;
            arready = 1'b1;
            repeat (2) @(posedge clk);
            arready = 1'b0;

            repeat (r_delay) @(posedge clk);
            rdata = mem[araddr_latched[6:2]];
            rresp = 2'b00;
            rvalid = 1'b1;
            wait (rready == 1'b1);
            repeat (2) @(posedge clk);
            rvalid = 1'b0;
        end
    end
endmodule

module emio_regfile_tb;
    localparam CLK_PERIOD = 10;
    localparam EMIO_WIDTH = 74;

    reg clk;
    reg resetn;
    reg [EMIO_WIDTH-1:0] emio_gpio_o;
    wire [EMIO_WIDTH-1:0] emio_gpio_i;

    wire [11:0] awaddr;
    wire [2:0]  awprot;
    wire        awvalid;
    wire        awready;
    wire [31:0] wdata;
    wire [3:0]  wstrb;
    wire        wvalid;
    wire        wready;
    wire [1:0]  bresp;
    wire        bvalid;
    wire        bready;
    wire [11:0] araddr;
    wire [2:0]  arprot;
    wire        arvalid;
    wire        arready;
    wire [31:0] rdata;
    wire [1:0]  rresp;
    wire        rvalid;
    wire        rready;

    integer failures;

    emio_regfile dut (
        .clk          (clk),
        .resetn       (resetn),
        .emio_gpio_o  (emio_gpio_o),
        .emio_gpio_i  (emio_gpio_i),
        .m_axi_awaddr (awaddr),
        .m_axi_awprot (awprot),
        .m_axi_awvalid(awvalid),
        .m_axi_awready(awready),
        .m_axi_wdata  (wdata),
        .m_axi_wstrb  (wstrb),
        .m_axi_wvalid (wvalid),
        .m_axi_wready (wready),
        .m_axi_bresp  (bresp),
        .m_axi_bvalid (bvalid),
        .m_axi_bready (bready),
        .m_axi_araddr (araddr),
        .m_axi_arprot (arprot),
        .m_axi_arvalid(arvalid),
        .m_axi_arready(arready),
        .m_axi_rdata  (rdata),
        .m_axi_rresp  (rresp),
        .m_axi_rvalid (rvalid),
        .m_axi_rready (rready)
    );

    axi_lite_stub slave (
        .clk     (clk),
        .resetn  (resetn),
        .awaddr  (awaddr),
        .awprot  (awprot),
        .awvalid (awvalid),
        .awready (awready),
        .wdata   (wdata),
        .wstrb   (wstrb),
        .wvalid  (wvalid),
        .wready  (wready),
        .bresp   (bresp),
        .bvalid  (bvalid),
        .bready  (bready),
        .araddr  (araddr),
        .arprot  (arprot),
        .arvalid (arvalid),
        .arready (arready),
        .rdata   (rdata),
        .rresp   (rresp),
        .rvalid  (rvalid),
        .rready  (rready)
    );

    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    task fail;
        input [255:0] msg;
        begin
            failures = failures + 1;
            $display("FAIL: %0s", msg);
        end
    endtask

    task emio_write;
        input [4:0] addr;
        input [31:0] data;
        begin
            emio_gpio_o[4:0]   = addr;
            emio_gpio_o[36:5]  = data;
            emio_gpio_o[37]    = 1'b1;
            emio_gpio_o[38]    = 1'b0;
            emio_gpio_o[39]    = 1'b0;
            repeat (3) @(posedge clk);
            emio_gpio_o[39]    = 1'b1;
            wait (emio_gpio_i[72] == 1'b1);
            if (emio_gpio_i[73] !== 1'b0)
                fail("write asserted rdata_valid");
            repeat (2) @(posedge clk);
            if (emio_gpio_i[72] !== 1'b1)
                fail("done did not hold while req stayed high");
            emio_gpio_o[39]    = 1'b0;
            wait (emio_gpio_i[72] == 1'b0);
            emio_gpio_o[37]    = 1'b0;
        end
    endtask

    reg [31:0] read_value;
    reg [31:0] stable_value;

    task emio_read;
        input [4:0] addr;
        begin
            emio_gpio_o[4:0]   = addr;
            emio_gpio_o[36:5]  = 32'h0;
            emio_gpio_o[37]    = 1'b0;
            emio_gpio_o[38]    = 1'b1;
            emio_gpio_o[39]    = 1'b0;
            repeat (3) @(posedge clk);
            emio_gpio_o[39]    = 1'b1;
            wait (emio_gpio_i[72] == 1'b1);
            if (emio_gpio_i[73] !== 1'b1)
                fail("read did not assert rdata_valid");
            read_value = emio_gpio_i[71:40];
            stable_value = read_value;
            repeat (3) @(posedge clk);
            if (emio_gpio_i[71:40] !== stable_value)
                fail("read data changed while req stayed high");
            emio_gpio_o[39]    = 1'b0;
            wait (emio_gpio_i[72] == 1'b0);
            if (emio_gpio_i[73] !== 1'b0)
                fail("rdata_valid did not drop after req deassert");
            emio_gpio_o[38]    = 1'b0;
        end
    endtask

    initial begin
        failures = 0;
        resetn = 0;
        emio_gpio_o = 0;
        repeat (8) @(posedge clk);
        resetn = 1;
        repeat (8) @(posedge clk);

        emio_write(5'h0A, 32'h1234_5678);
        emio_read(5'h0A);
        if (read_value !== 32'h1234_5678)
            fail("basic write/read mismatch");

        slave.aw_delay = 3;
        slave.w_delay  = 5;
        slave.b_delay  = 4;
        slave.ar_delay = 4;
        slave.r_delay  = 6;

        emio_write(5'h00, 32'hCAFE_BABE);
        emio_write(5'h01, 32'h0BAD_F00D);
        emio_read(5'h00);
        if (read_value !== 32'hCAFE_BABE)
            fail("delayed readback at word 0 mismatch");
        emio_read(5'h01);
        if (read_value !== 32'h0BAD_F00D)
            fail("delayed readback at word 1 mismatch");

        if (failures == 0) begin
            $display("PASS: emio_regfile handshake and AXI-Lite bridge");
            $finish;
        end else begin
            $display("FAIL: %0d failures", failures);
            $finish;
        end
    end

    initial begin
        repeat (20000) @(posedge clk);
        $display("FAIL: simulation watchdog timeout, state=%0d req=%0b done=%0b awv=%0b wv=%0b bv=%0b ar=%0b rv=%0b",
                 dut.state, emio_gpio_o[39], emio_gpio_i[72],
                 awvalid, wvalid, bvalid, arvalid, rvalid);
        $finish;
    end
endmodule
