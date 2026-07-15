// ============================================================================
// dct_2d — 8×8 二维 DCT-II 顶层模块 (行列分离 + 矩阵转置)
// ============================================================================
// 算法: 2D DCT = 1D-DCT(rows) → Transpose → 1D-DCT(columns)
//   第1步: 对 8 行分别做 8 点 1D DCT → 8×8 中间矩阵 G
//   第2步: 矩阵转置 G → G^T (通过 transpose_ram 地址变换实现)
//   第3步: 对 8 列分别做 8 点 1D DCT → 最终 8×8 系数矩阵 F
//
// 1D DCT 引擎: AAN (Arai-Agui-Nakajima) 蝶形算法, 22次乘法/8点
//   参数化 #(DIN_W=12, DOUT_W=12), 行列分时复用同一引擎
//   行 DCT: 8-bit 像素符号扩展→12-bit 输入 (充裕裕量, 防溢出)
//   列 DCT: 12-bit 中间系数全精度直通 (修复原 10-bit 截断丢 2 MSB 的 bug)
//
// 转置原理:
//   行 DCT 结果按 row-major 写入 transpose_ram (addr = row*8 + coeff)
//   列 DCT 按 column-major 读出 transpose_ram (addr = row_idx*8 + col)
//   物理地址不变, 只改变地址产生的顺序 → 无需额外转置逻辑
//
// 时序预算 (每 8×8 块):
//   S_LOAD   : 64 cycles (收像素 → arm.v)
//   Row DCT  : 8×(1_PRE + 8_FEED + 8_DRN) = 136 cycles
//   Col DCT  : 8×(1_PRE + 8_FEED + 8_DRN) = 136 cycles
//   S_DONE   : 1 cycle
//   总计     : ~337 cycles/块 @ 100MHz = 3.37 μs/块
//
// RAM: 均为 Quartus altsyncram IP, UNREGISTERED 输出 (读延迟 1 cycle)
//   arm.v          : 8-bit  × 4096  输入缓冲
//   transpose_ram.v: 12-bit × 64    转置缓冲
//
// 输出格式: column-major (与 MATLAB dct2 默认输出一致)
//   out_idx 0..7  = F[0][0],F[1][0],...,F[7][0]  (DC分量在 out_idx=0)
//   out_idx 8..15 = F[0][1],F[1][1],...,F[7][1]
//   out_idx 56..63= F[0][7],F[1][7],...,F[7][7]
// ============================================================================

