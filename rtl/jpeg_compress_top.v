///////////////////////////////////////////////////////////////////////////////
// Module:      jpeg_compress_top
// Function:    灰度 JPEG-like 压缩顶层
//              RGB565 → Y → 8×8 分块 → 2D-DCT → 量化 → Zig-Zag
//
// 输入:
//   clk, rst_n, en_in, rgb565_in[15:0]
// 输出:
//   ready_out      — 可继续接收像素 (0=反压上游暂停)
//   out_en         — Zig-Zag 系数有效
//   out_data[11:0] — 量化后 Zig-Zag 系数
//   out_idx[5:0]   — 系数在 Zig-Zag 流中的位置 0..63
//   block_done     — 一个 8×8 块处理完成 (1 cycle 脉冲)
//   frame_done     — 整帧 (1600 块) 处理完成
///////////////////////////////////////////////////////////////////////////////

`default_nettype none

module jpeg_compress_top (
    input  wire        clk,
    input  wire        rst_n,

    // 像素输入 (RGB565)
    input  wire        en_in,
    input  wire [15:0] rgb565_in,
    output wire        ready_out,

    // Zig-Zag 系数流 (调试用)
    output wire        out_en,
    output wire [11:0] out_data,
    output wire [5:0]  out_idx,
    output wire        block_done,

    // 熵编码输出
    output wire        entropy_valid,
    output wire        entropy_is_dc,
    output wire        entropy_is_eob,
    output wire [15:0] entropy_code,
    output wire [4:0]  entropy_len,
    output wire [11:0] entropy_extra,
    output wire [3:0]  entropy_extra_len,

    output wire        frame_done
);

    //==========================================================================
    // 图像参数
    //==========================================================================
    localparam IMAGE_W     = 320;
    localparam IMAGE_H     = 320;
    localparam BLOCK_W     = 8;
    localparam BLOCK_H     = 8;
    localparam BLOCK_COLS  = IMAGE_W / BLOCK_W;   // 40
    localparam BLOCK_ROWS  = IMAGE_H / BLOCK_H;   // 40
    localparam TOTAL_BLOCKS= BLOCK_COLS * BLOCK_ROWS; // 1600

    //==========================================================================
    // Y: RGB565 → 亮度 Y
    //==========================================================================
    wire        y_en;
    wire [7:0]  y_data;

    Y u_y (
        .clk     (clk),
        .rst_n   (rst_n),
        .en_in   (en_in),
        .in_data (rgb565_in),
        .en_out  (y_en),
        .out_y   (y_data)
    );

    //==========================================================================
    // image: 320×320 分块输出
    //==========================================================================
    wire        img_en;
    wire [7:0]  img_data;
    wire        fifo_almost_full;
    wire        img_ready_in;

    assign img_ready_in = !fifo_almost_full;
    assign ready_out    = img_ready_in;   // 上游按同一反压信号暂停

    image u_image (
        .clk       (clk),
        .rst_n     (rst_n),
        .en_in     (y_en),
        .in_data   (y_data),
        .ready_in  (img_ready_in),
        .en_out    (img_en),
        .out_data  (img_data)
    );

    //==========================================================================
    // block_fifo: image → dct_2d 像素缓冲
    //==========================================================================
    wire        fifo_rd_en;
    wire [7:0]  fifo_rd_data;
    wire        fifo_full;
    wire        fifo_empty;
    wire [9:0]  fifo_usedw;

    block_fifo #(
        .DEPTH         (512),
        .ALMOST_MARGIN (64)
    ) u_fifo (
        .clk          (clk),
        .rst_n        (rst_n),
        .wr_en        (img_en),
        .wr_data      (img_data),
        .rd_en        (fifo_rd_en),
        .rd_data      (fifo_rd_data),
        .full         (fifo_full),
        .almost_full  (fifo_almost_full),
        .empty        (fifo_empty),
        .usedw        (fifo_usedw)
    );

    //==========================================================================
    // dct_2d 控制器: 从 FIFO 取 64 像素送入 dct_2d
    //==========================================================================
    localparam C_IDLE  = 3'd0;
    localparam C_FLUSH = 3'd1;   // 启动后丢弃 FIFO 前 2 个无效像素
    localparam C_FEED  = 3'd2;
    localparam C_BUSY  = 3'd3;

    reg  [2:0]  ctrl_state;
    reg  [6:0]  feed_cnt;
    reg  [1:0]  flush_cnt;
    reg         flushed;        // 1=已完成首次 flush
    wire        dct_en_in;
    wire [7:0]  dct_in_data;
    wire        dct_done;       // 前向声明，由 dct_2d 实例化连接

    assign fifo_rd_en = (ctrl_state == C_FEED) || (ctrl_state == C_FLUSH);
    assign dct_en_in  = (ctrl_state == C_FEED);
    // dct_2d 要求输入为 像素值 - 128 (signed 8-bit)，在此处做电平移位
    wire signed [8:0] dct_pixel_signed = {1'b0, fifo_rd_data} - 9'sd128;
    assign dct_in_data = dct_pixel_signed[7:0];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_state <= C_IDLE;
            feed_cnt   <= 7'd0;
            flush_cnt  <= 2'd0;
            flushed    <= 1'b0;
        end else begin
            case (ctrl_state)
                C_IDLE: begin
                    if (fifo_usedw >= 7'd64) begin
                        if (flushed) begin
                            ctrl_state <= C_FEED;
                            feed_cnt   <= 7'd0;
                        end else begin
                            // 首次丢弃 FIFO 开头的 2 个无效像素
                            ctrl_state <= C_FLUSH;
                            flush_cnt  <= 2'd0;
                        end
                    end
                end

                C_FLUSH: begin
                    if (flush_cnt == 2'd1) begin
                        ctrl_state <= C_FEED;
                        feed_cnt   <= 7'd0;
                        flushed    <= 1'b1;
                    end else begin
                        flush_cnt <= flush_cnt + 2'd1;
                    end
                end

                C_FEED: begin
                    if (feed_cnt == 7'd63) begin
                        ctrl_state <= C_BUSY;
                    end else begin
                        feed_cnt <= feed_cnt + 7'd1;
                    end
                end

                C_BUSY: begin
                    // 等待 dct_2d 完成当前块
                    if (dct_done) begin
                        ctrl_state <= C_IDLE;
                    end
                end

                default: ctrl_state <= C_IDLE;
            endcase
        end
    end

    //==========================================================================
    // dct_2d: 8×8 二维 DCT
    //==========================================================================
    wire        dct_en_out;
    wire [11:0] dct_out_data;
    wire [5:0]  dct_out_idx;

    dct_2d u_dct_2d (
        .clk      (clk),
        .rst_n    (rst_n),
        .en_in    (dct_en_in),
        .in_data  (dct_in_data),
        .en_out   (dct_en_out),
        .out_data (dct_out_data),
        .out_idx  (dct_out_idx),
        .done     (dct_done)
    );

    //==========================================================================
    // quantizer: 标量量化
    //==========================================================================
    wire        q_en;
    wire [11:0] q_data;
    wire [5:0]  q_idx;

    quantizer u_quantizer (
        .clk      (clk),
        .rst_n    (rst_n),
        .dct_en   (dct_en_out),
        .dct_data (dct_out_data),
        .dct_idx  (dct_out_idx),
        .q_en     (q_en),
        .q_data   (q_data),
        .q_idx    (q_idx),
        .qm_load  (1'b0),
        .qm_addr  (6'd0),
        .qm_data  (16'd0)
    );

    //==========================================================================
    // zigzag_scan: Zig-Zag 扫描
    //==========================================================================
    wire        zz_en;
    wire [11:0] zz_data;
    wire [5:0]  zz_idx;

    zigzag_scan #(
        .DATA_W  (12),
        .ZZ_MODE (1)            // vertical-first，配合 dct_2d 内部转置
    ) u_zigzag (
        .clk       (clk),
        .rst_n     (rst_n),
        .din_en    (q_en),
        .din_data  (q_data),
        .din_idx   (q_idx),
        .dout_en   (zz_en),
        .dout_data (zz_data),
        .dout_idx  (zz_idx),
        .done      (block_done)
    );

    //==========================================================================
    // jpeg_entropy_encoder: DC 差分 + AC 游程 + Huffman 查表
    //==========================================================================
    wire        ent_valid;
    wire        ent_is_dc;
    wire        ent_is_eob;
    wire [15:0] ent_code;
    wire [4:0]  ent_len;
    wire [11:0] ent_extra;
    wire [3:0]  ent_extra_len;
    wire        ent_frame_done;

    jpeg_entropy_encoder u_entropy (
        .clk            (clk),
        .rst_n          (rst_n),
        .din_en         (zz_en),
        .din_data       (zz_data),
        .din_idx        (zz_idx),
        .block_done     (block_done),
        .frame_done     (frame_done),
        .out_valid      (ent_valid),
        .out_is_dc      (ent_is_dc),
        .out_is_eob     (ent_is_eob),
        .out_code       (ent_code),
        .out_len        (ent_len),
        .out_extra      (ent_extra),
        .out_extra_len  (ent_extra_len),
        .block_done_out (),
        .frame_done_out (ent_frame_done)
    );

    //==========================================================================
    // 顶层输出
    //==========================================================================
    assign out_en           = zz_en;
    assign out_data         = zz_data;
    assign out_idx          = zz_idx;

    assign entropy_valid    = ent_valid;
    assign entropy_is_dc    = ent_is_dc;
    assign entropy_is_eob   = ent_is_eob;
    assign entropy_code     = ent_code;
    assign entropy_len      = ent_len;
    assign entropy_extra    = ent_extra;
    assign entropy_extra_len= ent_extra_len;

    //==========================================================================
    // frame_done: 1600 个 block_done 后置 1
    //==========================================================================
    reg [10:0] block_cnt;
    reg        frame_done_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            block_cnt  <= 11'd0;
            frame_done_r <= 1'b0;
        end else begin
            if (block_done && block_cnt < TOTAL_BLOCKS) begin
                block_cnt <= block_cnt + 11'd1;
            end
            frame_done_r <= (block_cnt == TOTAL_BLOCKS);
        end
    end

    assign frame_done = frame_done_r;

endmodule
