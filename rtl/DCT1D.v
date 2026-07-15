// ============================================================================
// DCT1D -- 8 点一维 DCT-II (AAN 蝶形算法)
// ----------------------------------------------------------------------------
// 端口与 tb.v 实例化完全匹配:
//   clk, rst_n, en_in, in_data(signed 8bit), en_out, out_data(signed 10bit)
// 参数 DIN_W / DOUT_W 可调 (默认 8/10 匹配 tb; 2D 顶层引擎实例设 10/12)
// 系数缩放 1024, 与 tb 参考模型 t_dct1 的 a,b,c,d,e,f,g 完全一致
//
// 蝶形结构 (Arai-Agui-Nakajima 风格):
//   Stage 1: 输入蝶形 8 加减         b0..b7
//   Stage 2: 偶部 4 点蝶形           c0..c3 (奇部直接用 b4..b7)
//   Stage 3: 乘加输出 (22 次乘法)    y0..y7
//
// 时序: en_in=1 期间逐周期收样本, 第 8 个样本时组合蝶形完成;
//       en_in 拉低后串行输出所有结果 (en_out=1, 每周期一个)
//       支持 en_in 持续高连续处理多块 (tb 送 2 块)
// ============================================================================

`timescale 10ns/10ns

module DCT1D #(
    parameter DIN_W  = 8,           // 输入位宽, 默认 8 匹配 tb; 2D 引擎用 10
    parameter DOUT_W = 10           // 输出位宽, 默认 10 匹配 tb; 2D 引擎用 12
)(
    input                       clk,
    input                       rst_n,
    input                       en_in,
    input  signed [DIN_W-1:0]   in_data,
    output reg                  en_out,
    output reg signed [DOUT_W-1:0] out_data
);

    // ------------------------------------------------------------------
    // 系数 (×1024 定点, 与 tb 参考模型 a..g 一致)
    //   A0=a=362 : 1/(2√2) × 1024
    //   A1=b=502 : cos(π/16)/2 × 1024
    //   A2=c=473 : cos(π/8)/2 × 1024
    //   A3=d=426 : cos(3π/16)/2 × 1024
    //   A4=e=284 : cos(5π/16)/2 × 1024
    //   A5=f=196 : cos(3π/8)/2 = sin(π/8)/2 × 1024
    //   A6=g=100 : cos(7π/16)/2 × 1024
    // ------------------------------------------------------------------
    localparam signed [11:0] A0 = 12'sd362;
    localparam signed [11:0] A1 = 12'sd502;
    localparam signed [11:0] A2 = 12'sd473;
    localparam signed [11:0] A3 = 12'sd426;
    localparam signed [11:0] A4 = 12'sd284;
    localparam signed [11:0] A5 = 12'sd196;
    localparam signed [11:0] A6 = 12'sd100;

    // ------------------------------------------------------------------
    // 样本寄存器 x0..x6 (第 8 个样本 x7 直接用 in_data, 蝶形组合逻辑实时算)
    // ------------------------------------------------------------------
    reg signed [DIN_W-1:0] x0, x1, x2, x3, x4, x5, x6;

    // ------------------------------------------------------------------
    // Stage 1: 输入蝶形 (x7 = in_data)
    //   b0 = x0+x7   b4 = x3-x4
    //   b1 = x1+x6   b5 = x2-x5
    //   b2 = x2+x5   b6 = x1-x6
    //   b3 = x3+x4   b7 = x0-x7
    // ------------------------------------------------------------------
    wire signed [DIN_W:0] b0 = x0 + in_data;   // x0+x7
    wire signed [DIN_W:0] b1 = x1 + x6;
    wire signed [DIN_W:0] b2 = x2 + x5;
    wire signed [DIN_W:0] b3 = x3 + x4;
    wire signed [DIN_W:0] b4 = x3 - x4;
    wire signed [DIN_W:0] b5 = x2 - x5;
    wire signed [DIN_W:0] b6 = x1 - x6;
    wire signed [DIN_W:0] b7 = x0 - in_data;   // x0-x7

    // ------------------------------------------------------------------
    // Stage 2: 偶部 4 点蝶形 (奇部直接用 b4..b7 进 Stage 3)
    //   c0 = b0+b3   c2 = b0-b3
    //   c1 = b1+b2   c3 = b1-b2
    // ------------------------------------------------------------------
    wire signed [DIN_W+1:0] c0 = b0 + b3;
    wire signed [DIN_W+1:0] c1 = b1 + b2;
    wire signed [DIN_W+1:0] c2 = b0 - b3;
    wire signed [DIN_W+1:0] c3 = b1 - b2;

    // 偶部和/差 (多 1 位防溢出)
    wire signed [DIN_W+2:0] s_even_add = c0 + c1;   // 全部样本和
    wire signed [DIN_W+2:0] s_even_sub = c0 - c1;   // 偶序符号和

    // ------------------------------------------------------------------
    // Stage 3: 乘加输出 (组合, 第 8 样本时有效)
    //   偶部:
    //     y0 = (c0+c1) × A0       → X[0]   (tb: a*sum)
    //     y4 = (c0-c1) × A0       → X[4]   (tb: a*alt-sum)
    //     y2 = c2×A2 + c3×A5      → X[2]   (tb: c*(..)+f*(..))
    //     y6 = c2×A5 - c3×A2      → X[6]   (tb: f*(..)-c*(..))
    //   奇部 (用 b4,b5,b6,b7):
    //     y1 = b7×A1 + b6×A3 + b5×A4 + b4×A6   → X[1]
    //     y3 = b7×A3 - b6×A6 - b5×A1 - b4×A4   → X[3]
    //     y5 = b7×A4 - b6×A1 + b5×A6 + b4×A3   → X[5]
    //     y7 = b7×A6 - b6×A4 + b5×A3 - b4×A1   → X[7]
    // ------------------------------------------------------------------
    wire signed [23:0] y0 = s_even_add * A0;
    wire signed [23:0] y4 = s_even_sub * A0;
    wire signed [23:0] y2 = c2 * A2 + c3 * A5;
    wire signed [23:0] y6 = c2 * A5 - c3 * A2;
    wire signed [23:0] y1 = b7 * A1 + b6 * A3 + b5 * A4 + b4 * A6;
    wire signed [23:0] y3 = b7 * A3 - b6 * A6 - b5 * A1 - b4 * A4;
    wire signed [23:0] y5 = b7 * A4 - b6 * A1 + b5 * A6 + b4 * A3;
    wire signed [23:0] y7 = b7 * A6 - b6 * A4 + b5 * A3 - b4 * A1;

    // /1024 舍入: 加 512 后算术右移 10 位, 与量化器 round 方案一致
    //   (y + 512) >>> 10: 对正数等价于四舍五入, 对负数略向正偏 (仅影响 ±0.5 边界)
    //   避免了纯截断 (y/1024) 造成的系统性 -0.5LSB 偏差, 该偏差经 2D DCT 累积
    wire signed [23:0] y0_round = y0 + 512;
    wire signed [23:0] y1_round = y1 + 512;
    wire signed [23:0] y2_round = y2 + 512;
    wire signed [23:0] y3_round = y3 + 512;
    wire signed [23:0] y4_round = y4 + 512;
    wire signed [23:0] y5_round = y5 + 512;
    wire signed [23:0] y6_round = y6 + 512;
    wire signed [23:0] y7_round = y7 + 512;

    wire signed [DOUT_W-1:0] y0_r = y0_round >>> 10;
    wire signed [DOUT_W-1:0] y1_r = y1_round >>> 10;
    wire signed [DOUT_W-1:0] y2_r = y2_round >>> 10;
    wire signed [DOUT_W-1:0] y3_r = y3_round >>> 10;
    wire signed [DOUT_W-1:0] y4_r = y4_round >>> 10;
    wire signed [DOUT_W-1:0] y5_r = y5_round >>> 10;
    wire signed [DOUT_W-1:0] y6_r = y6_round >>> 10;
    wire signed [DOUT_W-1:0] y7_r = y7_round >>> 10;

    // ------------------------------------------------------------------
    // 状态机
    //   IDLE  : 等 en_in, 存第 1 样本到 x0
    //   LOAD  : 逐周期收 x1..x6; 第 8 样本(x7=in_data)时蝶形有效, 存结果
    //           en_in 仍高则继续收下一块; en_in=0 则转 DRAIN
    //   DRAIN : 串行输出所有结果, 完成回 IDLE
    // ------------------------------------------------------------------
    localparam IDLE  = 2'd0;
    localparam LOAD  = 2'd1;
    localparam DRAIN = 2'd2;

    reg [1:0] state;
    reg [2:0] sample_idx;       // 0..7, 当前块内样本索引
    reg [4:0] out_idx;          // DRAIN 输出索引
    reg [4:0] result_cnt;       // 已完成的结果组数 (tb 送 2 块)

    // 结果缓冲: 最多 2 组 × 8 = 16 个系数
    reg signed [DOUT_W-1:0] result_buf [0:15];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= IDLE;
            sample_idx <= 3'd0;
            out_idx    <= 5'd0;
            result_cnt <= 5'd0;
            en_out     <= 1'b0;
            out_data   <= 0;
            x0 <= 0; x1 <= 0; x2 <= 0; x3 <= 0;
            x4 <= 0; x5 <= 0; x6 <= 0;
        end else begin
            case (state)
                // ----------------------------------------------------
                IDLE: begin
                    en_out  <= 1'b0;
                    out_idx <= 5'd0;
                    if (en_in) begin
                        // 第 1 个样本 → x0
                        x0         <= in_data;
                        sample_idx <= 3'd1;
                        state      <= LOAD;
                    end
                end

                // ----------------------------------------------------
                LOAD: begin
                    if (en_in) begin
                        if (sample_idx < 3'd7) begin
                            // 样本 0..6 → x0..x6 (0 用于连续块第1个样本)
                            case (sample_idx)
                                3'd0: x0 <= in_data;
                                3'd1: x1 <= in_data;
                                3'd2: x2 <= in_data;
                                3'd3: x3 <= in_data;
                                3'd4: x4 <= in_data;
                                3'd5: x5 <= in_data;
                                3'd6: x6 <= in_data;
                                default: ;
                            endcase
                            sample_idx <= sample_idx + 3'd1;
                        end else begin
                            // sample_idx == 7: in_data 是 x7, 蝶形组合逻辑此时有效
                            result_buf[result_cnt*8 + 0] <= y0_r;
                            result_buf[result_cnt*8 + 1] <= y1_r;
                            result_buf[result_cnt*8 + 2] <= y2_r;
                            result_buf[result_cnt*8 + 3] <= y3_r;
                            result_buf[result_cnt*8 + 4] <= y4_r;
                            result_buf[result_cnt*8 + 5] <= y5_r;
                            result_buf[result_cnt*8 + 6] <= y6_r;
                            result_buf[result_cnt*8 + 7] <= y7_r;
                            result_cnt <= result_cnt + 5'd1;
                            sample_idx <= 3'd0;
                            // state 不变; 下周期若 en_in=1 则收下一块 x0
                        end
                    end else begin
                        // en_in=0: 转入输出
                        state    <= DRAIN;
                        out_idx  <= 5'd0;
                        en_out   <= 1'b1;
                        out_data <= result_buf[0];
                    end
                end

                // ----------------------------------------------------
                DRAIN: begin
                    if (out_idx < result_cnt*8 - 1) begin
                        out_data <= result_buf[out_idx + 1];
                        out_idx  <= out_idx + 5'd1;
                        en_out   <= 1'b1;
                    end else begin
                        en_out     <= 1'b0;
                        state      <= IDLE;
                        result_cnt <= 5'd0;
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
