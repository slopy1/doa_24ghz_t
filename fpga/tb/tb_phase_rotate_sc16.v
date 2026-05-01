// tb_phase_rotate_sc16.v — Testbench for phase_rotate_sc16
//
// Verifies complex rotation at 0/45/90/180 degrees against a Verilog-computed
// reference, which matches what NumPy would give us within 1 LSB.
//
// Q1.15 conversion: cos_cal = round(cos(theta) * 32768)
//   theta = 0     deg  → cos =  32767, sin =      0
//   theta = 45    deg  → cos =  23170, sin =  23170
//   theta = 90    deg  → cos =      0, sin =  32767
//   theta = 180   deg  → cos = -32767, sin =      0   (can't represent -32768 exactly)
//   theta = 16.33 deg  → cos =  31444, sin =   9214   (calibration default)
//
// Input sample (I=10000, Q=0) rotated by -theta:
//   theta = 0   → (10000, 0)
//   theta = 90  → (0, -10000)          because (I+jQ)*(cos-jsin) = 10000*(-j) = -j*10000
//   theta = 180 → (-10000, 0)

`timescale 1ns / 1ps

module tb_phase_rotate_sc16;

    localparam CLK_PERIOD = 10;

    reg               clk;
    reg               rst_n;
    reg signed [15:0] cos_cal;
    reg signed [15:0] sin_cal;
    reg  [31:0]       s_tdata;
    reg               s_tvalid;
    wire [31:0]       m_tdata;
    wire              m_tvalid;

    phase_rotate_sc16 dut (
        .clk     (clk),
        .rst_n   (rst_n),
        .cos_cal (cos_cal),
        .sin_cal (sin_cal),
        .s_tdata (s_tdata),
        .s_tvalid(s_tvalid),
        .m_tdata (m_tdata),
        .m_tvalid(m_tvalid)
    );

    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    wire signed [15:0] out_i = m_tdata[15:0];
    wire signed [15:0] out_q = m_tdata[31:16];

    integer test_pass;

    task drive_and_check;
        input signed [15:0] ci;
        input signed [15:0] cq;
        input signed [15:0] cos_v;
        input signed [15:0] sin_v;
        input signed [15:0] exp_i;
        input signed [15:0] exp_q;
        input [8*16-1:0]    label;
        begin
            @(posedge clk);
            cos_cal  <= cos_v;
            sin_cal  <= sin_v;
            s_tdata  <= {cq, ci};
            s_tvalid <= 1'b1;
            @(posedge clk);
            s_tvalid <= 1'b0;
            @(posedge clk);
            // Output valid after 1-cycle pipeline register
            if (!m_tvalid) begin
                $display("  %-12s FAIL: m_tvalid not asserted", label);
                test_pass = 0;
            end
            $display("  %-12s out=(%0d,%0d) expected=(%0d,%0d)",
                     label, out_i, out_q, exp_i, exp_q);
            // Allow +/- 2 LSB tolerance for integer rounding
            if ((out_i < exp_i - 2) || (out_i > exp_i + 2) ||
                (out_q < exp_q - 2) || (out_q > exp_q + 2)) begin
                $display("    FAIL: out of tolerance");
                test_pass = 0;
            end
        end
    endtask

    initial begin
        $dumpfile("tb_phase_rotate_sc16.vcd");
        $dumpvars(0, tb_phase_rotate_sc16);

        test_pass = 1;

        rst_n    = 0;
        cos_cal  = 0;
        sin_cal  = 0;
        s_tdata  = 32'd0;
        s_tvalid = 0;
        #(CLK_PERIOD * 5);
        rst_n = 1;
        #(CLK_PERIOD * 2);

        // ---------------------------------------------------------------
        // Test 1: identity rotation (theta = 0)
        //   cos=32767 sin=0 → output == input (within LSB)
        // ---------------------------------------------------------------
        $display("\n=== Test 1: theta = 0 (identity) ===");
        drive_and_check(16'sd10000, 16'sd0, 16'sd32767, 16'sd0,
                        16'sd10000, 16'sd0, "id_1");
        drive_and_check(16'sd5000, 16'sd3000, 16'sd32767, 16'sd0,
                        16'sd5000, 16'sd3000, "id_2");

        // ---------------------------------------------------------------
        // Test 2: 90-degree rotation
        //   cos=0 sin=32767 → (I+jQ)*(0-j) = Q - j*I
        //   So I' = Q, Q' = -I
        //   Input (10000, 0) → output (0, -10000)
        //   Input (0, 10000) → output (10000, 0)
        // ---------------------------------------------------------------
        $display("\n=== Test 2: theta = 90 deg ===");
        drive_and_check(16'sd10000, 16'sd0, 16'sd0, 16'sd32767,
                        16'sd0, -16'sd10000, "90_1");
        drive_and_check(16'sd0, 16'sd10000, 16'sd0, 16'sd32767,
                        16'sd10000, 16'sd0, "90_2");

        // ---------------------------------------------------------------
        // Test 3: 180-degree rotation
        //   cos=-32767 sin=0 → I' = -I, Q' = -Q
        // ---------------------------------------------------------------
        $display("\n=== Test 3: theta = 180 deg ===");
        drive_and_check(16'sd10000, 16'sd5000, -16'sd32767, 16'sd0,
                        -16'sd10000, -16'sd5000, "180_1");

        // ---------------------------------------------------------------
        // Test 4: 45-degree rotation
        //   cos ≈ sin ≈ 23170 (Q1.15)
        //   (10000 + j*0) * (23170 - j*23170) / 32768
        //   I' = (10000*23170 + 0*23170) / 32768 = 7071
        //   Q' = (0*23170 - 10000*23170) / 32768 = -7071
        // ---------------------------------------------------------------
        $display("\n=== Test 4: theta = 45 deg ===");
        drive_and_check(16'sd10000, 16'sd0, 16'sd23170, 16'sd23170,
                        16'sd7071, -16'sd7071, "45_1");

        // ---------------------------------------------------------------
        // Test 5: Real calibration angle 16.33 deg
        //   cos=31444 sin=9214 (from Python: round(cos(radians(16.33))*32768))
        //   Input (10000, 0)
        //   I' = 10000 * 31444 / 32768 = 9596
        //   Q' = -10000 * 9214 / 32768 = -2812
        // ---------------------------------------------------------------
        $display("\n=== Test 5: theta = 16.33 deg (real cal value) ===");
        drive_and_check(16'sd10000, 16'sd0, 16'sd31444, 16'sd9214,
                        16'sd9596, -16'sd2812, "cal_1");

        $display("\n========================================");
        if (test_pass)
            $display("  ALL TESTS PASSED");
        else
            $display("  SOME TESTS FAILED");
        $display("========================================\n");
        $finish;
    end

    initial begin
        #(CLK_PERIOD * 2000);
        $display("TIMEOUT");
        $finish;
    end

endmodule
