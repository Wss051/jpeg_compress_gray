#!/usr/bin/env python3
"""
Bit-accurate Python model v2 — uses correct input file 02_rgb888.raw.
Compares model output against actual hardware zz_out_all.txt.
"""

import math
from pathlib import Path

SIM_DIR = Path(__file__).parent
OUT_DIR = Path(__file__).parent.parent / "out"

# ============================================================================
# Hardware AAN coefficients (×1024, same as DCT1D.v)
# ============================================================================
A0, A1, A2, A3, A4, A5, A6 = 362, 502, 473, 426, 284, 196, 100

def dct1d_hw(inputs):
    """Exact replica of DCT1D.v AAN butterfly (DIN_W=10, DOUT_W=12)"""
    x0,x1,x2,x3,x4,x5,x6,x7 = [int(v) for v in inputs]

    # Stage 1
    b0, b1 = x0+x7, x1+x6
    b2, b3 = x2+x5, x3+x4
    b4, b5 = x3-x4, x2-x5
    b6, b7 = x1-x6, x0-x7

    # Stage 2
    c0, c1 = b0+b3, b1+b2
    c2, c3 = b0-b3, b1-b2
    s_even_add = c0 + c1
    s_even_sub = c0 - c1

    # Stage 3
    y = [0]*8
    y[0] = s_even_add * A0
    y[4] = s_even_sub * A0
    y[2] = c2*A2 + c3*A5
    y[6] = c2*A5 - c3*A2
    y[1] = b7*A1 + b6*A3 + b5*A4 + b4*A6
    y[3] = b7*A3 - b6*A6 - b5*A1 - b4*A4
    y[5] = b7*A4 - b6*A1 + b5*A6 + b4*A3
    y[7] = b7*A6 - b6*A4 + b5*A3 - b4*A1

    # /1024 truncation toward zero (Verilog signed /)
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
    # Row DCT: 8-bit signed → DCT1D (via sign-extend to 10-bit)
    row_out = []
    for r in range(8):
        row_out.append(dct1d_hw(block[r]))

    # Column DCT: 12-bit → [9:0] → DCT1D
    # This is the critical truncation step
    col_in = [[0]*8 for _ in range(8)]
    for c in range(8):
        for r in range(8):
            v12 = row_out[r][c]
            # dct_in = tram_q[9:0] — take lower 10 bits
            v10 = v12 & 0x3FF
            if v10 & 0x200:
                v10 = v10 - 0x400
            col_in[r][c] = v10

    # Column DCT
    result = [[0]*8 for _ in range(8)]
    for c in range(8):
        col_vec = [col_in[r][c] for r in range(8)]
        col_res = dct1d_hw(col_vec)
        for r in range(8):
            result[r][c] = col_res[r]

    return result


# ============================================================================
# Quantizer
# ============================================================================
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

def quantize_hw(coeffs):
    result = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            S = int(round((1 << SHIFT) / Q_LUM[r][c]))
            prod = coeffs[r][c] * S
            prod_round = prod + ROUND
            shifted = prod_round >> SHIFT
            result[r][c] = max(-2048, min(2047, shifted))
    return result


# ===========================================================================
# Main
# ===========================================================================
def load_y_image():
    """Load 02_rgb888.raw, compute Y values (matching hardware Y.v)"""
    raw = OUT_DIR / "02_rgb888.raw"
    data = raw.read_bytes()
    pixels = []
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i+1], data[i+2]
        r565, g565, b565 = r & 0xF8, g & 0xFC, b & 0xF8
        y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
        pixels.append(y)
    return pixels  # list of 102400 values, row-major


def load_actual_zz():
    """Load zz_out_all.txt (actual hardware output)"""
    zz = []
    with open(SIM_DIR / "zz_out_all.txt") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                zz.append(int(parts[1]))
    return zz

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


