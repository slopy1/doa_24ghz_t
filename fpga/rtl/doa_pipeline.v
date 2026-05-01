// doa_pipeline.v — Phase A top-level DoA processing pipeline
//
// Replaces xcorr_acc_axi in the Vivado block design. From the ARM's view,
// this is a single AXI-Lite peripheral at 0x4000_0000 (unchanged) plus an
// AXI-Stream slave for DMA input.
//
// Pipeline:
//   DMA → channel_splitter → fir_filter_sc16 → (ch0 direct, ch1→phase_rotate)
//       → interleaver → xcorr_acc
//                      → autocorr_acc
//       → AXI-Lite result registers (48-bit split readback)
//
// Register map (see spec §5):
//   0x00/04 XCORR_RE lo/hi    (RO)
//   0x08/0C XCORR_IM lo/hi    (RO)
//   0x10/14 R00 lo/hi          (RO)
//   0x18/1C R11 lo/hi          (RO)
//   0x20    STATUS (bit 0 = result_valid, clear-on-read)
//   0x24    SNAP_COUNT         (RO)
//   0x28    COS_CAL            (RW, Q1.15)
//   0x2C    SIN_CAL            (RW, Q1.15)
//   0x30    COEFF_ADDR         (RW, 0-23)
//   0x34    COEFF_DATA         (W-triggers FIR load)
//   0x38    FILTER_CTRL        (bit 0 = enable, bit 1 = loaded flag)
//
// SPEC FIXES (v1 → v2):
//   1. fir_filter_sc16 output truncation bits [30:15] (not [47:15]) — done in that module.
//   2. autocorr_acc is driven by a *one-cycle pulse* on the phase-0 interleave
//      cycle, not by the combined buf_*_valid which is level-high for 2 cycles.
//      This prevents double-counting the power sums.

