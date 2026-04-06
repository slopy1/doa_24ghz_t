// xcorr_acc_axi.v — AXI-Lite wrapper for xcorr_acc
//
// Wraps the streaming cross-correlator with an AXI-Lite slave interface
// so the ARM PS can read results as memory-mapped registers.
//
// Register map (active-word = 32 bits):
//   0x00  XCORR_RE    [R]   real part of cross-correlation (lower 32 bits)
//   0x04  XCORR_IM    [R]   imag part of cross-correlation (lower 32 bits)
//   0x08  STATUS      [R]   bit 0 = result_valid (sticky, cleared on read)
//   0x0C  SNAPSHOT_CT [R]   number of completed snapshots (32-bit counter)
//
// AXI-Stream slave port accepts 32-bit SC16 samples (two beats per sample pair).
// Target: Zynq-7000 XC7Z007S @ 100 MHz

`timescale 1ns / 1ps

module xcorr_acc_axi #(
    parameter SNAPSHOT_LEN      = 1024,
    parameter ACC_WIDTH         = 48,
    parameter C_S_AXI_DATA_WIDTH = 32,
    parameter C_S_AXI_ADDR_WIDTH = 12
)(

    // AXI-Lite Slave Interface

    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:s_axis, ASSOCIATED_RESET s_axi_aresetn" *)
    input  wire                                s_axi_aclk,
    input  wire                                s_axi_aresetn,

    // Write address channel
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]       s_axi_awaddr,
    input  wire [2:0]                          s_axi_awprot,
    input  wire                                s_axi_awvalid,
    output reg                                 s_axi_awready,

    // Write data channel
    input  wire [C_S_AXI_DATA_WIDTH-1:0]       s_axi_wdata,
    input  wire [(C_S_AXI_DATA_WIDTH/8)-1:0]   s_axi_wstrb,
    input  wire                                s_axi_wvalid,
    output reg                                 s_axi_wready,

    // Write response channel
    output reg  [1:0]                          s_axi_bresp,
    output reg                                 s_axi_bvalid,
    input  wire                                s_axi_bready,

    // Read address channel
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]       s_axi_araddr,
    input  wire [2:0]                          s_axi_arprot,
    input  wire                                s_axi_arvalid,
    output reg                                 s_axi_arready,

    // Read data channel
    output reg  [C_S_AXI_DATA_WIDTH-1:0]       s_axi_rdata,
    output reg  [1:0]                          s_axi_rresp,
    output reg                                 s_axi_rvalid,
    input  wire                                s_axi_rready,

    // AXI-Stream Slave Interface (32-bit, sample input from DMA)

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TDATA" *)
    (* X_INTERFACE_PARAMETER = "CLK_DOMAIN s_axi_aclk, FREQ_HZ 50000000, HAS_TKEEP 0, HAS_TLAST 0, HAS_TREADY 1, HAS_TSTRB 0, TDATA_NUM_BYTES 4" *)
    input  wire [31:0]                         s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TVALID" *)
    input  wire                                s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s_axis TREADY" *)
    output wire                                s_axis_tready
);

    
    // Internal signals from xcorr_acc core
    wire [ACC_WIDTH-1:0] xcorr_re_raw;
    wire [ACC_WIDTH-1:0] xcorr_im_raw;
    wire                 result_valid_pulse;


    // Instantiate the cross-correlation core
  
    xcorr_acc #(
        .SNAPSHOT_LEN(SNAPSHOT_LEN),
        .ACC_WIDTH(ACC_WIDTH)
    ) u_xcorr (
        .clk(s_axi_aclk),
        .rst_n(s_axi_aresetn),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .xcorr_re(xcorr_re_raw),
        .xcorr_im(xcorr_im_raw),
        .result_valid(result_valid_pulse)
    );

    // Result latching registers (hold values until ARM reads them)

    reg [31:0] reg_xcorr_re;    // 0x00
    reg [31:0] reg_xcorr_im;    // 0x04
    reg        reg_valid;       // 0x08 bit 0 — sticky, cleared on read
    reg [31:0] reg_snap_count;  // 0x0C — snapshot counter

    // Signal from read logic to clear the valid bit
    reg clear_valid;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            reg_xcorr_re  <= 0;
            reg_xcorr_im  <= 0;
            reg_valid     <= 0;
            reg_snap_count <= 0;
        end else begin
            // Clear-on-read has priority, but new result overrides
            if (clear_valid)
                reg_valid <= 0;
            if (result_valid_pulse) begin
                reg_xcorr_re  <= xcorr_re_raw[31:0];
                reg_xcorr_im  <= xcorr_im_raw[31:0];
                reg_valid     <= 1;
                reg_snap_count <= reg_snap_count + 1;
            end
        end
    end

   // AXI-Lite Read Logic
  
    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_araddr;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 0;
            axi_araddr    <= 0;
        end else if (s_axi_arvalid && !s_axi_arready) begin
            s_axi_arready <= 1;
            axi_araddr    <= s_axi_araddr;
        end else begin
            s_axi_arready <= 0;
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_rdata  <= 0;
            s_axi_rresp  <= 0;
            s_axi_rvalid <= 0;
            clear_valid  <= 0;
        end else if (s_axi_arready && s_axi_arvalid && !s_axi_rvalid) begin
            s_axi_rvalid <= 1;
            s_axi_rresp  <= 2'b00;  // OKAY
            case (axi_araddr[3:2])
                2'b00: s_axi_rdata <= reg_xcorr_re;           // 0x00
                2'b01: s_axi_rdata <= reg_xcorr_im;           // 0x04
                2'b10: s_axi_rdata <= {31'b0, reg_valid};     // 0x08
                2'b11: s_axi_rdata <= reg_snap_count;          // 0x0C
                default: s_axi_rdata <= 32'hDEADBEEF;
            endcase
        end else if (s_axi_rvalid && s_axi_rready) begin
            s_axi_rvalid <= 0;
            // Signal the latch block to clear valid on status read
            if (axi_araddr[3:2] == 2'b10)
                clear_valid <= 1;
            else
                clear_valid <= 0;
        end else begin
            clear_valid <= 0;
        end
    end


    // AXI-Lite Write Logic (no writable registers — accept and ignore)
    
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready <= 0;
            s_axi_wready  <= 0;
            s_axi_bvalid  <= 0;
            s_axi_bresp   <= 0;
        end else begin
            // Accept write address
            if (s_axi_awvalid && !s_axi_awready) begin
                s_axi_awready <= 1;
            end else begin
                s_axi_awready <= 0;
            end

            // Accept write data
            if (s_axi_wvalid && !s_axi_wready) begin
                s_axi_wready <= 1;
            end else begin
                s_axi_wready <= 0;
            end

            // Write response
            if (s_axi_awready && s_axi_awvalid && s_axi_wready && s_axi_wvalid && !s_axi_bvalid) begin
                s_axi_bvalid <= 1;
                s_axi_bresp  <= 2'b00;  // OKAY
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 0;
            end
        end
    end

endmodule
