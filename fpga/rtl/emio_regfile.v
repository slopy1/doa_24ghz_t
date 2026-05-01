// emio_regfile.v -- PS GPIO/EMIO to AXI-Lite register bridge
//
// EMIO line map, relative to the PS GPIO EMIO base:
//   0..4    PS -> PL  addr[4:0]        word address
//   5..36   PS -> PL  wdata[31:0]
//   37      PS -> PL  we
//   38      PS -> PL  re
//   39      PS -> PL  req
//   40..71  PL -> PS  rdata[31:0]
//   72      PL -> PS  done
//   73      PL -> PS  rdata_valid
//
// Python/libgpiod uses a four-phase handshake:
//   set addr/data/we/re with req=0 -> req=1 -> wait done=1 -> req=0.
// The bridge latches one command on the synchronized req rising edge and
// issues one AXI-Lite read or write. It holds done until req drops.

`timescale 1ns / 1ps

module emio_regfile #(
    parameter C_M_AXI_ADDR_WIDTH = 12,
    parameter C_M_AXI_DATA_WIDTH = 32,
    parameter EMIO_WIDTH         = 74
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF m_axi, ASSOCIATED_RESET resetn" *)
    input  wire                             clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire                             resetn,

    input  wire [EMIO_WIDTH-1:0]            emio_gpio_o,
    output wire [EMIO_WIDTH-1:0]            emio_gpio_i,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWADDR" *)
    // FREQ_HZ intentionally omitted — IP Integrator infers it from the
    // connected clock. KV260 IOPLL pl_clk0 measures 49,999,500 Hz, and a
    // hardcoded value (e.g. 100_000_000 or 99_999_000) would block
    // validate_bd_design. See doa_pipeline.v for the same rationale.
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 12, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1, HAS_BURST 0, HAS_LOCK 0, HAS_PROT 1, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, SUPPORTS_NARROW_BURST 0" *)
    output reg  [C_M_AXI_ADDR_WIDTH-1:0]    m_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWPROT" *)
    output wire [2:0]                       m_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWVALID" *)
    output reg                              m_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi AWREADY" *)
    input  wire                             m_axi_awready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WDATA" *)
    output reg  [C_M_AXI_DATA_WIDTH-1:0]    m_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WSTRB" *)
    output wire [(C_M_AXI_DATA_WIDTH/8)-1:0] m_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WVALID" *)
    output reg                              m_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi WREADY" *)
    input  wire                             m_axi_wready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi BRESP" *)
    input  wire [1:0]                       m_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi BVALID" *)
    input  wire                             m_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi BREADY" *)
    output reg                              m_axi_bready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARADDR" *)
    output reg  [C_M_AXI_ADDR_WIDTH-1:0]    m_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARPROT" *)
    output wire [2:0]                       m_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARVALID" *)
    output reg                              m_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi ARREADY" *)
    input  wire                             m_axi_arready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RDATA" *)
    input  wire [C_M_AXI_DATA_WIDTH-1:0]    m_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RRESP" *)
    input  wire [1:0]                       m_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RVALID" *)
    input  wire                             m_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 m_axi RREADY" *)
    output reg                              m_axi_rready
);

    localparam ST_IDLE       = 3'd0;
    localparam ST_WRITE      = 3'd1;
    localparam ST_WRITE_RESP = 3'd2;
    localparam ST_READ_ADDR  = 3'd3;
    localparam ST_READ_DATA  = 3'd4;
    localparam ST_DONE       = 3'd5;

    // Raw EMIO inputs (PS clock domain). Synchronized below before use.
    wire [38:0] emio_data_raw = emio_gpio_o[38:0];   // addr|wdata|we|re
    wire        emio_req      = emio_gpio_o[39];

    // 2-FF synchronizers. The data bus is held stable by the driver for many
    // PL cycles before req rises, so once req_sync is observed high we know
    // data_sync has long since propagated. Synchronizing both is still
    // required to keep CDC-clean and to tolerate alternate callers that may
    // not respect the strict data-then-req ordering.
    reg [38:0] data_meta;
    reg [38:0] data_sync;

    wire [4:0]  emio_addr_s  = data_sync[4:0];
    wire [31:0] emio_wdata_s = data_sync[36:5];
    wire        emio_we_s    = data_sync[37];
    wire        emio_re_s    = data_sync[38];

    reg [2:0]  state;
    reg        req_meta;
    reg        req_sync;
    reg        req_prev;
    reg        aw_done;
    reg        w_done;
    reg [31:0] rdata_reg;
    reg        done_reg;
    reg        rdata_valid_reg;

    wire req_rise = req_sync && !req_prev;
    wire aw_fire  = m_axi_awvalid && m_axi_awready;
    wire w_fire   = m_axi_wvalid && m_axi_wready;

    assign m_axi_awprot = 3'b000;
    assign m_axi_arprot = 3'b000;
    assign m_axi_wstrb  = {C_M_AXI_DATA_WIDTH/8{1'b1}};

    assign emio_gpio_i = {{(EMIO_WIDTH-74){1'b0}},
                          rdata_valid_reg,
                          done_reg,
                          rdata_reg,
                          40'b0};

    wire [C_M_AXI_ADDR_WIDTH-1:0] axi_addr =
        {{(C_M_AXI_ADDR_WIDTH-7){1'b0}}, emio_addr_s, 2'b00};

    always @(posedge clk) begin
        if (!resetn) begin
            req_meta         <= 1'b0;
            req_sync         <= 1'b0;
            req_prev         <= 1'b0;
            data_meta        <= 39'b0;
            data_sync        <= 39'b0;
        end else begin
            req_meta         <= emio_req;
            req_sync         <= req_meta;
            req_prev         <= req_sync;
            data_meta        <= emio_data_raw;
            data_sync        <= data_meta;
        end
    end

    always @(posedge clk) begin
        if (!resetn) begin
            state            <= ST_IDLE;
            m_axi_awaddr     <= 0;
            m_axi_awvalid    <= 1'b0;
            m_axi_wdata      <= 0;
            m_axi_wvalid     <= 1'b0;
            m_axi_bready     <= 1'b0;
            m_axi_araddr     <= 0;
            m_axi_arvalid    <= 1'b0;
            m_axi_rready     <= 1'b0;
            aw_done          <= 1'b0;
            w_done           <= 1'b0;
            rdata_reg        <= 0;
            done_reg         <= 1'b0;
            rdata_valid_reg  <= 1'b0;
        end else begin
            case (state)
                ST_IDLE: begin
                    m_axi_awvalid   <= 1'b0;
                    m_axi_wvalid    <= 1'b0;
                    m_axi_bready    <= 1'b0;
                    m_axi_arvalid   <= 1'b0;
                    m_axi_rready    <= 1'b0;
                    aw_done         <= 1'b0;
                    w_done          <= 1'b0;
                    done_reg        <= 1'b0;
                    rdata_valid_reg <= 1'b0;

                    if (req_rise) begin
                        if (emio_we_s) begin
                            m_axi_awaddr  <= axi_addr;
                            m_axi_wdata   <= emio_wdata_s;
                            m_axi_awvalid <= 1'b1;
                            m_axi_wvalid  <= 1'b1;
                            state         <= ST_WRITE;
                        end else if (emio_re_s) begin
                            m_axi_araddr  <= axi_addr;
                            m_axi_arvalid <= 1'b1;
                            state         <= ST_READ_ADDR;
                        end else begin
                            rdata_reg       <= 32'hBAD0_0000;
                            done_reg        <= 1'b1;
                            rdata_valid_reg <= 1'b0;
                            state           <= ST_DONE;
                        end
                    end
                end

                ST_WRITE: begin
                    if (aw_fire) begin
                        m_axi_awvalid <= 1'b0;
                        aw_done       <= 1'b1;
                    end
                    if (w_fire) begin
                        m_axi_wvalid <= 1'b0;
                        w_done       <= 1'b1;
                    end
                    if ((aw_done || aw_fire) && (w_done || w_fire)) begin
                        m_axi_bready <= 1'b1;
                        state        <= ST_WRITE_RESP;
                    end
                end

                ST_WRITE_RESP: begin
                    if (m_axi_bvalid) begin
                        m_axi_bready    <= 1'b0;
                        done_reg        <= 1'b1;
                        rdata_valid_reg <= 1'b0;
                        state           <= ST_DONE;
                    end
                end

                ST_READ_ADDR: begin
                    if (m_axi_arvalid && m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready  <= 1'b1;
                        state         <= ST_READ_DATA;
                    end
                end

                ST_READ_DATA: begin
                    if (m_axi_rvalid) begin
                        rdata_reg       <= m_axi_rdata;
                        m_axi_rready    <= 1'b0;
                        done_reg        <= 1'b1;
                        rdata_valid_reg <= 1'b1;
                        state           <= ST_DONE;
                    end
                end

                ST_DONE: begin
                    if (!req_sync) begin
                        done_reg        <= 1'b0;
                        rdata_valid_reg <= 1'b0;
                        state           <= ST_IDLE;
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

endmodule
