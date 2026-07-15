#!/usr/bin/env python3
"""
Pipeline 中间数据对比脚本.
从 zz_out_all.txt 反向推演 HW 的量化/DCT 输出, 与 bit-accurate 模型逐级对比,
定位数据路径中首次出现偏差的模块.
"""
import math
from pathlib import Path

SIM_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/sim")
OUT_DIR = Path("D:/FPGA/hc/jpeg_compress_gray/out")

# ===== 配置 =====
Q_LUM = [
    [16,11,10,16,24,40,51,61],[12,12,14,19,26,58,60,55],
    [14,13,16,24,40,57,69,56],[14,17,22,29,51,87,80,62],
    [18,22,37,56,68,109,103,77],[24,35,55,64,81,104,113,92],
    [49,64,78,87,103,121,120,101],[72,92,95,98,112,100,103,99]
]
ZZ_V = [
    0,8,1,2,9,16,24,17,10,3,4,11,18,25,32,40,
    33,26,19,12,5,6,13,20,27,34,41,48,56,49,42,35,
    28,21,14,7,15,22,29,36,43,50,57,58,51,44,37,30,
    23,31,38,45,52,59,60,53,46,39,47,54,61,62,55,63
]
SHIFT, ROUND = 15, 1 << 14

# AAN coefficients
A0,A1,A2,A3,A4,A5,A6 = 362,502,473,426,284,196,100

def dct1d_model(inputs):
    """Bit-accurate DCT1D with rounding (matches fixed RTL)"""
    x0,x1,x2,x3,x4,x5,x6,x7 = [int(v) for v in inputs]
    b0,b1,b2,b3 = x0+x7, x1+x6, x2+x5, x3+x4
    b4,b5,b6,b7 = x3-x4, x2-x5, x1-x6, x0-x7
    c0,c1 = b0+b3, b1+b2
    c2,c3 = b0-b3, b1-b2
    se_add, se_sub = c0+c1, c0-c1
    y = [se_add*A0, b7*A1+b6*A3+b5*A4+b4*A6, c2*A2+c3*A5,
         b7*A3-b6*A6-b5*A1-b4*A4, se_sub*A0, b7*A4-b6*A1+b5*A6+b4*A3,
         c2*A5-c3*A2, b7*A6-b6*A4+b5*A3-b4*A1]
    return [max(-2048, min(2047, (v+512)>>10)) for v in y]

