#!/usr/bin/env python3
"""
对 320×320 RGB888 raw 文件进行完整 JPEG 灰度编解码参考流程：
    RGB888 -> Y -> 8x8 分块 -> DCT -> 量化 -> Zig-Zag -> 熵编码 -> 解码 -> 灰度 PNG

输出:
    <prefix>_zz_ref.txt
    <prefix>_entropy_ref.txt
    <prefix>_decoded.png
"""

import sys
import math
from pathlib import Path

IMAGE_W = 320
IMAGE_H = 320
BLOCK = 8

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

ZZ_V_INV = [0] * 64
for zz_pos, rm_idx in enumerate(ZZ_V):
    ZZ_V_INV[rm_idx] = zz_pos


def rgb888_to_y(r: int, g: int, b: int) -> int:
    r565 = r & 0xF8
    g565 = g & 0xFC
    b565 = b & 0xF8
    y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
    return max(0, min(255, y))


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


def dct2d(block):
    return mat_mul(mat_mul(DCT, block), transpose(DCT))


def idct2d(block):
    return mat_mul(mat_mul(transpose(DCT), block), DCT)


def category(val: int) -> int:
    if val == 0:
        return 0
    return abs(val).bit_length()


def encode_extra(val: int, cat: int) -> int:
    """JPEG VLI 附加位编码，返回无符号整数（与 Verilog 12-bit 输出一致）。"""
    if cat == 0:
        return 0
    if val >= 0:
        return val
    return (val - 1) & ((1 << cat) - 1)


def decode_vli(extra: int, cat: int) -> int:
    if cat == 0:
        return 0
    half = 1 << (cat - 1)
    if extra < half:
        return extra - (1 << cat) + 1
    return extra


DC_HUFF = {
    0x0: (0b00, 2), 0x1: (0b010, 3), 0x2: (0b011, 3), 0x3: (0b100, 3),
    0x4: (0b101, 3), 0x5: (0b110, 3), 0x6: (0b1110, 4), 0x7: (0b11110, 5),
    0x8: (0b111110, 6), 0x9: (0b1111110, 7), 0xA: (0b11111110, 8),
    0xB: (0b111111110, 9),
}

