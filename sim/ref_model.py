#!/usr/bin/env python3
"""
JPEG 灰度压缩参考模型 (Python, 无第三方依赖)
用于与 Verilog 仿真输出 zz_out_all.txt 对比。

流程:
    320×320 RGB888 -> Y -> 8×8 分块 -> 定点 DCT2D -> 量化 -> Zig-Zag

注意: 本模型使用与 Verilog 相同的定点 AAN DCT 算法，
      因此与硬件输出应高度一致。
"""

import math
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "out"
DST_DIR = Path(__file__).parent
SRC_NAME = "02_rgb888.raw"
DST_NAME = "zz_ref_all.txt"

IMAGE_W = 320
IMAGE_H = 320
BLOCK = 8

# ============================================================================
# 硬件 AAN 系数 (×1024, 与 DCT1D.v 一致)
# ============================================================================
A0, A1, A2, A3, A4, A5, A6 = 362, 502, 473, 426, 284, 196, 100


def dct1d_hw(inputs):
    """Verilog DCT1D.v AAN 蝶形算法复刻 (DIN_W=10, DOUT_W=12)"""
    x0, x1, x2, x3, x4, x5, x6, x7 = [int(v) for v in inputs]

    # Stage 1
    b0, b1 = x0 + x7, x1 + x6
    b2, b3 = x2 + x5, x3 + x4
    b4, b5 = x3 - x4, x2 - x5
    b6, b7 = x1 - x6, x0 - x7

    # Stage 2
    c0, c1 = b0 + b3, b1 + b2
    c2, c3 = b0 - b3, b1 - b2
    s_even_add = c0 + c1
    s_even_sub = c0 - c1

    # Stage 3
    y = [0] * 8
    y[0] = s_even_add * A0
    y[4] = s_even_sub * A0
    y[2] = c2 * A2 + c3 * A5
    y[6] = c2 * A5 - c3 * A2
    y[1] = b7 * A1 + b6 * A3 + b5 * A4 + b4 * A6
    y[3] = b7 * A3 - b6 * A6 - b5 * A1 - b4 * A4
    y[5] = b7 * A4 - b6 * A1 + b5 * A6 + b4 * A3
    y[7] = b7 * A6 - b6 * A4 + b5 * A3 - b4 * A1

    # /1024 向零截断 (与 Verilog 有符号除法一致)
    def div1024(v):
        return int(v / 1024)

    def clamp12(v):
        return max(-2048, min(2047, v))

    return [clamp12(div1024(y[i])) for i in range(8)]


def dct2d_hw(block):
    """
    block: 8x8 row-major, signed 8-bit (level-shifted pixels)
    Returns: 8x8 row-major, signed 12-bit DCT coefficients
    """
    # 行 DCT: 8-bit 有符号 -> DCT1D
    row_out = []
    for r in range(8):
        row_out.append(dct1d_hw(block[r]))

    # 列 DCT: 12-bit -> 取低 10-bit -> DCT1D
    col_in = [[0] * 8 for _ in range(8)]
    for c in range(8):
        for r in range(8):
            v12 = row_out[r][c]
            v10 = v12 & 0x3FF
            if v10 & 0x200:
                v10 = v10 - 0x400
            col_in[r][c] = v10

    result = [[0] * 8 for _ in range(8)]
    for c in range(8):
        col_vec = [col_in[r][c] for r in range(8)]
        col_res = dct1d_hw(col_vec)
        for r in range(8):
            result[r][c] = col_res[r]

    return result


def rgb888_to_y(r: int, g: int, b: int) -> int:
    """BT.601 Y，与 Verilog Y.v 的 RGB565 扩展路径一致"""
    r565 = r & 0xF8
    g565 = g & 0xFC
    b565 = b & 0xF8
    y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
    return 0 if y < 0 else (255 if y > 255 else y)


def load_rgb888_crop():
    src_path = SRC_DIR / SRC_NAME
    raw = src_path.read_bytes()
    expected = IMAGE_W * IMAGE_H * 3
    if len(raw) != expected:
        raise ValueError(f"expected {expected} bytes, got {len(raw)}")
    img = []
    idx = 0
    for y in range(IMAGE_H):
        row = []
        for x in range(IMAGE_W):
            r = raw[(y * IMAGE_W + x) * 3]
            g = raw[(y * IMAGE_W + x) * 3 + 1]
            b = raw[(y * IMAGE_W + x) * 3 + 2]
            row.append(rgb888_to_y(r, g, b))
        img.append(row)
    return img


