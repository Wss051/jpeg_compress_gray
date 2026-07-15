#!/usr/bin/env python3
"""
JPEG 灰度解码器：从熵编码输出重建图像
解码流程: 熵符号 → 反向Huffman+VLI解码 → 反游程 → 逆zig-zag → 反量化 → IDCT → 图像
"""

import math
from pathlib import Path

SIM_DIR = Path(__file__).parent
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

# ---- Huffman 表 (与 ref_model.py 完全一致) ----
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
    0xF0: (0b11111111001, 11),  # ZRL
    0xF1: (0b1111111111110101, 16), 0xF2: (0b1111111111110110, 16),
    0xF3: (0b1111111111110111, 16), 0xF4: (0b1111111111111000, 16),
    0xF5: (0b1111111111111001, 16), 0xF6: (0b1111111111111010, 16),
    0xF7: (0b1111111111111011, 16), 0xF8: (0b1111111111111100, 16),
    0xF9: (0b1111111111111101, 16), 0xFA: (0b1111111111111110, 16),
}

# 构建反向查找表: (code, len) -> symbol
AC_HUFF_REV = {}
for sym, (code, length) in AC_HUFF.items():
    AC_HUFF_REV[(code, length)] = sym

DC_HUFF_REV = {}
for cat, (code, length) in DC_HUFF.items():
    DC_HUFF_REV[(code, length)] = cat


def decode_vli(extra: int, cat: int) -> int:
    """VLI 解码: extra>=0 时 val=extra; extra<0 时 val=extra+1"""
    if cat == 0:
        return 0
    if extra >= 0:
        return extra
    return extra + 1


def build_dct_matrix(N=8):
    M = [[0.0] * N for _ in range(N)]
    for k in range(N):
        alpha = math.sqrt(1.0 / N) if k == 0 else math.sqrt(2.0 / N)
        for n in range(N):
            M[k][n] = alpha * math.cos(math.pi / N * (n + 0.5) * k)
    return M


DCT = build_dct_matrix(8)


def mat_mul(A, B):
    N = len(A)
    M = len(B[0])
    P = len(B)
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


def idct2d(coeffs):
    """逆 2D-DCT: block = DCT^T * C * DCT"""
    tmp = mat_mul(transpose(DCT), coeffs)
    return mat_mul(tmp, DCT)


def parse_entropy_file(filepath):
    """解析熵编码文件，返回符号列表"""
    lines = Path(filepath).read_text(encoding="utf-8").strip().split("\n")
    symbols = []
    for line in lines:
        p = line.strip().split()
        symbols.append({
            "is_dc": int(p[0]),
            "is_eob": int(p[1]),
            "code": int(p[2]),
            "len": int(p[3]),
            "extra": int(p[4]),
            "extra_len": int(p[5]),
        })
    return symbols


def decode_block_symbols(symbols, prev_dc):
    """
    解码一个块的熵符号 -> 64元素 zig-zag 系数数组
    返回: (zz_array, new_prev_dc)
    """
    zz = [0] * 64
    pos = 0  # zig-zag 位置指针
    first_sym = True

    for s in symbols:
        if s["is_dc"]:
            # DC 差分解码
            cat = s["extra_len"]
            dc_diff = decode_vli(s["extra"], cat)
            dc_val = prev_dc + dc_diff
            zz[0] = dc_val
            prev_dc = dc_val
            pos = 1
            first_sym = False
        elif s["is_eob"]:
            # EOB: 剩余位置都是 0
            break
        elif s["code"] == 2041 and s["len"] == 11:
            # ZRL: 16 个零
            for _ in range(16):
                if pos < 64:
                    zz[pos] = 0
                    pos += 1
        else:
            # 普通 AC 符号: 反向 Huffman 查找得到 (run, cat)
            sym = AC_HUFF_REV.get((s["code"], s["len"]))
            if sym is None:
                raise ValueError(f"未知 Huffman 码: code={s['code']}, len={s['len']}")
            run = sym >> 4
            cat = sym & 0xF
            val = decode_vli(s["extra"], cat)
            # 填入 run 个零
            for _ in range(run):
                if pos < 64:
                    zz[pos] = 0
                    pos += 1
            # 填入非零值
            if pos < 64:
                zz[pos] = val
                pos += 1

    return zz, prev_dc


def inverse_zigzag(zz_array):
    """zig-zag 序列 -> 8x8 块 (row-major)"""
    block = [[0] * 8 for _ in range(8)]
    for pos in range(64):
        rm_idx = ZZ_V[pos]
        row, col = rm_idx // 8, rm_idx % 8
        block[row][col] = zz_array[pos]
    return block


def dequantize(block):
    """反量化: 乘以量化表"""
    return [[block[i][j] * Q_LUMINANCE[i][j] for j in range(8)] for i in range(8)]