AC_HUFF = {
    0x00: (0b1010, 4), 0x01: (0b00, 2), 0x02: (0b01, 2), 0x03: (0b100, 3),
    0x04: (0b1011, 4), 0x05: (0b11010, 5), 0x06: (0b1111000, 7),
    0x07: (0b11111000, 8), 0x08: (0b1111110110, 10),
    0x09: (0b1111111110000010, 16), 0x0A: (0b1111111110000011, 16),
    0x11: (0b1100, 4), 0x12: (0b11011, 5), 0x13: (0b1111001, 7),
    0x14: (0b111110110, 9), 0x15: (0b11111110110, 11),
    0x16: (0b1111111110000100, 16), 0x17: (0b1111111110000101, 16),
    0x18: (0b1111111110000110, 16), 0x19: (0b1111111110000111, 16),
    0x1A: (0b1111111110001000, 16), 0x21: (0b11100, 5),
    0x22: (0b11111001, 8), 0x23: (0b1111110111, 10),
    0x24: (0b111111110100, 12), 0x25: (0b1111111110001001, 16),
    0x26: (0b1111111110001010, 16), 0x27: (0b1111111110001011, 16),
    0x28: (0b1111111110001100, 16), 0x29: (0b1111111110001101, 16),
    0x2A: (0b1111111110001110, 16), 0x31: (0b111010, 6),
    0x32: (0b111110111, 9), 0x33: (0b111111110101, 12),
    0x34: (0b1111111110001111, 16), 0x35: (0b1111111110010000, 16),
    0x36: (0b1111111110010001, 16), 0x37: (0b1111111110010010, 16),
    0x38: (0b1111111110010011, 16), 0x39: (0b1111111110010100, 16),
    0x3A: (0b1111111110010101, 16), 0x41: (0b111011, 6),
    0x42: (0b1111111000, 10), 0x43: (0b1111111110010110, 16),
    0x44: (0b1111111110010111, 16), 0x45: (0b1111111110011000, 16),
    0x46: (0b1111111110011001, 16), 0x47: (0b1111111110011010, 16),
    0x48: (0b1111111110011011, 16), 0x49: (0b1111111110011100, 16),
    0x4A: (0b1111111110011101, 16), 0x51: (0b1111010, 7),
    0x52: (0b11111110111, 11), 0x53: (0b1111111110011110, 16),
    0x54: (0b1111111110011111, 16), 0x55: (0b1111111110100000, 16),
    0x56: (0b1111111110100001, 16), 0x57: (0b1111111110100010, 16),
    0x58: (0b1111111110100011, 16), 0x59: (0b1111111110100100, 16),
    0x5A: (0b1111111110100101, 16), 0x61: (0b1111011, 7),
    0x62: (0b111111110110, 12), 0x63: (0b1111111110100110, 16),
    0x64: (0b1111111110100111, 16), 0x65: (0b1111111110101000, 16),
    0x66: (0b1111111110101001, 16), 0x67: (0b1111111110101010, 16),
    0x68: (0b1111111110101011, 16), 0x69: (0b1111111110101100, 16),
    0x6A: (0b1111111110101101, 16), 0x71: (0b11111010, 8),
    0x72: (0b111111110111, 12), 0x73: (0b1111111110101110, 16),
    0x74: (0b1111111110101111, 16), 0x75: (0b1111111110110000, 16),
    0x76: (0b1111111110110001, 16), 0x77: (0b1111111110110010, 16),
    0x78: (0b1111111110110011, 16), 0x79: (0b1111111110110100, 16),
    0x7A: (0b1111111110110101, 16), 0x81: (0b111111000, 9),
    0x82: (0b111111111000000, 15), 0x83: (0b1111111110110110, 16),
    0x84: (0b1111111110110111, 16), 0x85: (0b1111111110111000, 16),
    0x86: (0b1111111110111001, 16), 0x87: (0b1111111110111010, 16),
    0x88: (0b1111111110111011, 16), 0x89: (0b1111111110111100, 16),
    0x8A: (0b1111111110111101, 16), 0x91: (0b111111001, 9),
    0x92: (0b1111111110111110, 16), 0x93: (0b1111111110111111, 16),
    0x94: (0b1111111111000000, 16), 0x95: (0b1111111111000001, 16),
    0x96: (0b1111111111000010, 16), 0x97: (0b1111111111000011, 16),
    0x98: (0b1111111111000100, 16), 0x99: (0b1111111111000101, 16),
    0x9A: (0b1111111111000110, 16), 0xA1: (0b111111010, 9),
    0xA2: (0b1111111111000111, 16), 0xA3: (0b1111111111001000, 16),
    0xA4: (0b1111111111001001, 16), 0xA5: (0b1111111111001010, 16),
    0xA6: (0b1111111111001011, 16), 0xA7: (0b1111111111001100, 16),
    0xA8: (0b1111111111001101, 16), 0xA9: (0b1111111111001110, 16),
    0xAA: (0b1111111111001111, 16), 0xB1: (0b1111111001, 10),
    0xB2: (0b1111111111010000, 16), 0xB3: (0b1111111111010001, 16),
    0xB4: (0b1111111111010010, 16), 0xB5: (0b1111111111010011, 16),
    0xB6: (0b1111111111010100, 16), 0xB7: (0b1111111111010101, 16),
    0xB8: (0b1111111111010110, 16), 0xB9: (0b1111111111010111, 16),
    0xBA: (0b1111111111011000, 16), 0xC1: (0b1111111010, 10),
    0xC2: (0b1111111111011001, 16), 0xC3: (0b1111111111011010, 16),
    0xC4: (0b1111111111011011, 16), 0xC5: (0b1111111111011100, 16),
    0xC6: (0b1111111111011101, 16), 0xC7: (0b1111111111011110, 16),
    0xC8: (0b1111111111011111, 16), 0xC9: (0b1111111111100000, 16),
    0xCA: (0b1111111111100001, 16), 0xD1: (0b11111111000, 11),
    0xD2: (0b1111111111100010, 16), 0xD3: (0b1111111111100011, 16),
    0xD4: (0b1111111111100100, 16), 0xD5: (0b1111111111100101, 16),
    0xD6: (0b1111111111100110, 16), 0xD7: (0b1111111111100111, 16),
    0xD8: (0b1111111111101000, 16), 0xD9: (0b1111111111101001, 16),
    0xDA: (0b1111111111101010, 16), 0xE1: (0b1111111111101011, 16),
    0xE2: (0b1111111111101100, 16), 0xE3: (0b1111111111101101, 16),
    0xE4: (0b1111111111101110, 16), 0xE5: (0b1111111111101111, 16),
    0xE6: (0b1111111111110000, 16), 0xE7: (0b1111111111110001, 16),
    0xE8: (0b1111111111110010, 16), 0xE9: (0b1111111111110011, 16),
    0xEA: (0b1111111111110100, 16), 0xF0: (0b11111111001, 11),
    0xF1: (0b1111111111110101, 16), 0xF2: (0b1111111111110110, 16),
    0xF3: (0b1111111111110111, 16), 0xF4: (0b1111111111111000, 16),
    0xF5: (0b1111111111111001, 16), 0xF6: (0b1111111111111010, 16),
    0xF7: (0b1111111111111011, 16), 0xF8: (0b1111111111111100, 16),
    0xF9: (0b1111111111111101, 16), 0xFA: (0b1111111111111110, 16),
}

AC_HUFF_INV = {v: (k >> 4, k & 0xF) for k, v in AC_HUFF.items()}


def encode_entropy(zz: list, prev_dc: int):
    symbols = []
    dc_diff = zz[0] - prev_dc
    cat = category(dc_diff)
    extra = encode_extra(dc_diff, cat)
    code, length = DC_HUFF[cat]
    symbols.append({"is_dc": 1, "is_eob": 0, "code": code, "len": length,
                    "extra": extra, "extra_len": cat})

    run = 0
    for i in range(1, 64):
        val = zz[i]
        if val == 0:
            run += 1
            if run == 16:
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

    code, length = AC_HUFF[0x00]
    symbols.append({"is_dc": 0, "is_eob": 1, "code": code, "len": length,
                    "extra": 0, "extra_len": 0})
    return symbols, zz[0]


