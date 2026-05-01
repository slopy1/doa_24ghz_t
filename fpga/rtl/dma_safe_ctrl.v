// dma_safe_ctrl.v -- AXI-Lite register-stride shim for KV260 AXI DMA
//
// The KV260 HPM0_FPD control path in this project only reliably commits the
// first 32-bit word of each 16-byte region. This shim exposes a 16-byte-spaced
// AXI-Lite slave window to Linux, then performs normal 32-bit AXI-Lite accesses
// to the stock AXI DMA control port inside PL.
//
// Software-visible safe offset -> real DMA offset:
//   0x000 -> 0x00  MM2S_DMACR
//   0x010 -> 0x04  MM2S_DMASR
//   0x020 -> 0x08  MM2S_CURDESC
//   0x040 -> 0x10  MM2S_TAILDESC
//
// In general: real_offset = safe_offset >> 2, provided safe_offset[3:0] == 0.

`timescale 1ns / 1ps

module dma_safe_ctrl #(
    parameter C_S_AXI_ADDR_WIDTH = 12,
    parameter C_M_AXI_ADDR_WIDTH = 12,
    parameter C_AXI_DATA_WIDTH   = 32
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi, ASSOCIATED_RESET resetn" *)
    input  wire                              clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire                              resetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi AWADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1, HAS_BURST 0, HAS_LOCK 0, HAS_PROT 1, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, SUPPORTS_NARROW_BURST 0" *)
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]     s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi AWPROT" *)
    input  wire [2:0]                        s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi AWVALID" *)
    input  wire                              s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi AWREADY" *)
    output wire                              s_axi_awready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi WDATA" *)
    input  wire [C_AXI_DATA_WIDTH-1:0]       s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi WSTRB" *)
    input  wire [(C_AXI_DATA_WIDTH/8)-1:0]   s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi WVALID" *)
    input  wire                              s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi WREADY" *)
    output wire                              s_axi_wready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi BRESP" *)
    output reg  [1:0]                        s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi BVALID" *)
    output reg                               s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi BREADY" *)
    input  wire                              s_axi_bready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi ARADDR" *)
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]     s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi ARPROT" *)
    input  wire [2:0]                        s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi ARVALID" *)
    input  wire                              s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi ARREADY" *)
    output wire                              s_axi_arready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi RDATA" *)
    output reg  [C_AXI_DATA_WIDTH-1:0]       s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi RRESP" *)
    output reg  [1:0]                        s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi RVALID" *)
    output reg                               s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 s_axi RREADY" *)
    input  wire                              s_axi_rready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1, HAS_BURST 0, HAS_LOCK 0, HAS_PROT 1, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, SUPPORTS_NARROW_BURST 0" *)
    output reg  [C_M_AXI_ADDR_WIDTH-1:0]     m_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWPROT" *)
    output wire [2:0]                        m_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWVALID" *)
    output reg                               m_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWREADY" *)
    input  wire                              m_axi_awready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WDATA" *)
    output reg  [C_AXI_DATA_WIDTH-1:0]       m_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WSTRB" *)
    output reg  [(C_AXI_DATA_WIDTH/8)-1:0]   m_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WVALID" *)
    output reg                               m_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WREADY" *)
    input  wire                              m_axi_wready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi BRESP" *)
    input  wire [1:0]                        m_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi BVALID" *)
    input  wire                              m_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi BREADY" *)
    output reg                               m_axi_bready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARADDR" *)
    output reg  [C_M_AXI_ADDR_WIDTH-1:0]     m_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARPROT" *)
    output wire [2:0]                        m_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARVALID" *)
    output reg                               m_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARREADY" *)
    input  wire                              m_axi_arready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RDATA" *)
    input  wire [C_AXI_DATA_WIDTH-1:0]       m_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RRESP" *)
    input  wire [1:0]                        m_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RVALID" *)
    input  wire                              m_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RREADY" *)
    output reg                               m_axi_rready
);

    localparam RESP_OKAY   = 2'b00;
    localparam RESP_SLVERR = 2'b10;

    localparam ST_IDLE        = 3'd0;
    localparam ST_WRITE_RECV  = 3'd1;
    localparam ST_WRITE_ISSUE = 3'd2;
    localparam ST_WRITE_RESP  = 3'd3;
    localparam ST_WRITE_REPLY = 3'd4;
    localparam ST_READ_ISSUE  = 3'd5;
    localparam ST_READ_DATA   = 3'd6;
    localparam ST_READ_REPLY  = 3'd7;

    reg [2:0] state;
    reg [C_S_AXI_ADDR_WIDTH-1:0] awaddr_reg;
    reg [C_AXI_DATA_WIDTH-1:0] wdata_reg;
    reg [(C_AXI_DATA_WIDTH/8)-1:0] wstrb_reg;
    reg aw_seen;
    reg w_seen;

    wire write_accepting = (state == ST_IDLE) || (state == ST_WRITE_RECV);
    assign s_axi_awready = write_accepting && !aw_seen;
    assign s_axi_wready  = write_accepting && !w_seen;
    assign s_axi_arready = (state == ST_IDLE) && !s_axi_awvalid && !s_axi_wvalid;

    wire aw_fire = s_axi_awvalid && s_axi_awready;
    wire w_fire  = s_axi_wvalid  && s_axi_wready;
    wire ar_fire = s_axi_arvalid && s_axi_arready;

    wire have_aw_next = aw_seen || aw_fire;
    wire have_w_next  = w_seen  || w_fire;
    wire [C_S_AXI_ADDR_WIDTH-1:0] awaddr_next = aw_fire ? s_axi_awaddr : awaddr_reg;
    wire [C_AXI_DATA_WIDTH-1:0] wdata_next = w_fire ? s_axi_wdata : wdata_reg;
    wire [(C_AXI_DATA_WIDTH/8)-1:0] wstrb_next = w_fire ? s_axi_wstrb : wstrb_reg;

    assign m_axi_awprot = 3'b000;
    assign m_axi_arprot = 3'b000;

    function safe_addr_valid;
        input [C_S_AXI_ADDR_WIDTH-1:0] safe_addr;
        begin
            safe_addr_valid = (safe_addr[3:0] == 4'h0);
        end
    endfunction

    function [C_M_AXI_ADDR_WIDTH-1:0] safe_to_dma_addr;
        input [C_S_AXI_ADDR_WIDTH-1:0] safe_addr;
        begin
            safe_to_dma_addr = (safe_addr >> 2);
        end
    endfunction

    always @(posedge clk) begin
        if (!resetn) begin
            state         <= ST_IDLE;
            awaddr_reg    <= 0;
            wdata_reg     <= 0;
            wstrb_reg     <= 0;
            aw_seen       <= 1'b0;
            w_seen        <= 1'b0;
            s_axi_bresp   <= RESP_OKAY;
            s_axi_bvalid  <= 1'b0;
            s_axi_rdata   <= 0;
            s_axi_rresp   <= RESP_OKAY;
            s_axi_rvalid  <= 1'b0;
            m_axi_awaddr  <= 0;
            m_axi_awvalid <= 1'b0;
            m_axi_wdata   <= 0;
            m_axi_wstrb   <= 0;
            m_axi_wvalid  <= 1'b0;
            m_axi_bready  <= 1'b0;
            m_axi_araddr  <= 0;
            m_axi_arvalid <= 1'b0;
            m_axi_rready  <= 1'b0;
        end else begin
            if (aw_fire) begin
                awaddr_reg <= s_axi_awaddr;
                aw_seen    <= 1'b1;
            end
            if (w_fire) begin
                wdata_reg <= s_axi_wdata;
                wstrb_reg <= s_axi_wstrb;
                w_seen    <= 1'b1;
            end

            case (state)
                ST_IDLE, ST_WRITE_RECV: begin
                    if (state == ST_IDLE && ar_fire) begin
                        if (safe_addr_valid(s_axi_araddr)) begin
                            m_axi_araddr  <= safe_to_dma_addr(s_axi_araddr);
                            m_axi_arvalid <= 1'b1;
                            state         <= ST_READ_ISSUE;
                        end else begin
                            s_axi_rdata  <= 32'hBAD0_0001;
                            s_axi_rresp  <= RESP_SLVERR;
                            s_axi_rvalid <= 1'b1;
                            state        <= ST_READ_REPLY;
                        end
                    end else if (have_aw_next && have_w_next) begin
                        aw_seen <= 1'b0;
                        w_seen  <= 1'b0;
                        if (safe_addr_valid(awaddr_next)) begin
                            m_axi_awaddr  <= safe_to_dma_addr(awaddr_next);
                            m_axi_wdata   <= wdata_next;
                            m_axi_wstrb   <= wstrb_next;
                            m_axi_awvalid <= 1'b1;
                            m_axi_wvalid  <= 1'b1;
                            state         <= ST_WRITE_ISSUE;
                        end else begin
                            s_axi_bresp  <= RESP_SLVERR;
                            s_axi_bvalid <= 1'b1;
                            state        <= ST_WRITE_REPLY;
                        end
                    end else if (state == ST_IDLE && (aw_fire || w_fire)) begin
                        state <= ST_WRITE_RECV;
                    end
                end

                ST_WRITE_ISSUE: begin
                    if (m_axi_awvalid && m_axi_awready) begin
                        m_axi_awvalid <= 1'b0;
                    end
                    if (m_axi_wvalid && m_axi_wready) begin
                        m_axi_wvalid <= 1'b0;
                    end
                    if ((!m_axi_awvalid || m_axi_awready) &&
                        (!m_axi_wvalid  || m_axi_wready)) begin
                        m_axi_bready <= 1'b1;
                        state        <= ST_WRITE_RESP;
                    end
                end

                ST_WRITE_RESP: begin
                    if (m_axi_bvalid) begin
                        m_axi_bready <= 1'b0;
                        s_axi_bresp  <= m_axi_bresp;
                        s_axi_bvalid <= 1'b1;
                        state        <= ST_WRITE_REPLY;
                    end
                end

                ST_WRITE_REPLY: begin
                    if (s_axi_bvalid && s_axi_bready) begin
                        s_axi_bvalid <= 1'b0;
                        s_axi_bresp  <= RESP_OKAY;
                        state        <= ST_IDLE;
                    end
                end

                ST_READ_ISSUE: begin
                    if (m_axi_arvalid && m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready  <= 1'b1;
                        state         <= ST_READ_DATA;
                    end
                end

                ST_READ_DATA: begin
                    if (m_axi_rvalid) begin
                        m_axi_rready <= 1'b0;
                        s_axi_rdata  <= m_axi_rdata;
                        s_axi_rresp  <= m_axi_rresp;
                        s_axi_rvalid <= 1'b1;
                        state        <= ST_READ_REPLY;
                    end
                end

                ST_READ_REPLY: begin
                    if (s_axi_rvalid && s_axi_rready) begin
                        s_axi_rvalid <= 1'b0;
                        s_axi_rresp  <= RESP_OKAY;
                        state        <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
