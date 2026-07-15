#!/usr/bin/env python3
"""
对比 Verilog 仿真输出 (zz_out_all.txt) 与 Python 参考模型 (zz_ref_all.txt)

允许一定误差，因为 Verilog 使用定点 AAN DCT，而参考模型使用浮点 DCT。
通常低频系数误差很小，高频系数可能有 ±1~±2 差异。
"""

from pathlib import Path

SIM_FILE = Path(__file__).parent / "zz_out_all.txt"
REF_FILE = Path(__file__).parent / "zz_ref_all.txt"


def load_file(path: Path):
    data = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                idx = int(parts[0])
                val = int(parts[1])
                data.append((idx, val))
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
        print(f"长度不一致: sim={len(sim)}, ref={len(ref)}")
        return

    total = len(sim)
    errors = 0
    threshold = 3  # 允许误差范围

    for i, ((s_idx, s_val), (r_idx, r_val)) in enumerate(zip(sim, ref)):
        if s_idx != r_idx:
            print(f"索引不一致 at {i}: sim_idx={s_idx}, ref_idx={r_idx}")
            errors += 1
            continue
        if abs(s_val - r_val) > threshold:
            if errors < 10:
                print(f"大误差 at {i} (idx={s_idx}): sim={s_val}, ref={r_val}, diff={abs(s_val-r_val)}")
            errors += 1

    print(f"=====================================")
    print(f"总系数: {total}")
    print(f"大误差 (> {threshold}): {errors}")
    print(f"匹配率: {(total - errors) / total * 100:.2f}%")
    if errors == 0:
        print("结果: 完全匹配")
    elif errors < total * 0.01:
        print("结果: 基本一致 (少量定点误差)")
    else:
        print("结果: 差异较大，请检查实现")
    print(f"=====================================")


if __name__ == "__main__":
    main()
