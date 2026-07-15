#!/usr/bin/env python3
"""
JPEG 灰度解码器 → PNG
从 Verilog 硬件输出解码重建图像，保存为 PNG。

输入:
  - entropy_out.txt : 熵编码符号流 (需完整解码: 反Huffman+VLI→反游程→逆zz→反量化→IDCT)
  - zz_out_all.txt  : zig-zag 量化系数 (只需: 逆zz→反量化→IDCT)

输出 (D:\\FPGA\\hc\\jpeg_compress_gray\\out):
  - decoded_entropy.png : 从熵编码解码的图像
  - decoded_zz.png       :从 zig-zag 系数解码的图像
"""

import math
from pathlib import Path
from PIL import Image

SIM_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/sim")
OUT_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/out")

IMAGE_W = 320
IMAGE_H = 320
BLOCK = 8

# 标准 JPEG 亮度量化表
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

# 竖直优先 Zig-Zag (与 ref_model.py 一致)
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

# ---- Huffman 表 ----
DC_HUFF = {
    0x0: (0b00, 2),  0x1: (0b010, 3),  0x2: (0b011, 3),
    0x3: (0b100, 3), 0x4: (0b101, 3),  0x5: (0b110, 3),
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

AC_HUFF_REV = {}
for _s, (_c, _l) in AC_HUFF.items():
    AC_HUFF_REV[(_c, _l)] = _s


# ---- DCT 矩阵 ----
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


# ---- VLI 解码 ----
def decode_vli(extra, cat):
    """
    VLI 解码:
    - cat == 0: val = 0
    - extra >= 2048: 12位无符号表示的负数, val = extra - 4095
      (因为 encode_extra(-val,cat) = -val-1, 12位无符号 = 4096+(-val-1) = 4095-val)
    - 0 <= extra < 2048: 正数, val = extra
    - extra < 0: 旧格式(有符号), val = extra + 1
    """
    if cat == 0:
        return 0
    if extra >= 2048:
        return extra - 4095
    if extra >= 0:
        return extra
    return extra + 1


# ---- 熵解码: 符号流 → 64 zig-zag 系数 ----
def entropy_decode_block(symbols, prev_dc):
    zz = [0] * 64
    pos = 0
    for s in symbols:
        is_dc, is_eob, code, length, extra, extra_len = s
        if is_dc:
            dc_diff = decode_vli(extra, extra_len)
            dc_val = prev_dc + dc_diff
            zz[0] = dc_val
            prev_dc = dc_val
            pos = 1
        elif is_eob:
            break
        elif code == 2041 and length == 11:
            pos += 16  # ZRL: 16 个零 (已初始化为0)
        else:
            sym = AC_HUFF_REV[(code, length)]
            run = sym >> 4
            cat = sym & 0xF
            val = decode_vli(extra, cat)
            pos += run
            if pos < 64:
                zz[pos] = val
            pos += 1
    return zz, prev_dc


def decode_entropy_file(filepath):
    """从熵编码文件解码出 320×320 图像"""
    lines = Path(filepath).read_text(encoding="utf-8").strip().split("\n")
    symbols = [tuple(int(x) for x in l.split()) for l in lines]

    # 按 EOB 分块
    blocks, cur = [], []
    for s in symbols:
        cur.append(s)
        if s[1] == 1:  # is_eob
            blocks.append(cur)
            cur = []

    print(f"  符号: {len(symbols)}, 块: {len(blocks)}")

    img = [[0] * IMAGE_W for _ in range(IMAGE_H)]
    prev_dc = 0
    for bi, bsyms in enumerate(blocks):
        zz, prev_dc = entropy_decode_block(bsyms, prev_dc)
        block = inverse_zigzag(zz)
        block = dequantize(block)
        block = idct2d(block)
        by = (bi // (IMAGE_W // 8)) * 8
        bx = (bi % (IMAGE_W // 8)) * 8
        for i in range(8):
            for j in range(8):
                val = round(block[i][j] + 128.0)
                img[by + i][bx + j] = max(0, min(255, val))
    return img


# ---- zz_out 解码: 量化系数 → 图像 ----
def decode_zz_file(filepath):
    """从 zig-zag 量化系数文件解码出 320×320 图像"""
    lines = Path(filepath).read_text(encoding="utf-8").strip().split("\n")
    # 每行: "zz_idx value", 每 64 行一个块
    img = [[0] * IMAGE_W for _ in range(IMAGE_H)]
    n_blocks = (IMAGE_W // 8) * (IMAGE_H // 8)
    prev_dc = 0  # zz_out 存的是绝对值, 不需要差分

    for bi in range(n_blocks):
        zz = [0] * 64
        for k in range(64):
            parts = lines[bi * 64 + k].split()
            zz_idx = int(parts[0])
            val = int(parts[1])
            zz[zz_idx] = val

        block = inverse_zigzag(zz)
        block = dequantize(block)
        block = idct2d(block)
        by = (bi // (IMAGE_W // 8)) * 8
        bx = (bi % (IMAGE_W // 8)) * 8
        for i in range(8):
            for j in range(8):
                val = round(block[i][j] + 128.0)
                img[by + i][bx + j] = max(0, min(255, val))

    print(f"  块: {n_blocks}")
    return img


def inverse_zigzag(zz):
    block = [[0.0] * 8 for _ in range(8)]
    for p in range(64):
        r, c = ZZ_V[p] // 8, ZZ_V[p] % 8
        block[r][c] = float(zz[p])
    return block


def dequantize(block):
    return [[block[i][j] * Q_LUMINANCE[i][j] for j in range(8)] for i in range(8)]


def save_png(img, filepath):
    """用 PIL 保存灰度 PNG"""
    flat = []
    for row in img:
        flat.extend(row)
    im = Image.new("L", (IMAGE_W, IMAGE_H))
    im.putdata(flat)
    im.save(filepath)
    print(f"  已保存: {filepath}")


def main():
    print("=" * 60)
    print("JPEG 解码 → PNG")
    print("=" * 60)

    # 1. 从熵编码解码
    ent_file = SIM_DIR / "entropy_out.txt"
    print(f"\n[1] 解码熵编码: {ent_file}")
    img_ent = decode_entropy_file(ent_file)
    save_png(img_ent, str(OUT_DIR / "decoded_entropy.png"))

    # 2. 从 zig-zag 系数解码
    zz_file = SIM_DIR / "zz_out_all.txt"
    print(f"\n[2] 解码 zig-zag: {zz_file}")
    img_zz = decode_zz_file(zz_file)
    save_png(img_zz, str(OUT_DIR / "decoded_zz.png"))

    # 3. 对比两张图
    print(f"\n[3] 对比 (熵解码 vs zig-zag解码):")
    diff_count = 0
    max_diff = 0
    sum_diff = 0
    for y in range(IMAGE_H):
        for x in range(IMAGE_W):
            d = abs(img_ent[y][x] - img_zz[y][x])
            if d > 0:
                diff_count += 1
                sum_diff += d
                if d > max_diff:
                    max_diff = d
    total = IMAGE_W * IMAGE_H
    print(f"  不同像素: {diff_count}/{total} ({diff_count/total*100:.2f}%)")
    print(f"  最大差异: {max_diff}")
    if diff_count > 0:
        print(f"  平均差异: {sum_diff/diff_count:.2f}")

    print(f"\n完成! 输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