# 标准 JPEG 亮度量化表 (row-major)
Q_LUMINANCE = [
    [16, 11, 10, 16, 24, 40, 51, 61],
    [12, 12, 14, 19, 26, 58, 60, 55],
    [14, 13, 16, 24, 40, 57, 69, 56],
    [14, 17, 22, 29, 51, 87, 80, 62],
    [18, 22, 37, 56, 68, 109, 103, 77],
    [24, 35, 55, 64, 81, 104, 113, 92],
    [49, 64, 78, 87, 103, 121, 120, 101],
    [72, 92, 95, 98, 112, 100, 103, 99]
]

# 竖直优先 Zig-Zag 地址映射 (row-major 索引 -> Zig-Zag 位置)
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


# 标准 JPEG 亮度量化缩放表 (S = round(2^15 / Q))
Q_SCALE = [[int(round((1 << 15) / Q_LUMINANCE[r][c])) for c in range(8)] for r in range(8)]


def quantize_hw(coeffs):
    """与 Verilog quantizer.v 一致的定点量化"""
    result = [[0] * 8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            prod = coeffs[r][c] * Q_SCALE[r][c]
            prod_round = prod + (1 << 14)
            shifted = prod_round >> 15
            result[r][c] = max(-2048, min(2047, shifted))
    return result


# ============================================================================
# JPEG 熵编码参考函数
# ============================================================================

def category(val: int) -> int:
    """计算 category = bit_length(abs(val))，0 返回 0"""
    if val == 0:
        return 0
    return (abs(val)).bit_length()


def encode_extra(val: int, cat: int) -> int:
    """JPEG VLI 附加位编码，返回无符号整数（与 Verilog 12-bit 输出一致）。"""
    if cat == 0:
        return 0
    if val >= 0:
        return val
    return (val - 1) & ((1 << cat) - 1)


# 标准 JPEG 亮度 DC Huffman 表 (category -> (code, len))
DC_HUFF = {
    0x0: (0b00, 2),
    0x1: (0b010, 3),
    0x2: (0b011, 3),
    0x3: (0b100, 3),
    0x4: (0b101, 3),
    0x5: (0b110, 3),
    0x6: (0b1110, 4),
    0x7: (0b11110, 5),
    0x8: (0b111110, 6),
    0x9: (0b1111110, 7),
    0xA: (0b11111110, 8),
    0xB: (0b111111110, 9),
}

# 标准 JPEG 亮度 AC Huffman 表 (sym=run*16+cat -> (code, len))
AC_HUFF = {
    0x00: (0b1010, 4),                # EOB
    0x01: (0b00, 2),
    0x02: (0b01, 2),
    0x03: (0b100, 3),
    0x04: (0b1011, 4),
    0x05: (0b11010, 5),
    0x06: (0b1111000, 7),
    0x07: (0b11111000, 8),
    0x08: (0b1111110110, 10),
    0x09: (0b1111111110000010, 16),
    0x0A: (0b1111111110000011, 16),
    0x11: (0b1100, 4),
    0x12: (0b11011, 5),
    0x13: (0b1111001, 7),
    0x14: (0b111110110, 9),
    0x15: (0b11111110110, 11),
    0x16: (0b1111111110000100, 16),
    0x17: (0b1111111110000101, 16),
    0x18: (0b1111111110000110, 16),
    0x19: (0b1111111110000111, 16),
    0x1A: (0b1111111110001000, 16),
    0x21: (0b11100, 5),
    0x22: (0b11111001, 8),
    0x23: (0b1111110111, 10),
    0x24: (0b111111110100, 12),
    0x25: (0b1111111110001001, 16),
    0x26: (0b1111111110001010, 16),
    0x27: (0b1111111110001011, 16),
    0x28: (0b1111111110001100, 16),
    0x29: (0b1111111110001101, 16),
    0x2A: (0b1111111110001110, 16),
    0x31: (0b111010, 6),
    0x32: (0b111110111, 9),
    0x33: (0b111111110101, 12),
    0x34: (0b1111111110001111, 16),
    0x35: (0b1111111110010000, 16),
    0x36: (0b1111111110010001, 16),
    0x37: (0b1111111110010010, 16),
    0x38: (0b1111111110010011, 16),
    0x39: (0b1111111110010100, 16),
    0x3A: (0b1111111110010101, 16),
    0x41: (0b111011, 6),
    0x42: (0b1111111000, 10),
    0x43: (0b1111111110010110, 16),
    0x44: (0b1111111110010111, 16),
    0x45: (0b1111111110011000, 16),
    0x46: (0b1111111110011001, 16),
    0x47: (0b1111111110011010, 16),
    0x48: (0b1111111110011011, 16),
    0x49: (0b1111111110011100, 16),
    0x4A: (0b1111111110011101, 16),
    0x51: (0b1111010, 7),
    0x52: (0b11111110111, 11),
    0x53: (0b1111111110011110, 16),
    0x54: (0b1111111110011111, 16),
    0x55: (0b1111111110100000, 16),
    0x56: (0b1111111110100001, 16),
    0x57: (0b1111111110100010, 16),
    0x58: (0b1111111110100011, 16),
    0x59: (0b1111111110100100, 16),
    0x5A: (0b1111111110100101, 16),
    0x61: (0b1111011, 7),
    0x62: (0b111111110110, 12),
    0x63: (0b1111111110100110, 16),
    0x64: (0b1111111110100111, 16),
    0x65: (0b1111111110101000, 16),
    0x66: (0b1111111110101001, 16),
    0x67: (0b1111111110101010, 16),
    0x68: (0b1111111110101011, 16),
    0x69: (0b1111111110101100, 16),
    0x6A: (0b1111111110101101, 16),
    0x71: (0b11111010, 8),
    0x72: (0b111111110111, 12),
    0x73: (0b1111111110101110, 16),
    0x74: (0b1111111110101111, 16),
    0x75: (0b1111111110110000, 16),
    0x76: (0b1111111110110001, 16),
    0x77: (0b1111111110110010, 16),
    0x78: (0b1111111110110011, 16),
    0x79: (0b1111111110110100, 16),
    0x7A: (0b1111111110110101, 16),
    0x81: (0b111111000, 9),
    0x82: (0b111111111000000, 15),
    0x83: (0b1111111110110110, 16),
    0x84: (0b1111111110110111, 16),
    0x85: (0b1111111110111000, 16),
    0x86: (0b1111111110111001, 16),
    0x87: (0b1111111110111010, 16),
    0x88: (0b1111111110111011, 16),
    0x89: (0b1111111110111100, 16),
    0x8A: (0b1111111110111101, 16),
    0x91: (0b111111001, 9),
    0x92: (0b1111111110111110, 16),
    0x93: (0b1111111110111111, 16),
    0x94: (0b1111111111000000, 16),
    0x95: (0b1111111111000001, 16),
    0x96: (0b1111111111000010, 16),
    0x97: (0b1111111111000011, 16),
    0x98: (0b1111111111000100, 16),
    0x99: (0b1111111111000101, 16),
    0x9A: (0b1111111111000110, 16),
    0xA1: (0b111111010, 9),
    0xA2: (0b1111111111000111, 16),
    0xA3: (0b1111111111001000, 16),
    0xA4: (0b1111111111001001, 16),
    0xA5: (0b1111111111001010, 16),
    0xA6: (0b1111111111001011, 16),
    0xA7: (0b1111111111001100, 16),
    0xA8: (0b1111111111001101, 16),
    0xA9: (0b1111111111001110, 16),
    0xAA: (0b1111111111001111, 16),
    0xB1: (0b1111111001, 10),
    0xB2: (0b1111111111010000, 16),
    0xB3: (0b1111111111010001, 16),
    0xB4: (0b1111111111010010, 16),
    0xB5: (0b1111111111010011, 16),
    0xB6: (0b1111111111010100, 16),
    0xB7: (0b1111111111010101, 16),
    0xB8: (0b1111111111010110, 16),
    0xB9: (0b1111111111010111, 16),
    0xBA: (0b1111111111011000, 16),
    0xC1: (0b1111111010, 10),
    0xC2: (0b1111111111011001, 16),
    0xC3: (0b1111111111011010, 16),
    0xC4: (0b1111111111011011, 16),
    0xC5: (0b1111111111011100, 16),
    0xC6: (0b1111111111011101, 16),
    0xC7: (0b1111111111011110, 16),
    0xC8: (0b1111111111011111, 16),
    0xC9: (0b1111111111100000, 16),
    0xCA: (0b1111111111100001, 16),
    0xD1: (0b11111111000, 11),
    0xD2: (0b1111111111100010, 16),
    0xD3: (0b1111111111100011, 16),
    0xD4: (0b1111111111100100, 16),
    0xD5: (0b1111111111100101, 16),
    0xD6: (0b1111111111100110, 16),
    0xD7: (0b1111111111100111, 16),
    0xD8: (0b1111111111101000, 16),
    0xD9: (0b1111111111101001, 16),
    0xDA: (0b1111111111101010, 16),
    0xE1: (0b1111111111101011, 16),
    0xE2: (0b1111111111101100, 16),
    0xE3: (0b1111111111101101, 16),
    0xE4: (0b1111111111101110, 16),
    0xE5: (0b1111111111101111, 16),
    0xE6: (0b1111111111110000, 16),
    0xE7: (0b1111111111110001, 16),
    0xE8: (0b1111111111110010, 16),
    0xE9: (0b1111111111110011, 16),
    0xEA: (0b1111111111110100, 16),
    0xF0: (0b11111111001, 11),        # ZRL
    0xF1: (0b1111111111110101, 16),
    0xF2: (0b1111111111110110, 16),
    0xF3: (0b1111111111110111, 16),
    0xF4: (0b1111111111111000, 16),
    0xF5: (0b1111111111111001, 16),
    0xF6: (0b1111111111111010, 16),
    0xF7: (0b1111111111111011, 16),
    0xF8: (0b1111111111111100, 16),
    0xF9: (0b1111111111111101, 16),
    0xFA: (0b1111111111111110, 16),
}


def entropy_encode_block(zz: list, prev_dc: int) -> tuple:
    """
    对一个 8x8 块的 Zig-Zag 系数做熵编码。
    返回: (symbols, new_prev_dc)
    symbol 格式与 entropy_out.txt 一致:
        {"is_dc": int, "is_eob": int, "code": int, "len": int,
         "extra": int, "extra_len": int}
    """
    symbols = []

    # DC 差分
    dc_diff = zz[0] - prev_dc
    cat = category(dc_diff)
    extra = encode_extra(dc_diff, cat)
    code, length = DC_HUFF[cat]
    symbols.append({"is_dc": 1, "is_eob": 0, "code": code, "len": length,
                    "extra": extra, "extra_len": cat})

    # AC 游程编码
    run = 0
    for i in range(1, 64):
        val = zz[i]
        if val == 0:
            run += 1
            if run == 16:
                # ZRL
                code, length = AC_HUFF[0xF0]
                symbols.append({"is_dc": 0, "is_eob": 0, "code": code, "len": length,
                                "extra": 0, "extra_len": 0})
                run = 0
        else:
            cat = category(val)
            extra = encode_extra(val, cat)
            sym = (run << 4) | cat
            code, length = AC_HUFF[sym]
            symbols.append({"is_dc": 0, "is_eob": 0, "code": code, "len": length,
                            "extra": extra, "extra_len": cat})
            run = 0

    # EOB
    code, length = AC_HUFF[0x00]
    symbols.append({"is_dc": 0, "is_eob": 1, "code": code, "len": length,
                    "extra": 0, "extra_len": 0})

    return symbols, zz[0]


def main():
    img_y = load_rgb888_crop()

    zz_lines = []
    ent_lines = []
    n_blocks = 0
    prev_dc = 0
    entropy_total_bits = 0

    for by in range(0, IMAGE_H, BLOCK):
        for bx in range(0, IMAGE_W, BLOCK):
            # 取出 8x8 块并电平移位 (-128)
            block = [[img_y[by + i][bx + j] - 128.0 for j in range(BLOCK)] for i in range(BLOCK)]
            coeffs = dct2d_hw(block)
            # 量化
            q = quantize_hw(coeffs)
            # Zig-Zag 扫描 (vertical-first)
            zz = [0] * 64
            for pos in range(64):
                rm_idx = ZZ_V[pos]
                row, col = rm_idx // 8, rm_idx % 8
                zz[pos] = q[row][col]

            # 写 Zig-Zag 参考
            for pos, val in enumerate(zz):
                zz_lines.append(f"{pos} {val}\n")

            # 熵编码
            symbols, prev_dc = entropy_encode_block(zz, prev_dc)
            for s in symbols:
                ent_lines.append(f"{s['is_dc']} {s['is_eob']} {s['code']} {s['len']} {s['extra']} {s['extra_len']}\n")
                entropy_total_bits += s['len'] + s['extra_len']

            n_blocks += 1

    (DST_DIR / DST_NAME).write_text("".join(zz_lines), encoding="utf-8")
    (DST_DIR / "entropy_out_ref.txt").write_text("".join(ent_lines), encoding="utf-8")

    print(f"Generated {DST_DIR / DST_NAME}")
    print(f"Generated {DST_DIR / 'entropy_out_ref.txt'}")
    print(f"  Blocks: {n_blocks}")
    print(f"  Zig-Zag coeffs: {len(zz_lines)}")
    print(f"  Entropy symbols: {len(ent_lines)}")
    print(f"  Entropy total bits: {entropy_total_bits}")
    print(f"  Compression ratio: {entropy_total_bits / (IMAGE_W * IMAGE_H):.3f} bpp")


if __name__ == "__main__":
    main()
