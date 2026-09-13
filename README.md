# LAND (蓝电) `.cex` 数据工具

把蓝电 (LAND, 如 CT2001A) 电池测试软件保存的二进制 `.cex` 文件解码为 CSV，或把 CSV 打包回 `.cex`
供蓝电软件读取。带 Streamlit 图形界面（拖放上传、预览、曲线、下载）。

## 使用 / Usage

```bash
uv sync                      # 安装依赖（需要 uv；或 pip install streamlit pandas numpy plotly）
uv run streamlit run app.py  # 打开浏览器界面
uv run pytest                # 运行测试（使用 samples/ 下的样例文件）
```

Python API:

```python
from cex_tool import parse_cex, to_dataframe, cycle_summary, build_cex, normalize_table

cex = parse_cex(open("test.cex", "rb").read())
df = to_dataframe(cex)          # Index, Cycle, Step, StepSeq, Mode, TestTime_s, StepTime_s,
                                # Voltage_V, Current_mA, Capacity_mAh, Energy_mWh, DateTime
summary = cycle_summary(df)     # 每圈充放电容量、能量、库伦效率

table = normalize_table(pd.read_csv("data.csv"))   # 自动识别 时间/电压/电流/容量… 列
open("out.cex", "wb").write(build_cex(table, start_ts=1_784_176_364, channel=11))
```

## 导出 CSV 的列

| 列 | 含义 |
|---|---|
| `Index` | 记录序号 |
| `Cycle` | 循环号（工步号不再递增时 +1） |
| `Step` / `StepSeq` | 工步号（对应工步设置）/ 工步在文件中的顺序号 |
| `Mode` | `Rest` 静置 · `CC_DChg` 恒流放电 · `CC_Chg` 恒流充电 |
| `TestTime_s` / `StepTime_s` | 累计测试时间 / 工步内时间 (s) |
| `Voltage_V`, `Current_mA` | 电压 (V)、电流 (mA，充电为正、放电为负) |
| `Capacity_mAh`, `Energy_mWh` | 工步内累计容量、能量（每个工步从 0 开始） |
| `DateTime` | 起始时间戳 + 测试时间（按文件记录的本地时间显示） |

每列是测量值还是计算值、计算公式见 [docs/DATA_COLUMNS.md](docs/DATA_COLUMNS.md)。

循环统计图右侧可调整容量和库仑效率。先将每圈充、放电总容量分别变为
`原容量 × 缩放百分比 / 100 + offset (mAh)`，再将容量调整后的效率变为
`CE × 缩放百分比 / 100 + offset (百分点)`，保持目标充电容量、反算放电容量。
同圈多个同类工步按原容量占比分配目标容量，各工步仍从零累计；电流按工步目标容量
重新标定，能量按电压和容量增量积分。默认参数不修改数据，静置记录保持原值。
数据预览、曲线、CSV 和 ZIP 使用相同的调整结果，CSV 转回 CEX 时 offset 不会被工步归零抵消。
转换后的容量、能量受 float32 精度限制，电流受通道分辨率限制。末圈未完成测试时仍按实际记录统计。

## 新威 NDAX 独立页面

启动方式仍为 `streamlit run app.py`。从侧栏的「打开新威 NDAX 页面」进入，支持 NDAX 多文件上传、
工步与修改历史、测量预览、曲线、循环统计、容量/效率调整以及 CSV/ZIP 下载。
它使用 NDAX 每条记录的电流量程，不受 LAND 页面 LSB 设置影响。
当前验证了 NDC v5 / type 1 的单 data.ndc 格式，未知版本和量程明确报错；暂不提供 NDAX 写回。

文件结构和公式见 [NDAX_FORMAT.md](docs/NDAX_FORMAT.md)，
本次两份文件的分析见 [NDAX_SAMPLES.md](docs/NDAX_SAMPLES.md)。

## CSV → CEX

- 只需上传 **测量量**：累计时间、电压、电流三列（列名与单位自动识别：`Time`, `TestTime(s)`, `电压/V`,
  `Current(mA)` …，也可在界面中手动指定）。
- 按电流符号自动划分 静置 / 放电 / 充电 工步，按 `∫|I|dt`、`∫V|I|dt` 积分容量与能量，再计算循环号、工步时间、
  DateTime——生成的 `.cex` 与仪器文件的数据种类完全一致，界面直接预览回读结果（表格 / 曲线 / 循环统计）。
  若 CSV 已有容量 / 能量 / 工步号 / 工步类型列则优先采用。
- 文件头（含工步设置）来自内置模板（取自真实 CT2001A 文件），也可上传一个 `.cex` 作为模板。
  起始时间、通道号、工步的电流 / 截止电压、以及全部校验和都会重新写入。
- 本工具导出的 CSV 可无损转换回 `.cex`（原始整数值逐条一致）。

## 文件格式（逆向整理）/ File format

所有整数小端 (little-endian)。

```
0x0000  文件头 64 B      10 11 09 88 | u16 ver? | u8 通道(0起) u8 单元 | u16 ? | u32 ? |
                         u32 开始时间戳 @0x10 | ... | u32 开始时间戳 @0x30, @0x34 |
                         u32 校验和 @0x3C = 0x00..0x3B 的 u16 字和
0x0040  数据块链         AA AA FF FF <id:u16> <size:u16> <8 B>  ...size B...  BB BB FF FF <同样 12 B>
          id 0xAA (64 B)  信息块: u32 最后保存时间 @+8; u32 校验和 @+60 (= 前 60 B 的 u16 字和)
          id 0x55 (16 B), id 0x78 (384 B): 全 0
          id 0x13 (2992 B) 工步设置: 子头 0x30 B; u32 校验和 @+0x30 (= @+0x40 起的 u16 字和);
                          @+0x40 目录表 [u16 偏移][u8 类型][FF]…(类型 02 = 工步, 0C = 循环, 13 = 元数据, FD = 结束)
                          工步条目 56 B: u32 模式(0x70 静置, 2 恒流放电, 3 恒流充电) | f32 电流 A | …
                                         | u16 结束条件类型 @+40 (0x0100 时间, 0x0200 电压) | u16 子类型 | f32 值 @+44
事件    CC CC FF FF 33 00 00 00 01 02 00 00 <u32 时间戳>            测试开始
        CC CC FF FF 44 00 00 00 <u32 循环起点标志> <u16 工步|0x8000> <u16 循环计数>   跳转到工步
工步    CD CC FF FF 22 00 <u16 工步|0x8000> <u8 模式> 05 <81|00> 00 <u32 工步开始时间戳>
        后接 16 B 记录直到下一个标记：
记录    u32 时间 (×10 ms) | u16 电压原始值 | i16 电流原始值 | f32 容量 Ah | f32 能量 Wh
```

原始值换算（5 V / 10 mA 通道，由实测数据标定）：**电压 = 原始值 × 0.155 mV**，**电流 = 原始值 × 0.31 µA**，
时间 = 原始值 × 0.01 s。其它量程的通道请在界面侧栏按比例调整。

未解读的字段（如文件头 0x0C、0x14，工步块 0x2C4–0x2CF）在写文件时原样沿用模板。