def decode_entropy(symbols):
    img_y = [[0] * IMAGE_W for _ in range(IMAGE_H)]
    idx = 0
    prev_dc = 0
    block_idx = 0

    while idx < len(symbols):
        sym = symbols[idx]
        dc_diff = decode_vli(sym["extra"], sym["extra_len"])
        dc = prev_dc + dc_diff
        prev_dc = dc

        zz = [0] * 64
        zz[0] = dc
        zz_pos = 1
        idx += 1

        while idx < len(symbols):
            sym = symbols[idx]
            if sym["is_eob"]:
                idx += 1
                break
            key = (sym["code"], sym["len"])
            run, cat = AC_HUFF_INV[key]
            if run == 15 and cat == 0:
                zz_pos += 16
            else:
                zz_pos += run
                level = decode_vli(sym["extra"], cat)
                if zz_pos < 64:
                    zz[zz_pos] = level
                zz_pos += 1
            idx += 1

        block_rm = [[0.0] * BLOCK for _ in range(BLOCK)]
        for rm_pos in range(64):
            row, col = rm_pos // 8, rm_pos % 8
            zz_pos = ZZ_V_INV[rm_pos]
            block_rm[row][col] = float(zz[zz_pos] * Q_LUMINANCE[row][col])

        block_pixels = idct2d(block_rm)

        bx = (block_idx % (IMAGE_W // BLOCK)) * BLOCK
        by = (block_idx // (IMAGE_W // BLOCK)) * BLOCK
        for i in range(BLOCK):
            for j in range(BLOCK):
                val = int(round(block_pixels[i][j] + 128.0))
                img_y[by + i][bx + j] = max(0, min(255, val))

        block_idx += 1

    return img_y


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_rgb888.raw> <output_prefix>")
        sys.exit(1)

    raw_path = Path(sys.argv[1])
    prefix = Path(sys.argv[2])
    prefix.parent.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    raw = raw_path.read_bytes()
    assert len(raw) == IMAGE_W * IMAGE_H * 3

    img_y = [[0] * IMAGE_W for _ in range(IMAGE_H)]
    idx = 0
    for y in range(IMAGE_H):
        for x in range(IMAGE_W):
            r, g, b = raw[idx], raw[idx+1], raw[idx+2]
            img_y[y][x] = rgb888_to_y(r, g, b)
            idx += 3

    zz_lines = []
    ent_lines = []
    n_blocks = 0
    prev_dc = 0
    total_bits = 0

    for by in range(0, IMAGE_H, BLOCK):
        for bx in range(0, IMAGE_W, BLOCK):
            block = [[img_y[by+i][bx+j] - 128.0 for j in range(BLOCK)] for i in range(BLOCK)]
            coeffs = dct2d(block)
            q = [[int(round(coeffs[i][j] / Q_LUMINANCE[i][j])) for j in range(BLOCK)] for i in range(BLOCK)]

            zz = [0] * 64
            for pos in range(64):
                rm_idx = ZZ_V[pos]
                row, col = rm_idx // 8, rm_idx % 8
                zz[pos] = q[row][col]

            for pos, val in enumerate(zz):
                zz_lines.append(f"{pos} {val}\n")

            symbols, prev_dc = encode_entropy(zz, prev_dc)
            for s in symbols:
                ent_lines.append(f"{s['is_dc']} {s['is_eob']} {s['code']} {s['len']} {s['extra']} {s['extra_len']}\n")
                total_bits += s['len'] + s['extra_len']

            n_blocks += 1

    (prefix.with_name(prefix.name + "_zz_ref.txt")).write_text("".join(zz_lines), encoding="utf-8")
    (prefix.with_name(prefix.name + "_entropy_ref.txt")).write_text("".join(ent_lines), encoding="utf-8")

    # Decode back
    symbols = []
    for line in ent_lines:
        parts = line.strip().split()
        symbols.append({
            "is_dc": int(parts[0]), "is_eob": int(parts[1]),
            "code": int(parts[2]), "len": int(parts[3]),
            "extra": int(parts[4]), "extra_len": int(parts[5]),
        })

    decoded = decode_entropy(symbols)
    flat = [decoded[y][x] for y in range(IMAGE_H) for x in range(IMAGE_W)]
    out_img = Image.new("L", (IMAGE_W, IMAGE_H))
    out_img.putdata(flat)
    out_path = prefix.with_name(prefix.name + "_decoded.png")
    out_img.save(out_path)

    print(f"Blocks: {n_blocks}")
    print(f"Entropy symbols: {len(ent_lines)}")
    print(f"Entropy total bits: {total_bits}")
    print(f"Compression ratio: {total_bits / (IMAGE_W * IMAGE_H):.3f} bpp")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
