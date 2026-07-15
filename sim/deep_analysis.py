#!/usr/bin/env python3
"""
Deep analysis: compare HW output against various hypotheses to find the bug.
"""
import math
from pathlib import Path

SIM_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/sim")
OUT_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/out")

# Load actual HW zigzag output
actual_zz = []
with open(SIM_DIR / "zz_out_all.txt") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) == 2:
            actual_zz.append(int(parts[1]))

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

def reconstruct_hw_quantized(block_idx):
    """Reverse zigzag to get row-major quantized block from zz output"""
    zz_block = actual_zz[block_idx*64:(block_idx+1)*64]
    block = [[0]*8 for _ in range(8)]
    for zz_pos in range(64):
        rm_idx = ZZ_V[zz_pos]
        r, c = rm_idx // 8, rm_idx % 8
        block[r][c] = zz_block[zz_pos]
    return block

def load_model_block(block_idx):
    """Load a block from the model (using same input as HW)"""
    # Load 02_rgb888.raw
    raw = (OUT_DIR / "02_rgb888.raw").read_bytes()
    IMAGE_W = 320
    by = (block_idx // (IMAGE_W // 8)) * 8
    bx = (block_idx % (IMAGE_W // 8)) * 8

    block = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            idx = ((by + r) * IMAGE_W + (bx + c)) * 3
            r_pix, g_pix, b_pix = raw[idx], raw[idx+1], raw[idx+2]
            r565, g565, b565 = r_pix & 0xF8, g_pix & 0xFC, b_pix & 0xF8
            y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
            block[r][c] = y - 128  # level shift
    return block

# AAN DCT (matches DCT1D.v exactly)
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

def model_quantize(coeffs):
    SHIFT = 15
    ROUND = 1 << 14
    result = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            S = int(round(32768 / Q_LUM[r][c]))
            prod = coeffs[r][c] * S
            shifted = (prod + ROUND) >> SHIFT
            result[r][c] = max(-2048, min(2047, shifted))
    return result

# ====================================================================
# MAIN ANALYSIS
# ====================================================================
print("=" * 70)
print("DEEP ANALYSIS: Comparing HW output vs hypotheses")
print("=" * 70)

# Analyze first 10 blocks
for bi in [0, 1, 2, 939]:
    hw_block = reconstruct_hw_quantized(bi)
    ls_block = load_model_block(bi)

    # Model DCT + quantize
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
    model_block = model_quantize(hw_dct)

    # Compute float DCT for reference
    def dct1d_float(inputs):
        N = 8
        result = []
        for k in range(N):
            alpha = math.sqrt(1.0/N) if k == 0 else math.sqrt(2.0/N)
            s = sum(inputs[n] * math.cos(math.pi/N * (n + 0.5) * k) for n in range(N))
            result.append(alpha * s)
        return result
    float_row = [dct1d_float(ls_block[r]) for r in range(8)]
    float_dct = [[0.0]*8 for _ in range(8)]
    for c in range(8):
        cv = [float_row[r][c] for r in range(8)]
        co = dct1d_float(cv)
        for r in range(8):
            float_dct[r][c] = co[r]
    ref_block = [[int(round(float_dct[r][c] / Q_LUM[r][c])) for c in range(8)] for r in range(8)]

    print(f"\n{'='*70}")
    print(f"BLOCK #{bi}")
    print(f"{'='*70}")

    # Compare model vs ref
    model_ref_match = sum(1 for r in range(8) for c in range(8) if model_block[r][c] == ref_block[r][c])
    print(f"Model vs Ref match: {model_ref_match}/64")

    # Compare HW vs model
    hw_model_match = sum(1 for r in range(8) for c in range(8) if hw_block[r][c] == model_block[r][c])
    print(f"HW vs Model match: {hw_model_match}/64")

    # Compare HW vs ref
    hw_ref_match = sum(1 for r in range(8) for c in range(8) if hw_block[r][c] == ref_block[r][c])
    print(f"HW vs Ref match: {hw_ref_match}/64")

    if bi == 939:  # worst block - detailed analysis
        print(f"\nDetailed comparison for block #{bi}:")
        print(f"{'RC':>6s} {'HW':>5s} {'Model':>6s} {'Ref':>5s}")
        for r in range(8):
            for c in range(8):
                marker = ""
                if hw_block[r][c] != model_block[r][c]:
                    marker = " ***"
                print(f"[{r}][{c}] {hw_block[r][c]:5d} {model_block[r][c]:6d} {ref_block[r][c]:5d}{marker}")

        # Test hypothesis: wrong quantization at specific positions
        print(f"\n--- Hypothesis testing ---")
        # For each position, try to find what Q value would make HW == model
        print("Positions where Model and Ref agree but HW differs:")
        for r in range(8):
            for c in range(8):
                if model_block[r][c] == ref_block[r][c] and hw_block[r][c] != model_block[r][c]:
                    # What Q value would explain the HW output?
                    dct_val = hw_dct[r][c]
                    hw_val = hw_block[r][c]
                    # Reverse: hw_val = round(dct_val / Q_effective)
                    if dct_val != 0:
                        Q_eff = abs(dct_val / hw_val) if hw_val != 0 else float('inf')
                        Q_expected = Q_LUM[r][c]
                        print(f"  [{r}][{c}]: DCT={dct_val:5d}, HW={hw_val:4d}, Model={model_block[r][c]:4d}, "
                              f"Q_eff={Q_eff:.1f}, Q_expected={Q_expected}")

print(f"\n{'='*70}")
print("BLOCK 0 DETAILED TRACE")
print(f"{'='*70}")

# For block 0, trace through the full pipeline step by step
bi = 0
hw_block = reconstruct_hw_quantized(bi)
ls_block = load_model_block(bi)

print("Level-shifted pixels (first block):")
for r in range(8):
    print("  " + " ".join(f"{v:4d}" for v in ls_block[r]))

row_dct = [dct1d_hw(ls_block[r]) for r in range(8)]
print("\nRow DCT output:")
for r in range(8):
    print("  " + " ".join(f"{v:5d}" for v in row_dct[r]))

# Check column DCT input truncation
print("\nColumn DCT input (after [9:0] truncation):")
col_in = [[0]*8 for _ in range(8)]
trunc_errs = 0
for r in range(8):
    for c in range(8):
        v12 = row_dct[r][c]
        v10 = v12 & 0x3FF
        if v10 & 0x200:
            v10 = v10 - 0x400
        col_in[r][c] = v10
        if v12 != v10:
            trunc_errs += 1
print(f"Truncation errors: {trunc_errs}")

print("\nColumn DCT output:")
hw_dct = [[0]*8 for _ in range(8)]
for c in range(8):
    cv = [col_in[r][c] for r in range(8)]
    co = dct1d_hw(cv)
    for r in range(8):
        hw_dct[r][c] = co[r]
for r in range(8):
    print("  " + " ".join(f"{v:5d}" for v in hw_dct[r]))

model_block = model_quantize(hw_dct)
print("\nModel quantized:")
for r in range(8):
    print("  " + " ".join(f"{v:4d}" for v in model_block[r]))

print("\nHW quantized (from zz_out):")
for r in range(8):
    print("  " + " ".join(f"{v:4d}" for v in hw_block[r]))

# Float reference
float_row = [dct1d_float(ls_block[r]) for r in range(8)]
float_dct_2d = [[0.0]*8 for _ in range(8)]
for c in range(8):
    cv = [float_row[r][c] for r in range(8)]
    co = dct1d_float(cv)
    for r in range(8):
        float_dct_2d[r][c] = co[r]

print("\nFloat DCT:")
for r in range(8):
    print("  " + " ".join(f"{v:6.1f}" for v in float_dct_2d[r]))

ref_block = [[int(round(float_dct_2d[r][c] / Q_LUM[r][c])) for c in range(8)] for r in range(8)]
print("\nRef quantized:")
for r in range(8):
    print("  " + " ".join(f"{v:4d}" for v in ref_block[r]))

print(f"\nModel vs Ref match: {sum(1 for r in range(8) for c in range(8) if model_block[r][c]==ref_block[r][c])}/64")
print(f"HW vs Model match: {sum(1 for r in range(8) for c in range(8) if hw_block[r][c]==model_block[r][c])}/64")
print(f"HW vs Ref match: {sum(1 for r in range(8) for c in range(8) if hw_block[r][c]==ref_block[r][c])}/64")
