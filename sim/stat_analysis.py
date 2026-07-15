#!/usr/bin/env python3
"""
Statistical analysis of HW errors across all 1600 blocks.
Find patterns in which blocks fail and which don't.
"""
from pathlib import Path

SIM_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/sim")
OUT_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/out")

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

# Load HW zz output
actual_zz = []
with open(SIM_DIR / "zz_out_all.txt") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) == 2:
            actual_zz.append(int(parts[1]))

# Load image Y values
raw = (OUT_DIR / "02_rgb888.raw").read_bytes()
IMAGE_W = 320
pixels_y = []
for i in range(0, len(raw), 3):
    r, g, b = raw[i], raw[i+1], raw[i+2]
    r565, g565, b565 = r & 0xF8, g & 0xFC, b & 0xF8
    y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
    pixels_y.append(y)

# AAN DCT model
A0, A1, A2, A3, A4, A5, A6 = 362, 502, 473, 426, 284, 196, 100

def dct1d_hw(inputs):
    x0,x1,x2,x3,x4,x5,x6,x7 = [int(v) for v in inputs]
    b0,b1,b2,b3 = x0+x7, x1+x6, x2+x5, x3+x4
    b4,b5,b6,b7 = x3-x4, x2-x5, x1-x6, x0-x7
    c0,c1 = b0+b3, b1+b2
    c2,c3 = b0-b3, b1-b2
    s_even_add = c0 + c1
    s_even_sub = c0 - c1
    y0 = s_even_add * A0
    y4 = s_even_sub * A0
    y2 = c2*A2 + c3*A5
    y6 = c2*A5 - c3*A2
    y1 = b7*A1 + b6*A3 + b5*A4 + b4*A6
    y3 = b7*A3 - b6*A6 - b5*A1 - b4*A4
    y5 = b7*A4 - b6*A1 + b5*A6 + b4*A3
    y7 = b7*A6 - b6*A4 + b5*A3 - b4*A1
    y = [y0,y1,y2,y3,y4,y5,y6,y7]
    return [max(-2048,min(2047,int(v/1024))) for v in y]