def main():
    print("=" * 70)
    print("Bit-Accurate Model v2: Full Pipeline Trace")
    print("=" * 70)

    # Load image
    pixels = load_y_image()
    print(f"Loaded {len(pixels)} Y pixels")

    # Load actual hardware zigzag output
    actual_zz = load_actual_zz()
    print(f"Loaded {len(actual_zz)} hardware zz coefficients")

    # Process all blocks
    IMAGE_W, BLOCK = 320, 8
    N_BLOCKS = (IMAGE_W // BLOCK) * (IMAGE_W // BLOCK)
    model_zz_all = []
    block_errors = []
    max_block_err = 0
    worst_block = -1

    for bi in range(N_BLOCKS):
        by = (bi // (IMAGE_W // BLOCK)) * BLOCK
        bx = (bi % (IMAGE_W // BLOCK)) * BLOCK

        # Extract 8x8 block of Y values
        block_y = [[0]*8 for _ in range(8)]
        for r in range(8):
            for c in range(8):
                block_y[r][c] = pixels[(by + r) * IMAGE_W + (bx + c)]

        # Level shift
        block_ls = [[block_y[r][c] - 128 for c in range(8)] for r in range(8)]

        # Hardware-equivalent 2D DCT
        hw_dct = dct2d_hw(block_ls)

        # Quantize
        hw_quant = quantize_hw(hw_dct)

        # Zig-Zag scan (vertical-first)
        zz = [0]*64
        for pos in range(64):
            rm_idx = ZZ_V[pos]
            r, c = rm_idx // 8, rm_idx % 8
            zz[pos] = hw_quant[r][c]
        model_zz_all.extend(zz)

        # Compare with actual hardware for this block
        actual_block = actual_zz[bi*64:(bi+1)*64]
        err = sum(1 for i in range(64) if zz[i] != actual_block[i])
        block_errors.append(err)
        if err > max_block_err:
            max_block_err = err
            worst_block = bi

    # Overall statistics
    total_coeffs = len(model_zz_all)
    if total_coeffs == len(actual_zz):
        exact_match = sum(1 for i in range(total_coeffs) if model_zz_all[i] == actual_zz[i])
        large_err = sum(1 for i in range(total_coeffs) if abs(model_zz_all[i] - actual_zz[i]) > 1)

        print(f"\nOverall Statistics:")
        print(f"  Exact matches: {exact_match}/{total_coeffs} ({100*exact_match/total_coeffs:.1f}%)")
        print(f"  Large errors (>1): {large_err} ({100*large_err/total_coeffs:.2f}%)")
        print(f"  Blocks with errors: {sum(1 for e in block_errors if e > 0)}/{N_BLOCKS}")
        print(f"  Max block errors: {max_block_err}/64 (block {worst_block})")

        # Detailed worst block analysis
        print(f"\n{'='*70}")
        print(f"WORST BLOCK #{worst_block} ANALYSIS")
        print(f"{'='*70}")

        by = (worst_block // (IMAGE_W // BLOCK)) * BLOCK
        bx = (worst_block % (IMAGE_W // BLOCK)) * BLOCK

        print(f"\nBlock ({bx},{by}): Y values (unsigned):")
        for r in range(8):
            row_vals = [pixels[(by+r)*IMAGE_W + bx + c] for c in range(8)]
            print(f"  " + " ".join(f"{v:3d}" for v in row_vals))

        # Recompute with trace
        block_y = [[0]*8 for _ in range(8)]
        for r in range(8):
            for c in range(8):
                block_y[r][c] = pixels[(by+r)*IMAGE_W + (bx+c)]
        block_ls = [[block_y[r][c] - 128 for c in range(8)] for r in range(8)]

        print(f"\nLevel-shifted (signed):")
        for r in range(8):
            print(f"  " + " ".join(f"{v:4d}" for v in block_ls[r]))

        # Row DCT output
        row_dct = [dct1d_hw(block_ls[r]) for r in range(8)]
        print(f"\nRow DCT output (12-bit signed):")
        for r in range(8):
            print(f"  " + " ".join(f"{v:5d}" for v in row_dct[r]))
        row_max_mag = max(max(abs(v) for v in row) for row in row_dct)
        print(f"  Row DCT max |value|: {row_max_mag}")

        # Column DCT input (after [9:0] truncation)
        col_inputs = [[0]*8 for _ in range(8)]
        truncation_errors = []
        for r in range(8):
            for c in range(8):
                v12 = row_dct[r][c]
                v10 = v12 & 0x3FF
                if v10 & 0x200:
                    v10 = v10 - 0x400
                col_inputs[r][c] = v10
                if v12 != v10:
                    truncation_errors.append((r, c, v12, v10))

        if truncation_errors:
            print(f"\n*** TRUNCATION ERRORS in column DCT input ({len(truncation_errors)}):")
            for r, c, v12, v10 in truncation_errors[:20]:
                print(f"  [{r}][{c}]: 12-bit={v12:5d} → 10-bit[9:0]={v10:5d} (diff={v10-v12})")
        else:
            print(f"\nNo truncation errors (all row DCT values fit in 10-bit signed)")

        # Column DCT output
        hw_dct = [[0]*8 for _ in range(8)]
        for c in range(8):
            cv = [col_inputs[r][c] for r in range(8)]
            col_res = dct1d_hw(cv)
            for r in range(8):
                hw_dct[r][c] = col_res[r]

        print(f"\nFull 2D DCT output (12-bit signed):")
        for r in range(8):
            print(f"  " + " ".join(f"{v:5d}" for v in hw_dct[r]))

        # Quantized
        hw_quant = quantize_hw(hw_dct)
        print(f"\nQuantized output:")
        for r in range(8):
            print(f"  " + " ".join(f"{v:4d}" for v in hw_quant[r]))

        # Zigzag
        zz_model = [0]*64
        for zz_pos in range(64):
            rm_idx = ZZ_V[zz_pos]
            r, c = rm_idx // 8, rm_idx % 8
            zz_model[zz_pos] = hw_quant[r][c]

        actual = actual_zz[worst_block*64:(worst_block+1)*64]
        print(f"\nZigzag comparison (first 25):")
        print(f"{'Pos':>4s} {'Model':>6s} {'HW':>6s} {'Diff':>6s}")
        for i in range(25):
            d = zz_model[i] - actual[i]
            m = " ***" if d != 0 else ""
            print(f"{i:4d} {zz_model[i]:6d} {actual[i]:6d} {d:+6d}{m}")

        # Also compute float DCT for comparison
        print(f"\n{'='*70}")
        print(f"FLOAT DCT REFERENCE (for comparison)")
        print(f"{'='*70}")

        def dct1d_float(inputs):
            N = 8
            result = []
            for k in range(N):
                alpha = math.sqrt(1.0/N) if k == 0 else math.sqrt(2.0/N)
                s = sum(inputs[n] * math.cos(math.pi/N * (n + 0.5) * k) for n in range(N))
                result.append(alpha * s)
            return result

        float_row = [dct1d_float(block_ls[r]) for r in range(8)]
        float_dct = [[0.0]*8 for _ in range(8)]
        for c in range(8):
            cv = [float_row[r][c] for r in range(8)]
            co = dct1d_float(cv)
            for r in range(8):
                float_dct[r][c] = co[r]

        print(f"\nFloat DCT:")
        for r in range(8):
            print(f"  " + " ".join(f"{v:6.2f}" for v in float_dct[r]))

        # Quantize float DCT
        float_quant = [[int(round(float_dct[r][c] / Q_LUM[r][c])) for c in range(8)] for r in range(8)]
        print(f"\nFloat quantized:")
        for r in range(8):
            print(f"  " + " ".join(f"{v:4d}" for v in float_quant[r]))

        float_zz = [0]*64
        for zz_pos in range(64):
            rm_idx = ZZ_V[zz_pos]
            r, c = rm_idx // 8, rm_idx % 8
            float_zz[zz_pos] = float_quant[r][c]

        print(f"\nFloat zigzag (first 25):")
        for i in range(25):
            d = float_zz[i] - actual[i]
            m = " ***" if abs(d) > 1 else ""
            print(f"{i:4d} {float_zz[i]:6.1f} {actual[i]:6d} {float_zz[i]-actual[i]:+6.1f}{m}")

        # Quantify the error: HW DCT vs Float DCT
        print(f"\nHW vs Float DCT comparison:")
        for r in range(8):
            for c in range(8):
                diff = hw_dct[r][c] - float_dct[r][c]
                if abs(diff) > 2:
                    print(f"  [{r}][{c}]: HW={hw_dct[r][c]:5d}, Float={float_dct[r][c]:7.2f}, diff={diff:+.1f}")

    else:
        print(f"Count mismatch: model={total_coeffs}, actual={len(actual_zz)}")


if __name__ == "__main__":
    main()
