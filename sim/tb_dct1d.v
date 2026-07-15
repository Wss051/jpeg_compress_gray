///////////////////////////////////////////////////////////////////////////////
// Testbench: tb_dct1d
// Function:  单独验证 DCT1D 模块
//            输入: 第一行像素 (已电平移位 -128)
//            期望输出 (AAN, /1024): [189, 5, 1, 0, 0, 0, 0, 1]
///////////////////////////////////////////////////////////////////////////////

`timescale 10ns/10ns

module tb_dct1d;

    parameter CYCLE = 10;

    reg        clk;
    reg        rst_n;
    reg        en_in;
    reg  signed [9:0] in_data;
    wire       en_out;
    wire signed [11:0] out_data;

    // 待测 DCT1D: 与 dct_2d 中列 DCT 配置一致 (DIN_W=10, DOUT_W=12)
    DCT1D #(
        .DIN_W (10),
        .DOUT_W(12)
    ) u_dct (
        .clk      (clk),
        .rst_n    (rst_n),
        .en_in    (en_in),
        .in_data  (in_data),
        .en_out   (en_out),
        .out_data (out_data)
    );

    // 测试向量: 02.png 第一块第一行，电平移位后
    reg signed [9:0] test_vec [0:7];
    integer i;
    integer out_cnt;

    initial begin
        clk = 0;
        forever #(CYCLE/2) clk = ~clk;
    end

    initial begin
        // 第一行 Y: 199,197,197,194,194,193,193,193 -> -128
        test_vec[0] = 10'sd71;
        test_vec[1] = 10'sd69;
        test_vec[2] = 10'sd69;
        test_vec[3] = 10'sd66;
        test_vec[4] = 10'sd66;
        test_vec[5] = 10'sd65;
        test_vec[6] = 10'sd65;
        test_vec[7] = 10'sd65;

        rst_n = 0;
        en_in = 0;
        in_data = 0;
        out_cnt = 0;

        #(10 * CYCLE);
        @(negedge clk);
        rst_n = 1;
        @(negedge clk);

        // 喂入 8 个样本
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge clk);
            en_in = 1'b1;
            in_data = test_vec[i];
        end

        @(negedge clk);
        en_in = 1'b0;
        in_data = 10'sd0;

        // 等待输出
        $display("DCT1D output:");
        while (out_cnt < 8) begin
            @(posedge clk);
            if (en_out) begin
                $display("out[%0d] = %0d", out_cnt, out_data);
                out_cnt = out_cnt + 1;
            end
        end

        $display("Expected: 189, 5, 1, 0, 0, 0, 0, 1");
        $finish;
    end

endmodule
