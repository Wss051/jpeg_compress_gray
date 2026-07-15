// ============================================================================
// quantizer — 8×8 2D-DCT 后级可编程标量量化模块 (独立模块)
// ============================================================================
// 数学模型:  F_q(u,v) = round( F(u,v) / Q(u,v) )
// 硬件实现:  F_q = round( F * S / 2^SHIFT ),  S = round( 2^SHIFT / Q )
//
// 特性:
//   - 64-entry 可编程量化缩放表 (64 × SCALE_W)
//   - 3 级流水线, 吞吐率 1 sample/cycle
//   - 输入/输出流式握手 (en / idx / data)
//   - 输出带符号饱和, 防止溢出
//   - 上电默认加载标准 JPEG 亮度量化缩放表
//
// 接口:
//   dct_*  : DCT 系数输入流 (en / idx / data)
//   q_*    : 量化后系数输出流
//   qm_*   : 量化表加载接口 (qm_load 高电平时写入 qm_addr)
// ============================================================================

`timescale 10ns/10ns

module quantizer #(
    parameter DCT_W   = 12,         // DCT 系数位宽
    parameter SCALE_W = 16,         // 量化缩放值位宽
    parameter OUT_W   = 12,         // 量化输出位宽
    parameter SHIFT   = 15          // 定点缩放因子 2^SHIFT
)(
    input               clk,
    input               rst_n,

    // DCT 系数输入流
    input               dct_en,
    input  [DCT_W-1:0]  dct_data,
    input  [5:0]        dct_idx,

    // 量化后输出流
    output reg          q_en,
    output reg [OUT_W-1:0] q_data,
    output reg [5:0]    q_idx,

    // 量化表加载接口
    input               qm_load,
    input  [5:0]        qm_addr,
    input  [SCALE_W-1:0] qm_data
);

    // ------------------------------------------------------------------
    // 默认 JPEG 亮度量化缩放表 (S = round(2^15 / Q))
    // 按 DCT 输出 column-major 顺序排列: dct_idx = {col[2:0], row[2:0]}
    // 因此 qtable[idx] 对应标准 Q[row][col]
    //
    // 使用 Verilog-2001 兼容的扁平参数, qtable[i] 对应 DEFAULT_SCALE_FLAT[i*16 +: 16]
    // ------------------------------------------------------------------
    localparam [SCALE_W*64-1:0] DEFAULT_SCALE_FLAT = {
        // qtable[63] .. qtable[56]
        16'd331, 16'd324, 16'd356, 16'd426, 16'd529, 16'd585, 16'd596, 16'd537,
        // qtable[55] .. qtable[48]
        16'd318, 16'd273, 16'd290, 16'd318, 16'd410, 16'd475, 16'd546, 16'd643,
        // qtable[47] .. qtable[40]
        16'd328, 16'd271, 16'd315, 16'd301, 16'd377, 16'd575, 16'd565, 16'd819,
        // qtable[39] .. qtable[32]
        16'd293, 16'd318, 16'd405, 16'd482, 16'd643, 16'd819, 16'd1260, 16'd1365,
        // qtable[31] .. qtable[24]
        16'd334, 16'd377, 16'd512, 16'd585, 16'd1130, 16'd1365, 16'd1725, 16'd2048,
        // qtable[23] .. qtable[16]
        16'd345, 16'd420, 16'd596, 16'd886, 16'd1489, 16'd2048, 16'd2341, 16'd3277,
        // qtable[15] .. qtable[8]
        16'd356, 16'd512, 16'd936, 16'd1489, 16'd1928, 16'd2521, 16'd2731, 16'd2979,
        // qtable[7] .. qtable[0]
        16'd455, 16'd669, 16'd1365, 16'd1820, 16'd2341, 16'd2341, 16'd2731, 16'd2048
    };

    // ------------------------------------------------------------------
    // 量化表 RAM: 64 × SCALE_W, 组合读 / 时序写
    // ------------------------------------------------------------------
    reg [SCALE_W-1:0] qtable [0:63];

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < 64; i = i + 1)
                qtable[i] <= DEFAULT_SCALE_FLAT[i*SCALE_W +: SCALE_W];
        end else if (qm_load) begin
            qtable[qm_addr] <= qm_data;
        end
    end

    // ------------------------------------------------------------------
    // 第 1 级: 锁存输入并读取量化表
    // ------------------------------------------------------------------
    reg        en_p1;
    reg signed [DCT_W-1:0]   data_p1;
    reg        [5:0]         idx_p1;
    reg signed [SCALE_W-1:0] scale_p1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            en_p1    <= 1'b0;
            data_p1  <= {DCT_W{1'b0}};
            idx_p1   <= 6'd0;
            scale_p1 <= {SCALE_W{1'b0}};
        end else begin
            en_p1    <= dct_en;
            data_p1  <= $signed(dct_data);
            idx_p1   <= dct_idx;
            scale_p1 <= $signed(qtable[dct_idx]);
        end
    end

    // ------------------------------------------------------------------
    // 第 2 级: 有符号乘法 (signed × signed)
    // ------------------------------------------------------------------
    reg        en_p2;
    reg [5:0]  idx_p2;
    reg signed [DCT_W+SCALE_W-1:0] prod_p2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            en_p2   <= 1'b0;
            idx_p2  <= 6'd0;
            prod_p2 <= {DCT_W+SCALE_W{1'b0}};
        end else begin
            en_p2   <= en_p1;
            idx_p2  <= idx_p1;
            prod_p2 <= data_p1 * scale_p1;
        end
    end

    // ------------------------------------------------------------------
    // 第 3 级: 舍入、右移、饱和
    //
    // 采用定点舍入方案:
    //   F_q = floor( (F * S + 2^(SHIFT-1)) / 2^SHIFT )
    //
    // 对正数等价于四舍五入; 对负数会略偏向 0 (仅对恰好为 -0.5 的 half 值有差异),
    // 这是 FPGA 量化常用方案, 硬件开销最小。
    // ------------------------------------------------------------------
    localparam signed [DCT_W+SCALE_W-1:0] ROUND = (1 << (SHIFT - 1));
    wire signed [DCT_W+SCALE_W-1:0] prod_round = prod_p2 + ROUND;
    wire signed [DCT_W+SCALE_W-1:0] prod_shift = prod_round >>> SHIFT;

    localparam signed [OUT_W-1:0] MAX_VAL = {1'b0, {(OUT_W-1){1'b1}}};   // +2047
    // 使用 -2047 而非 -2048, 避免熵编码器 category=12 查表越界
    // (JPEG 标准 Huffman 表仅支持 category 0~11, 对应幅值 ≤2047)
    localparam signed [OUT_W-1:0] MIN_VAL = -12'sd2047;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q_en   <= 1'b0;
            q_data <= {OUT_W{1'b0}};
            q_idx  <= 6'd0;
        end else begin
            q_en  <= en_p2;
            q_idx <= idx_p2;
            if (en_p2) begin
                if (prod_shift > MAX_VAL)
                    q_data <= MAX_VAL;
                else if (prod_shift < MIN_VAL)
                    q_data <= MIN_VAL;
                else
                    q_data <= prod_shift[OUT_W-1:0];
            end
        end
    end

endmodule
