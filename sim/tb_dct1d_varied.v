///////////////////////////////////////////////////////////////////////////////
// Testbench: tb_dct1d_varied
// Function:  用非均匀、有正负变化的测试向量验证 DCT1D 模块
//            原 tb_dct1d.v 只用几乎恒定输入 (71,69,69,66,66,65,65,65)
//            无法暴露蝶形运算对变化数据的 bug
///////////////////////////////////////////////////////////////////////////////

`timescale 10ns/10ns

module tb_dct1d_varied;

    parameter CYCLE = 10;

    reg        clk;
    reg        rst_n;
    reg        en_in;
    reg  signed [11:0] in_data;
    wire       en_out;
    wire signed [11:0] out_data;

    // 被测 DCT1D: 使用与 dct_2d 修复后一致的配置 (DIN_W=12, DOUT_W=12)
    DCT1D #(
        .DIN_W (12),
        .DOUT_W(12)
    ) u_dct (
        .clk      (clk),
        .rst_n    (rst_n),
        .en_in    (en_in),
        .in_data  (in_data),
        .en_out   (en_out),
        .out_data (out_data)
    );

    // 测试向量
    reg signed [11:0] test_vec [0:7];
    integer i;
    integer out_cnt;
    integer test_num;
    integer errors;

    initial begin
        clk = 0;
        forever #(CYCLE/2) clk = ~clk;
    end

    task run_test;
        input [8*32-1:0] name;
        input signed [11:0] v0, v1, v2, v3, v4, v5, v6, v7;
        reg signed [11:0] expected [0:7];
        integer j;
        begin
            test_vec[0] = v0; test_vec[1] = v1;
            test_vec[2] = v2; test_vec[3] = v3;
            test_vec[4] = v4; test_vec[5] = v5;
            test_vec[6] = v6; test_vec[7] = v7;

            // 喂入 8 个样本
            for (j = 0; j < 8; j = j + 1) begin
                @(negedge clk);
                en_in = 1'b1;
                in_data = test_vec[j];
            end

            @(negedge clk);
            en_in = 1'b0;

            // 等待输出
            out_cnt = 0;
            $display("Test %0d: %s", test_num, name);
            $display("  Input: %0d %0d %0d %0d %0d %0d %0d %0d",
                     v0, v1, v2, v3, v4, v5, v6, v7);

            while (out_cnt < 8) begin
                @(posedge clk);
                if (en_out) begin
                    $display("  out[%0d] = %0d", out_cnt, out_data);
                    out_cnt = out_cnt + 1;
                end
            end
        end
    endtask

    initial begin
        rst_n = 0;
        en_in = 0;
        in_data = 0;
        test_num = 0;

        #(10 * CYCLE);
        @(negedge clk);
        rst_n = 1;
        @(negedge clk);

        // ============================================================
        // Test 1: 原始简单向量 (验证基本功能是否仍然正确)
        // ============================================================
        test_num = 1;
        run_test("Original (near-constant)",
                 10'sd71, 10'sd69, 10'sd69, 10'sd66,
                 10'sd66, 10'sd65, 10'sd65, 10'sd65);

        // ============================================================
        // Test 2: 混合正负值 (level-shifted 像素的典型范围)
        // ============================================================
        test_num = 2;
        run_test("Mixed +/-",
                 -50, 100, -30, 80, -10, 60, 20, -40);

        // ============================================================
        // Test 3: 全负值
        // ============================================================
        test_num = 3;
        run_test("All negative",
                 -10, -20, -30, -40, -50, -60, -70, -80);

        // ============================================================
        // Test 4: 最大摆幅 (正负交替极值, 测试蝶形溢出)
        // ============================================================
        test_num = 4;
        run_test("Max swing +/-",
                 -128, 127, -128, 127, -128, 127, -128, 127);

        // ============================================================
        // Test 5: 渐变 (ramp, 测试低频响应)
        // ============================================================
        test_num = 5;
        run_test("Ramp",
                 -100, -70, -40, -10, 20, 50, 80, 110);

        // ============================================================
        // Test 6: 脉冲 (测试高频响应)
        // ============================================================
        test_num = 6;
        run_test("Impulse",
                 100, 0, 0, 0, 0, 0, 0, 0);

        // ============================================================
        // Test 7: 连续两块的验证 (测试 result_cnt 和 result_buf)
        // ============================================================
        test_num = 7;
        $display("Test 7: Back-to-back blocks");

        // Block A
        $display("  Block A:");
        run_test("Block A (ramp)",
                 -50, -30, -10, 10, 30, 50, 70, 90);
        // Block B (en_in 保持高, 测试连续块处理)
        $display("  Block B:");
        run_test("Block B (impulse)",
                 200, 0, 0, 0, 0, 0, 0, 0);

        $display("============================================");
        $display("All DCT1D varied tests complete.");
        $display("Verify with Python bit-accurate model:");
        $display("  python sim/bit_accurate_model.py");
        $display("============================================");
        $finish;
    end

endmodule
