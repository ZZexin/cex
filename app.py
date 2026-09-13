"""Streamlit UI: LAND (蓝电) .cex  ⇄  CSV converter."""
from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from cex_tool import format as F
from cex_tool.reader import cycle_summary, parse_cex, to_dataframe
from cex_tool.ui import MODE_ZH, csv_bytes, render_dataset
from cex_tool.writer import (ROLES, UNIT_FACTORS, build_cex, detect_columns, load_template,
                             normalize_table, segment_table, template_from_cex)

st.set_page_config(page_title="LAND CEX 工具", page_icon="🔋", layout="wide")

# ----------------------------------------------------------------------------- cached work
@st.cache_data(show_spinner="解析 .cex …")
def parse_bytes(data: bytes, v_lsb: float, i_lsb: float):
    cex = parse_cex(data)
    df = to_dataframe(cex, v_lsb, i_lsb)
    summ = cycle_summary(df)
    meta = {
        "channel": cex.channel + 1, "unit": cex.unit,
        "start": pd.Timestamp(cex.start_ts, unit="s"),
        "saved": pd.Timestamp(cex.save_ts, unit="s") if cex.save_ts else None,
        "records": cex.n_records, "steps": len(cex.steps),
        "cycles": int(df["Cycle"].max()) if len(df) else 0,
        "duration_h": float(df["TestTime_s"].iloc[-1] / 3600) if len(df) else 0.0,
        "recipe": [{"工步": s.number, "类型": f"{MODE_ZH.get(s.mode_name, s.mode_name)} ({s.mode_name})",
                    "电流 mA": None if s.mode == F.MODE_REST else s.current_a * 1e3,
                    "结束条件": s.describe().split("end: ")[-1]} for s in cex.recipe],
        "checksums": cex.checksums_ok(),
    }
    return df, summ, meta, cex.warnings


@st.cache_data(show_spinner=False)
def read_table(data: bytes) -> pd.DataFrame:
    last = None
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding=enc)
        except UnicodeDecodeError as e:  # try next encoding
            last = e
    raise last  # pragma: no cover


def guess_start_datetime(raw: pd.DataFrame) -> dt.datetime | None:
    """If the CSV carries an absolute date/time column, use its first value as the test start."""
    for c in raw.columns:
        n = str(c).lower()
        if any(k in n for k in ("datetime", "date", "timestamp", "绝对时间", "日期")):
            try:
                v = pd.to_datetime(raw[c].dropna().iloc[0])
                return v.to_pydatetime().replace(microsecond=0)
            except (ValueError, TypeError, IndexError):
                continue
    return None


# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🔋 LAND CEX 工具")
    st.caption("蓝电 (LAND) 电池测试 `.cex` 数据解码 / 转换")
    st.page_link("pages/1_NDAX.py", label="打开新威 NDAX 页面", icon="🔬")
    st.subheader("⚙️ 原始值换算")
    v_lsb = st.number_input("电压分辨率 mV / LSB", value=F.V_LSB * 1e3, format="%.5f", step=0.001, min_value=1e-6) * 1e-3
    i_lsb = st.number_input("电流分辨率 µA / LSB", value=F.I_LSB * 1e6, format="%.4f", step=0.01, min_value=1e-6) * 1e-6
    st.caption("默认值按 5 V / 10 mA 通道 (CT2001A) 标定。其他量程的通道请按比例修改，例如 100 mA 通道电流分辨率 ×10。")
    st.divider()
    st.caption("时间列均为累计测试时间；DateTime = 文件内起始时间戳 + 测试时间（按文件记录的本地时间显示）。")

tab_read, tab_write, tab_doc = st.tabs(["📥 CEX → CSV", "📤 CSV → CEX", "📖 格式说明"])

