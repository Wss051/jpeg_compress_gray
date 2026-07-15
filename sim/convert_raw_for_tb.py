#!/usr/bin/env python3
"""
把 D:\FPGA\hc\txys\txt 中的 RGB888 raw 文件裁剪成 320×320，
并转换为 RGB565 hex 文件，供 Verilog 测试平台 $readmemh 使用。

输出格式:
- 每行一个 4 位十六进制数，表示一个 16-bit RGB565 像素
- 共 320×320 = 102400 行
- 像素按行优先存储

用法:
    python convert_raw_for_tb.py
"""

from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "out"
DST_DIR = Path(__file__).parent
SRC_NAME = "02_rgb888.raw"
DST_NAME = "image_320x320_rgb565.hex"

SRC_W = 320
SRC_H = 320
DST_W = 320
DST_H = 320


def rgb888_to_rgb565(r: int, g: int, b: int) -> int:
    """R8G8B8 -> R5G6B5"""
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    return (r5 << 11) | (g6 << 5) | b5


def main():
    src_path = SRC_DIR / SRC_NAME
    dst_path = DST_DIR / DST_NAME

    raw_bytes = src_path.read_bytes()
    expected = SRC_W * SRC_H * 3
    if len(raw_bytes) != expected:
        raise ValueError(
            f"{src_path.name}: expected {expected} bytes, got {len(raw_bytes)}"
        )

    # 从原图读取 320×320
    start_y = 0
    start_x = 0

    lines = []
    for y in range(start_y, start_y + DST_H):
        for x in range(start_x, start_x + DST_W):
            idx = (y * DST_W + x) * 3
            r = raw_bytes[idx]
            g = raw_bytes[idx + 1]
            b = raw_bytes[idx + 2]
            rgb565 = rgb888_to_rgb565(r, g, b)
            lines.append(f"{rgb565:04X}\n")

    dst_path.write_text("".join(lines))
    print(f"Generated {dst_path}")
    print(f"  Source: {src_path} ({SRC_W}x{SRC_H})")
    print(f"  Output: {DST_W}x{DST_H}")
    print(f"  Pixels: {len(lines)}")


if __name__ == "__main__":
    main()