def decode_to_image(entropy_file, output_pgm):
    """完整解码流程: 熵编码文件 -> PGM 图像"""
    symbols = parse_entropy_file(entropy_file)

    # 按块分割 (DC 符号标志新块开始)
    blocks_sym = []
    cur = []
    for s in symbols:
        cur.append(s)
        if s["is_eob"]:
            blocks_sym.append(cur)
            cur = []
    if cur:
        blocks_sym.append(cur)

    print(f"  块数: {len(blocks_sym)}")

    # 解码每个块
    img = [[0] * IMAGE_W for _ in range(IMAGE_H)]
    prev_dc = 0

    for b_idx, block_syms in enumerate(blocks_sym):
        zz, prev_dc = decode_block_symbols(block_syms, prev_dc)
        q_block = inverse_zigzag(zz)
        dct_block = dequantize(q_block)
        pixel_block = idct2d(dct_block)

        # 电平偏移恢复 (+128) 并裁剪
        by = (b_idx // (IMAGE_W // 8)) * 8
        bx = (b_idx % (IMAGE_W // 8)) * 8
        for i in range(8):
            for j in range(8):
                val = pixel_block[i][j] + 128.0
                val = max(0, min(255, round(val)))
                img[by + i][bx + j] = val

    # 保存为 PGM
    out_path = Path(output_pgm)
    header = f"P5\n{IMAGE_W} {IMAGE_H}\n255\n"
    data = bytearray()
    data.extend(header.encode("ascii"))
    for row in img:
        for val in row:
            data.append(val)
    out_path.write_bytes(data)
    print(f"  已保存: {out_path}")

    return img


def load_original_y():
    """加载原始图像的 Y 分量"""
    raw_path = Path(__file__).parent.parent / "out" / "02_rgb888.raw"
    raw = raw_path.read_bytes()

    def rgb888_to_y(r, g, b):
        r565 = r & 0xF8
        g565 = g & 0xFC
        b565 = b & 0xF8
        y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
        return max(0, min(255, y))

    img = []
    for y in range(IMAGE_H):
        row = []
        for x in range(IMAGE_W):
            idx = (y * IMAGE_W + x) * 3
            r = raw[idx]
            g = raw[idx + 1]
            b = raw[idx + 2]
            row.append(rgb888_to_y(r, g, b))
        img.append(row)
    return img


def compare_images(img1, img2, name1, name2):
    """像素级对比两幅图像"""
    if len(img1) != len(img2) or len(img1[0]) != len(img2[0]):
        print(f"  图像尺寸不一致!")
        return

    total = len(img1) * len(img1[0])
    max_diff = 0
    sum_abs_diff = 0
    exact_match = 0
    diff_dist = {}

    for i in range(len(img1)):
        for j in range(len(img1[0])):
            d = abs(img1[i][j] - img2[i][j])
            if d == 0:
                exact_match += 1
            else:
                diff_dist[d] = diff_dist.get(d, 0) + 1
            sum_abs_diff += d
            if d > max_diff:
                max_diff = d

    match_rate = exact_match / total * 100
    mae = sum_abs_diff / total
    psnr = float('inf') if max_diff == 0 else 20 * math.log10(255 / (math.sqrt(sum((img1[i][j] - img2[i][j])**2 for i in range(len(img1)) for j in range(len(img1[0]))) / total)))

    print(f"  {name1} vs {name2}:")
    print(f"    精确匹配: {exact_match}/{total} ({match_rate:.2f}%)")
    print(f"    最大误差: {max_diff}")
    print(f"    平均绝对误差(MAE): {mae:.4f}")
    if diff_dist:
        print(f"    误差分布:")
        for d in sorted(diff_dist.keys()):
            print(f"      diff={d}: {diff_dist[d]}像素 ({diff_dist[d]/total*100:.2f}%)")
    return mae, max_diff


def main():
    print("=" * 60)
    print("JPEG 灰度解码器")
    print("=" * 60)

    # 解码硬件输出
    print("\n--- 解码 entropy_out.txt (硬件输出) ---")
    img_out = decode_to_image(
        SIM_DIR / "entropy_out.txt",
        SIM_DIR / "decoded_out.pgm"
    )

    # 解码参考输出
    print("\n--- 解码 entropy_out_ref.txt (参考输出) ---")
    img_ref = decode_to_image(
        SIM_DIR / "entropy_out_ref.txt",
        SIM_DIR / "decoded_ref.pgm"
    )

    # 加载原始图像
    print("\n--- 加载原始图像 ---")
    img_orig = load_original_y()
    print(f"  原始图像: {IMAGE_W}x{IMAGE_H} 灰度")

    # 对比
    print("\n" + "=" * 60)
    print("图像质量对比")
    print("=" * 60)

    print("\n[1] 硬件解码 vs 原始图像:")
    compare_images(img_out, img_orig, "OUT", "原始")

    print("\n[2] 参考解码 vs 原始图像:")
    compare_images(img_ref, img_orig, "REF", "原始")

    print("\n[3] 硬件解码 vs 参考解码:")
    compare_images(img_out, img_ref, "OUT", "REF")

    # 保存原始图像 PGM 供对比
    orig_pgm = SIM_DIR / "original.pgm"
    header = f"P5\n{IMAGE_W} {IMAGE_H}\n255\n"
    data = bytearray()
    data.extend(header.encode("ascii"))
    for row in img_orig:
        for val in row:
            data.append(val)
    orig_pgm.write_bytes(data)
    print(f"\n原始图像已保存: {orig_pgm}")


if __name__ == "__main__":
    main()
