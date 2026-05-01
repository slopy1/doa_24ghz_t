// doa_pipeline_kv260_separate.v
//
// Separate KV260 FPGA-side implementation. This file intentionally does not
// replace doa_pipeline.v; it provides a clean top-level module for a parallel
// Vivado build while keeping the same software-visible register map.
//
// Data path:
//   AXI DMA MM2S -> interleaved SC16 pair capture
//                -> optional 48-tap symmetric FIR
//                -> ch1 calibration phase rotation
//                -> xcorr/autocorr accumulation
//                -> AXI-Lite result registers
//
// Register map:
//   0x00/04 XCORR_RE lo/hi    (RO, signed 48-bit)
//   0x08/0C XCORR_IM lo/hi    (RO, signed 48-bit)
//   0x10/14 R00 lo/hi         (RO, unsigned 48-bit)
//   0x18/1C R11 lo/hi         (RO, unsigned 48-bit)
//   0x20    STATUS            (RO, bit 0 = result_valid, clear-on-read)
//   0x24    SNAP_COUNT        (RO)
//   0x28    COS_CAL           (RW, Q1.15)
//   0x2C    SIN_CAL           (RW, Q1.15)
//   0x30    COEFF_ADDR        (RW, 0-23)
//   0x34    COEFF_DATA        (W, Q1.15)
//   0x38    FILTER_CTRL       (RW, bit 0 = enable, bit 1 = loaded flag)

