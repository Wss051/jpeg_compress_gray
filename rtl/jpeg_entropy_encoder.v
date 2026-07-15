///////////////////////////////////////////////////////////////////////////////
// Module:      jpeg_entropy_encoder
// Function:    JPEG 灰度熵编码器
//              - DC 差分编码: diff = DC_cur - DC_prev
//              - AC 游程编码: 统计零游程，产生 (run/level) 对，支持 ZRL/EOB
//              - Huffman 查表: 标准 JPEG 亮度 DC/AC 表
//
// 输入: Zig-Zag 系数流 (din_en + din_data + din_idx + block_done)
// 输出: 每个符号的 Huffman code + extra bits
//
// 输出格式:
//   out_valid    — 当前周期输出有效
//   out_is_dc    — 1=DC 符号, 0=AC/EOB/ZRL
//   out_is_eob   — 1=EOB 符号
//   out_code     — Huffman 码 (右对齐，有效位长度 out_len)
//   out_len      — Huffman 码长度 (0~16)
//   out_extra    — 附加位 (VLI 编码后的幅值，右对齐)
//   out_extra_len— 附加位长度 (= category)
///////////////////////////////////////////////////////////////////////////////

`default_nettype none

module jpeg_entropy_encoder (
    input  wire        clk,
    input  wire        rst_n,

    // Zig-Zag 输入流
    input  wire        din_en,
    input  wire [11:0] din_data,
    input  wire [5:0]  din_idx,
    input  wire        block_done,
    input  wire        frame_done,

    // 熵编码输出
    output reg         out_valid,
    output reg         out_is_dc,
    output reg         out_is_eob,
    output reg  [15:0] out_code,
    output reg  [4:0]  out_len,
    output reg  [11:0] out_extra,
    output reg  [3:0]  out_extra_len,
    output reg         block_done_out,
    output reg         frame_done_out
);

    `include "huffman_tables.vh"

    //==========================================================================
    // 函数：计算 category = bit_length(abs(val))，0 时返回 0
    //==========================================================================
    function [3:0] category;
        input signed [11:0] val;
        reg [11:0] abs_val;
        begin
            abs_val = val >= 0 ? val : -val;
            // 优先判断高位: 修复 abs_val=2048 (12'h800) 时 bit[10]=0 导致
            // 错误落入 cat=0 的 bug (量化器虽已饱和至 ±2047, 此处做防御)
            if (abs_val == 0)       category = 4'd0;
            else if (abs_val[11])   category = 4'd12;  // >= 2048 (防御)
            else if (abs_val[10])   category = 4'd11;  // >= 1024
            else if (abs_val[9])    category = 4'd10;  // >= 512
            else if (abs_val[8])    category = 4'd9;
            else if (abs_val[7])    category = 4'd8;
            else if (abs_val[6])    category = 4'd7;
            else if (abs_val[5])    category = 4'd6;
            else if (abs_val[4])    category = 4'd5;
            else if (abs_val[3])    category = 4'd4;
            else if (abs_val[2])    category = 4'd3;
            else if (abs_val[1])    category = 4'd2;
            else                    category = 4'd1;
        end
    endfunction

    //==========================================================================
    // 函数：VLI 附加位编码
    //   val > 0: 直接取 val 的低 cat 位
    //   val < 0: 取 (val - 1) 的低 cat 位 (JPEG 负数编码规则)
    //==========================================================================
    function [11:0] encode_extra;
        input signed [11:0] val;
        input [3:0] cat;
        reg [11:0] mask;
        begin
            if (cat == 0)
                encode_extra = 12'd0;
            else if (val >= 0)
                encode_extra = val;
            else begin
                // 修复: VLI 负数编码需掩码至 cat 位宽
                //   JPEG 标准: extra = (val - 1) & ((1 << cat) - 1)
                //   原代码输出完整 12-bit 值 (如 -1 -> 4094), 虽功能正确
                //   (解码端会自行掩码) 但位流打包时会带入高位垃圾 bit
                mask = (12'd1 << cat) - 12'd1;
                encode_extra = (val - 12'sd1) & mask;
            end
        end
    endfunction

    //==========================================================================
    // 状态寄存器
    //==========================================================================
    reg signed [11:0] prev_dc;
    reg [3:0]         ac_run_cnt;

    //==========================================================================
    // 组合逻辑：当前输入产生的符号
    //==========================================================================
    wire signed [11:0] dc_diff = $signed(din_data) - prev_dc;
    wire [3:0]         dc_cat  = category(dc_diff);
    wire [11:0]        dc_extra= encode_extra(dc_diff, dc_cat);
    // 防御: 饱和至 11, 防止 cat=12 时 DC_HUFF_CODE/LEN 数组越界
    // (量化器已饱和至 ±2047, cat=12 仅在硬件 SEU 等异常场景触发)
    wire [3:0]         dc_cat_safe = (dc_cat > 4'd11) ? 4'd11 : dc_cat;
    wire [15:0]        dc_huff_code = DC_HUFF_CODE[dc_cat_safe*16 +: 16];
    wire [4:0]         dc_huff_len  = DC_HUFF_LEN[dc_cat_safe*5 +: 5];

    wire [3:0]         ac_cat  = category($signed(din_data));
    wire [11:0]        ac_extra= encode_extra($signed(din_data), ac_cat);
    // 防御: 饱和 AC category 至 11, 避免查表越界
    wire [3:0]         ac_cat_safe = (ac_cat > 4'd11) ? 4'd11 : ac_cat;
    wire [7:0]         ac_sym  = {ac_run_cnt, ac_cat_safe};
    wire [15:0]        ac_huff_code = AC_HUFF_CODE[ac_sym*16 +: 16];
    wire [4:0]         ac_huff_len  = AC_HUFF_LEN[ac_sym*5 +: 5];

    wire [7:0]         eob_sym = 8'h00;  // (0,0)
    wire [15:0]        eob_huff_code = AC_HUFF_CODE[eob_sym*16 +: 16];
    wire [4:0]         eob_huff_len  = AC_HUFF_LEN[eob_sym*5 +: 5];

    wire [7:0]         zrl_sym = 8'hF0;  // (15,0)
    wire [15:0]        zrl_huff_code = AC_HUFF_CODE[zrl_sym*16 +: 16];
    wire [4:0]         zrl_huff_len  = AC_HUFF_LEN[zrl_sym*5 +: 5];

    //==========================================================================
    // 输出控制（纯组合）
    //==========================================================================
    always @(*) begin
        // 默认值
        out_valid     = 1'b0;
        out_is_dc     = 1'b0;
        out_is_eob    = 1'b0;
        out_code      = 16'd0;
        out_len       = 5'd0;
        out_extra     = 12'd0;
        out_extra_len = 4'd0;
        block_done_out= 1'b0;
        frame_done_out= 1'b0;

        // DC 符号（每个块第 0 个系数）
        if (din_en && din_idx == 6'd0) begin
            out_valid     = 1'b1;
            out_is_dc     = 1'b1;
            out_code      = dc_huff_code;
            out_len       = dc_huff_len;
            out_extra     = dc_extra;
            out_extra_len = dc_cat_safe;  // 使用安全 category, 与查表一致
        end
        // AC 符号
        else if (din_en && din_idx > 6'd0) begin
            if ($signed(din_data) == 12'sd0) begin
                // 第 16 个连续零 -> 输出 ZRL
                if (ac_run_cnt == 4'd15) begin
                    out_valid = 1'b1;
                    out_code  = zrl_huff_code;
                    out_len   = zrl_huff_len;
                end
            end else begin
                out_valid     = 1'b1;
                out_code      = ac_huff_code;
                out_len       = ac_huff_len;
                out_extra     = ac_extra;
                out_extra_len = ac_cat_safe;  // 使用安全 category, 与查表一致
            end
        end

        // EOB 在 block_done 周期输出
        if (block_done) begin
            out_valid      = 1'b1;
            out_is_eob     = 1'b1;
            out_code       = eob_huff_code;
            out_len        = eob_huff_len;
            block_done_out = 1'b1;
        end

        if (frame_done) begin
            frame_done_out = 1'b1;
        end
    end

    //==========================================================================
    // 时序逻辑：更新 prev_dc 与 ac_run_cnt
    //==========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            prev_dc    <= 12'sd0;
            ac_run_cnt <= 4'd0;
        end else begin
            if (din_en && din_idx == 6'd0) begin
                prev_dc <= $signed(din_data);
            end

            if (din_en && din_idx > 6'd0) begin
                if ($signed(din_data) == 12'sd0) begin
                    if (ac_run_cnt == 4'd15) begin
                        ac_run_cnt <= 4'd0;  // ZRL 已发，重新开始计数
                    end else begin
                        ac_run_cnt <= ac_run_cnt + 4'd1;
                    end
                end else begin
                    ac_run_cnt <= 4'd0;
                end
            end

            if (block_done) begin
                ac_run_cnt <= 4'd0;
            end
        end
    end

endmodule
