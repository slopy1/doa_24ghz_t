`timescale 1ns / 1ps

module dma_safe_ctrl_tb;
    localparam ADDR_W = 12;
    localparam DATA_W = 32;

    reg clk = 1'b0;
    reg resetn = 1'b0;

    always #5 clk = ~clk;

    reg  [ADDR_W-1:0] s_axi_awaddr;
    reg  [2:0]        s_axi_awprot;
    reg               s_axi_awvalid;
    wire              s_axi_awready;
    reg  [DATA_W-1:0] s_axi_wdata;
    reg  [3:0]        s_axi_wstrb;
    reg               s_axi_wvalid;
    wire              s_axi_wready;
    wire [1:0]        s_axi_bresp;
    wire              s_axi_bvalid;
    reg               s_axi_bready;
    reg  [ADDR_W-1:0] s_axi_araddr;
    reg  [2:0]        s_axi_arprot;
    reg               s_axi_arvalid;
    wire              s_axi_arready;
    wire [DATA_W-1:0] s_axi_rdata;
    wire [1:0]        s_axi_rresp;
    wire              s_axi_rvalid;
    reg               s_axi_rready;

    wire [ADDR_W-1:0] m_axi_awaddr;
    wire [2:0]        m_axi_awprot;
    wire              m_axi_awvalid;
    reg               m_axi_awready;
    wire [DATA_W-1:0] m_axi_wdata;
    wire [3:0]        m_axi_wstrb;
    wire              m_axi_wvalid;
    reg               m_axi_wready;
    reg  [1:0]        m_axi_bresp;
    reg               m_axi_bvalid;
    wire              m_axi_bready;
    wire [ADDR_W-1:0] m_axi_araddr;
    wire [2:0]        m_axi_arprot;
    wire              m_axi_arvalid;
    reg               m_axi_arready;
    reg  [DATA_W-1:0] m_axi_rdata;
    reg  [1:0]        m_axi_rresp;
    reg               m_axi_rvalid;
    wire              m_axi_rready;

    reg [31:0] dma_regs [0:255];
    reg [ADDR_W-1:0] fake_awaddr;
    reg [DATA_W-1:0] fake_wdata;
    reg [3:0] fake_wstrb;
    reg fake_aw_seen;
    reg fake_w_seen;
    reg [ADDR_W-1:0] fake_awaddr_next;
    reg [DATA_W-1:0] fake_wdata_next;
    reg [3:0] fake_wstrb_next;
    reg fake_have_aw_next;
    reg fake_have_w_next;
    integer i;

    dma_safe_ctrl dut (
        .clk(clk),
        .resetn(resetn),
        .s_axi_awaddr(s_axi_awaddr),
        .s_axi_awprot(s_axi_awprot),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr),
        .s_axi_arprot(s_axi_arprot),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready)
    );

    always @(posedge clk) begin
        fake_awaddr_next = (m_axi_awvalid && m_axi_awready) ? m_axi_awaddr : fake_awaddr;
        fake_wdata_next  = (m_axi_wvalid && m_axi_wready) ? m_axi_wdata : fake_wdata;
        fake_wstrb_next  = (m_axi_wvalid && m_axi_wready) ? m_axi_wstrb : fake_wstrb;
        fake_have_aw_next = fake_aw_seen || (m_axi_awvalid && m_axi_awready);
        fake_have_w_next  = fake_w_seen  || (m_axi_wvalid && m_axi_wready);

        if (!resetn) begin
            for (i = 0; i < 256; i = i + 1)
                dma_regs[i] <= 32'h0;
            m_axi_awready <= 1'b0;
            m_axi_wready  <= 1'b0;
            m_axi_bresp   <= 2'b00;
            m_axi_bvalid  <= 1'b0;
            m_axi_arready <= 1'b0;
            m_axi_rdata   <= 32'h0;
            m_axi_rresp   <= 2'b00;
            m_axi_rvalid  <= 1'b0;
            fake_awaddr   <= 0;
            fake_wdata    <= 0;
            fake_wstrb    <= 0;
            fake_aw_seen  <= 1'b0;
            fake_w_seen   <= 1'b0;
        end else begin
            m_axi_awready <= 1'b1;
            m_axi_wready  <= 1'b1;
            m_axi_arready <= 1'b1;

            if (m_axi_awvalid && m_axi_awready) begin
                fake_awaddr  <= m_axi_awaddr;
                fake_aw_seen <= 1'b1;
            end
            if (m_axi_wvalid && m_axi_wready) begin
                fake_wdata  <= m_axi_wdata;
                fake_wstrb  <= m_axi_wstrb;
                fake_w_seen <= 1'b1;
            end

            if (!m_axi_bvalid && fake_have_aw_next && fake_have_w_next) begin
                dma_regs[fake_awaddr_next[9:2]] <= fake_wdata_next;
                if (fake_wstrb_next !== 4'hf) begin
                    $display("FAIL: expected full-word WSTRB, got %h", fake_wstrb_next);
                    $finish;
                end
                fake_aw_seen <= 1'b0;
                fake_w_seen  <= 1'b0;
                m_axi_bresp  <= 2'b00;
                m_axi_bvalid <= 1'b1;
            end else if (m_axi_bvalid && m_axi_bready) begin
                m_axi_bvalid <= 1'b0;
            end

            if (m_axi_arvalid && m_axi_arready) begin
                m_axi_rdata  <= dma_regs[m_axi_araddr[9:2]];
                m_axi_rresp  <= 2'b00;
                m_axi_rvalid <= 1'b1;
            end else if (m_axi_rvalid && m_axi_rready) begin
                m_axi_rvalid <= 1'b0;
            end
        end
    end

    task axi_write;
        input [ADDR_W-1:0] addr;
        input [31:0] data;
        input [1:0] expected_resp;
        begin
            @(posedge clk);
            s_axi_awaddr  <= addr;
            s_axi_wdata   <= data;
            s_axi_wstrb   <= 4'hf;
            s_axi_awvalid <= 1'b1;
            s_axi_wvalid  <= 1'b1;
            while (!(s_axi_awready && s_axi_wready))
                @(posedge clk);
            @(posedge clk);
            s_axi_awvalid <= 1'b0;
            s_axi_wvalid  <= 1'b0;
            s_axi_bready  <= 1'b1;
            while (!s_axi_bvalid)
                @(posedge clk);
            if (s_axi_bresp !== expected_resp) begin
                $display("FAIL: write 0x%03x response %b expected %b",
                         addr, s_axi_bresp, expected_resp);
                $finish;
            end
            @(posedge clk);
            s_axi_bready <= 1'b0;
        end
    endtask

    task axi_read;
        input [ADDR_W-1:0] addr;
        output [31:0] data;
        input [1:0] expected_resp;
        begin
            @(posedge clk);
            s_axi_araddr  <= addr;
            s_axi_arvalid <= 1'b1;
            while (!s_axi_arready)
                @(posedge clk);
            @(posedge clk);
            s_axi_arvalid <= 1'b0;
            s_axi_rready  <= 1'b1;
            while (!s_axi_rvalid)
                @(posedge clk);
            data = s_axi_rdata;
            if (s_axi_rresp !== expected_resp) begin
                $display("FAIL: read 0x%03x response %b expected %b",
                         addr, s_axi_rresp, expected_resp);
                $finish;
            end
            @(posedge clk);
            s_axi_rready <= 1'b0;
        end
    endtask

    task expect_reg;
        input integer index;
        input [31:0] expected;
        begin
            if (dma_regs[index] !== expected) begin
                $display("FAIL: dma_regs[%0d] = 0x%08x expected 0x%08x",
                         index, dma_regs[index], expected);
                $finish;
            end
        end
    endtask

    reg [31:0] rd;

    initial begin
        s_axi_awaddr  = 0;
        s_axi_awprot  = 0;
        s_axi_awvalid = 0;
        s_axi_wdata   = 0;
        s_axi_wstrb   = 0;
        s_axi_wvalid  = 0;
        s_axi_bready  = 0;
        s_axi_araddr  = 0;
        s_axi_arprot  = 0;
        s_axi_arvalid = 0;
        s_axi_rready  = 0;

        repeat (5) @(posedge clk);
        resetn = 1'b1;
        repeat (2) @(posedge clk);

        axi_write(12'h000, 32'h0000_0004, 2'b00); // safe 0x00 -> DMA 0x00
        expect_reg(0, 32'h0000_0004);

        axi_write(12'h020, 32'h445b_0000, 2'b00); // safe 0x20 -> DMA 0x08
        expect_reg(2, 32'h445b_0000);

        axi_write(12'h040, 32'h445b_0000, 2'b00); // safe 0x40 -> DMA 0x10
        expect_reg(4, 32'h445b_0000);

        dma_regs[1] = 32'h0001_0002;              // DMA 0x04 -> safe 0x10
        axi_read(12'h010, rd, 2'b00);
        if (rd !== 32'h0001_0002) begin
            $display("FAIL: read DMASR via safe 0x10 got 0x%08x", rd);
            $finish;
        end

        axi_write(12'h024, 32'hdead_beef, 2'b10); // lower nibble not safe
        expect_reg(2, 32'h445b_0000);
        axi_read(12'h014, rd, 2'b10);

        $display("PASS: dma_safe_ctrl maps 16-byte-safe offsets to DMA regs");
        $finish;
    end
endmodule