def compute_model_block(bi):
    by = (bi // (IMAGE_W // 8)) * 8
    bx = (bi % (IMAGE_W // 8)) * 8
    ls_block = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            ls_block[r][c] = pixels_y[(by+r)*IMAGE_W + (bx+c)] - 128
    row_dct = [dct1d_hw(ls_block[r]) for r in range(8)]
    col_in = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            v12 = row_dct[r][c]
            v10 = v12 & 0x3FF
            if v10 & 0x200:
                v10 = v10 - 0x400
            col_in[r][c] = v10
    hw_dct = [[0]*8 for _ in range(8)]
    for c in range(8):
        cv = [col_in[r][c] for r in range(8)]
        co = dct1d_hw(cv)
        for r in range(8):
            hw_dct[r][c] = co[r]
    # Quantize
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
    SHIFT = 15
    ROUND = 1 << 14
    result = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            S = int(round(32768 / Q_LUM[r][c]))
            prod = hw_dct[r][c] * S
            shifted = (prod + ROUND) >> SHIFT
            result[r][c] = max(-2048, min(2047, shifted))
    return result

# Analyze all blocks
print("=" * 70)
print("STATISTICAL ERROR ANALYSIS ACROSS ALL 1600 BLOCKS")
print("=" * 70)

N_BLOCKS = 1600
block_errors = []  # (block_idx, n_errors, row_var, max_row_dct)
perfect_blocks = []
error_blocks = []

for bi in range(N_BLOCKS):
    hw_zz = actual_zz[bi*64:(bi+1)*64]
    model_block = compute_model_block(bi)

    # Compare
    n_err = 0
    for r in range(8):
        for c in range(8):
            rm_idx = r * 8 + c
            # Map to zigzag position
            # zz_pos where ZZ_V[zz_pos] = rm_idx
            zz_pos = ZZ_V.index(rm_idx)
            if hw_zz[zz_pos] != model_block[r][c]:
                n_err += 1

    # Block statistics
    by = (bi // (IMAGE_W // 8)) * 8
    bx = (bi % (IMAGE_W // 8)) * 8
    block_pixels = [pixels_y[(by+r)*IMAGE_W + bx + c] for r in range(8) for c in range(8)]
    row_var = max(block_pixels) - min(block_pixels)  # pixel range in block

    block_errors.append((bi, n_err, row_var, bx, by))
    if n_err == 0:
        perfect_blocks.append(bi)
    else:
        error_blocks.append((bi, n_err, row_var, bx, by))

print(f"\nPerfect blocks (0 errors): {len(perfect_blocks)}/{N_BLOCKS}")
print(f"Blocks with errors: {len(error_blocks)}/{N_BLOCKS}")

# Analyze error patterns
print(f"\n--- Error distribution ---")
err_counts = [e[1] for e in error_blocks]
print(f"Max errors in a block: {max(err_counts)}")
print(f"Mean errors per error block: {sum(err_counts)/len(err_counts):.1f}")

# Check if errors correlate with pixel variance
print(f"\n--- Correlation with pixel range ---")
hi_var_blocks = [(bi, n, v, bx, by) for bi, n, v, bx, by in error_blocks if v > 100]
lo_var_blocks = [(bi, n, v, bx, by) for bi, n, v, bx, by in error_blocks if v <= 100]
print(f"High-variance blocks (>100 range): {len(hi_var_blocks)} error blocks")
print(f"Low-variance blocks (<=100 range): {len(lo_var_blocks)} error blocks")
if hi_var_blocks:
    print(f"  High-var mean errors: {sum(e[1] for e in hi_var_blocks)/len(hi_var_blocks):.1f}")
if lo_var_blocks:
    print(f"  Low-var mean errors: {sum(e[1] for e in lo_var_blocks)/len(lo_var_blocks):.1f}")

# Check if errors correlate with block position
print(f"\n--- Block position analysis ---")
# First row, first column, etc.
first_row_errs = [(bi, n) for bi, n, v, bx, by in error_blocks if by == 0]
first_col_errs = [(bi, n) for bi, n, v, bx, by in error_blocks if bx == 0]
print(f"First row (y=0) error blocks: {len(first_row_errs)}")
print(f"First col (x=0) error blocks: {len(first_col_errs)}")

# Check if block 0 specifically has errors
block0 = next((e for e in error_blocks if e[0] == 0), None)
if block0:
    print(f"Block 0: {block0[1]} errors (pixel range={block0[2]})")
else:
    print("Block 0: PERFECT")

# Check block 1
block1 = next((e for e in error_blocks if e[0] == 1), None)
if block1:
    print(f"Block 1: {block1[1]} errors (pixel range={block1[2]})")
else:
    print("Block 1: PERFECT")

# Pattern: do errors cluster in certain rows of blocks?
print(f"\n--- Block row error pattern ---")
for block_row in range(40):  # 40 block rows
    start = block_row * 40
    end = start + 40
    row_errs = [e for e in error_blocks if start <= e[0] < end]
    total_errs = sum(e[1] for e in row_errs)
    n_bad = len(row_errs)
    print(f"  Block-row {block_row:2d}: {n_bad:2d} bad blocks, {total_errs:4d} total errors", end="")
    if n_bad > 30:
        print(" ***")
    else:
        print()

# Per zigzag position error rate
print(f"\n--- Per zigzag position error rate ---")
zz_pos_errors = [0] * 64
for bi, n_err, v, bx, by in error_blocks:
    hw_zz = actual_zz[bi*64:(bi+1)*64]
    model_block = compute_model_block(bi)
    for zz_pos in range(64):
        rm_idx = ZZ_V[zz_pos]
        r, c = rm_idx // 8, rm_idx % 8
        if hw_zz[zz_pos] != model_block[r][c]:
            zz_pos_errors[zz_pos] += 1

print(f"{'ZZ Pos':>6s} {'Errors':>8s} {'Rate':>8s}")
for zz_pos in range(64):
    rate = zz_pos_errors[zz_pos] / N_BLOCKS * 100
    marker = " ***" if rate > 50 else ""
    print(f"{zz_pos:6d} {zz_pos_errors[zz_pos]:8d} {rate:7.1f}%{marker}")

# Check if errors are systematic (same sign/direction)
print(f"\n--- Error direction analysis (first 10 error blocks) ---")
for bi, n_err, v, bx, by in error_blocks[:10]:
    hw_zz = actual_zz[bi*64:(bi+1)*64]
    model_block = compute_model_block(bi)
    pos_errs = 0
    neg_errs = 0
    for zz_pos in range(64):
        rm_idx = ZZ_V[zz_pos]
        r, c = rm_idx // 8, rm_idx % 8
        if hw_zz[zz_pos] != model_block[r][c]:
            if hw_zz[zz_pos] > model_block[r][c]:
                pos_errs += 1
            else:
                neg_errs += 1
    print(f"  Block {bi}: {n_err} errors, {pos_errs} HW>Model, {neg_errs} HW<Model")
