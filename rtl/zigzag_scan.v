// ============================================================================
// zigzag_scan — 8×8 矩阵 Zig-Zag 扫描模块
// ============================================================================
// 功能: 接收 column-major 顺序的 64 个系数, 按 Zig-Zag 顺序输出
//
// 输入约定:
//   din_idx = {col[2:0], row[2:0]}  (与 dct_2d / quantizer 输出一致)
//   din_en  高电平持续 64 cycle, 每 cycle 写入一个系数到内部 RAM
//
// 输出约定:
//   dout_idx 顺序递增 0..63
//   dout_data 为 Zig-Zag 位置 dout_idx 对应的系数
//   done      整个 8×8 块扫描完成后输出 1 cycle 脉冲
//
// 参数:
//   ZZ_MODE = 0: 标准 JPEG Zig-Zag (水平优先)
//   ZZ_MODE = 1: 转置 Zig-Zag (竖直优先, 适合 dct_2d 做了内部转置的情况)
//
// 状态机:
//   S_IDLE -> S_LOAD (写 64 点) -> S_SCAN (读 64 点) -> S_DONE -> S_IDLE
// ============================================================================

`timescale 10ns/10ns

module zigzag_scan #(
    parameter DATA_W  = 12,
    parameter ZZ_MODE = 1          // 默认竖直优先 (转置 Zig-Zag)
)(
    input               clk,
    input               rst_n,

    // 输入流 (column-major)
    input               din_en,
    input  [DATA_W-1:0] din_data,
    input  [5:0]        din_idx,

    // 输出流 (Zig-Zag 顺序)
    output reg          dout_en,
    output reg [DATA_W-1:0] dout_data,
    output reg [5:0]    dout_idx,
    output reg          done
);

    // ------------------------------------------------------------------
    // 状态定义
    // ------------------------------------------------------------------
    localparam S_IDLE = 2'd0;
    localparam S_LOAD = 2'd1;
    localparam S_SCAN = 2'd2;
    localparam S_DONE = 2'd3;

    reg [1:0] state;
    reg [6:0] cnt;          // 0..63 计数

    // ------------------------------------------------------------------
    // 内部 RAM: 64 × DATA_W
    // ------------------------------------------------------------------
    reg [DATA_W-1:0] ram [0:63];

    // ------------------------------------------------------------------
    // Zig-Zag 地址 ROM (Verilog-2001 扁平参数)
    //   输出位置 zz_pos (0..63) 对应的输入 column-major 地址
    //   ZZ_ADDR_FLAT[zz_pos*6 +: 6]
    //
    // ZZ_MODE = 0: 标准 JPEG, 水平优先
    //   0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, ...
    // ZZ_MODE = 1: 转置, 竖直优先
    //   0, 8, 1, 2, 9, 16, 24, 17, 10, 3, 4, 11, ...
    // ------------------------------------------------------------------
    localparam [6*64-1:0] ZZ_ADDR_H = {
        // zz_pos 63 .. 56
        6'd63, 6'd55, 6'd62, 6'd61, 6'd54, 6'd47, 6'd39, 6'd46,
        // zz_pos 55 .. 48
        6'd53, 6'd60, 6'd59, 6'd52, 6'd45, 6'd38, 6'd31, 6'd23,
        // zz_pos 47 .. 40
        6'd30, 6'd37, 6'd44, 6'd51, 6'd58, 6'd57, 6'd50, 6'd43,
        // zz_pos 39 .. 32
        6'd36, 6'd29, 6'd22, 6'd15, 6'd7,  6'd14, 6'd21, 6'd28,
        // zz_pos 31 .. 24
        6'd35, 6'd42, 6'd49, 6'd56, 6'd48, 6'd41, 6'd34, 6'd27,
        // zz_pos 23 .. 16
        6'd20, 6'd13, 6'd6,  6'd5,  6'd12, 6'd19, 6'd26, 6'd33,
        // zz_pos 15 .. 8
        6'd40, 6'd32, 6'd25, 6'd18, 6'd11, 6'd4,  6'd3,  6'd10,
        // zz_pos 7 .. 0
        6'd17, 6'd24, 6'd16, 6'd9,  6'd2,  6'd1,  6'd8,  6'd0
    };

    localparam [6*64-1:0] ZZ_ADDR_V = {
        // zz_pos 63 .. 56
        6'd63, 6'd62, 6'd55, 6'd47, 6'd54, 6'd61, 6'd60, 6'd53,
        // zz_pos 55 .. 48
        6'd46, 6'd39, 6'd31, 6'd38, 6'd45, 6'd52, 6'd59, 6'd58,
        // zz_pos 47 .. 40
        6'd51, 6'd44, 6'd37, 6'd30, 6'd23, 6'd15, 6'd22, 6'd29,
        // zz_pos 39 .. 32
        6'd36, 6'd43, 6'd50, 6'd57, 6'd56, 6'd49, 6'd42, 6'd35,
        // zz_pos 31 .. 24
        6'd28, 6'd21, 6'd14, 6'd7,  6'd6,  6'd13, 6'd20, 6'd27,
        // zz_pos 23 .. 16
        6'd34, 6'd41, 6'd48, 6'd40, 6'd33, 6'd26, 6'd19, 6'd12,
        // zz_pos 15 .. 8
        6'd5,  6'd4,  6'd11, 6'd18, 6'd25, 6'd32, 6'd24, 6'd17,
        // zz_pos 7 .. 0
        6'd10, 6'd3,  6'd2,  6'd9,  6'd16, 6'd8,  6'd1,  6'd0
    };

    // ------------------------------------------------------------------
    // 写 RAM: 在输入阶段 (S_IDLE 或 S_LOAD) 且 din_en 有效时写入
    // ------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // 复位时不初始化 RAM
        end else if (din_en && (state == S_IDLE || state == S_LOAD)) begin
            ram[din_idx] <= din_data;
        end
    end

    // ------------------------------------------------------------------
    // 状态机 + 输出控制
    // ------------------------------------------------------------------
    wire [5:0] zz_addr = (ZZ_MODE == 0) ? ZZ_ADDR_H[cnt[5:0]*6 +: 6]
                                         : ZZ_ADDR_V[cnt[5:0]*6 +: 6];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            cnt      <= 7'd0;
            dout_en  <= 1'b0;
            dout_data<= {DATA_W{1'b0}};
            dout_idx <= 6'd0;
            done     <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (din_en) begin
                        state <= S_LOAD;
                        cnt   <= 7'd1;      // 第 0 点已写入 RAM
                    end
                end

                S_LOAD: begin
                    if (din_en) begin
                        if (cnt == 7'd63) begin
                            state <= S_SCAN;
                            cnt   <= 7'd0;
                        end else begin
                            cnt <= cnt + 7'd1;
                        end
                    end
                end

                S_SCAN: begin
                    dout_en   <= 1'b1;
                    dout_data <= ram[zz_addr];
                    dout_idx  <= cnt[5:0];

                    if (cnt == 7'd63) begin
                        state <= S_DONE;
                        cnt   <= 7'd0;
                    end else begin
                        cnt <= cnt + 7'd1;
                    end
                end

                S_DONE: begin
                    dout_en <= 1'b0;
                    done    <= 1'b1;
                    state   <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
