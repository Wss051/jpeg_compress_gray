#!/usr/bin/env python3
"""
对比 Verilog 熵编码输出 (entropy_out.txt) 与 Python 参考模型 (entropy_out_ref.txt)
"""

from pathlib import Path

SIM_FILE = Path(__file__).parent / "entropy_out.txt"
REF_FILE = Path(__file__).parent / "entropy_out_ref.txt"


def load_file(path: Path):
    data = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 6:
                data.append({
                    "is_dc": int(parts[0]),
                    "is_eob": int(parts[1]),
                    "code": int(parts[2]),
                    "len": int(parts[3]),
                    "extra": int(parts[4]),
                    "extra_len": int(parts[5]),
                })
    return data


def main():
    if not SIM_FILE.exists():
        print(f"未找到 {SIM_FILE}，请先运行 Verilog 仿真")
        return
    if not REF_FILE.exists():
        print(f"未找到 {REF_FILE}，请先运行 python ref_model.py")
        return

    sim = load_file(SIM_FILE)
    ref = load_file(REF_FILE)

    if len(sim) != len(ref):
        print(f"符号数量不一致: sim={len(sim)}, ref={len(ref)}")
        return

    total = len(sim)
    errors = 0
    sim_bits = 0
    ref_bits = 0

    for i, (s, r) in enumerate(zip(sim, ref)):
        sim_bits += s["len"] + s["extra_len"]
        ref_bits += r["len"] + r["extra_len"]
        if s != r:
            if errors < 10:
                print(f"不匹配 at {i}: sim={s}, ref={r}")
            errors += 1

    print(f"=====================================")
    print(f"总符号数: {total}")
    print(f"不匹配符号: {errors}")
    print(f"匹配率: {(total - errors) / total * 100:.2f}%")
    print(f"Verilog 总比特: {sim_bits}")
    print(f"参考模型总比特: {ref_bits}")
    print(f"Verilog 压缩率: {sim_bits / (320*320):.3f} bpp")
    print(f"参考模型压缩率: {ref_bits / (320*320):.3f} bpp")
    if errors == 0:
        print("结果: 完全匹配")
    elif errors < total * 0.01:
        print("结果: 基本一致 (少量定点误差)")
    else:
        print("结果: 差异较大，请检查实现")
    print(f"=====================================")


if __name__ == "__main__":
    main()
