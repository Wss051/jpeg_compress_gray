#!/usr/bin/env python3
"""
将 Verilog 熵编码输出 entropy_out.txt 解码回灰度 PNG 图像。

用法:
    python entropy_decode_to_png.py <entropy_out.txt> <output.png>

流程:
    Huffman 符号 -> DC 差分解码 + AC 游程解码 -> 反 Zig-Zag -> 反量化 -> IDCT -> +128 -> 灰度图
"""

import math
import sys
from pathlib import Path

IMAGE_W = 320
IMAGE_H = 320
BLOCK = 8

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

# 竖直优先 Zig-Zag: ZZ_V[zigzag_pos] = row_major_idx
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

# 反 Zig-Zag 映射: row_major_idx -> zigzag_pos
ZZ_V_INV = [0] * 64
for zz_pos, rm_idx in enumerate(ZZ_V):
    ZZ_V_INV[rm_idx] = zz_pos


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
            s = 0.0
            for k in range(P):
                s += A[i][k] * B[k][j]
            C[i][j] = s
    return C


def transpose(A):
    return [[A[j][i] for j in range(len(A))] for i in range(len(A[0]))]


def idct2d(block):
    """2D IDCT-II = DCT^T @ block @ DCT"""
    return mat_mul(transpose(DCT), mat_mul(block, DCT))


def decode_vli(extra: int, cat: int) -> int:
    """JPEG VLI 解码：从附加位还原有符号值。
    兼容 Verilog 12-bit 输出：先按 category 宽度取低 bit。"""
    if cat == 0:
        return 0
    extra = extra & ((1 << cat) - 1)
    half = 1 << (cat - 1)
    if extra < half:
        return extra - (1 << cat) + 1
    return extra


def parse_entropy(path: Path):
    """解析 entropy_out.txt，返回符号列表"""
    symbols = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 6:
                symbols.append({
                    "is_dc": int(parts[0]),
                    "is_eob": int(parts[1]),
                    "code": int(parts[2]),
                    "len": int(parts[3]),
                    "extra": int(parts[4]),
                    "extra_len": int(parts[5]),
                })
    return symbols


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

# 反查表: (code, len) -> (run, cat)
AC_HUFF_INV = {}
for sym, (code, length) in AC_HUFF.items():
    AC_HUFF_INV[(code, length)] = (sym >> 4, sym & 0xF)


def decode_entropy(symbols):
    """将符号序列解码为 320x320 Y 图像"""
    img_y = [[0] * IMAGE_W for _ in range(IMAGE_H)]
    idx = 0
    prev_dc = 0
    block_idx = 0

    while idx < len(symbols):
        sym = symbols[idx]
        if not sym["is_dc"]:
            raise ValueError(f"Expected DC symbol at {idx}, got {sym}")

        # DC 解码
        dc_diff = decode_vli(sym["extra"], sym["extra_len"])
        dc = prev_dc + dc_diff
        prev_dc = dc

        # AC 解码
        zz = [0] * 64
        zz[0] = dc
        zz_pos = 1
        idx += 1

        while idx < len(symbols):
            sym = symbols[idx]
            if sym["is_eob"]:
                idx += 1
                break

            # 反查 Huffman 表得到 run/cat
            key = (sym["code"], sym["len"])
            if key not in AC_HUFF_INV:
                raise ValueError(f"Unknown AC Huffman code at {idx}: {key}")
            run, cat = AC_HUFF_INV[key]

            # ZRL: 16 个零
            if run == 15 and cat == 0:
                zz_pos += 16
            else:
                zz_pos += run
                level = decode_vli(sym["extra"], cat)
                if zz_pos < 64:
                    zz[zz_pos] = level
                zz_pos += 1

            idx += 1

        # 反 Zig-Zag
        block_rm = [[0.0] * BLOCK for _ in range(BLOCK)]
        for rm_pos in range(64):
            row, col = rm_pos // 8, rm_pos % 8
            zz_pos = ZZ_V_INV[rm_pos]
            block_rm[row][col] = float(zz[zz_pos] * Q_LUMINANCE[row][col])

        # IDCT
        block_pixels = idct2d(block_rm)

        # 写回图像
        bx = (block_idx % (IMAGE_W // BLOCK)) * BLOCK
        by = (block_idx // (IMAGE_W // BLOCK)) * BLOCK
        for i in range(BLOCK):
            for j in range(BLOCK):
                val = int(round(block_pixels[i][j] + 128.0))
                val = max(0, min(255, val))
                img_y[by + i][bx + j] = val

        block_idx += 1

    if block_idx != (IMAGE_W // BLOCK) * (IMAGE_H // BLOCK):
        print(f"WARNING: decoded {block_idx} blocks, expected {(IMAGE_W//BLOCK)*(IMAGE_H//BLOCK)}")

    return img_y


def save_grayscale_png(img_y, path: Path):
    from PIL import Image
    flat = [img_y[y][x] for y in range(IMAGE_H) for x in range(IMAGE_W)]
    img = Image.new("L", (IMAGE_W, IMAGE_H))
    img.putdata(flat)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print(f"Saved {path}")


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <entropy_out.txt> <output.png>")
        sys.exit(1)

    entropy_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    symbols = parse_entropy(entropy_path)
    print(f"Parsed {len(symbols)} entropy symbols")

    img_y = decode_entropy(symbols)
    save_grayscale_png(img_y, output_path)


if __name__ == "__main__":
    main()