`timescale 1ns / 1ps

module doa_pipeline_kv260_separate #(
    parameter SNAPSHOT_LEN       = 1024,
    parameter ACC_WIDTH          = 48,
    parameter NUM_TAPS           = 48,
    parameter NUM_UNIQUE         = NUM_TAPS/2,
    parameter C_S_AXI_DATA_WIDTH = 32,
    parameter C_S_AXI_ADDR_WIDTH = 12
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:s_axis, ASSOCIATED_RESET s_axi_aresetn" *)
    input  wire                             s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire                             s_axi_aresetn,

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

    input  wire [31:0]                      s_axis_tdata,
    input  wire                             s_axis_tvalid,
    output wire                             s_axis_tready
);

    localparam STREAM_CH0 = 1'b0;
    localparam STREAM_CH1 = 1'b1;

    localparam PROC_IDLE  = 2'd0;
    localparam PROC_FIR   = 2'd1;
    localparam PROC_ACCUM = 2'd2;

    reg stream_phase;
    reg [1:0] proc_state;

    reg [31:0] raw_ch0;
    reg [31:0] raw_ch1;
    reg [31:0] proc_ch0;
    reg [31:0] proc_ch1;

    wire input_idle = (proc_state == PROC_IDLE);
    assign s_axis_tready = (stream_phase == STREAM_CH1) || input_idle;

    // ------------------------------------------------------------------
    // Writable configuration registers
    // ------------------------------------------------------------------
    reg signed [15:0] reg_cos_cal;
    reg signed [15:0] reg_sin_cal;
    reg [4:0]         reg_coeff_addr;
    reg signed [15:0] reg_coeff_data;
    reg               reg_filter_en;
    reg               reg_coeff_loaded;
    reg               coeff_wr_pulse;

    reg signed [15:0] coeffs [0:NUM_UNIQUE-1];
    integer ci;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            for (ci = 0; ci < NUM_UNIQUE; ci = ci + 1)
                coeffs[ci] <= 16'sd0;
        end else if (coeff_wr_pulse) begin
            coeffs[reg_coeff_addr] <= reg_coeff_data;
        end
    end

    // ------------------------------------------------------------------
    // FIR delay lines and MAC
    // ------------------------------------------------------------------
    reg signed [15:0] ch0_delay_i [0:NUM_TAPS-1];
    reg signed [15:0] ch0_delay_q [0:NUM_TAPS-1];
    reg signed [15:0] ch1_delay_i [0:NUM_TAPS-1];
    reg signed [15:0] ch1_delay_q [0:NUM_TAPS-1];

    reg [$clog2(NUM_UNIQUE)-1:0] tap_idx;
    reg signed [ACC_WIDTH-1:0] ch0_fir_i;
    reg signed [ACC_WIDTH-1:0] ch0_fir_q;
    reg signed [ACC_WIDTH-1:0] ch1_fir_i;
    reg signed [ACC_WIDTH-1:0] ch1_fir_q;

    wire signed [16:0] ch0_sym_i =
        ch0_delay_i[tap_idx] + ch0_delay_i[NUM_TAPS-1-tap_idx];
    wire signed [16:0] ch0_sym_q =
        ch0_delay_q[tap_idx] + ch0_delay_q[NUM_TAPS-1-tap_idx];
    wire signed [16:0] ch1_sym_i =
        ch1_delay_i[tap_idx] + ch1_delay_i[NUM_TAPS-1-tap_idx];
    wire signed [16:0] ch1_sym_q =
        ch1_delay_q[tap_idx] + ch1_delay_q[NUM_TAPS-1-tap_idx];

    wire signed [ACC_WIDTH-1:0] ch0_fir_i_next =
        ch0_fir_i + ($signed(coeffs[tap_idx]) * ch0_sym_i);
    wire signed [ACC_WIDTH-1:0] ch0_fir_q_next =
        ch0_fir_q + ($signed(coeffs[tap_idx]) * ch0_sym_q);
    wire signed [ACC_WIDTH-1:0] ch1_fir_i_next =
        ch1_fir_i + ($signed(coeffs[tap_idx]) * ch1_sym_i);
    wire signed [ACC_WIDTH-1:0] ch1_fir_q_next =
        ch1_fir_q + ($signed(coeffs[tap_idx]) * ch1_sym_q);

    wire signed [15:0] raw_ch0_i = raw_ch0[15:0];
    wire signed [15:0] raw_ch0_q = raw_ch0[31:16];
    wire signed [15:0] raw_ch1_i = raw_ch1[15:0];
    wire signed [15:0] raw_ch1_q = raw_ch1[31:16];

    // ------------------------------------------------------------------
    // Calibration phase rotation for ch1
    // ------------------------------------------------------------------
    function [31:0] rotate_ch1;
        input signed [15:0] in_i;
        input signed [15:0] in_q;
        reg signed [31:0] i_cos;
        reg signed [31:0] q_sin;
        reg signed [31:0] q_cos;
        reg signed [31:0] i_sin;
        reg signed [32:0] rot_i_full;
        reg signed [32:0] rot_q_full;
        reg signed [15:0] rot_i;
        reg signed [15:0] rot_q;
        begin
            i_cos = in_i * reg_cos_cal;
            q_sin = in_q * reg_sin_cal;
            q_cos = in_q * reg_cos_cal;
            i_sin = in_i * reg_sin_cal;
            rot_i_full = i_cos + q_sin;
            rot_q_full = q_cos - i_sin;
            rot_i = rot_i_full[30:15];
            rot_q = rot_q_full[30:15];
            rotate_ch1 = {rot_q, rot_i};
        end
    endfunction

    // ------------------------------------------------------------------
    // Covariance accumulators
    // ------------------------------------------------------------------
    reg signed [ACC_WIDTH-1:0] acc_xcorr_re;
    reg signed [ACC_WIDTH-1:0] acc_xcorr_im;
    reg [ACC_WIDTH-1:0]        acc_r00;
    reg [ACC_WIDTH-1:0]        acc_r11;
    reg [$clog2(SNAPSHOT_LEN)-1:0] sample_cnt;

    reg [ACC_WIDTH-1:0] reg_xcorr_re;
    reg [ACC_WIDTH-1:0] reg_xcorr_im;
    reg [ACC_WIDTH-1:0] reg_r00;
    reg [ACC_WIDTH-1:0] reg_r11;
    reg                 reg_valid;
    reg [31:0]          reg_snap_count;
    reg                 clear_valid;

    wire signed [15:0] proc_ch0_i = proc_ch0[15:0];
    wire signed [15:0] proc_ch0_q = proc_ch0[31:16];
    wire signed [15:0] proc_ch1_i = proc_ch1[15:0];
    wire signed [15:0] proc_ch1_q = proc_ch1[31:16];

    wire signed [ACC_WIDTH-1:0] xcorr_re_term =
        (proc_ch0_i * proc_ch1_i) + (proc_ch0_q * proc_ch1_q);
    wire signed [ACC_WIDTH-1:0] xcorr_im_term =
        (proc_ch0_q * proc_ch1_i) - (proc_ch0_i * proc_ch1_q);
    wire [ACC_WIDTH-1:0] r00_term =
        (proc_ch0_i * proc_ch0_i) + (proc_ch0_q * proc_ch0_q);
    wire [ACC_WIDTH-1:0] r11_term =
        (proc_ch1_i * proc_ch1_i) + (proc_ch1_q * proc_ch1_q);

    integer di;
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            stream_phase   <= STREAM_CH0;
            proc_state     <= PROC_IDLE;
            raw_ch0        <= 32'd0;
            raw_ch1        <= 32'd0;
            proc_ch0       <= 32'd0;
            proc_ch1       <= 32'd0;
            tap_idx        <= 0;
            ch0_fir_i      <= 0;
            ch0_fir_q      <= 0;
            ch1_fir_i      <= 0;
            ch1_fir_q      <= 0;
            acc_xcorr_re   <= 0;
            acc_xcorr_im   <= 0;
            acc_r00        <= 0;
            acc_r11        <= 0;
            sample_cnt     <= 0;
            reg_xcorr_re   <= 0;
            reg_xcorr_im   <= 0;
            reg_r00        <= 0;
            reg_r11        <= 0;
            reg_valid      <= 0;
            reg_snap_count <= 0;
            for (di = 0; di < NUM_TAPS; di = di + 1) begin
                ch0_delay_i[di] <= 16'sd0;
                ch0_delay_q[di] <= 16'sd0;
                ch1_delay_i[di] <= 16'sd0;
                ch1_delay_q[di] <= 16'sd0;
            end
        end else begin
            if (clear_valid)
                reg_valid <= 1'b0;

            if (s_axis_tvalid && s_axis_tready) begin
                if (stream_phase == STREAM_CH0) begin
                    raw_ch0      <= s_axis_tdata;
                    stream_phase <= STREAM_CH1;
                end else begin
                    raw_ch1      <= s_axis_tdata;
                    stream_phase <= STREAM_CH0;

                    if (reg_filter_en) begin
                        for (di = NUM_TAPS-1; di > 0; di = di - 1) begin
                            ch0_delay_i[di] <= ch0_delay_i[di-1];
                            ch0_delay_q[di] <= ch0_delay_q[di-1];
                            ch1_delay_i[di] <= ch1_delay_i[di-1];
                            ch1_delay_q[di] <= ch1_delay_q[di-1];
                        end
                        ch0_delay_i[0] <= raw_ch0[15:0];
                        ch0_delay_q[0] <= raw_ch0[31:16];
                        ch1_delay_i[0] <= s_axis_tdata[15:0];
                        ch1_delay_q[0] <= s_axis_tdata[31:16];

                        ch0_fir_i  <= 0;
                        ch0_fir_q  <= 0;
                        ch1_fir_i  <= 0;
                        ch1_fir_q  <= 0;
                        tap_idx    <= 0;
                        proc_state <= PROC_FIR;
                    end else begin
                        proc_ch0    <= raw_ch0;
                        proc_ch1    <= rotate_ch1(s_axis_tdata[15:0], s_axis_tdata[31:16]);
                        proc_state  <= PROC_ACCUM;
                    end
                end
            end

            case (proc_state)
                PROC_IDLE: begin
                    // Wait for the stream FSM to capture a complete pair.
                end

                PROC_FIR: begin
                    if (tap_idx == NUM_UNIQUE - 1) begin
                        proc_ch0 <= {ch0_fir_q_next[30:15], ch0_fir_i_next[30:15]};
                        proc_ch1 <= rotate_ch1(ch1_fir_i_next[30:15], ch1_fir_q_next[30:15]);
                        proc_state <= PROC_ACCUM;
                    end else begin
                        ch0_fir_i <= ch0_fir_i_next;
                        ch0_fir_q <= ch0_fir_q_next;
                        ch1_fir_i <= ch1_fir_i_next;
                        ch1_fir_q <= ch1_fir_q_next;
                        tap_idx   <= tap_idx + 1'b1;
                    end
                end

                PROC_ACCUM: begin
                    if (sample_cnt == SNAPSHOT_LEN - 1) begin
                        reg_xcorr_re   <= acc_xcorr_re + xcorr_re_term;
                        reg_xcorr_im   <= acc_xcorr_im + xcorr_im_term;
                        reg_r00        <= acc_r00 + r00_term;
                        reg_r11        <= acc_r11 + r11_term;
                        reg_valid      <= 1'b1;
                        reg_snap_count <= reg_snap_count + 1'b1;
                        acc_xcorr_re   <= 0;
                        acc_xcorr_im   <= 0;
                        acc_r00        <= 0;
                        acc_r11        <= 0;
                        sample_cnt     <= 0;
                    end else begin
                        acc_xcorr_re <= acc_xcorr_re + xcorr_re_term;
                        acc_xcorr_im <= acc_xcorr_im + xcorr_im_term;
                        acc_r00      <= acc_r00 + r00_term;
                        acc_r11      <= acc_r11 + r11_term;
                        sample_cnt   <= sample_cnt + 1'b1;
                    end
                    proc_state <= PROC_IDLE;
                end

                default: proc_state <= PROC_IDLE;
            endcase
        end
    end

    // ------------------------------------------------------------------
    // AXI-Lite read channel
    // ------------------------------------------------------------------
    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_araddr;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 0;
            axi_araddr    <= 0;
        end else if (s_axi_arvalid && !s_axi_arready) begin
            s_axi_arready <= 1'b1;
            axi_araddr    <= s_axi_araddr;
        end else begin
            s_axi_arready <= 1'b0;
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_rdata  <= 0;
            s_axi_rresp  <= 0;
            s_axi_rvalid <= 0;
            clear_valid  <= 0;
        end else if (s_axi_arready && s_axi_arvalid && !s_axi_rvalid) begin
            s_axi_rvalid <= 1'b1;
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
            s_axi_rvalid <= 1'b0;
            clear_valid  <= (axi_araddr[5:2] == 4'h8);
        end else begin
            clear_valid <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    // AXI-Lite write channel
    // ------------------------------------------------------------------
    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_awaddr;
    reg aw_captured;
    reg w_captured;

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready    <= 0;
            s_axi_wready     <= 0;
            s_axi_bvalid     <= 0;
            s_axi_bresp      <= 0;
            axi_awaddr       <= 0;
            aw_captured      <= 0;
            w_captured       <= 0;
            reg_cos_cal      <= 16'sd32767;
            reg_sin_cal      <= 16'sd0;
            reg_coeff_addr   <= 0;
            reg_coeff_data   <= 0;
            coeff_wr_pulse   <= 0;
            reg_filter_en    <= 0;
            reg_coeff_loaded <= 0;
        end else begin
            coeff_wr_pulse <= 1'b0;

            if (s_axi_awvalid && !s_axi_awready && !aw_captured && !s_axi_bvalid) begin
                s_axi_awready <= 1'b1;
                axi_awaddr    <= s_axi_awaddr;
                aw_captured   <= 1'b1;
            end else begin
                s_axi_awready <= 1'b0;
            end

            if (s_axi_wvalid && !s_axi_wready && !w_captured && !s_axi_bvalid) begin
                s_axi_wready <= 1'b1;
                w_captured   <= 1'b1;
            end else begin
                s_axi_wready <= 1'b0;
            end

            if (aw_captured && w_captured && !s_axi_bvalid) begin
                aw_captured  <= 1'b0;
                w_captured   <= 1'b0;
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= 2'b00;

                case (axi_awaddr[5:2])
                    4'hA: reg_cos_cal    <= s_axi_wdata[15:0];
                    4'hB: reg_sin_cal    <= s_axi_wdata[15:0];
                    4'hC: reg_coeff_addr <= s_axi_wdata[4:0];
                    4'hD: begin
                        reg_coeff_data <= s_axi_wdata[15:0];
                        coeff_wr_pulse <= 1'b1;
                    end
                    4'hE: begin
                        reg_filter_en    <= s_axi_wdata[0];
                        reg_coeff_loaded <= s_axi_wdata[1];
                    end
                    default: ;
                endcase
            end

            if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 1'b0;
        end
    end

endmodule
