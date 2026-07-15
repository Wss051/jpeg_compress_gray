#!/usr/bin/env python3
"""
对比原始图像（转灰度）与解码后的灰度图像，计算 PSNR/MSE。
"""

import sys
import math
from pathlib import Path


def rgb_to_y(r: int, g: int, b: int) -> int:
    """BT.601，与 Verilog Y.v 一致"""
    r565 = r & 0xF8
    g565 = g & 0xFC
    b565 = b & 0xF8
    y = (r565 * 77 + g565 * 150 + b565 * 29) >> 8
    return max(0, min(255, y))


def compute_psnr(img1, img2):
    if len(img1) != len(img2):
        raise ValueError("Image size mismatch")
    mse = sum((a - b) ** 2 for a, b in zip(img1, img2)) / len(img1)
    if mse == 0:
        return float('inf')
    return 10 * math.log10(255.0 * 255.0 / mse)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <original.png> <decoded.png>")
        sys.exit(1)

    from PIL import Image

    orig_path = Path(sys.argv[1])
    dec_path = Path(sys.argv[2])

    orig = Image.open(orig_path).convert("RGB")
    dec = Image.open(dec_path).convert("L")

    if orig.size != dec.size:
        print(f"Size mismatch: {orig.size} vs {dec.size}")
        sys.exit(1)

    orig_y = [rgb_to_y(r, g, b) for r, g, b in orig.getdata()]
    dec_y = list(dec.getdata())

    mse = sum((a - b) ** 2 for a, b in zip(orig_y, dec_y)) / len(orig_y)
    psnr = compute_psnr(orig_y, dec_y)

    # 保存差异图
    diff = [abs(a - b) for a, b in zip(orig_y, dec_y)]
    diff_img = Image.new("L", orig.size)
    diff_img.putdata(diff)
    diff_path = dec_path.with_name(dec_path.stem + "_diff.png")
    diff_img.save(diff_path)

    print(f"Original : {orig_path}")
    print(f"Decoded  : {dec_path}")
    print(f"Size     : {orig.size[0]}x{orig.size[1]}")
    print(f"MSE      : {mse:.2f}")
    print(f"PSNR     : {psnr:.2f} dB")
    print(f"Diff map : {diff_path}")


if __name__ == "__main__":
    main()
