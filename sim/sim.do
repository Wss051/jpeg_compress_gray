# ===========================================================================
# ModelSim 仿真脚本 — JPEG Compress 完整验证 (修复后版本)
# 用法: 在 ModelSim/Questa 中执行  do sim/sim.do
#       然后运行  python sim/verify_all.py --cmp-only  进行对比
# ===========================================================================
transcript on

# 切换到 sim 目录，确保 $fopen 相对路径正确
cd [file dirname [info script]]

# 清理并建库
if {[file exists rtl_work]} {
    vdel -lib rtl_work -all
}
vlib rtl_work
vmap work rtl_work

# ---- 编译 RTL (含全部修复) ----
# 注意: DCT1D.v 已修改为 (y+512)>>>10 舍入
#       dct_2d.v 已修改为 DIN_W=12, 列 DCT 全精度
#       quantizer.v 已修改 MIN_VAL=-2047
#       jpeg_entropy_encoder.v 已修复 category 查表越界
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/Y.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/image.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/ram_dp.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/block_fifo.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/arm.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/transpose_ram.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/DCT1D.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/dct_2d.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/quantizer.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/zigzag_scan.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/jpeg_entropy_encoder.v
vlog -vlog01compat -work work +incdir+../../rtl ../../rtl/jpeg_compress_top.v

# ---- 编译 Testbench ----
vlog -vlog01compat -work work +incdir+../../rtl ../../sim/tb_jpeg_compress.v

# ---- 启动仿真 (使用绝对路径确保 Quartus 仿真库可访问) ----
vsim -t 1ps -L altera_ver -L lpm_ver -L sgate_ver -L altera_mf_ver -L altera_lnsim_ver -L cycloneive_ver -L rtl_work -L work -voptargs="+acc" tb_jpeg_compress

# ===========================================================================
# 波形窗口: 顶层接口
# ===========================================================================
add wave -group "TOP" /tb_jpeg_compress/clk
add wave -group "TOP" /tb_jpeg_compress/rst_n
add wave -group "TOP" /tb_jpeg_compress/en_in
add wave -group "TOP" -radix hex /tb_jpeg_compress/rgb565_in
add wave -group "TOP" /tb_jpeg_compress/ready_out
add wave -group "TOP" /tb_jpeg_compress/out_en
add wave -group "TOP" -radix decimal /tb_jpeg_compress/out_data
add wave -group "TOP" /tb_jpeg_compress/out_idx
add wave -group "TOP" /tb_jpeg_compress/block_done
add wave -group "TOP" /tb_jpeg_compress/frame_done

# ===========================================================================
# DCT1D 内部信号 (调试蝶形运算)
# ===========================================================================
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/clk
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/en_in
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/in_data
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/en_out
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/out_data
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/state
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/sample_idx
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/out_idx
add wave -group "DCT1D" /tb_jpeg_compress/dut/u_dct_2d/u_dct/result_cnt
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x0
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x1
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x2
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x3
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x4
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x5
add wave -group "DCT1D" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/x6

# DCT1D 蝶形中间结果
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b0
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b1
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b2
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b3
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b4
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b5
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b6
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/b7
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/c0
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/c1
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/c2
add wave -group "DCT1D_butterfly" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/c3

# DCT1D 最终输出 (舍入后)
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y0_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y1_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y2_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y3_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y4_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y5_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y6_r
add wave -group "DCT1D_out" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/u_dct/y7_r

# ===========================================================================
# dct_2d 状态机
# ===========================================================================
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/state
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/row
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/col
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/feed_cnt
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/drain_cnt
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/dct_en_in
add wave -group "dct2d_FSM" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/dct_in
add wave -group "dct2d_FSM" /tb_jpeg_compress/dut/u_dct_2d/dct_en_out
add wave -group "dct2d_FSM" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/dct_out

# ===========================================================================
# 量化器 和 Zigzag
# ===========================================================================
add wave -group "QUANT" /tb_jpeg_compress/dut/u_quantizer/dct_en
add wave -group "QUANT" -radix decimal /tb_jpeg_compress/dut/u_quantizer/dct_data
add wave -group "QUANT" /tb_jpeg_compress/dut/u_quantizer/dct_idx
add wave -group "QUANT" /tb_jpeg_compress/dut/u_quantizer/q_en
add wave -group "QUANT" -radix decimal /tb_jpeg_compress/dut/u_quantizer/q_data
add wave -group "QUANT" /tb_jpeg_compress/dut/u_quantizer/q_idx

add wave -group "ZIGZAG" /tb_jpeg_compress/dut/u_zigzag/din_en
add wave -group "ZIGZAG" -radix decimal /tb_jpeg_compress/dut/u_zigzag/din_data
add wave -group "ZIGZAG" /tb_jpeg_compress/dut/u_zigzag/din_idx
add wave -group "ZIGZAG" /tb_jpeg_compress/dut/u_zigzag/dout_en
add wave -group "ZIGZAG" -radix decimal /tb_jpeg_compress/dut/u_zigzag/dout_data
add wave -group "ZIGZAG" /tb_jpeg_compress/dut/u_zigzag/dout_idx
add wave -group "ZIGZAG" /tb_jpeg_compress/dut/u_zigzag/state
add wave -group "ZIGZAG" /tb_jpeg_compress/dut/u_zigzag/cnt

# ===========================================================================
# 日志输出
# ===========================================================================
echo "============================================"
echo "波形窗口已配置完毕。"
echo "运行 run -all 开始仿真。"
echo "仿真结束后运行: python sim/verify_all.py --cmp-only"
echo "============================================"

# 自动运行到结束
run -all