`timescale 1ns / 1ps

module doa_pipeline #(
    parameter SNAPSHOT_LEN       = 1024,
    parameter ACC_WIDTH          = 48,
    parameter NUM_TAPS           = 48,
    parameter C_S_AXI_DATA_WIDTH = 32,
    parameter C_S_AXI_ADDR_WIDTH = 12
)(
    // Single PL clock drives both AXI-Lite and AXI-Stream interfaces.
    // X_INTERFACE_PARAMETER binds both bus interfaces to this clock.
    // FREQ_HZ is intentionally omitted so IP Integrator infers it from the
    // connected source — on KV260 the ZU+ IOPLL produces 49,999,500 Hz, not
    // exactly 50 MHz, and a hardcoded value would block validate_bd_design.
    // The 500 Hz delta is within RTL timing margin (Phase A WNS +3.74 ns).
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:s_axis, ASSOCIATED_RESET s_axi_aresetn" *)
    input  wire                             s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire                             s_axi_aresetn,

    // AXI-Lite slave
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]    s_axi_awaddr,
    input  wire [2:0]                       s_axi_awprot,
    input  wire                             s_axi_awvalid,
    output reg                              s_axi_awready,

    input  wire [C_S_AXI_DATA_WIDTH-1:0]    s_axi_wdata,
    input  wire [3:0]                       s_axi_wstrb,
    input  wire                             s_axi_wvalid,
    output reg                              s_axi_wready,

    output reg  [1:0]                       s_axi_bresp,
    output reg                              s_axi_bvalid,
    input  wire                             s_axi_bready,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0]    s_axi_araddr,
    input  wire [2:0]                       s_axi_arprot,
    input  wire                             s_axi_arvalid,
    output reg                              s_axi_arready,

    output reg  [C_S_AXI_DATA_WIDTH-1:0]    s_axi_rdata,
    output reg  [1:0]                       s_axi_rresp,
    output reg                              s_axi_rvalid,
    input  wire                             s_axi_rready,

    // AXI-Stream slave (DMA in)
    input  wire [31:0]                      s_axis_tdata,
    input  wire                             s_axis_tvalid,
    output wire                             s_axis_tready
);

    // ===============================================================
    // Writable configuration registers
    // ===============================================================
    reg signed [15:0]   reg_cos_cal;
    reg signed [15:0]   reg_sin_cal;
    reg [4:0]           reg_coeff_addr;
    reg signed [15:0]   reg_coeff_data;
    reg                 coeff_wr_pulse;
    reg                 reg_filter_en;
    reg                 reg_coeff_loaded;

    // Result registers (latched at snapshot boundary)
    reg [ACC_WIDTH-1:0] reg_xcorr_re;
    reg [ACC_WIDTH-1:0] reg_xcorr_im;
    reg [ACC_WIDTH-1:0] reg_r00;
    reg [ACC_WIDTH-1:0] reg_r11;
    reg                 reg_valid;
    reg [31:0]          reg_snap_count;
    reg                 clear_valid;

    // ===============================================================
    // Stage 1: split interleaved stream into ch0/ch1
    // ===============================================================
    wire [31:0] split_ch0_tdata;
    wire        split_ch0_tvalid;
    wire [31:0] split_ch1_tdata;
    wire        split_ch1_tvalid;

    channel_splitter u_splitter (
        .clk          (s_axi_aclk),
        .rst_n        (s_axi_aresetn),
        .s_axis_tdata (s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .ch0_tdata    (split_ch0_tdata),
        .ch0_tvalid   (split_ch0_tvalid),
        .ch1_tdata    (split_ch1_tdata),
        .ch1_tvalid   (split_ch1_tvalid)
    );

    // ===============================================================
    // Stage 2: FIR filter (time-shared ch0/ch1)
    // ===============================================================
    wire [31:0] fir_ch0_tdata;
    wire        fir_ch0_tvalid;
    wire [31:0] fir_ch1_tdata;
    wire        fir_ch1_tvalid;

    fir_filter_sc16 #(
        .NUM_TAPS (NUM_TAPS),
        .ACC_WIDTH(ACC_WIDTH)
    ) u_fir (
        .clk           (s_axi_aclk),
        .rst_n         (s_axi_aresetn),
        .coeff_addr    (reg_coeff_addr),
        .coeff_data    (reg_coeff_data),
        .coeff_wr_en   (coeff_wr_pulse),
        .filter_en     (reg_filter_en),
        .ch0_tdata     (split_ch0_tdata),
        .ch0_tvalid    (split_ch0_tvalid),
        .ch0_out_tdata (fir_ch0_tdata),
        .ch0_out_tvalid(fir_ch0_tvalid),
        .ch1_tdata     (split_ch1_tdata),
        .ch1_tvalid    (split_ch1_tvalid),
        .ch1_out_tdata (fir_ch1_tdata),
        .ch1_out_tvalid(fir_ch1_tvalid)
    );

    // ===============================================================
    // Stage 3: phase rotation on ch1 only
    // ===============================================================
    wire [31:0] rot_ch1_tdata;
    wire        rot_ch1_tvalid;

    phase_rotate_sc16 u_rotate (
        .clk     (s_axi_aclk),
        .rst_n   (s_axi_aresetn),
        .cos_cal (reg_cos_cal),
        .sin_cal (reg_sin_cal),
        .s_tdata (fir_ch1_tdata),
        .s_tvalid(fir_ch1_tvalid),
        .m_tdata (rot_ch1_tdata),
        .m_tvalid(rot_ch1_tvalid)
    );

    // ===============================================================
    // Stage 4: re-interleave filtered/rotated ch0 and ch1 for xcorr
    //          and emit a matched single-cycle pulse for autocorr
    // ===============================================================
    //
    // Timing note: fir_ch0 arrives at the same time as fir_ch1 (the FIR
    // OUTPUT state emits both valids on the same clock). phase_rotate
    // delays ch1 by 1 cycle, so rot_ch1 is one cycle later than fir_ch0.
    // We buffer both, then emit when both are ready.

    reg [31:0] buf_ch0;
    reg        buf_ch0_valid;
    reg [31:0] buf_ch1;
    reg        buf_ch1_valid;

    reg [31:0] xcorr_axis_tdata;
    reg        xcorr_axis_tvalid;
    reg        interleave_phase;  // 0=emit ch0, 1=emit ch1

    // Single-cycle pulses for autocorr (SPEC FIX — not the level combine)
    reg        autocorr_pulse;
    reg [31:0] autocorr_ch0_data;
    reg [31:0] autocorr_ch1_data;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            buf_ch0           <= 0;
            buf_ch0_valid     <= 0;
            buf_ch1           <= 0;
            buf_ch1_valid     <= 0;
            xcorr_axis_tdata  <= 0;
            xcorr_axis_tvalid <= 0;
            interleave_phase  <= 0;
            autocorr_pulse    <= 0;
            autocorr_ch0_data <= 0;
            autocorr_ch1_data <= 0;
        end else begin
            xcorr_axis_tvalid <= 0;   // default: no output this cycle
            autocorr_pulse    <= 0;   // default: no pulse this cycle

            if (fir_ch0_tvalid) begin
                buf_ch0       <= fir_ch0_tdata;
                buf_ch0_valid <= 1;
            end

            if (rot_ch1_tvalid) begin
                buf_ch1       <= rot_ch1_tdata;
                buf_ch1_valid <= 1;
            end

            // Emit interleaved beats and matched autocorr pulse
            if (buf_ch0_valid && buf_ch1_valid) begin
                if (interleave_phase == 1'b0) begin
                    // Phase 0: emit ch0, pulse autocorr with both samples
                    xcorr_axis_tdata  <= buf_ch0;
                    xcorr_axis_tvalid <= 1;
                    interleave_phase  <= 1'b1;

                    autocorr_ch0_data <= buf_ch0;
                    autocorr_ch1_data <= buf_ch1;
                    autocorr_pulse    <= 1'b1;
                end else begin
                    // Phase 1: emit ch1, clear buffers
                    xcorr_axis_tdata  <= buf_ch1;
                    xcorr_axis_tvalid <= 1;
                    interleave_phase  <= 1'b0;
                    buf_ch0_valid     <= 0;
                    buf_ch1_valid     <= 0;
                end
            end
        end
    end

    // ===============================================================
    // Stage 4a: xcorr_acc (existing IP, unchanged)
    // ===============================================================
    wire [ACC_WIDTH-1:0] xcorr_re_raw;
    wire [ACC_WIDTH-1:0] xcorr_im_raw;
    wire                 xcorr_valid;

    xcorr_acc #(
        .SNAPSHOT_LEN(SNAPSHOT_LEN),
        .ACC_WIDTH   (ACC_WIDTH)
    ) u_xcorr (
        .clk          (s_axi_aclk),
        .rst_n        (s_axi_aresetn),
        .s_axis_tdata (xcorr_axis_tdata),
        .s_axis_tvalid(xcorr_axis_tvalid),
        .s_axis_tready(/* unused — xcorr is always ready */),
        .xcorr_re     (xcorr_re_raw),
        .xcorr_im     (xcorr_im_raw),
        .result_valid (xcorr_valid)
    );

    // ===============================================================
    // Stage 4b: autocorr_acc — driven by single-cycle pulse
    // ===============================================================
    wire [ACC_WIDTH-1:0] r00_raw;
    wire [ACC_WIDTH-1:0] r11_raw;
    wire                 autocorr_valid;

    autocorr_acc #(
        .SNAPSHOT_LEN(SNAPSHOT_LEN),
        .ACC_WIDTH   (ACC_WIDTH)
    ) u_autocorr (
        .clk         (s_axi_aclk),
        .rst_n       (s_axi_aresetn),
        .ch0_tdata   (autocorr_ch0_data),
        .ch0_tvalid  (autocorr_pulse),
        .ch1_tdata   (autocorr_ch1_data),
        .ch1_tvalid  (autocorr_pulse),
        .r00         (r00_raw),
        .r11         (r11_raw),
        .result_valid(autocorr_valid)
    );

    // ===============================================================
    // Latch results on xcorr completion
    // ===============================================================
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            reg_xcorr_re   <= 0;
            reg_xcorr_im   <= 0;
            reg_r00        <= 0;
            reg_r11        <= 0;
            reg_valid      <= 0;
            reg_snap_count <= 0;
        end else begin
            if (clear_valid)
                reg_valid <= 0;

            if (xcorr_valid) begin
                reg_xcorr_re   <= xcorr_re_raw;
                reg_xcorr_im   <= xcorr_im_raw;
                // autocorr_valid fires on the same cycle (same sample count)
                reg_r00        <= r00_raw;
                reg_r11        <= r11_raw;
                reg_valid      <= 1;
                reg_snap_count <= reg_snap_count + 1;
            end
        end
    end

    // ===============================================================
    // AXI-Lite Read channel
    // ===============================================================
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
            s_axi_rresp  <= 2'b00;
            case (axi_araddr[5:2])
                4'h0: s_axi_rdata <= reg_xcorr_re[31:0];
                4'h1: s_axi_rdata <= {{(32-(ACC_WIDTH-32)){reg_xcorr_re[ACC_WIDTH-1]}},
                                       reg_xcorr_re[ACC_WIDTH-1:32]};
                4'h2: s_axi_rdata <= reg_xcorr_im[31:0];
                4'h3: s_axi_rdata <= {{(32-(ACC_WIDTH-32)){reg_xcorr_im[ACC_WIDTH-1]}},
                                       reg_xcorr_im[ACC_WIDTH-1:32]};
                4'h4: s_axi_rdata <= reg_r00[31:0];
                4'h5: s_axi_rdata <= {{(32-(ACC_WIDTH-32)){1'b0}},
                                       reg_r00[ACC_WIDTH-1:32]};
                4'h6: s_axi_rdata <= reg_r11[31:0];
                4'h7: s_axi_rdata <= {{(32-(ACC_WIDTH-32)){1'b0}},
                                       reg_r11[ACC_WIDTH-1:32]};
                4'h8: s_axi_rdata <= {31'b0, reg_valid};
                4'h9: s_axi_rdata <= reg_snap_count;
                4'hA: s_axi_rdata <= {{16{reg_cos_cal[15]}}, reg_cos_cal};
                4'hB: s_axi_rdata <= {{16{reg_sin_cal[15]}}, reg_sin_cal};
                4'hC: s_axi_rdata <= {27'b0, reg_coeff_addr};
                4'hD: s_axi_rdata <= {{16{reg_coeff_data[15]}}, reg_coeff_data};
                4'hE: s_axi_rdata <= {30'b0, reg_coeff_loaded, reg_filter_en};
                default: s_axi_rdata <= 32'hDEADBEEF;
            endcase
        end else if (s_axi_rvalid && s_axi_rready) begin
            s_axi_rvalid <= 0;
            clear_valid  <= (axi_araddr[5:2] == 4'h8);  // clear STATUS on read
        end else begin
            clear_valid <= 0;
        end
    end

    // ===============================================================
    // AXI-Lite Write channel
    // ===============================================================
    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_awaddr;
    reg                           aw_captured;
    reg                           w_captured;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready    <= 0;
            s_axi_wready     <= 0;
            s_axi_bvalid     <= 0;
            s_axi_bresp      <= 0;
            axi_awaddr       <= 0;
            aw_captured      <= 0;
            w_captured       <= 0;
            reg_cos_cal      <= 0;
            reg_sin_cal      <= 0;
            reg_coeff_addr   <= 0;
            reg_coeff_data   <= 0;
            coeff_wr_pulse   <= 0;
            reg_filter_en    <= 0;
            reg_coeff_loaded <= 0;
        end else begin
            coeff_wr_pulse <= 1'b0;  // default — pulse only during AXI write

            // Latch write address (block rearm while bvalid still outstanding)
            if (s_axi_awvalid && !s_axi_awready && !aw_captured && !s_axi_bvalid) begin
                s_axi_awready <= 1'b1;
                axi_awaddr    <= s_axi_awaddr;
                aw_captured   <= 1'b1;
            end else begin
                s_axi_awready <= 1'b0;
            end

            // Latch write data (same bvalid gate)
            if (s_axi_wvalid && !s_axi_wready && !w_captured && !s_axi_bvalid) begin
                s_axi_wready <= 1'b1;
                w_captured   <= 1'b1;
            end else begin
                s_axi_wready <= 1'b0;
            end

            // Both address and data captured → decode and store
            if (aw_captured && w_captured && !s_axi_bvalid) begin
                aw_captured <= 1'b0;
                w_captured  <= 1'b0;
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= 2'b00;

                case (axi_awaddr[5:2])
                    4'hA: reg_cos_cal    <= s_axi_wdata[15:0];
                    4'hB: reg_sin_cal    <= s_axi_wdata[15:0];
                    4'hC: reg_coeff_addr <= s_axi_wdata[4:0];
                    4'hD: begin
                        reg_coeff_data <= s_axi_wdata[15:0];
                        coeff_wr_pulse <= 1'b1;  // pulse FIR coefficient write
                    end
                    4'hE: begin
                        reg_filter_en    <= s_axi_wdata[0];
                        reg_coeff_loaded <= s_axi_wdata[1];
                    end
                    default: ; // ignore writes to RO addresses
                endcase
            end

            // Response handshake clear
            if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

endmodule
