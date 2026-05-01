`timescale 1ns / 1ps

module tb_doa_pipeline_kv260_separate;
    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    reg [31:0] s_axis_tdata = 0;
    reg        s_axis_tvalid = 0;
    wire       s_axis_tready;

    wire [31:0] s_axi_rdata;
    wire [1:0]  s_axi_rresp;
    wire        s_axi_rvalid;
    wire        s_axi_arready;
    wire        s_axi_awready;
    wire        s_axi_wready;
    wire [1:0]  s_axi_bresp;
    wire        s_axi_bvalid;

    doa_pipeline_kv260_separate #(
        .SNAPSHOT_LEN(2)
    ) dut (
        .s_axi_aclk(clk),
        .s_axi_aresetn(rst_n),
        .s_axi_awaddr(12'd0),
        .s_axi_awprot(3'd0),
        .s_axi_awvalid(1'b0),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(32'd0),
        .s_axi_wstrb(4'hF),
        .s_axi_wvalid(1'b0),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(1'b1),
        .s_axi_araddr(12'd0),
        .s_axi_arprot(3'd0),
        .s_axi_arvalid(1'b0),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(1'b1),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready)
    );

    task send_beat;
        input [31:0] data;
        begin
            @(posedge clk);
            while (!s_axis_tready) @(posedge clk);
            s_axis_tdata <= data;
            s_axis_tvalid <= 1'b1;
            @(posedge clk);
            while (!s_axis_tready) @(posedge clk);
            s_axis_tvalid <= 1'b0;
            s_axis_tdata <= 32'd0;
        end
    endtask

    task send_pair;
        input signed [15:0] ch0_i;
        input signed [15:0] ch0_q;
        input signed [15:0] ch1_i;
        input signed [15:0] ch1_q;
        begin
            send_beat({ch0_q, ch0_i});
            send_beat({ch1_q, ch1_i});
        end
    endtask

    initial begin
        repeat (5) @(posedge clk);
        rst_n <= 1'b1;
        repeat (2) @(posedge clk);

        // Filter disabled, default calibration is cos ~= 1, sin = 0.
        send_pair(16'sd1000, 16'sd0, 16'sd2000, 16'sd0);
        send_pair(16'sd3000, 16'sd0, 16'sd4000, 16'sd0);

        repeat (20) @(posedge clk);

        if (!dut.reg_valid)
            $fatal(1, "expected result_valid");
        if (dut.reg_snap_count !== 32'd1)
            $fatal(1, "snap_count mismatch: %0d", dut.reg_snap_count);
        if (dut.reg_xcorr_re !== 48'd13996000)
            $fatal(1, "xcorr_re mismatch: %0d", dut.reg_xcorr_re);
        if (dut.reg_xcorr_im !== 48'd0)
            $fatal(1, "xcorr_im mismatch: %0d", dut.reg_xcorr_im);
        if (dut.reg_r00 !== 48'd10000000)
            $fatal(1, "r00 mismatch: %0d", dut.reg_r00);
        if (dut.reg_r11 !== 48'd19988002)
            $fatal(1, "r11 mismatch: %0d", dut.reg_r11);

        $display("PASS tb_doa_pipeline_kv260_separate");
        $finish;
    end
endmodule
