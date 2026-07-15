///////////////////////////////////////////////////////////////////////////////
// Module:      Y
// Function:    RGB 565 to luminance Y (BT.601), 2-stage multiply-add pipeline
// Pipeline:    2-stage (stage 1: multiply, stage 2: add & shift)
///////////////////////////////////////////////////////////////////////////////

`default_nettype none

module Y (
    input  wire        clk,      // system clock
    input  wire        rst_n,    // async reset, active low
    input  wire        en_in,    // input data enable
    input  wire [15:0] in_data,  // RGB 565 pixel data
    output reg         en_out,   // output valid flag
    output reg  [7:0]  out_y     // luminance Y output
);

    //==========================================================================
    // Parameter definitions (BT.601 luminance coefficients, scaled x256)
    //==========================================================================
    parameter R_COEFF = 77;   // 0.299  * 256 = 76.544 ~ 77
    parameter G_COEFF = 150;  // 0.587  * 256 = 150.272 ~ 150
    parameter B_COEFF = 29;   // 0.114  * 256 = 29.184 ~ 29

    //==========================================================================
    // Internal signal declarations
    //==========================================================================
    reg [15:0] mul_r_reg;     // stage 1 product: R_expanded * R_COEFF
    reg [15:0] mul_g_reg;     // stage 1 product: G_expanded * G_COEFF
    reg [15:0] mul_b_reg;     // stage 1 product: B_expanded * B_COEFF
    reg        en_pipe_reg;   // pipeline enable (1 cycle delayed en_in)

    //==========================================================================
    // Stage 1: expand RGB and multiply with coefficients
    //==========================================================================
    // R = in_data[15:11] (5-bit),  expand to 8-bit: {R, 3'b0}
    // G = in_data[10:5]  (6-bit),  expand to 8-bit: {G, 2'b0}
    // B = in_data[4:0]   (5-bit),  expand to 8-bit: {B, 3'b0}
    //==========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mul_r_reg   <= 16'd0;
            mul_g_reg   <= 16'd0;
            mul_b_reg   <= 16'd0;
            en_pipe_reg <= 1'b0;
        end else if (en_in) begin
            mul_r_reg   <= {in_data[15:11], 3'b0} * R_COEFF;
            mul_g_reg   <= {in_data[10:5],  2'b0} * G_COEFF;
            mul_b_reg   <= {in_data[4:0],   3'b0} * B_COEFF;
            en_pipe_reg <= 1'b1;
        end else begin
            mul_r_reg   <= mul_r_reg;
            mul_g_reg   <= mul_g_reg;
            mul_b_reg   <= mul_b_reg;
            en_pipe_reg <= 1'b0;
        end
    end

    //==========================================================================
    // Stage 2: sum three products, right-shift by 8, output luminance Y
    //==========================================================================
    // Y = (R_8 * 77 + G_8 * 150 + B_8 * 29) >> 8
    //==========================================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_y <= 8'd0;
            en_out <= 1'b0;
        end else if (en_pipe_reg) begin
            out_y <= (mul_r_reg + mul_g_reg + mul_b_reg) >> 8;
            en_out <= 1'b1;
        end else begin
            out_y <= out_y;
            en_out <= 1'b0;
        end
    end

endmodule