# ============================================================================= CEX -> CSV
with tab_read:
    st.markdown("把 `.cex` 文件拖进下方区域（可多选）。解析后可预览数据、查看曲线，并下载 CSV。")
    files = st.file_uploader("拖放 .cex 文件 / Drop .cex files", type=["cex"], accept_multiple_files=True,
                             label_visibility="collapsed")
    inputs: list[tuple[str, bytes]] = [(f.name, f.getvalue()) for f in files or []]
    exports: list[tuple[str, bytes]] = []
    for name, data in inputs:
        stem = Path(name).stem
        with st.container(border=True):
            st.subheader(f"📄 {name}")
            try:
                df, summ, meta, warns = parse_bytes(data, v_lsb, i_lsb)
            except Exception as e:  # noqa: BLE001
                st.error(f"解析失败: {e}")
                continue
            for w in warns:
                st.warning(w)
            if not all(meta["checksums"].values()):
                st.warning(f"校验和不匹配: {meta['checksums']}（文件可能被修改或来自不同版本的软件）")

            m = st.columns([1, 1, 1, 0.8, 1.3, 1.2])
            m[0].metric("记录数", f"{meta['records']:,}")
            m[1].metric("工步数", f"{meta['steps']:,}")
            m[2].metric("循环数", meta["cycles"])
            m[3].metric("通道", meta["channel"], help=f"设备/单元 {meta['unit']}")
            saved = f"，最后保存 {meta['saved']:%Y-%m-%d %H:%M}" if meta["saved"] is not None else ""
            m[4].metric("开始日期", meta["start"].strftime("%Y-%m-%d"), help=f"开始 {meta['start']:%Y-%m-%d %H:%M:%S}{saved}")
            m[5].metric("总时长", f"{meta['duration_h']:.0f} h")

            with st.expander("工步设置 Recipe"):
                st.dataframe(pd.DataFrame(meta["recipe"]), hide_index=True, use_container_width=True)

            data_csv, summ_csv = render_dataset(stem, df, summ, key=f"read-{stem}",
                                                allow_cycle_adjustments=True)
            if data_csv:
                exports.append((f"{stem}.csv", data_csv))
            if summ_csv:
                exports.append((f"{stem}_cycles.csv", summ_csv))

    if len(inputs) > 1 and exports:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in exports:
                z.writestr(name, content)
        st.download_button("⬇️ 打包下载全部 CSV (zip)", buf.getvalue(), file_name="cex_export.zip", mime="application/zip")

