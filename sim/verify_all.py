#!/usr/bin/env python3
"""
============================================================================
JPEG Compress 仿真验证脚本 (仿真环境启动前 — Python 部分)
============================================================================
用途:
  1. 生成仿真输入文件 (若尚无)
  2. 运行 Python 参考模型生成期望输出
  3. 输出 ModelSim 仿真启动指令
  4. 仿真结束后对比 HW 输出与参考, 并解码为 PNG 比对

用法:
  python verify_all.py              # 完整流程 (先生成参考, 提示手动仿真, 再对比)
  python verify_all.py --ref-only   # 仅生成参考模型输出
  python verify_all.py --cmp-only   # 仅对比已有仿真结果
  python verify_all.py --full-auto  # 全自动 (如 vsim 在 PATH 中)
============================================================================
"""
import sys
import math
import subprocess
import struct
import zlib
from pathlib import Path

# ===== 路径配置（自动检测项目根目录） =====
PROJ_ROOT  = Path(__file__).parent.parent
SIM_DIR    = PROJ_ROOT / "sim"
OUT_DIR    = PROJ_ROOT / "out"
RTL_DIR    = PROJ_ROOT / "rtl"
Q_MODELSIM = PROJ_ROOT / "quartus/simulation/modelsim"

# 仿真输入
HEX_INPUT  = SIM_DIR / "image_320x320_rgb565.hex"
RAW_INPUT  = OUT_DIR / "02_rgb888.raw"

# 期望输出
ZZ_REF     = SIM_DIR / "zz_ref_all.txt"
ENT_REF    = SIM_DIR / "entropy_out_ref.txt"

# 硬件输出
ZZ_HW      = SIM_DIR / "zz_out_all.txt"
ENT_HW     = SIM_DIR / "entropy_out.txt"

# 解码图像输出
IMG_HW     = OUT_DIR / "decoded_hw_verify.png"
IMG_REF    = OUT_DIR / "decoded_ref_verify.png"
IMG_DIFF   = OUT_DIR / "decoded_hw_diff.png"

IMAGE_W = 320
IMAGE_H = 320
BLOCK   = 8


