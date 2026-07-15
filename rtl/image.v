///////////////////////////////////////////////////////////////////////////////
// Module:      image
// Function:    320×320 图像按 8×8 不重叠块输出（乒乓双 RAM，8 行 chunk）
//              - 输入：按行扫描写入，en_in=1 时写入 1 个有效像素
//              - 输出：按 8×8 块读出，块内行优先、块间行优先
//              - 乒乓操作：每写满 8 行（2560 像素，一个 block row）切换
//              - 使用 Quartus 生成的双端口 RAM IP（ram_dp.v）
///////////////////////////////////////////////////////////////////////////////

`default_nettype none

module image (
    input  wire        clk,      // system clock
    input  wire        rst_n,    // async reset, active low
    input  wire        en_in,    // input data enable
    input  wire [7:0]  in_data,  // 像素输入（8位）
    input  wire        ready_in, // 下游反压：0=暂停读/输出，1=正常输出
    output reg         en_out,   // output valid flag
    output reg  [7:0]  out_data  // 像素输出
);

    //==========================================================================
    // 图像与块参数
    //==========================================================================
    localparam IMAGE_H          = 320;    // 图像高度
    localparam IMAGE_W          = 320;    // 图像宽度
    localparam BLOCK_H          = 8;      // 块高
    localparam BLOCK_W          = 8;      // 块宽
    localparam BLOCK_ROWS       = IMAGE_H / BLOCK_H;          // 40
    localparam BLOCK_COLS       = IMAGE_W / BLOCK_W;          // 40
    localparam PIXELS_PER_CHUNK = BLOCK_H * IMAGE_W;          // 2560 = 8行
    localparam CHUNK_ADDR_W     = 12;                         // ceil(log2(2560))
    localparam RAM_ADDR_WIDTH   = 17;                         // ram_dp IP 地址宽度

    //==========================================================================
    // 坐标与计数器
    //==========================================================================
    reg [CHUNK_ADDR_W-1:0] wr_pixels;     // chunk 内写像素计数 0~2559
    reg [2:0]              inner_row;      // 块内行 0~7
    reg [2:0]              inner_col;      // 块内列 0~7
    reg [5:0]              block_col;      // chunk 内块列 0~39
    reg                    rd_active;      // 读取已激活（首个 chunk 写完后）
    reg                    wr_sel;         // 0=写ram_a, 1=写ram_b
    reg                    rd_sel;         // 0=读ram_a, 1=读ram_b

    //==========================================================================
    // 地址生成
    //==========================================================================
    // 写地址：chunk 内顺序写入（高位补零适配 17-bit RAM）
    wire [RAM_ADDR_WIDTH-1:0] wr_addr = {5'd0, wr_pixels};

    // 读地址：chunk 内 8×8 块顺序（每个 chunk 仅 8 行，去掉 block_row 偏移）
    wire [CHUNK_ADDR_W-1:0] rd_addr_chunk = (inner_row * IMAGE_W)
                                           + (block_col * BLOCK_W + inner_col);
    wire [RAM_ADDR_WIDTH-1:0] rd_addr = {5'd0, rd_addr_chunk};

    //==========================================================================
    // 双端口 RAM 乒乓实例化
    // ram_a/ram_b 各有一个写端口 A 和一个读端口 B
    //==========================================================================
    wire        wr_en_a = en_in && (wr_sel == 1'b0);
    wire        wr_en_b = en_in && (wr_sel == 1'b1);
    wire        rd_en_a = rd_active && (rd_sel == 1'b0);
    wire        rd_en_b = rd_active && (rd_sel == 1'b1);
    wire [7:0]  q_a, q_b;

    ram_dp u_ram_a (
        .clock     (clk),
        .address_a (wr_addr),
        .data_a    (in_data),
        .wren_a    (wr_en_a),
        .address_b (rd_addr),
        .rden_b    (rd_en_a),
        .q_b       (q_a)
    );

    ram_dp u_ram_b (
        .clock     (clk),
        .address_a (wr_addr),
        .data_a    (in_data),
        .wren_a    (wr_en_b),
        .address_b (rd_addr),
        .rden_b    (rd_en_b),
        .q_b       (q_b)
    );

    //==========================================================================
    // 输出选择
    //==========================================================================
    always @(posedge clk) begin
        if (rd_active && ready_in) begin
            out_data <= rd_sel ? q_b : q_a;
        end else begin
            out_data <= 8'd0;
        end
    end

    //==========================================================================
    // 状态机与坐标更新
    //==========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_pixels  <= {CHUNK_ADDR_W{1'b0}};
            inner_row  <= 3'd0;
            inner_col  <= 3'd0;
            block_col  <= 6'd0;
            rd_active  <= 1'b0;
            en_out     <= 1'b0;
            wr_sel     <= 1'b0;   // 初始写 ram_a
            rd_sel     <= 1'b1;   // 读 ram_b（空）
        end else begin
            // en_out 与 out_data 对齐：ram_dp 为 UNREGISTERED 输出，
            // out_data 寄存一拍，因此 en_out 只延迟 rd_active&&ready_in 一拍。
            if (ready_in) begin
                en_out     <= rd_active && ready_in;
            end else begin
                en_out     <= 1'b0;
            end

            // 读坐标更新（rd_active 且 ready_in 有效时才更新）
            if (rd_active && ready_in) begin
                if (inner_col == BLOCK_W - 1) begin
                    inner_col <= 3'd0;
                    if (inner_row == BLOCK_H - 1) begin
                        inner_row <= 3'd0;
                        if (block_col == BLOCK_COLS - 1) begin
                            block_col <= 6'd0;  // chunk 读完，回绕
                        end else begin
                            block_col <= block_col + 1'b1;
                        end
                    end else begin
                        inner_row <= inner_row + 1'b1;
                    end
                end else begin
                    inner_col <= inner_col + 1'b1;
                end
            end

            // 写操作（en_in 有效时）
            if (en_in) begin
                if (wr_pixels == PIXELS_PER_CHUNK - 1) begin
                    // 当前 chunk 写满，乒乓切换
                    wr_pixels <= {CHUNK_ADDR_W{1'b0}};
                    wr_sel    <= ~wr_sel;
                    rd_sel    <= ~rd_sel;
                    rd_active <= 1'b1;           // 首个 chunk 后激活读取
                end else begin
                    wr_pixels <= wr_pixels + 1'b1;
                end
            end
        end
    end

endmodule
