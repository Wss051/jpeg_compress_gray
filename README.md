# JPEG 灰度图像压缩器 (FPGA Verilog)

基于 FPGA 的 JPEG 灰度图像压缩引擎，采用流水线架构实现完整的 JPEG Baseline 压缩流程。

📦 **GitHub**: [Wss051/jpeg_compress_gray](https://github.com/Wss051/jpeg_compress_gray)

---

## 项目概述

本项目实现了一个完整的 **320×320 灰度图像 JPEG-like 压缩器**，输入为 RGB565 像素流，输出为标准 JPEG 熵编码符号流。设计采用 **Altera Cyclone IV** 系列 FPGA 为目标平台，使用 **Quartus Prime** 进行综合与实现。

### 主要特性

| 特性 | 参数 |
|------|------|
| 输入分辨率 | 320 × 320 |
| 输入格式 | RGB565 像素流 |
| 色彩处理 | RGB565 → Y (亮度) |
| DCT 算法 | AAN (Arai-Agui-Nakajima) 蝶形算法，22 次乘法/8 点 |
| 量化表 | 标准 JPEG 亮度量化表 (可编程) |
| Zig-Zag | 竖直优先 (适配 DCT 行列分离转置) |
| 熵编码 | DC 差分 + AC 游程 + 标准 Huffman 查表 |
| 时钟频率 | 100 MHz |
| 处理性能 | ~3.37 μs / 8×8 块 (1600 块/帧 ≈ 5.4 ms/帧) |
| 压缩比 | 约 0.3~0.8 bpp (取决于图像内容) |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      jpeg_compress_top                       │
│  ┌─────────┐   ┌────────┐   ┌─────────┐   ┌──────────┐    │
│  │   Y     │   │ image  │   │block_fifo│   │  dct_2d  │    │
│  │RGB565→Y │ → │320×320 │ → │ 512×8b  │ → │ 8×8 2D   │    │
│  │  8-bit  │   │分块输出 │   │  缓冲   │   │   DCT    │    │
│  └─────────┘   └────────┘   └─────────┘   └────┬─────┘    │
│                                                  │          │
│  ┌─────────┐   ┌──────────┐   ┌────────────────┐ │          │
│  │quantizer│ ← │   arm    │ ← │ transpose_ram  │ │          │
│  │ 标量量化│   │ 输入缓冲 │   │  8×8 转置缓冲  │ │          │
│  └────┬────┘   └──────────┘   └────────────────┘ │          │
│       │                                          │          │
│       ↓                                          │          │
│  ┌──────────┐   ┌──────────────────────┐         │          │
│  │zigzag_scan│ → │ jpeg_entropy_encoder │ →  Huffman 码流   │
│  │ ZZ 扫描   │   │  DC差分+AC游程+查表  │                  │
│  └──────────┘   └──────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

### 数据流 pipeline

```
RGB565(16b) → Y(8b) → 8×8 Block → 2D-DCT(12b) → Quantize(12b) → Zig-Zag → Entropy
```

---

## 模块说明

### 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **jpeg_compress_top** | `jpeg_compress_top.v` | 顶层模块，集成所有子模块，处理 320×320 整帧图像 |
| **dct_2d** | `dct_2d.v` | 二维 DCT 控制器，行列分离架构，通过转置 RAM 实现 2D DCT |
| **DCT1D** | `DCT1D.v` | 一维 8 点 DCT 引擎，AAN 蝶形算法，支持参数化位宽 |
| **quantizer** | `quantizer.v` | 3 级流水线标量量化器，可编程量化表，支持舍入与饱和 |
| **zigzag_scan** | `zigzag_scan.v` | Zig-Zag 扫描模块，支持水平/竖直优先两种模式 |
| **jpeg_entropy_encoder** | `jpeg_entropy_encoder.v` | JPEG 熵编码器，DC 差分编码 + AC 游程编码 + Huffman 查表 |
| **Y** | `Y.v` | RGB565 到 Y (亮度) 色彩空间转换 |
| **image** | `image.v` | 图像分块控制器，将行扫描像素重组为 8×8 块 |
| **block_fifo** | `block_fifo.v` | 像素缓冲 FIFO，连接图像分块与 DCT 模块 |

### 存储 IP (Quartus altsyncram)

| 模块 | 文件 | 功能 |
|------|------|------|
| **arm** | `arm.v`, `arm.qip` | 8-bit × 4096 输入像素缓冲 (single-port RAM) |
| **transpose_ram** | `transpose_ram.v`, `transpose_ram.qip` | 12-bit × 64 转置缓冲 (single-port RAM) |
| **ram_dp** | `ram_dp.v` | 双端口 RAM 通用模板 |

### Huffman 表

| 文件 | 说明 |
|------|------|
| `huffman_tables.vh` | 标准 JPEG 亮度 DC/AC Huffman 码表 (Verilog 参数格式) |
| `gen_huffman_tables.py` | Python 生成脚本，将 Huffman 表转换为 Verilog 参数 |

---

## 2D-DCT 实现细节

本项目采用 **行列分离法** 实现 2D-DCT：

```
2D-DCT = 1D-DCT(行) → 转置 → 1D-DCT(列)
```

### 时序安排 (每 8×8 块)

| 阶段 | 周期数 | 说明 |
|------|--------|------|
| S_LOAD | 64 | 接收 64 像素写入 arm.v |
| Row DCT | 136 | 8 行 × (1 PRE + 8 FEED + 8 DRAIN) |
| Col DCT | 136 | 8 列 × (1 PRE + 8 FEED + 8 DRAIN) |
| S_DONE | 1 | 完成脉冲 |
| **总计** | **~337** | @ 100MHz = 3.37 μs/块 |

### AAN 算法系数 (×1024 定点)

| 系数 | 值 | 数学含义 |
|------|------|----------|
| A0 | 362 | 1/(2√2) × 1024 |
| A1 | 502 | cos(π/16)/2 × 1024 |
| A2 | 473 | cos(π/8)/2 × 1024 |
| A3 | 426 | cos(3π/16)/2 × 1024 |
| A4 | 284 | cos(5π/16)/2 × 1024 |
| A5 | 196 | cos(3π/8)/2 × 1024 |
| A6 | 100 | cos(7π/16)/2 × 1024 |

---

## 验证与参考模型

项目包含完整的 **软硬件协同验证** 环境：

### Python 参考模型

| 脚本 | 功能 |
|------|------|
| `ref_model.py` | 定点 AAN DCT 复刻模型，生成 Zig-Zag 和熵编码参考输出 |
| `bit_accurate_model.py` | 位精确模型，逐位对比硬件输出 |
| `jpeg_decode.py` | JPEG 解码器，从熵编码输出重建图像并评估质量 |
| `verify_all.py` | 完整验证脚本，生成参考、对比 HW 输出、解码图像 |

### 验证流程

```bash
# 1. 生成仿真输入 (从 PNG 图像)
python sim/png_to_sim_input.py input.png out/sample

# 2. 生成 Python 参考模型输出
python sim/verify_all.py --ref-only

# 3. 运行 ModelSim 仿真
cd sim
vsim -do sim.do
# 或: do sim.do

# 4. 对比硬件输出与参考模型
python sim/verify_all.py --cmp-only

# 5. 解码熵编码输出为图像并评估质量
python sim/jpeg_decode.py
```

### 验证指标

验证脚本输出以下指标：
- **Zig-Zag 系数对比**: 逐系数对比，报告差异位置
- **熵编码符号对比**: 逐符号对比，验证 Huffman 编码一致性
- **图像质量**: PSNR、MAE (Mean Absolute Error)、精确匹配率
- **压缩率**: 总比特数 / 像素数 (bpp)

---

## 文件结构

```
jpeg_compress_gray/
├── README.md                     # 本文件
├── .gitignore                    # Git 忽略规则
├── system_module_port_connection.png   # 系统模块连接图
│
├── rtl/                          # RTL 源代码
│   ├── jpeg_compress_top.v       # 顶层模块
│   ├── dct_2d.v                  # 2D DCT 控制器
│   ├── DCT1D.v                   # 1D DCT 引擎 (AAN)
│   ├── quantizer.v               # 标量量化器
│   ├── zigzag_scan.v             # Zig-Zag 扫描
│   ├── jpeg_entropy_encoder.v    # 熵编码器
│   ├── Y.v                       # RGB565 → Y 转换
│   ├── image.v                   # 图像分块控制器
│   ├── block_fifo.v              # 像素缓冲 FIFO
│   ├── ram_dp.v                  # 双端口 RAM 模板
│   ├── huffman_tables.vh         # Huffman 码表
│   ├── arm.v / arm.qip           # Quartus 输入 RAM IP
│   ├── transpose_ram.v / transpose_ram.qip   # 转置 RAM IP
│   ├── arm_bb.v                  # arm 黑盒接口
│   └── transpose_ram_bb.v      # transpose_ram 黑盒接口
│
├── sim/                          # 仿真与验证
│   ├── tb_jpeg_compress.v        # 整帧 320×320 Testbench
│   ├── tb_dct1d.v                # DCT1D 单元测试
│   ├── tb_dct2d.v                # DCT2D 单元测试
│   ├── tb_quantizer.v            # 量化器单元测试
│   ├── tb_dct1d_varied.v         # DCT1D 变输入测试
│   ├── sim.do                    # ModelSim 仿真脚本
│   ├── modelsim.ini              # ModelSim 配置
│   ├── ref_model.py              # Python 参考模型
│   ├── bit_accurate_model.py     # 位精确模型
│   ├── jpeg_decode.py            # JPEG 解码器
│   ├── verify_all.py             # 完整验证脚本
│   ├── gen_huffman_tables.py     # Huffman 表生成器
│   ├── png_to_sim_input.py       # PNG → 仿真输入转换
│   ├── convert_raw_for_tb.py     # 测试数据格式转换
│   ├── compare.py                # 对比工具
│   ├── compare_entropy.py        # 熵编码对比
│   ├── compare_images.py         # 图像对比
│   ├── compare_pipeline.py       # 流水线对比
│   ├── encode_decode_raw.py      # 编解码测试
│   ├── entropy_decode_to_png.py  # 熵解码转 PNG
│   ├── decode_png.py             # PNG 解码工具
│   ├── stat_analysis.py          # 统计分析
│   ├── deep_analysis.py          # 深度分析
│   └── verify_fixes.py           # 修复验证
│
├── quartus/                      # Quartus 工程
│   ├── jpeg_compress_gray.qpf     # 工程文件
│   └── jpeg_compress_gray.qsf     # 设置文件
│
└── out/                          # 输出结果示例 (可选)
    ├── 02.png                     # 原始测试图像
    ├── 02_decoded.png             # 硬件解码结果
    ├── 02_decoded_diff.png        # 误差热图
    └── ...
```

---

## 使用说明

### 环境要求

- **FPGA 开发**: Quartus Prime (支持 Cyclone IV E)
- **仿真**: ModelSim / QuestaSim (Altera 版)
- **Python 验证**: Python 3.7+ (无第三方依赖)

### 综合与实现

1. 打开 Quartus Prime
2. 打开工程 `quartus/jpeg_compress_gray.qpf`
3. 运行 **Analysis & Synthesis** → **Fitter** → **Assembler**
4. 生成 `.sof` 文件下载到 FPGA

### 仿真步骤

```bash
# 进入仿真目录
cd sim

# 启动 ModelSim 并运行仿真脚本
vsim -do sim.do

# 或在 ModelSim 控制台中:
do sim.do
```

### Python 验证

```bash
# 完整验证流程
python sim/verify_all.py

# 仅生成参考模型
python sim/verify_all.py --ref-only

# 仅对比已有仿真结果
python sim/verify_all.py --cmp-only
```

---

## 设计思路与关键决策

### 1. 行列分离 2D-DCT 架构

- 1D-DCT 引擎 **分时复用**，先处理 8 行，转置后处理 8 列
- 转置通过 **地址重映射** 实现，无需物理数据搬移
- 行 DCT: 8-bit 像素 → 12-bit 输出；列 DCT: 12-bit 全精度 → 12-bit 输出

### 2. AAN 蝶形算法

- 相比直接矩阵乘法，**22 次乘法 vs 64 次乘法** (8 点 1D-DCT)
- 纯组合逻辑 + 状态机控制，无需乘法器 IP
- 系数缩放 1024，最后通过 `(y + 512) >>> 10` 舍入

### 3. 三级流水线量化器

- 第 1 级: 锁存输入 + 读取量化缩放表
- 第 2 级: 有符号乘法
- 第 3 级: 舍入右移 + 饱和限幅
- 吞吐率: **1 sample/cycle**

### 4. 熵编码器设计

- **纯组合输出**: 每个周期产生一个 Huffman 符号
- DC 差分: `diff = DC_cur - DC_prev`，category 查表
- AC 游程: 统计连续零个数，支持 ZRL (16 零) 和 EOB
- 饱和保护: category 限制在 0~11，避免 Huffman 表越界

### 5. 反压与流控

- 顶层 `ready_out` 信号对上游反压
- FIFO 缓冲吸收图像分块与 DCT 之间的速率差异
- 整帧处理完成后输出 `frame_done` 脉冲

---

## 性能与资源

### 资源占用 (Cyclone IV EP4CE6E22C8)

| 资源 | 使用量 | 占比 |
|------|--------|------|
| Logic Elements | ~2,800 | ~45% |
| Registers | ~1,200 | ~19% |
| Memory Bits | ~36,864 | ~3% |
| Multipliers (9-bit) | ~0 | (使用移位近似) |

### 时序性能

| 指标 | 数值 |
|------|------|
| 最高时钟频率 | > 120 MHz |
| 每块处理时间 | ~3.37 μs (@ 100MHz) |
| 每帧处理时间 | ~5.4 ms (320×320, 1600 块) |
| 理论帧率 | > 180 fps |

---

## 已知问题与修复记录

| 问题 | 修复 | 文件 |
|------|------|------|
| DCT 舍入截断偏差 | 改为 `(y + 512) >>> 10` 舍入 | `DCT1D.v` |
| 列 DCT 截断 2 MSB | DIN_W 从 10 提升到 12 | `dct_2d.v` |
| 量化器 category 越界 | MIN_VAL 设为 -2047 | `quantizer.v` |
| 熵编码 category 越界 | 饱和至 11 | `jpeg_entropy_encoder.v` |
| VLI 负数编码高位垃圾 | 增加 cat 位宽掩码 | `jpeg_entropy_encoder.v` |
| 输出数据 en_out=0 时跳变 | 增加输出寄存器 | `dct_2d.v` |

---

## 许可证

MIT License

---

## 作者

- **GitHub**: [Wss051](https://github.com/Wss051)
- 项目完成日期: 2025 年 7 月
