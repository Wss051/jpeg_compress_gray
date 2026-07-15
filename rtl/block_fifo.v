///////////////////////////////////////////////////////////////////////////////
// Module:      block_fifo
// Function:    8-bit 双端口同步 FIFO，用于 image.v 与 dct_2d 之间的像素缓冲
//              基于 Quartus altsyncram 双端口 RAM IP (ram_dp.v)
//
// 说明:
//   - 写端口 A: 接收 image.v 输出的像素 (wr_en/wr_data)
//   - 读端口 B: 供 dct_2d 控制器按块读出 (rd_en/rd_data)
//   - 提供 almost_full 给 image.v 做反压 (ready_in)
//   - ram_dp.v 为 UNREGISTERED 输出，读数据与读地址同周期有效
///////////////////////////////////////////////////////////////////////////////

`default_nettype none

module block_fifo #(
    parameter DEPTH          = 512,         // FIFO 深度 (像素数)
    parameter ALMOST_MARGIN  = 64           // almost_full 阈值余量
)(
    input  wire        clk,
    input  wire        rst_n,

    input  wire        wr_en,               // 写使能
    input  wire [7:0]  wr_data,             // 写数据

    input  wire        rd_en,               // 读使能
    output wire [7:0]  rd_data,             // 读数据 (组合输出)

    output wire        full,
    output wire        almost_full,
    output wire        empty,
    output reg  [$clog2(DEPTH):0] usedw      // 当前占用字数
);

    //==========================================================================
    // 指针与地址
    //==========================================================================
    localparam PTR_W = $clog2(DEPTH);

    reg [PTR_W-1:0] wr_ptr;
    reg [PTR_W-1:0] rd_ptr;

    // ram_dp.v 地址宽度为 17-bit，高位补零
    wire [16:0] ram_wr_addr = {{(17-PTR_W){1'b0}}, wr_ptr};
    wire [16:0] ram_rd_addr = {{(17-PTR_W){1'b0}}, rd_ptr};

    //==========================================================================
    // 实例化双端口 RAM (ram_dp.v 已配置为 8-bit x 102400)
    //==========================================================================
    ram_dp u_ram (
        .clock     (clk),
        .address_a (ram_wr_addr),
        .data_a    (wr_data),
        .wren_a    (wr_en && !full),
        .address_b (ram_rd_addr),
        .rden_b    (rd_en && !empty),
        .q_b       (rd_data)
    );

    //==========================================================================
    // 状态标志
    //==========================================================================
    assign full        = (usedw == DEPTH);
    assign almost_full = (usedw >= DEPTH - ALMOST_MARGIN);
    assign empty       = (usedw == 0);

    //==========================================================================
    // 指针更新
    //==========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= {PTR_W{1'b0}};
            rd_ptr <= {PTR_W{1'b0}};
        end else begin
            if (wr_en && !full)
                wr_ptr <= wr_ptr + 1'b1;
            if (rd_en && !empty)
                rd_ptr <= rd_ptr + 1'b1;
        end
    end

    //==========================================================================
    // 占用计数
    //==========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            usedw <= {$clog2(DEPTH)+1{1'b0}};
        end else begin
            case ({wr_en && !full, rd_en && !empty})
                2'b10:   usedw <= usedw + 1'b1;
                2'b01:   usedw <= usedw - 1'b1;
                default: usedw <= usedw;
            endcase
        end
    end

endmodule
