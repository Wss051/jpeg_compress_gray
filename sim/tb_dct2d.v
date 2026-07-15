///////////////////////////////////////////////////////////////////////////////
// Testbench: tb_dct2d
// Function:  单独验证 dct_2d 模块
//            输入: 02.png 第一个 8x8 块 (已电平移位 -128)
//            输出: 64 个 DCT 系数 (column-major)
//            期望前几个: 548, -4.6, -0.4, -5.1, -1.6, 2.5, 0.0, -0.6, ...
///////////////////////////////////////////////////////////////////////////////

`timescale 10ns/10ns

module tb_dct2d;

    parameter CYCLE = 10;

    reg         clk;
    reg         rst_n;
    reg         en_in;
    reg  [7:0]  in_data;
    wire        en_out;
    wire [11:0] out_data;
    wire [5:0]  out_idx;
    wire        done;

    dct_2d u_dct_2d (
        .clk      (clk),
        .rst_n    (rst_n),
        .en_in    (en_in),
        .in_data  (in_data),
        .en_out   (en_out),
        .out_data (out_data),
        .out_idx  (out_idx),
        .done     (done)
    );

    // 02.png 第一个 8x8 块，Y 值 -128
    reg signed [7:0] block [0:63];
    integer i;
    integer out_cnt;

    initial begin
        clk = 0;
        forever #(CYCLE/2) clk = ~clk;
    end

    initial begin
        // 第一块 Y 值
        block[0]  = 71;  block[1]  = 69;  block[2]  = 69;  block[3]  = 66;
        block[4]  = 66;  block[5]  = 65;  block[6]  = 65;  block[7]  = 65;
        block[8]  = 66;  block[9]  = 66;  block[10] = 66;  block[11] = 69;
        block[12] = 69;  block[13] = 69;  block[14] = 69;  block[15] = 69;
        block[16] = 68;  block[17] = 68;  block[18] = 68;  block[19] = 70;
        block[20] = 70;  block[21] = 70;  block[22] = 70;  block[23] = 70;
        block[24] = 68;  block[25] = 68;  block[26] = 68;  block[27] = 70;
        block[28] = 70;  block[29] = 70;  block[30] = 70;  block[31] = 70;
        block[32] = 67;  block[33] = 67;  block[34] = 67;  block[35] = 68;
        block[36] = 68;  block[37] = 68;  block[38] = 68;  block[39] = 68;
        block[40] = 69;  block[41] = 69;  block[42] = 69;  block[43] = 68;
        block[44] = 68;  block[45] = 68;  block[46] = 68;  block[47] = 68;
        block[48] = 69;  block[49] = 69;  block[50] = 69;  block[51] = 70;
        block[52] = 70;  block[53] = 70;  block[54] = 70;  block[55] = 70;
        block[56] = 69;  block[57] = 69;  block[58] = 69;  block[59] = 70;
        block[60] = 70;  block[61] = 70;  block[62] = 70;  block[63] = 70;

        rst_n = 0;
        en_in = 0;
        in_data = 0;
        out_cnt = 0;

        #(10 * CYCLE);
        @(negedge clk);
        rst_n = 1;
        @(negedge clk);

        // 喂入 64 个像素
        for (i = 0; i < 64; i = i + 1) begin
            @(negedge clk);
            en_in = 1'b1;
            in_data = block[i];
        end

        @(negedge clk);
        en_in = 1'b0;
        in_data = 8'd0;

        // 等待并打印输出
        $display("dct_2d output (column-major idx -> data):");
        while (out_cnt < 64) begin
            @(posedge clk);
            if (en_out) begin
                $display("idx=%0d -> %0d", out_idx, $signed(out_data));
                out_cnt = out_cnt + 1;
            end
        end

        $display("Expected first 16 (approx): 548,-4,-0,-5,-1,2,0,-0,-1,1,3,5,2,2,3,0");
        $finish;
    end

endmodule
