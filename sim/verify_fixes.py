#!/usr/bin/env python3
"""
Verify the fixes: rounding DCT + 12-bit column DCT input.
Compares hardware output against fixed model.
"""
from pathlib import Path

SIM_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/sim")
OUT_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/out")

A0, A1, A2, A3, A4, A5, A6 = 362, 502, 473, 426, 284, 196, 100

def dct1d_fixed(inputs):
    """DCT1D with ROUNDING (y+512)>>>10 instead of y/1024 truncation"""
    x0,x1,x2,x3,x4,x5,x6,x7 = [int(v) for v in inputs]
    b0,b1,b2,b3 = x0+x7, x1+x6, x2+x5, x3+x4
    b4,b5,b6,b7 = x3-x4, x2-x5, x1-x6, x0-x7
    c0,c1 = b0+b3, b1+b2
    c2,c3 = b0-b3, b1-b2
    se_add = c0 + c1
    se_sub = c0 - c1
    y = [
        se_add * A0,
        b7*A1 + b6*A3 + b5*A4 + b4*A6,
        c2*A2 + c3*A5,
        b7*A3 - b6*A6 - b5*A1 - b4*A4,
        se_sub * A0,
        b7*A4 - b6*A1 + b5*A6 + b4*A3,
        c2*A5 - c3*A2,
        b7*A6 - b6*A4 + b5*A3 - b4*A1,
    ]
    # FIX: (y+512)>>10 rounding instead of y/1024 truncation
    return [max(-2048, min(2047, (v + 512) >> 10)) for v in y]

def dct1d_old(inputs):
    """OLD DCT1D with y/1024 truncation"""
    x0,x1,x2,x3,x4,x5,x6,x7 = [int(v) for v in inputs]
    b0,b1,b2,b3 = x0+x7, x1+x6, x2+x5, x3+x4
    b4,b5,b6,b7 = x3-x4, x2-x5, x1-x6, x0-x7
    c0,c1 = b0+b3, b1+b2
    c2,c3 = b0-b3, b1-b2
    se_add = c0 + c1
    se_sub = c0 - c1
    y = [
        se_add * A0,
        b7*A1 + b6*A3 + b5*A4 + b4*A6,
        c2*A2 + c3*A5,
        b7*A3 - b6*A6 - b5*A1 - b4*A4,
        se_sub * A0,
        b7*A4 - b6*A1 + b5*A6 + b4*A3,
        c2*A5 - c3*A2,
        b7*A6 - b6*A4 + b5*A3 - b4*A1,
    ]
    return [max(-2048, min(2047, int(v/1024))) for v in y]

def compute_model_block(bi, use_rounding=True, use_12bit_col=True):
    """Compute a block with the specified fixes"""
    raw = (OUT_DIR / "02_rgb888.raw").read_bytes()
    IMAGE_W = 320
    by = (bi // (IMAGE_W // 8)) * 8
    bx = (bi % (IMAGE_W // 8)) * 8

    ls = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            idx = ((by+r)*IMAGE_W + (bx+c)) * 3
            r_pix, g_pix, b_pix = raw[idx], raw[idx+1], raw[idx+2]
            y_pix = (((r_pix&0xF8)*77 + (g_pix&0xFC)*150 + (b_pix&0xF8)*29) >> 8)
            ls[r][c] = y_pix - 128

    dct_fn = dct1d_fixed if use_rounding else dct1d_old

    # Row DCT
    row_dct = [dct_fn(ls[r]) for r in range(8)]

    # Column DCT input
    col_in = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            v12 = row_dct[r][c]
            if use_12bit_col:
                col_in[r][c] = v12  # full 12-bit pass through (FIX)
            else:
                # OLD: truncate to 10-bit
                v10 = v12 & 0x3FF
                if v10 & 0x200:
                    v10 = v10 - 0x400
                col_in[r][c] = v10

    # Column DCT
    hw_dct = [[0]*8 for _ in range(8)]
    for c in range(8):
        cv = [col_in[r][c] for r in range(8)]
        co = dct_fn(cv)
        for r in range(8):
            hw_dct[r][c] = co[r]

    # Quantize
    Q_LUM = [
        [16,11,10,16,24,40,51,61],[12,12,14,19,26,58,60,55],
        [14,13,16,24,40,57,69,56],[14,17,22,29,51,87,80,62],
        [18,22,37,56,68,109,103,77],[24,35,55,64,81,104,113,92],
        [49,64,78,87,103,121,120,101],[72,92,95,98,112,100,103,99]
    ]
    result = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            S = int(round(32768 / Q_LUM[r][c]))
            prod = hw_dct[r][c] * S
            result[r][c] = max(-2048, min(2047, (prod + 16384) >> 15))
    return result

# Load actual HW data
actual_zz = []
with open(SIM_DIR / "zz_out_all.txt") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) == 2:
            actual_zz.append(int(parts[1]))

ZZ_V = [
    0,8,1,2,9,16,24,17,10,3,4,11,18,25,32,40,
    33,26,19,12,5,6,13,20,27,34,41,48,56,49,42,35,
    28,21,14,7,15,22,29,36,43,50,57,58,51,44,37,30,
    23,31,38,45,52,59,60,53,46,39,47,54,61,62,55,63
]

print("=" * 70)
print("VERIFYING FIXES: Old vs New model vs HW")
print("=" * 70)

for label, rounding, col12 in [
    ("OLD (y/1024 trunc, 10-bit col)", False, False),
    ("FIX (rounding, 12-bit col)", True, True),
]:
    match_total = 0
    err_total = 0
    large_err = 0
    N = 1600
    for bi in range(N):
        model = compute_model_block(bi, use_rounding=rounding, use_12bit_col=col12)
        hw_zz = actual_zz[bi*64:(bi+1)*64]
        n_match = 0
        for r in range(8):
            for c in range(8):
                rm_idx = r*8 + c
                zz_pos = ZZ_V.index(rm_idx)
                if hw_zz[zz_pos] == model[r][c]:
                    n_match += 1
                elif abs(hw_zz[zz_pos] - model[r][c]) > 2:
                    large_err += 1
        match_total += n_match
        err_total += (64 - n_match)

    print(f"\n{label}:")
    print(f"  Exact matches: {match_total}/{N*64} ({100*match_total/(N*64):.1f}%)")
    print(f"  Total errors: {err_total}")
    print(f"  Large errors (>2): {large_err}")

    # Perfect blocks
    perfect = 0
    for bi in range(N):
        model = compute_model_block(bi, use_rounding=rounding, use_12bit_col=col12)
        hw_zz = actual_zz[bi*64:(bi+1)*64]
        ok = all(hw_zz[ZZ_V.index(r*8+c)] == model[r][c] for r in range(8) for c in range(8))
        if ok:
            perfect += 1
    print(f"  Perfect blocks: {perfect}/{N}")

print(f"\n{'='*70}")
print("CONCLUSION")
print(f"{'='*70}")
print("The fixes address:")
print("  1. DCT1D: truncation→rounding (y+512)>>>10")
print("  2. dct_2d: column DCT 10-bit→12-bit full precision")
print("If the model with fixes matches the HW significantly better,")
print("these are the correct fixes to apply to the Verilog.")