# ====================================================================
# 1. 参考模型 (与 ref_model.py 一致, 使用浮点 DCT + 标准量化)
# ====================================================================
def generate_reference():
    """生成参考 zigzag 系数和熵编码输出"""
    print("=" * 60)
    print("[1/4] 生成 Python 参考模型输出 ...")
    print("=" * 60)

    if not RAW_INPUT.exists():
        # 从 hex 转换
        print(f"  从 {HEX_INPUT} 读取像素...")
        if not HEX_INPUT.exists():
            print(f"  ERROR: 找不到 {HEX_INPUT}")
            print(f"  请运行: python sim/png_to_sim_input.py <your.png> out/02")
            return False
        # 直接从 02_rgb888.raw 读取 (如果存在)
        if not RAW_INPUT.exists():
            print(f"  ERROR: 找不到 {RAW_INPUT}, 需要原始 RGB 文件")
            return False

    raw = RAW_INPUT.read_bytes()
    pixels_y = []
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i+1], raw[i+2]
        r565, g565, b565 = r & 0xF8, g & 0xFC, b & 0xF8
        y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
        pixels_y.append(y)

    # DCT 矩阵
    def build_dct_matrix(N=8):
        M = [[0.0] * N for _ in range(N)]
        for k in range(N):
            alpha = math.sqrt(1.0 / N) if k == 0 else math.sqrt(2.0 / N)
            for n in range(N):
                M[k][n] = alpha * math.cos(math.pi / N * (n + 0.5) * k)
        return M

    DCT = build_dct_matrix(8)

    def mat_mul(A, B):
        N, M, P = len(A), len(B[0]), len(B)
        C = [[0.0] * M for _ in range(N)]
        for i in range(N):
            for j in range(M):
                C[i][j] = sum(A[i][k] * B[k][j] for k in range(P))
        return C

    def transpose(A):
        return [[A[j][i] for j in range(len(A))] for i in range(len(A[0]))]

    def dct2d(block):
        tmp = mat_mul(DCT, block)
        return mat_mul(tmp, transpose(DCT))

    # 量化表
    Q_LUM = [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99]
    ]

    ZZ_V = [
        0,  8,  1,  2,  9,  16, 24, 17,
        10, 3,  4,  11, 18, 25, 32, 40,
        33, 26, 19, 12, 5,  6,  13, 20,
        27, 34, 41, 48, 56, 49, 42, 35,
        28, 21, 14, 7,  15, 22, 29, 36,
        43, 50, 57, 58, 51, 44, 37, 30,
        23, 31, 38, 45, 52, 59, 60, 53,
        46, 39, 47, 54, 61, 62, 55, 63
    ]

    # Huffman 表
    DC_HUFF = {
        0x0: (0b00, 2), 0x1: (0b010, 3), 0x2: (0b011, 3),
        0x3: (0b100, 3), 0x4: (0b101, 3), 0x5: (0b110, 3),
        0x6: (0b1110, 4), 0x7: (0b11110, 5), 0x8: (0b111110, 6),
        0x9: (0b1111110, 7), 0xA: (0b11111110, 8), 0xB: (0b111111110, 9),
    }

    AC_HUFF = {
        0x00: (0b1010, 4), 0x01: (0b00, 2), 0x02: (0b01, 2),
        0x03: (0b100, 3), 0x04: (0b1011, 4), 0x05: (0b11010, 5),
        0x06: (0b1111000, 7), 0x07: (0b11111000, 8),
        0x08: (0b1111110110, 10), 0x09: (0b1111111110000010, 16),
        0x0A: (0b1111111110000011, 16),
        0x11: (0b1100, 4), 0x12: (0b11011, 5), 0x13: (0b1111001, 7),
        0x14: (0b111110110, 9), 0x15: (0b11111110110, 11),
        0x16: (0b1111111110000100, 16), 0x17: (0b1111111110000101, 16),
        0x18: (0b1111111110000110, 16), 0x19: (0b1111111110000111, 16),
        0x1A: (0b1111111110001000, 16),
        0x21: (0b11100, 5), 0x22: (0b11111001, 8), 0x23: (0b1111110111, 10),
        0x24: (0b111111110100, 12), 0x25: (0b1111111110001001, 16),
        0x26: (0b1111111110001010, 16), 0x27: (0b1111111110001011, 16),
        0x28: (0b1111111110001100, 16), 0x29: (0b1111111110001101, 16),
        0x2A: (0b1111111110001110, 16),
        0x31: (0b111010, 6), 0x32: (0b111110111, 9), 0x33: (0b111111110101, 12),
        0x34: (0b1111111110001111, 16), 0x35: (0b1111111110010000, 16),
        0x36: (0b1111111110010001, 16), 0x37: (0b1111111110010010, 16),
        0x38: (0b1111111110010011, 16), 0x39: (0b1111111110010100, 16),
        0x3A: (0b1111111110010101, 16),
        0x41: (0b111011, 6), 0x42: (0b1111111000, 10),
        0x43: (0b1111111110010110, 16), 0x44: (0b1111111110010111, 16),
        0x45: (0b1111111110011000, 16), 0x46: (0b1111111110011001, 16),
        0x47: (0b1111111110011010, 16), 0x48: (0b1111111110011011, 16),
        0x49: (0b1111111110011100, 16), 0x4A: (0b1111111110011101, 16),
        0x51: (0b1111010, 7), 0x52: (0b11111110111, 11),
        0x53: (0b1111111110011110, 16), 0x54: (0b1111111110011111, 16),
        0x55: (0b1111111110100000, 16), 0x56: (0b1111111110100001, 16),
        0x57: (0b1111111110100010, 16), 0x58: (0b1111111110100011, 16),
        0x59: (0b1111111110100100, 16), 0x5A: (0b1111111110100101, 16),
        0x61: (0b1111011, 7), 0x62: (0b111111110110, 12),
        0x63: (0b1111111110100110, 16), 0x64: (0b1111111110100111, 16),
        0x65: (0b1111111110101000, 16), 0x66: (0b1111111110101001, 16),
        0x67: (0b1111111110101010, 16), 0x68: (0b1111111110101011, 16),
        0x69: (0b1111111110101100, 16), 0x6A: (0b1111111110101101, 16),
        0x71: (0b11111010, 8), 0x72: (0b111111110111, 12),
        0x73: (0b1111111110101110, 16), 0x74: (0b1111111110101111, 16),
        0x75: (0b1111111110110000, 16), 0x76: (0b1111111110110001, 16),
        0x77: (0b1111111110110010, 16), 0x78: (0b1111111110110011, 16),
        0x79: (0b1111111110110100, 16), 0x7A: (0b1111111110110101, 16),
        0x81: (0b111111000, 9), 0x82: (0b111111111000000, 15),
        0x83: (0b1111111110110110, 16), 0x84: (0b1111111110110111, 16),
        0x85: (0b1111111110111000, 16), 0x86: (0b1111111110111001, 16),
        0x87: (0b1111111110111010, 16), 0x88: (0b1111111110111011, 16),
        0x89: (0b1111111110111100, 16), 0x8A: (0b1111111110111101, 16),
        0x91: (0b111111001, 9), 0x92: (0b1111111110111110, 16),
        0x93: (0b1111111110111111, 16), 0x94: (0b1111111111000000, 16),
        0x95: (0b1111111111000001, 16), 0x96: (0b1111111111000010, 16),
        0x97: (0b1111111111000011, 16), 0x98: (0b1111111111000100, 16),
        0x99: (0b1111111111000101, 16), 0x9A: (0b1111111111000110, 16),
        0xA1: (0b111111010, 9), 0xA2: (0b1111111111000111, 16),
        0xA3: (0b1111111111001000, 16), 0xA4: (0b1111111111001001, 16),
        0xA5: (0b1111111111001010, 16), 0xA6: (0b1111111111001011, 16),
        0xA7: (0b1111111111001100, 16), 0xA8: (0b1111111111001101, 16),
        0xA9: (0b1111111111001110, 16), 0xAA: (0b1111111111001111, 16),
        0xB1: (0b1111111001, 10), 0xB2: (0b1111111111010000, 16),
        0xB3: (0b1111111111010001, 16), 0xB4: (0b1111111111010010, 16),
        0xB5: (0b1111111111010011, 16), 0xB6: (0b1111111111010100, 16),
        0xB7: (0b1111111111010101, 16), 0xB8: (0b1111111111010110, 16),
        0xB9: (0b1111111111010111, 16), 0xBA: (0b1111111111011000, 16),
        0xC1: (0b1111111010, 10), 0xC2: (0b1111111111011001, 16),
        0xC3: (0b1111111111011010, 16), 0xC4: (0b1111111111011011, 16),
        0xC5: (0b1111111111011100, 16), 0xC6: (0b1111111111011101, 16),
        0xC7: (0b1111111111011110, 16), 0xC8: (0b1111111111011111, 16),
        0xC9: (0b1111111111100000, 16), 0xCA: (0b1111111111100001, 16),
        0xD1: (0b11111111000, 11), 0xD2: (0b1111111111100010, 16),
        0xD3: (0b1111111111100011, 16), 0xD4: (0b1111111111100100, 16),
        0xD5: (0b1111111111100101, 16), 0xD6: (0b1111111111100110, 16),
        0xD7: (0b1111111111100111, 16), 0xD8: (0b1111111111101000, 16),
        0xD9: (0b1111111111101001, 16), 0xDA: (0b1111111111101010, 16),
        0xE1: (0b1111111111101011, 16), 0xE2: (0b1111111111101100, 16),
        0xE3: (0b1111111111101101, 16), 0xE4: (0b1111111111101110, 16),
        0xE5: (0b1111111111101111, 16), 0xE6: (0b1111111111110000, 16),
        0xE7: (0b1111111111110001, 16), 0xE8: (0b1111111111110010, 16),
        0xE9: (0b1111111111110011, 16), 0xEA: (0b1111111111110100, 16),
        0xF0: (0b11111111001, 11),
        0xF1: (0b1111111111110101, 16), 0xF2: (0b1111111111110110, 16),
        0xF3: (0b1111111111110111, 16), 0xF4: (0b1111111111111000, 16),
        0xF5: (0b1111111111111001, 16), 0xF6: (0b1111111111111010, 16),
        0xF7: (0b1111111111111011, 16), 0xF8: (0b1111111111111100, 16),
        0xF9: (0b1111111111111101, 16), 0xFA: (0b1111111111111110, 16),
    }

    def category(val):
        if val == 0: return 0
        return abs(val).bit_length()

    def encode_extra(val, cat):
        if cat == 0: return 0
        if val >= 0: return val
        return (val - 1) & ((1 << cat) - 1)

    # 处理所有块
    n_blocks = (IMAGE_W // BLOCK) * (IMAGE_H // BLOCK)
    zz_lines, ent_lines = [], []
    prev_dc = 0
    entropy_total_bits = 0

    for bi in range(n_blocks):
        by = (bi // (IMAGE_W // BLOCK)) * BLOCK
        bx = (bi % (IMAGE_W // BLOCK)) * BLOCK

        # 8x8 块
        block = [[pixels_y[(by + i) * IMAGE_W + (bx + j)] - 128.0
                  for j in range(BLOCK)] for i in range(BLOCK)]
        coeffs = dct2d(block)

        # 量化
        q = [[int(round(coeffs[i][j] / Q_LUM[i][j])) for j in range(BLOCK)] for i in range(BLOCK)]

        # Zig-zag
        zz = [0] * 64
        for pos in range(64):
            rm_idx = ZZ_V[pos]
            row, col = rm_idx // 8, rm_idx % 8
            zz[pos] = q[row][col]

        for pos, val in enumerate(zz):
            zz_lines.append(f"{pos} {val}\n")

        # 熵编码
        dc_diff = zz[0] - prev_dc
        cat = category(dc_diff)
        extra = encode_extra(dc_diff, cat)
        code, length = DC_HUFF.get(cat, (0, 0))
        ent_lines.append(f"1 0 {code} {length} {extra} {cat}\n")
        entropy_total_bits += length + cat

        run = 0
        for i in range(1, 64):
            val = zz[i]
            if val == 0:
                run += 1
                if run == 16:
                    code, length = AC_HUFF[0xF0]
                    ent_lines.append(f"0 0 {code} {length} 0 0\n")
                    entropy_total_bits += length
                    run = 0
            else:
                cat = category(val)
                extra = encode_extra(val, cat)
                sym = (run << 4) | cat
                code, length = AC_HUFF.get(sym, (0, 0))
                ent_lines.append(f"0 0 {code} {length} {extra} {cat}\n")
                entropy_total_bits += length + cat
                run = 0

        code, length = AC_HUFF[0x00]  # EOB
        ent_lines.append(f"0 1 {code} {length} 0 0\n")
        entropy_total_bits += length
        prev_dc = zz[0]

    ZZ_REF.write_text("".join(zz_lines), encoding="utf-8")
    ENT_REF.write_text("".join(ent_lines), encoding="utf-8")

    print(f"  参考 Zig-Zag 系数: {ZZ_REF} ({len(zz_lines)} 行)")
    print(f"  参考熵编码符号:   {ENT_REF} ({len(ent_lines)} 行)")
    print(f"  压缩率: {entropy_total_bits / (IMAGE_W * IMAGE_H):.3f} bpp")
    return True


# ====================================================================
# 2. 对比仿真结果
# ====================================================================
def compare_results():
    """对比 HW 仿真输出与参考模型"""
    print()
    print("=" * 60)
    print("[2/4] 对比 HW 仿真输出 vs 参考模型 ...")
    print("=" * 60)

    if not ZZ_HW.exists():
        print(f"  ERROR: 找不到 {ZZ_HW}")
        print(f"  请先在 ModelSim 中运行仿真: do sim/run_verify.do")
        return False

    if not ZZ_REF.exists():
        print(f"  WARNING: 参考文件不存在, 先生成...")
        generate_reference()

    # 加载数据
    def load_zz(path):
        data = []
        with open(path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    data.append(int(parts[1]))
        return data

    hw = load_zz(ZZ_HW)
    ref = load_zz(ZZ_REF)

    if len(hw) != len(ref):
        print(f"  ERROR: 长度不匹配: HW={len(hw)}, Ref={len(ref)}")
        return False

    total = len(hw)
    exact_match = 0
    error_1 = 0      # |diff| = 1
    error_2 = 0      # |diff| = 2
    error_big = 0    # |diff| > 2
    max_err = 0

    # 每 block 统计
    n_blocks = total // 64
    block_errs = [0] * n_blocks

    for i in range(total):
        diff = abs(hw[i] - ref[i])
        if diff == 0:
            exact_match += 1
        elif diff == 1:
            error_1 += 1
        elif diff == 2:
            error_2 += 1
        else:
            error_big += 1
        if diff > max_err:
            max_err = diff

        bi = i // 64
        if diff > 0:
            block_errs[bi] += 1

    perfect_blocks = sum(1 for e in block_errs if e == 0)

    print(f"\n  ---- Zig-Zag 系数对比 ----")
    print(f"  总系数:          {total}")
    print(f"  完全匹配:        {exact_match} ({100*exact_match/total:.1f}%)")
    print(f"  误差=1:          {error_1} ({100*error_1/total:.2f}%)")
    print(f"  误差=2:          {error_2} ({100*error_2/total:.2f}%)")
    print(f"  大误差 (>2):     {error_big} ({100*error_big/total:.2f}%)")
    print(f"  最大误差:        {max_err}")
    print(f"  完美 block:      {perfect_blocks}/{n_blocks} ({100*perfect_blocks/n_blocks:.1f}%)")
    print(f"  平均错误/block:  {sum(block_errs)/n_blocks:.1f}")

    # 评判
    if exact_match == total:
        grade = "A+ (完全一致!)"
    elif error_big == 0:
        grade = "A (仅 ±1~2 定点舍入误差, 正常)"
    elif error_big < total * 0.01:
        grade = "B (少量定点误差)"
    elif error_big < total * 0.10:
        grade = "C (存在显著偏差, 需检查)"
    else:
        grade = "F (严重失真, 存在 bug!)"

    print(f"\n  综合评级: {grade}")

    # 如果大误差很少, 打印前几个
    if 0 < error_big <= 20:
        print(f"\n  大误差详情 (前 10 个):")
        count = 0
        for i in range(total):
            diff = abs(hw[i] - ref[i])
            if diff > 2:
                bi = i // 64
                zi = i % 64
                print(f"    Block {bi}, zz[{zi}]: HW={hw[i]}, Ref={ref[i]}, diff={diff}")
                count += 1
                if count >= 10:
                    break

    return True


# ====================================================================
# 3. 解码为 PNG 对比
# ====================================================================
def decode_and_compare():
    """将 zigzag 系数解码为 PNG, 计算 PSNR"""
    print()
    print("=" * 60)
    print("[3/4] 解码为 PNG 并计算 PSNR ...")
    print("=" * 60)

    try:
        from PIL import Image
        HAS_PIL = True
    except ImportError:
        HAS_PIL = False

    raw = RAW_INPUT.read_bytes()
    pixels_y_orig = []
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i+1], raw[i+2]
        r565, g565, b565 = r & 0xF8, g & 0xFC, b & 0xF8
        y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
        pixels_y_orig.append(y)

    # IDCT
    def build_dct_matrix(N=8):
        M = [[0.0] * N for _ in range(N)]
        for k in range(N):
            alpha = math.sqrt(1.0 / N) if k == 0 else math.sqrt(2.0 / N)
            for n in range(N):
                M[k][n] = alpha * math.cos(math.pi / N * (n + 0.5) * k)
        return M

    DCT = build_dct_matrix(8)

    def mat_mul(A, B):
        N, M, P = len(A), len(B[0]), len(B)
        C = [[0.0] * M for _ in range(N)]
        for i in range(N):
            for j in range(M):
                C[i][j] = sum(A[i][k] * B[k][j] for k in range(P))
        return C

    def transpose(A):
        return [[A[j][i] for j in range(len(A))] for i in range(len(A[0]))]

    def idct2d(coeffs):
        tmp = mat_mul(transpose(DCT), coeffs)
        return mat_mul(tmp, DCT)

    Q_LUM = [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99]
    ]

    ZZ_V = [
        0,  8,  1,  2,  9,  16, 24, 17,
        10, 3,  4,  11, 18, 25, 32, 40,
        33, 26, 19, 12, 5,  6,  13, 20,
        27, 34, 41, 48, 56, 49, 42, 35,
        28, 21, 14, 7,  15, 22, 29, 36,
        43, 50, 57, 58, 51, 44, 37, 30,
        23, 31, 38, 45, 52, 59, 60, 53,
        46, 39, 47, 54, 61, 62, 55, 63
    ]

    def load_zz(path):
        data = []
        with open(path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    data.append(int(parts[1]))
        return data

    def decode_zz_to_image(zz_data):
        img = [[0] * IMAGE_W for _ in range(IMAGE_H)]
        n_blocks = (IMAGE_W // BLOCK) * (IMAGE_H // BLOCK)

        for bi in range(n_blocks):
            zz = zz_data[bi*64:(bi+1)*64]
            # Inverse zigzag
            block = [[0.0] * 8 for _ in range(8)]
            for pos in range(64):
                rm_idx = ZZ_V[pos]
                r, c = rm_idx // 8, rm_idx % 8
                block[r][c] = float(zz[pos])

            # Dequantize
            block = [[block[i][j] * Q_LUM[i][j] for j in range(8)] for i in range(8)]

            # IDCT
            block = idct2d(block)

            by = (bi // (IMAGE_W // BLOCK)) * BLOCK
            bx = (bi % (IMAGE_W // BLOCK)) * BLOCK
            for i in range(8):
                for j in range(8):
                    val = round(block[i][j] + 128.0)
                    img[by + i][bx + j] = max(0, min(255, val))

        return img

    def save_png(img, path):
        flat = [p for row in img for p in row]
        if HAS_PIL:
            im = Image.new("L", (IMAGE_W, IMAGE_H))
            im.putdata(flat)
            im.save(str(path))
        else:
            _write_png_gray(flat, IMAGE_W, IMAGE_H, str(path))

    def save_diff_png(diff_flat, path):
        if HAS_PIL:
            diff_img = Image.new("L", (IMAGE_W, IMAGE_H))
            diff_img.putdata(diff_flat)
            diff_img.save(str(path))
        else:
            _write_png_gray(diff_flat, IMAGE_W, IMAGE_H, str(path))

    # 解码 HW
    if ZZ_HW.exists():
        hw_data = load_zz(ZZ_HW)
        if len(hw_data) == 102400:
            img_hw = decode_zz_to_image(hw_data)
            save_png(img_hw, IMG_HW)
            print(f"  HW 解码图像: {IMG_HW}")
        else:
            print(f"  WARNING: HW zz 数据长度异常 ({len(hw_data)}), 跳过")
            img_hw = None
    else:
        print(f"  WARNING: 找不到 {ZZ_HW}")
        img_hw = None

    # 解码 Ref
    ref_data = load_zz(ZZ_REF) if ZZ_REF.exists() else None
    if ref_data and len(ref_data) == 102400:
        img_ref = decode_zz_to_image(ref_data)
        save_png(img_ref, IMG_REF)
        print(f"  Ref 解码图像: {IMG_REF}")
    else:
        img_ref = None

    # PSNR
    if img_hw and img_ref:
        hw_flat = [p for row in img_hw for p in row]
        ref_flat = [p for row in img_ref for p in row]
        mse = sum((a - b) ** 2 for a, b in zip(hw_flat, ref_flat)) / len(hw_flat)
        if mse == 0:
            psnr = float('inf')
        else:
            psnr = 10 * math.log10(255.0 * 255.0 / mse)

        # 差异图
        diff = [abs(a - b) for a, b in zip(hw_flat, ref_flat)]
        save_diff_png(diff, IMG_DIFF)

        print(f"\n  ---- 图像质量 ----")
        print(f"  MSE:  {mse:.2f}")
        print(f"  PSNR: {psnr:.2f} dB")
        print(f"  差异图: {IMG_DIFF}")
        if psnr > 50:
            print(f"  评价: 优秀 (视觉无损)")
        elif psnr > 40:
            print(f"  评价: 良好 (几乎无感知差异)")
        elif psnr > 30:
            print(f"  评价: 一般 (可见轻微失真)")
        else:
            print(f"  评价: 差 (明显失真, 存在bug)")

    return True


def _png_chunk(chunk_type, data):
    """Helper: build a PNG chunk with CRC"""
    chunk = struct.pack(">I", len(data)) + chunk_type + data
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return chunk + struct.pack(">I", crc)


def _write_png_gray(pixels, width, height, path):
    """Write an 8-bit grayscale PNG without Pillow."""
    # PNG signature
    sig = b'\x89PNG\r\n\x1a\n'

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    ihdr = _png_chunk(b'IHDR', ihdr_data)

    # Raw image data: each row starts with filter byte 0
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        row_start = y * width
        raw.extend(pixels[row_start:row_start + width])

    # IDAT (compressed)
    compressed = zlib.compress(bytes(raw), 9)
    idat = _png_chunk(b'IDAT', compressed)

    # IEND
    iend = _png_chunk(b'IEND', b'')

    with open(path, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


# ====================================================================
# 4. 生成 ModelSim 仿真脚本
# ====================================================================
def generate_modelsim_script():
    """生成 run_verify.do 供 ModelSim 执行"""
    print()
    print("=" * 60)
    print("[4/4] 生成 ModelSim 仿真脚本 ...")
    print("=" * 60)

    do_content = f"""\
# ===========================================================================
# JPEG Compress 验证仿真脚本 (自动生成)
# 用法: 在 ModelSim/Questa 中执行  do {SIM_DIR.as_posix()}/run_verify.do
# ===========================================================================
transcript on

# 清理并建库
if {{[file exists rtl_work]}} {{
    vdel -lib rtl_work -all
}}
vlib rtl_work
vmap work rtl_work

# ---- 编译 RTL (含修复后版本) ----
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/Y.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/image.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/ram_dp.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/block_fifo.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/arm.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/transpose_ram.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/DCT1D.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/dct_2d.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/quantizer.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/zigzag_scan.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/jpeg_entropy_encoder.v
vlog -vlog01compat -work work +incdir+{RTL_DIR.as_posix()} {RTL_DIR.as_posix()}/jpeg_compress_top.v

# ---- 编译 Testbench ----
vlog -vlog01compat -work work +incdir+{SIM_DIR.as_posix()} {SIM_DIR.as_posix()}/tb_jpeg_compress.v

# ---- 启动仿真 ----
vsim -t 1ps -L altera_ver -L lpm_ver -L sgate_ver -L altera_mf_ver -L altera_lnsim_ver -L cycloneive_ver -L rtl_work -L work -voptargs="+acc" tb_jpeg_compress

# ---- 添加关键波形 (调试用) ----
add wave -group "top" /tb_jpeg_compress/clk
add wave -group "top" /tb_jpeg_compress/rst_n
add wave -group "top" /tb_jpeg_compress/en_in
add wave -group "top" /tb_jpeg_compress/ready_out
add wave -group "top" /tb_jpeg_compress/out_en
add wave -group "top" -radix decimal /tb_jpeg_compress/out_data
add wave -group "top" /tb_jpeg_compress/out_idx
add wave -group "top" /tb_jpeg_compress/block_done
add wave -group "top" /tb_jpeg_compress/frame_done

# ---- DCT 内部信号 (调试 DCT 问题) ----
add wave -group "dct_2d" /tb_jpeg_compress/dut/u_dct_2d/state
add wave -group "dct_2d" /tb_jpeg_compress/dut/u_dct_2d/row
add wave -group "dct_2d" /tb_jpeg_compress/dut/u_dct_2d/col
add wave -group "dct_2d" /tb_jpeg_compress/dut/u_dct_2d/dct_en_in
add wave -group "dct_2d" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/dct_in
add wave -group "dct_2d" /tb_jpeg_compress/dut/u_dct_2d/dct_en_out
add wave -group "dct_2d" -radix decimal /tb_jpeg_compress/dut/u_dct_2d/dct_out

# ---- 运行 ----
run -all

# ---- 结果说明 ----
echo "============================================"
echo "仿真完成!"
echo "输出文件:"
echo "  zz_out_all.txt   - Zig-Zag 系数"
echo "  entropy_out.txt  - 熵编码符号"
echo ""
echo "接下来运行: python sim/verify_all.py --cmp-only"
echo "============================================"
"""

    do_path = SIM_DIR / "run_verify.do"
    do_path.write_text(do_content, encoding="utf-8")
    print(f"  ModelSim 脚本: {do_path}")
    print(f"")
    print(f"  在 ModelSim 中执行:")
    print(f"    do {do_path.as_posix()}")
    return do_path


# ====================================================================
# Main
# ====================================================================
def main():
    print("=" * 70)
    print("  JPEG Compress 硬件仿真验证流程")
    print("=" * 70)
    print(f"  项目根目录: {PROJ_ROOT}")
    print()

    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "--ref-only":
        generate_reference()
        return

    if mode == "--cmp-only":
        compare_results()
        decode_and_compare()
        return

    if mode == "--gen-do":
        generate_modelsim_script()
        return

    # 完整流程
    # Step 1: 生成参考
    if not ZZ_REF.exists():
        generate_reference()
    else:
        print("[1/4] 参考文件已存在, 跳过生成")
        print(f"  若要重新生成: del {ZZ_REF}")

    # Step 2: 生成 ModelSim 脚本
    do_path = generate_modelsim_script()

    # Step 3: 提示运行仿真
    print()
    print("=" * 60)
    print(">>> 下一步: 在 ModelSim 中运行仿真 <<<")
    print("=" * 60)
    print(f"  1. 打开 ModelSim / Questa")
    print(f"  2. cd {SIM_DIR}")
    print(f"  3. do run_verify.do")
    print(f"  4. 仿真结束后关闭 ModelSim")
    print(f"  5. 回到此终端运行:")
    print(f"       python {Path(__file__).as_posix()} --cmp-only")
    print()

    # 如果 vsim 在 PATH 中, 尝试自动运行
    if mode == "--full-auto":
        print(">>> 尝试自动运行 ModelSim...")
        result = subprocess.run(
            ["vsim", "-c", "-do", f"do {do_path.as_posix()}; quit"],
            cwd=str(SIM_DIR),
            capture_output=True, text=True, timeout=600
        )
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        if result.returncode != 0:
            print(f"ModelSim stderr:\n{result.stderr[-1000:]}")
            return

        # Step 4: 对比
        compare_results()
        decode_and_compare()


if __name__ == "__main__":
    main()
