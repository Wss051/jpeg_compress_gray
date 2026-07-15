///////////////////////////////////////////////////////////////////////////////
// Testbench: tb_quantizer
// Function:  单独验证 quantizer 模块
//            输入: dct_2d 第一个块输出的 64 个系数
//            期望量化值: 34, 0, 0, 0, 0, 0, 0, 0, ...
///////////////////////////////////////////////////////////////////////////////

`timescale 10ns/10ns

module tb_quantizer;

    parameter CYCLE = 10;

    reg         clk;
    reg         rst_n;
    reg         dct_en;
    reg  [11:0] dct_data;
    reg  [5:0]  dct_idx;
    wire        q_en;
    wire [11:0] q_data;
    wire [5:0]  q_idx;

    quantizer u_quantizer (
        .clk      (clk),
        .rst_n    (rst_n),
        .dct_en   (dct_en),
        .dct_data (dct_data),
        .dct_idx  (dct_idx),
        .q_en     (q_en),
        .q_data   (q_data),
        .q_idx    (q_idx),
        .qm_load  (1'b0),
        .qm_addr  (6'd0),
        .qm_data  (16'd0)
    );

    // dct_2d 第一个块输出 (column-major)
    reg [11:0] dct_vec [0:63];
    integer i;
    integer out_cnt;

    initial begin
        clk = 0;
        forever #(CYCLE/2) clk = ~clk;
    end

    initial begin
        // 前 16 个来自 tb_dct2d 实际输出
        dct_vec[0]  = 12'd546; dct_vec[1]  = 12'hFFC;  // -4
        dct_vec[2]  = 12'd0;   dct_vec[3]  = 12'hFFC;  // -4
        dct_vec[4]  = 12'hFFF; // -1
        dct_vec[5]  = 12'd2;   dct_vec[6]  = 12'd0;    dct_vec[7]  = 12'd0;
        dct_vec[8]  = 12'hFFF; // -1
        dct_vec[9]  = 12'd1;   dct_vec[10] = 12'd2;    dct_vec[11] = 12'd4;
        dct_vec[12] = 12'd2;   dct_vec[13] = 12'd1;    dct_vec[14] = 12'd2;    dct_vec[15] = 12'd0;

        // 后面补 0 (实际块高频也接近 0)
        for (i = 16; i < 64; i = i + 1)
            dct_vec[i] = 12'd0;

        rst_n = 0;
        dct_en = 0;
        dct_data = 0;
        dct_idx = 0;
        out_cnt = 0;

        #(10 * CYCLE);
        @(negedge clk);
        rst_n = 1;
        @(negedge clk);

        // 喂入 64 个系数
        for (i = 0; i < 64; i = i + 1) begin
            @(negedge clk);
            dct_en   = 1'b1;
            dct_data = dct_vec[i];
            dct_idx  = i[5:0];
        end

        @(negedge clk);
        dct_en = 1'b0;
        dct_data = 0;
        dct_idx = 0;

        $display("Quantizer output (idx -> q):");
        while (out_cnt < 64) begin
            @(posedge clk);
            if (q_en) begin
                if (out_cnt < 16)
                    $display("idx=%0d -> %0d", q_idx, $signed(q_data));
                out_cnt = out_cnt + 1;
            end
        end

        $display("Expected first 16: 34, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0");
        #(10 * CYCLE);
        $finish;
    end

endmodule
