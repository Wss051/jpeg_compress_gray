#!/usr/bin/env python3
"""
PNG 解码器（纯 Python，无 Pillow 依赖）
支持 RGB/RGBA 灰度 PNG，输出 RGB888 raw 和 RGB565 hex
"""

import sys
import struct
import zlib
from pathlib import Path
import itertools


def read_png(filepath):
    """读取 PNG 文件，返回 (width, height, mode, pixels)"""
    with open(filepath, 'rb') as f:
        # PNG signature
        sig = f.read(8)
        if sig != b'\x89PNG\r\n\x1a\n':
            raise ValueError("Not a PNG file")

        chunks = []
        while True:
            length = struct.unpack('>I', f.read(4))[0]
            chunk_type = f.read(4)
            data = f.read(length)
            crc = f.read(4)
            chunks.append((chunk_type, data))
            if chunk_type == b'IEND':
                break

        # Parse IHDR
        ihdr_type, ihdr_data = chunks[0]
        assert ihdr_type == b'IHDR'
        width, height, bit_depth, color_type, compression, filter_method, interlace = \
            struct.unpack('>IIBBBBB', ihdr_data)

        # Determine mode
        if color_type == 0:  # Grayscale
            mode = 'L'
            channels = 1
        elif color_type == 2:  # RGB
            mode = 'RGB'
            channels = 3
        elif color_type == 3:  # Indexed (palette)
            mode = 'P'
            channels = 1
        elif color_type == 4:  # Grayscale + Alpha
            mode = 'LA'
            channels = 2
        elif color_type == 6:  # RGBA
            mode = 'RGBA'
            channels = 4  # 4 bytes per pixel (R,G,B,A), we drop A
        else:
            raise ValueError(f"Unsupported color type: {color_type}")

        # Get palette if indexed
        palette = None
        for ctype, cdata in chunks:
            if ctype == b'PLTE':
                palette = [tuple(cdata[i:i+3]) for i in range(0, len(cdata), 3)]
                break

        # Decompress IDAT chunks
        idat_data = b''.join(cdata for ctype, cdata in chunks if ctype == b'IDAT')
        decompressed = zlib.decompress(idat_data)

        # Reconstruct image
        stride = width * channels
        if color_type == 3:
            stride = width  # 1 byte per pixel for indexed

        rows = []
        pos = 0
        for y in range(height):
            filter_type = decompressed[pos]
            pos += 1
            row = list(decompressed[pos:pos + stride])
            pos += stride

            # Apply filter
            if filter_type == 0:  # None
                pass
            elif filter_type == 1:  # Sub
                for x in range(channels, stride):
                    row[x] = (row[x] + row[x - channels]) & 0xFF
            elif filter_type == 2:  # Up
                if y > 0:
                    for x in range(stride):
                        row[x] = (row[x] + rows[-1][x]) & 0xFF
            elif filter_type == 3:  # Average
                for x in range(stride):
                    a = row[x - channels] if x >= channels else 0
                    b = rows[-1][x] if y > 0 else 0
                    row[x] = (row[x] + (a + b) // 2) & 0xFF
            elif filter_type == 4:  # Paeth
                for x in range(stride):
                    a = row[x - channels] if x >= channels else 0
                    b = rows[-1][x] if y > 0 else 0
                    c = rows[-1][x - channels] if y > 0 and x >= channels else 0
                    row[x] = (row[x] + paeth_predictor(a, b, c)) & 0xFF

            rows.append(row)

        # Convert to RGB tuples
        pixels = []
        for row in rows:
            if mode == 'RGB':
                for i in range(0, len(row), 3):
                    pixels.append((row[i], row[i+1], row[i+2]))
            elif mode == 'RGBA':
                for i in range(0, len(row), 4):
                    pixels.append((row[i], row[i+1], row[i+2]))
            elif mode == 'L':
                for v in row:
                    pixels.append((v, v, v))
            elif mode == 'LA':
                for i in range(0, len(row), 2):
                    v = row[i]
                    pixels.append((v, v, v))
            elif mode == 'P':
                if palette is None:
                    raise ValueError("Indexed PNG without palette")
                for idx in row:
                    pixels.append(palette[idx])

        return width, height, mode, pixels


def paeth_predictor(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    else:
        return c


def rgb888_to_rgb565(r, g, b):
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    return (r5 << 11) | (g6 << 5) | b5


def resize_crop(pixels, src_w, src_h, dst_w, dst_h):
    """简单最近邻缩放 + 中心裁剪"""
    if src_w == dst_w and src_h == dst_h:
        return pixels

    # Scale to fit dst in both dimensions
    scale_x = dst_w / src_w
    scale_y = dst_h / src_h
    scale = max(scale_x, scale_y)

    new_w = int(src_w * scale)
    new_h = int(src_h * scale)

    # Resize using nearest neighbor
    new_pixels = []
    for y in range(new_h):
        src_y = int(y / scale)
        src_y = min(src_y, src_h - 1)
        for x in range(new_w):
            src_x = int(x / scale)
            src_x = min(src_x, src_w - 1)
            idx = src_y * src_w + src_x
            new_pixels.append(pixels[idx])

    # Center crop
    left = (new_w - dst_w) // 2
    top = (new_h - dst_h) // 2
    cropped = []
    for y in range(top, top + dst_h):
        for x in range(left, left + dst_w):
            idx = y * new_w + x
            cropped.append(new_pixels[idx])

    return cropped


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.png> <output_prefix>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_prefix = Path(sys.argv[2])
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    width, height, mode, pixels = read_png(str(input_path))
    print(f"Input: {input_path} ({width}x{height}, {mode})")

    # Resize/crop to 320x320
    target_size = (320, 320)
    if (width, height) != target_size:
        pixels = resize_crop(pixels, width, height, *target_size)
        print(f"Resized to {target_size[0]}x{target_size[1]}")
    else:
        print(f"Already {target_size[0]}x{target_size[1]}, no resize needed")

    assert len(pixels) == 320 * 320, f"Expected 102400 pixels, got {len(pixels)}"

    # Write RGB888 raw and RGB565 hex
    raw_bytes = bytearray()
    hex_lines = []
    for r, g, b in pixels:
        raw_bytes.extend([r, g, b])
        hex_lines.append(f"{rgb888_to_rgb565(r, g, b):04X}\n")

    raw_path = output_prefix.with_name(output_prefix.name + "_rgb888.raw")
    hex_path = output_prefix.with_name(output_prefix.name + "_rgb565.hex")

    raw_path.write_bytes(raw_bytes)
    hex_path.write_text("".join(hex_lines), encoding="utf-8")

    print(f"RGB888: {raw_path}")
    print(f"RGB565: {hex_path}")


if __name__ == "__main__":
    main()
