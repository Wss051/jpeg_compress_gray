///////////////////////////////////////////////////////////////////////////////
// Testbench: tb_jpeg_compress
// Function:  对 jpeg_compress_top 进行整帧 320×320 仿真
//              - 从 image_320x320_rgb565.hex 读取 102400 个 RGB565 像素
//              - 按 ready_out 反压逐像素送入 DUT
//              - 捕获 Zig-Zag 输出到 zz_out_all.txt
//              - 捕获熵编码符号到 entropy_out.txt
///////////////////////////////////////////////////////////////////////////////

`timescale 10ns/10ns

module tb_jpeg_compress;

    parameter CYCLE = 10;                       // 100 MHz
    parameter IMAGE_W = 320;
    parameter IMAGE_H = 320;
    parameter TOTAL_PIXELS = IMAGE_W * IMAGE_H; // 102400
    parameter TOTAL_BLOCKS = (IMAGE_W/8) * (IMAGE_H/8); // 1600
    parameter TOTAL_COEFFS = TOTAL_BLOCKS * 64; // 102400

    //----------------------------------------------------------------------
    // DUT 信号
    //----------------------------------------------------------------------
    reg         clk;
    reg         rst_n;
    reg         en_in;
    reg  [15:0] rgb565_in;
    wire        ready_out;

    // Zig-Zag 调试输出
    wire        out_en;
    wire [11:0] out_data;
    wire [5:0]  out_idx;
    wire        block_done;

    // 熵编码输出
    wire        entropy_valid;
    wire        entropy_is_dc;
    wire        entropy_is_eob;
    wire [15:0] entropy_code;
    wire [4:0]  entropy_len;
    wire [11:0] entropy_extra;
    wire [3:0]  entropy_extra_len;

    wire        frame_done;

    //----------------------------------------------------------------------
    // DUT 实例化
    //----------------------------------------------------------------------
    jpeg_compress_top dut (
        .clk             (clk),
        .rst_n           (rst_n),
        .en_in           (en_in),
        .rgb565_in       (rgb565_in),
        .ready_out       (ready_out),
        .out_en          (out_en),
        .out_data        (out_data),
        .out_idx         (out_idx),
        .block_done      (block_done),
        .entropy_valid   (entropy_valid),
        .entropy_is_dc   (entropy_is_dc),
        .entropy_is_eob  (entropy_is_eob),
        .entropy_code    (entropy_code),
        .entropy_len     (entropy_len),
        .entropy_extra   (entropy_extra),
        .entropy_extra_len(entropy_extra_len),
        .frame_done      (frame_done)
    );

    //----------------------------------------------------------------------
    // 时钟
    //----------------------------------------------------------------------
    initial begin
        clk = 0;
        forever begin
            #(CYCLE/2);
            clk = ~clk;
        end
    end

    //----------------------------------------------------------------------
    // 测试数据与计数器
    //----------------------------------------------------------------------
    reg  [15:0] pixel_mem [0:TOTAL_PIXELS-1];
    integer     i;
    integer     pixel_cnt;
    integer     out_cnt;
    integer     block_cnt;
    integer     entropy_cnt;
    integer     entropy_total_bits;
    integer     fout_zz;
    integer     fout_ent;
    integer     timeout_cnt;

    //----------------------------------------------------------------------
    // 捕获 Zig-Zag 输出
    //----------------------------------------------------------------------
    always @(posedge clk) begin
        if (out_en) begin
            $fwrite(fout_zz, "%0d %0d\n", out_idx, $signed(out_data));
            out_cnt = out_cnt + 1;
        end
    end

    always @(posedge clk) begin
        if (block_done)
            block_cnt = block_cnt + 1;
    end

    //----------------------------------------------------------------------
    // 捕获熵编码输出
    //   每行一个符号: is_dc is_eob code len extra extra_len
    //----------------------------------------------------------------------
    always @(posedge clk) begin
        if (entropy_valid) begin
            $fwrite(fout_ent, "%0d %0d %0d %0d %0d %0d\n",
                    entropy_is_dc, entropy_is_eob,
                    entropy_code, entropy_len,
                    entropy_extra, entropy_extra_len);
            entropy_cnt = entropy_cnt + 1;
            entropy_total_bits = entropy_total_bits + entropy_len + entropy_extra_len;
        end
    end

    //----------------------------------------------------------------------
    // 主流程
    //----------------------------------------------------------------------
    initial begin
        // 初始化
        en_in      = 1'b0;
        rgb565_in  = 16'd0;
        pixel_cnt  = 0;
        out_cnt    = 0;
        block_cnt  = 0;
        entropy_cnt= 0;
        entropy_total_bits = 0;
        timeout_cnt= 0;

        // 读取 320×320 RGB565 像素
        $readmemh("E:/fpga/jpeg_compress_gray/sim/image_320x320_rgb565.hex", pixel_mem);

        // 打开输出文件
        fout_zz  = $fopen("E:/fpga/jpeg_compress_gray/sim/zz_out_all.txt", "w");
        fout_ent = $fopen("E:/fpga/jpeg_compress_gray/sim/entropy_out.txt", "w");

        // 复位
        rst_n = 0;
        #(10 * CYCLE);
        @(negedge clk);
        rst_n = 1;

        // 等待几拍后开始送数据
        @(negedge clk);
        @(negedge clk);

        // 逐像素送入，按 ready_out 反压
        for (i = 0; i < TOTAL_PIXELS; i = i + 1) begin
            @(negedge clk);
            while (!ready_out) begin
                en_in = 1'b0;
                @(negedge clk);
            end
            en_in     = 1'b1;
            rgb565_in = pixel_mem[i];
        end

        // 最后一像素后再保持 1 拍，然后拉低
        @(negedge clk);
        en_in     = 1'b0;
        rgb565_in = 16'd0;

        $display("=== All %0d pixels sent ===", TOTAL_PIXELS);

        // 等待 frame_done，带超时保护
        timeout_cnt = 0;
        while (!frame_done && timeout_cnt < 5000000) begin
            @(posedge clk);
            timeout_cnt = timeout_cnt + 1;
        end

        if (!frame_done) begin
            $display("ERROR: timeout waiting for frame_done");
        end else begin
            $display("=== frame_done received ===");
        end

        // 再等待几拍确保所有输出已捕获
        #(100 * CYCLE);

        $fclose(fout_zz);
        $fclose(fout_ent);

        $display("==============================================");
        $display("= JPEG Compress Top Simulation Complete");
        $display("= Input pixels      : %0d", TOTAL_PIXELS);
        $display("= Zig-Zag coeffs    : %0d (expected %0d)", out_cnt, TOTAL_COEFFS);
        $display("= Block done cnt    : %0d (expected %0d)", block_cnt, TOTAL_BLOCKS);
        $display("= Entropy symbols   : %0d", entropy_cnt);
        $display("= Entropy total bits: %0d", entropy_total_bits);
        $display("= Compression ratio : %0d bits / %0d pixels = %.3f bpp",
                 entropy_total_bits, TOTAL_PIXELS,
                 entropy_total_bits * 1.0 / TOTAL_PIXELS);
        if (out_cnt == TOTAL_COEFFS && block_cnt == TOTAL_BLOCKS)
            $display("= RESULT: PASS");
        else
            $display("= RESULT: FAIL");
        $display("==============================================");

        $finish;
    end

endmodule