`timescale 10ns/10ns

module dct_2d (
    input               clk,
    input               rst_n,
    input               en_in,          // 像素输入有效 (持续 64 cycles)
    input      [7:0]    in_data,        // 串行像素 (signed 8-bit, 已电平移位)
    output              en_out,         // 系数输出有效
    output     [11:0]   out_data,       // DCT 系数 (signed 12-bit)
    output     [5:0]    out_idx,        // 输出索引 0..63 (column-major)
    output              done            // 块处理完成 (1 cycle 脉冲)
);

// =========================================================================
// 状态定义
// =========================================================================
localparam S_IDLE     = 4'd0;   // 空闲, 等待 en_in
localparam S_LOAD     = 4'd1;   // 接收 64 像素写入 arm.v
localparam S_ROW_PRE  = 4'd2;   // 行 DCT: 预取行首像素
localparam S_ROW_FEED = 4'd3;   // 行 DCT: 串行喂 8 样本到 DCT1D
localparam S_ROW_DRN  = 4'd4;   // 行 DCT: 收 8 结果写入 transpose_ram
localparam S_COL_PRE  = 4'd5;   // 列 DCT: 预取列首值
localparam S_COL_FEED = 4'd6;   // 列 DCT: 串行喂 8 值到 DCT1D
localparam S_COL_DRN  = 4'd7;   // 列 DCT: 收 8 结果并输出
localparam S_DONE     = 4'd8;   // done 脉冲

// =========================================================================
// 内部寄存器
// =========================================================================
reg  [3:0]  state;
reg  [6:0]  load_cnt;      // S_LOAD 写入计数 0..63
reg  [2:0]  row;           // 当前行 0..7
reg  [2:0]  col;           // 当前列 0..7
reg  [2:0]  feed_cnt;      // 喂样本计数 0..7
reg  [2:0]  drain_cnt;     // 收结果计数 0..7

// =========================================================================
// DCT1D 引擎接口信号
// =========================================================================
wire        dct_en_out;
wire [11:0] dct_out;

reg         dct_en_in;
reg  [11:0] dct_in;

// =========================================================================
// DCT1D 引擎实例化 (行列分时复用)
//   行 DCT: 8-bit 像素符号扩展→12-bit 输入, 12-bit 输出→transpose_ram
//   列 DCT: 12-bit 中间系数全精度输入, 12-bit 输出→最终结果
//   修复: DIN_W 从 10 提升到 12, 列 DCT 不再截断 2 MSB
// =========================================================================
DCT1D #(
    .DIN_W (12),
    .DOUT_W(12)
) u_dct (
    .clk      (clk),
    .rst_n    (rst_n),
    .en_in    (dct_en_in),
    .in_data  (dct_in),
    .en_out   (dct_en_out),
    .out_data (dct_out)
);

// =========================================================================
// arm.v — 输入像素缓冲 (8-bit × 4096, single-port, UNREGISTERED 输出)
// =========================================================================
wire [7:0]  arm_q;
reg  [11:0] arm_addr;
reg  [7:0]  arm_data;
reg         arm_wren;

arm u_arm (
    .address (arm_addr),
    .clock   (clk),
    .data    (arm_data),
    .rden    (1'b1),       // 读始终使能
    .wren    (arm_wren),
    .q       (arm_q)
);

// =========================================================================
// transpose_ram.v — 转置缓冲 (12-bit × 64, single-port, UNREGISTERED 输出)
//   写入: row-major  (addr = {row,    coeff})
//   读出: colum-major (addr = {row_idx, col  }) — 实现转置
// =========================================================================
wire [11:0] tram_q;
reg  [5:0]  tram_addr;
reg  [11:0] tram_data;
reg         tram_wren;

transpose_ram u_tram (
    .address (tram_addr),
    .clock   (clk),
    .data    (tram_data),
    .rden    (1'b1),       // 读始终使能
    .wren    (tram_wren),
    .q       (tram_q)
);

// =========================================================================
// 输出寄存器 (仅 S_COL_DRN 期间更新, 其他状态保持上次值)
//   修复: 原 assign out_data = dct_out 组合直通会在行 DCT DRAIN / LOAD 等
//   阶段透传 DCT1D 内部 out_data 寄存器, 导致顶层 out_data 在 en_out=0
//   时仍然跳变 (波形表现为 "混乱, 未被使能控制")
//   寄存后 out_data/en_out/out_idx 仅在列 DCT 输出有效时更新, 其余阶段稳定
// =========================================================================
reg         en_out_r;
reg [11:0]  out_data_r;
reg [5:0]   out_idx_r;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        en_out_r   <= 1'b0;
        out_data_r <= 12'd0;
        out_idx_r  <= 6'd0;
    end else if (state == S_COL_DRN && dct_en_out) begin
        en_out_r   <= 1'b1;
        out_data_r <= dct_out;
        out_idx_r  <= {col, drain_cnt};       // column-major: col*8 + row
    end else begin
        en_out_r <= 1'b0;
        // out_data_r / out_idx_r 保持上次值 (不在 en_out=0 时跳变)
    end
end

assign en_out   = en_out_r;
assign out_data = out_data_r;
assign out_idx  = out_idx_r;
assign done     = (state == S_DONE);

// =========================================================================
// 组合逻辑: 数据通路多路选择
//   根据 state 控制各 RAM 的读写地址/数据以及 DCT1D 输入
//   默认值保证所有未使用路径的安全状态
// =========================================================================
always @(*) begin
    // ---- 默认值 (安全状态) ----
    arm_addr  = 12'd0;
    arm_data  =  8'd0;
    arm_wren  =  1'b0;
    tram_addr =  6'd0;
    tram_data = 12'd0;
    tram_wren =  1'b0;
    dct_en_in =  1'b0;
    dct_in    = 12'd0;

    case (state)

        // ============================================================
        // S_IDLE: 检测 en_in, 写第 0 号像素到 arm.v[0]
        // ============================================================
        S_IDLE: begin
            if (en_in) begin
                arm_wren = 1'b1;
                arm_addr = 12'd0;
                arm_data = in_data;
            end
        end

        // ============================================================
        // S_LOAD: 写像素 1..63 到 arm.v[1..63]
        // ============================================================
        S_LOAD: begin
            arm_wren = 1'b1;
            arm_addr = {5'd0, load_cnt};
            arm_data = in_data;
        end

        // ============================================================
        // 行 DCT 阶段: arm.v → 符号扩展 → DCT1D
        //
        // 预取时序 (RAM 读延迟 1 cycle):
        //   S_ROW_PRE : 发出 row*8 读地址
        //   S_ROW_FEED: arm_q = 预取像素 → DCT1D; 同时发出下个读地址
        //   S_ROW_DRN : DCT1D 输出有效 → 写入 transpose_ram
        // ============================================================

        S_ROW_PRE: begin
            // 预取当前行第 0 个像素
            arm_addr = {6'd0, row, 3'b000};       // addr = row * 8
        end

        S_ROW_FEED: begin
            // 当前周期: 将预取的像素送入 DCT1D
            dct_en_in = 1'b1;
            dct_in    = {{4{arm_q[7]}}, arm_q};    // 8-bit 符号扩展 → 12-bit (修复: 配合 DIN_W=12)
            // 预取下一个像素 (下一周期使用)
            arm_addr  = {6'd0, row, (feed_cnt + 3'd1)};
        end

        S_ROW_DRN: begin
            // DCT1D 串行输出 8 个系数, 写入 transpose_ram (row-major)
            if (dct_en_out) begin
                tram_wren = 1'b1;
                tram_addr = {row, drain_cnt};       // addr = row*8 + coeff_idx
                tram_data = dct_out;
            end
        end

        // ============================================================
        // 列 DCT 阶段: transpose_ram → 12-bit 全精度 → DCT1D
        //
        // 预取时序:
        //   S_COL_PRE : 发出 col (第0行此列) 读地址
        //   S_COL_FEED: tram_q = 预取值 → DCT1D; 同时发出下行同列地址
        //   S_COL_DRN : DCT1D 输出有效 → 直通到顶层输出
        //
        // 转置关键: addr = {row_idx, col}
        //   列 DCT 按 row_idx=0..7 逐行扫描同一列
        //   等价于按列读取 (column-major read)
        // ============================================================

        S_COL_PRE: begin
            // 预取第 0 行、当前列的值
            tram_addr = {3'b000, col};              // addr = 0*8 + col = col
        end

        S_COL_FEED: begin
            // 当前周期: 将预取值送入 DCT1D
            dct_en_in = 1'b1;
            dct_in    = tram_q;                     // 12-bit 全精度直通 (修复: 不再截断 2 MSB)
            // 预取下一行同列的值
            tram_addr = {(feed_cnt + 3'd1), col};   // addr = (row+1)*8 + col
        end

        // S_COL_DRN: 输出在 assign 中组合直通, 无需额外逻辑

        default: ;
    endcase
end

// =========================================================================
// 时序逻辑: FSM 状态机
// =========================================================================
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state     <= S_IDLE;
        load_cnt  <= 7'd0;
        row       <= 3'd0;
        col       <= 3'd0;
        feed_cnt  <= 3'd0;
        drain_cnt <= 3'd0;

    end else begin
        case (state)

            // ========================================================
            // S_IDLE → S_LOAD
            //   检测 en_in 上升后, 像素 0 已在上层组合逻辑中写入
            //   此处跳转并初始化 load_cnt=1 (下一个写入地址)
            // ========================================================
            S_IDLE: begin
                if (en_in) begin
                    state    <= S_LOAD;
                    load_cnt <= 7'd1;
                end
            end

            // ========================================================
            // S_LOAD → S_ROW_PRE
            //   连续写入 64 像素到 arm.v, 完成后进入行 DCT
            // ========================================================
            S_LOAD: begin
                load_cnt <= load_cnt + 7'd1;
                if (load_cnt == 7'd63) begin
                    state    <= S_ROW_PRE;
                    row      <= 3'd0;
                    load_cnt <= 7'd0;
                end
            end

            // ========================================================
            // 行 DCT 循环: 8 行 × (PRE → FEED → DRN)
            //   PRE : 预取行首 → 无条件跳转 FEED
            //   FEED: 喂 8 样本 → 跳转 DRN
            //   DRN : 收 8 结果写 transpose_ram → 下一行或进入列 DCT
            // ========================================================
            S_ROW_PRE: begin
                state    <= S_ROW_FEED;
                feed_cnt <= 3'd0;
            end

            S_ROW_FEED: begin
                if (feed_cnt == 3'd7) begin
                    state     <= S_ROW_DRN;
                    drain_cnt <= 3'd0;
                end
                feed_cnt <= feed_cnt + 3'd1;
            end

            S_ROW_DRN: begin
                if (dct_en_out) begin
                    if (drain_cnt == 3'd7) begin
                        // 当前行完成
                        drain_cnt <= 3'd0;
                        if (row == 3'd7) begin
                            // 所有 8 行完成 → 进入列 DCT
                            state <= S_COL_PRE;
                            row   <= 3'd0;
                            col   <= 3'd0;
                        end else begin
                            // 继续下一行
                            state <= S_ROW_PRE;
                            row   <= row + 3'd1;
                        end
                    end else begin
                        drain_cnt <= drain_cnt + 3'd1;
                    end
                end
            end

            // ========================================================
            // 列 DCT 循环: 8 列 × (PRE → FEED → DRN)
            //   PRE : 预取列首 → 无条件跳转 FEED
            //   FEED: 喂 8 值 → 跳转 DRN
            //   DRN : 收 8 结果输出 → 下一列或完成
            // ========================================================
            S_COL_PRE: begin
                state    <= S_COL_FEED;
                feed_cnt <= 3'd0;
            end

            S_COL_FEED: begin
                if (feed_cnt == 3'd7) begin
                    state     <= S_COL_DRN;
                    drain_cnt <= 3'd0;
                end
                feed_cnt <= feed_cnt + 3'd1;
            end

            S_COL_DRN: begin
                if (dct_en_out) begin
                    if (drain_cnt == 3'd7) begin
                        drain_cnt <= 3'd0;
                        if (col == 3'd7) begin
                            // 所有 8 列完成
                            state <= S_DONE;
                        end else begin
                            // 继续下一列
                            state <= S_COL_PRE;
                            col   <= col + 3'd1;
                        end
                    end else begin
                        drain_cnt <= drain_cnt + 3'd1;
                    end
                end
            end

            // ========================================================
            // S_DONE → S_IDLE
            //   done 脉冲 1 周期后回到空闲态, 等待下一个块
            // ========================================================
            S_DONE: begin
                state <= S_IDLE;
            end

            default: state <= S_IDLE;

        endcase
    end
end

endmodule