def compute_model_full(block_idx):
    """Full model pipeline for one block: pixel → DCT → quantize → zigzag"""
    raw = (OUT_DIR / "02_rgb888.raw").read_bytes()
    W = 320
    by = (block_idx // 40) * 8
    bx = (block_idx % 40) * 8
    # Level-shifted pixels
    ls = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            idx = ((by+r)*W + (bx+c)) * 3
            r_p, g_p, b_p = raw[idx], raw[idx+1], raw[idx+2]
            y = (((r_p&0xF8)*77 + (g_p&0xFC)*150 + (b_p&0xF8)*29) >> 8)
            ls[r][c] = y - 128
    # Row DCT
    row_dct = [dct1d_model(ls[r]) for r in range(8)]
    # Column DCT (12-bit full precision)
    col_dct = [[0]*8 for _ in range(8)]
    for c in range(8):
        cv = [row_dct[r][c] for r in range(8)]
        co = dct1d_model(cv)
        for r in range(8):
            col_dct[r][c] = co[r]
    # Quantize
    quant = [[0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            S = int(round(32768 / Q_LUM[r][c]))
            prod = col_dct[r][c] * S
            quant[r][c] = max(-2048, min(2047, (prod + ROUND) >> SHIFT))
    # Zigzag
    zz = [0]*64
    for pos in range(64):
        rm = ZZ_V[pos]
        r, c = rm // 8, rm % 8
        zz[pos] = quant[r][c]
    return ls, row_dct, col_dct, quant, zz


def estimate_hw_dct(hw_quant_block):
    """从 HW 量化值反推 DCT 系数 (近似, 忽略舍入)"""
    hw_dct = [[0.0]*8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            S = int(round(32768 / Q_LUM[r][c]))
            if S > 0:
                hw_dct[r][c] = hw_quant_block[r][c] * 32768.0 / S
    return hw_dct


def main():
    print("=" * 70)
    print("PIPELINE COMPARISON: HW vs Model (Bit-Accurate)")
    print("=" * 70)

    # Load HW zz output
    actual_zz = []
    with open(SIM_DIR / "zz_out_all.txt") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                actual_zz.append(int(parts[1]))

    # Analyze selected blocks
    blocks_to_check = [0, 1, 2, 939]  # 0=first, 1=perfect neighbor, 939=worst

    for bi in blocks_to_check:
        ls, row_dct_m, col_dct_m, quant_m, zz_m = compute_model_full(bi)

        # HW zigzag → reconstruct quantized block
        hw_zz = actual_zz[bi*64:(bi+1)*64]
        hw_quant = [[0]*8 for _ in range(8)]
        for pos in range(64):
            rm = ZZ_V[pos]
            r, c = rm // 8, rm % 8
            hw_quant[r][c] = hw_zz[pos]

        print(f"\n{'='*70}")
        print(f"BLOCK #{bi} (bx={(bi%40)*8}, by={(bi//40)*8})")
        print(f"{'='*70}")

        # Compare at each pipeline stage
        zz_match = sum(1 for i in range(64) if zz_m[i] == hw_zz[i])
        quant_match = sum(1 for r in range(8) for c in range(8)
                         if quant_m[r][c] == hw_quant[r][c])

        print(f"\n  Zigzag match:  {zz_match}/64 ({100*zz_match/64:.0f}%)")
        print(f"  Quant match:   {quant_match}/64 ({100*quant_match/64:.0f}%)")

        # If quant mismatch, estimate HW DCT and compare
        if quant_match < 64:
            hw_dct_est = estimate_hw_dct(hw_quant)

            # Find positions with largest DCT discrepancy
            print(f"\n  Top DCT discrepancies (HW_est vs Model):")
            diffs = []
            for r in range(8):
                for c in range(8):
                    diff = abs(hw_dct_est[r][c] - col_dct_m[r][c])
                    if diff > 2:
                        diffs.append((r, c, col_dct_m[r][c], hw_dct_est[r][c], diff))
            diffs.sort(key=lambda x: -x[4])

            for r, c, model_v, hw_v, diff in diffs[:10]:
                print(f"    [{r}][{c}]: Model={model_v:7.1f}, HW_est={hw_v:7.1f}, "
                      f"diff={diff:7.1f}")

            # Detailed: show full 8x8 HW_est DCT
            if bi == 0:
                print(f"\n  HW Estimated DCT (8x8):")
                for r in range(8):
                    print(f"    " + " ".join(f"{hw_dct_est[r][c]:7.1f}" for c in range(8)))

                print(f"\n  Model DCT (8x8):")
                for r in range(8):
                    print(f"    " + " ".join(f"{col_dct_m[r][c]:7.1f}" for c in range(8)))

                # Ratio analysis to find systematic error
                print(f"\n  Error type analysis:")
                for r in range(8):
                    for c in range(8):
                        m = col_dct_m[r][c]
                        h = hw_dct_est[r][c]
                        if abs(m) > 5 and abs(h) > 5:
                            ratio = h / m
                            print(f"    [{r}][{c}]: ratio HW/Model = {ratio:.3f}")

        else:
            print(f"  OK Quantizer output matches model")

    print(f"\n{'='*70}")
    print("DIAGNOSIS:")
    print(f"{'='*70}")
    print("If Quant match is high but Zigzag match is low:")
    print("  → Bug in zigzag_scan module (address mapping)")
    print("If Quant match is low and DCT discrepancy is systematic (constant ratio):")
    print("  → Bug in quantizer (wrong scale factors)")
    print("If Quant match is low and DCT discrepancy is random/scattered:")
    print("  → Bug in DCT1D/dct_2d (butterfly computation or state machine)")
    print("If Block 0 wrong but Block 1 correct:")
    print("  → Pipeline initialization issue (first-block state anomaly)")


if __name__ == "__main__":
    main()