# ============================================================================= CSV -> CEX
with tab_write:
    st.markdown(
        "上传只含 **测量量** 的 CSV 即可：**累计时间、电压、电流**（三列，列名与单位自动识别，可手动改）。"
        "工具会自动划分静置 / 放电 / 充电工步，积分出 **容量、能量**，并计算 **循环号、工步时间、DateTime**，"
        "生成与仪器 `.cex` 数据种类完全一致的文件；下方直接预览计算结果。"
        "（本工具导出的 CSV 也可直接转回；可选提供容量 / 能量 / 工步号 / 工步类型列，有则优先采用。）"
    )
    c1, c2 = st.columns(2)
    csv_file = c1.file_uploader("拖放 CSV / Drop CSV", type=["csv", "txt"])
    tpl_file = c2.file_uploader("模板 .cex（可选，用其文件头 / 工步设置）", type=["cex"])

    if csv_file:
        csv_name = csv_file.name
        try:
            raw = read_table(csv_file.getvalue())
        except Exception as e:  # noqa: BLE001
            st.error(f"读取 CSV 失败: {e}")
            st.stop()
        st.caption(f"{len(raw):,} 行 × {len(raw.columns)} 列 — 前 10 行预览")
        st.dataframe(raw.head(10), use_container_width=True, hide_index=True)

        auto = detect_columns(raw.columns)
        st.markdown("**列映射 / Column mapping**")
        labels = {"time": "累计时间 Time", "voltage": "电压 Voltage", "current": "电流 Current",
                  "capacity": "容量 Capacity（可选）", "energy": "能量 Energy（可选）",
                  "step": "工步号 Step（可选）", "mode": "工步类型 Mode（可选）"}
        opts = ["(无)"] + list(map(str, raw.columns))
        mapping: dict[str, str | None] = {}
        units: dict[str, str] = {}
        grid = st.columns(4)
        for k, role in enumerate(ROLES):
            with grid[k % 4]:
                idx = opts.index(str(auto[role])) if auto[role] is not None else 0
                sel = st.selectbox(labels[role], opts, index=idx, key=f"map-{role}")
                mapping[role] = None if sel == "(无)" else sel
                if role in UNIT_FACTORS and mapping[role]:
                    ulist = list(UNIT_FACTORS[role])
                    from cex_tool.writer import _guess_unit  # noqa: PLC0415
                    g = _guess_unit(mapping[role], role)
                    units[role] = st.selectbox("单位", ulist, index=ulist.index(g) if g in ulist else 0,
                                               key=f"unit-{role}", label_visibility="collapsed")

        st.markdown("**文件信息**")
        guess = guess_start_datetime(raw)
        o = st.columns(4)
        d0 = o[0].date_input("开始日期", value=guess.date() if guess else dt.date.today())
        t0 = o[1].time_input("开始时刻", value=guess.time() if guess else dt.time(0, 0))
        ch = o[2].number_input("通道号 (1 起)", min_value=1, max_value=256, value=1)
        patch = o[3].checkbox("按数据更新工步设置(电流/截止电压)", value=True)
        start_ts = int(dt.datetime.combine(d0, t0).replace(tzinfo=dt.timezone.utc).timestamp())

        try:
            table = normalize_table(raw, mapping, units)
            segs = segment_table(table)
        except Exception as e:  # noqa: BLE001
            st.error(f"无法整理数据: {e}")
            st.stop()

        seg_rows = []
        for k, s in enumerate(segs, 1):
            part = table.iloc[s.start:s.stop]
            seg_rows.append({
                "序号": k, "工步类型": f"{MODE_ZH.get(F.mode_name(s.mode), '')} ({F.mode_name(s.mode)})",
                "记录数": s.n,
                "起始 h": part["time_s"].iloc[0] / 3600,
                "时长 h": (part["time_s"].iloc[-1] - part["time_s"].iloc[0]) / 3600,
                "电压范围 V": f"{part['voltage_v'].min():.3f} – {part['voltage_v'].max():.3f}",
                "电流中值 mA": float(part["current_ma"].median()),
            })
        st.markdown(f"**识别出的工步：{len(segs)} 个**")
        st.dataframe(pd.DataFrame(seg_rows), height=min(420, 40 + 35 * len(seg_rows)), use_container_width=True, hide_index=True)

        try:
            template = template_from_cex(tpl_file.getvalue()) if tpl_file else load_template()
            out = build_cex(table, template=template, start_ts=start_ts, channel=ch - 1,
                            patch_recipe=patch, v_lsb=v_lsb, i_lsb=i_lsb)
            back = parse_cex(out)
            df_back = to_dataframe(back, v_lsb, i_lsb)
        except Exception as e:  # noqa: BLE001
            st.error(f"生成失败: {e}")
            st.stop()

        summ_back = cycle_summary(df_back)
        stem = Path(csv_name).stem
        st.success(f"已生成 .cex：{len(out):,} 字节，{back.n_records:,} 条记录，{len(back.steps)} 个工步，"
                   f"{int(df_back['Cycle'].max()) if len(df_back) else 0} 个循环；校验和 {'✅' if all(back.checksums_ok().values()) else '❌'}")
        st.download_button("⬇️ 下载 .cex", out, file_name=f"{stem}.cex", mime="application/octet-stream", type="primary")

        # what came from the CSV vs. what was computed
        role_cols = {"time": "TestTime_s", "voltage": "Voltage_V", "current": "Current_mA",
                     "capacity": "Capacity_mAh", "energy": "Energy_mWh", "step": "Step / StepSeq", "mode": "Mode"}
        how = {"capacity": "Capacity_mAh = ∫|I|dt/3600", "energy": "Energy_mWh = ∫V·|I|dt/3600",
               "step": "Step / StepSeq（按电流符号分段）", "mode": "Mode（按电流符号）"}
        provided = [role_cols[r] for r in ROLES if mapping.get(r)]
        computed = [how[r] for r in ROLES if not mapping.get(r) and r in how]
        computed += ["Cycle（工步号不再递增时 +1）", "StepTime_s = TestTime_s − 工步首条", "DateTime = 开始时间 + TestTime_s"]
        st.markdown(f"**来自 CSV：** {'、'.join(provided)}  \n**计算得到：** {'、'.join(computed)}")
        dv = float(np.abs(df_back["Voltage_V"].to_numpy() - table["voltage_v"].to_numpy()).max()) * 1e3
        di = float(np.abs(df_back["Current_mA"].to_numpy() - table["current_ma"].to_numpy()).max()) * 1e3
        st.caption(f"写入 .cex 的量化误差（受 LSB 分辨率限制）：电压 ≤ {dv:.3f} mV，电流 ≤ {di:.3f} µA。"
                   "下方显示从生成的 .cex 回读的数据；循环统计按本工具的工步分组和放电/充电容量比计算。")
        render_dataset(stem, df_back, summ_back, key="csv2cex")

# ============================================================================= docs
with tab_doc:
    st.markdown(Path(__file__).with_name("README.md").read_text(encoding="utf-8"))
