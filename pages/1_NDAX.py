"""Neware NDAX page, independent of LAND's channel calibration."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import streamlit as st

from cex_tool.ndax import NdaxFormatError, parse_ndax
from cex_tool.reader import cycle_summary
from cex_tool.ui import render_dataset

st.set_page_config(page_title="新威 NDAX 工具", page_icon="🔬", layout="wide")


@st.cache_data(show_spinner="解码 NDAX …")
def decode_upload(data: bytes, cycle_mode: str):
    return parse_ndax(data, cycle_mode)


with st.sidebar:
    st.title("🔬 新威 NDAX")
    st.caption("电压、电流按 NDAX 自身的记录量程换算。")
    st.page_link("app.py", label="返回 LAND CEX", icon="🔋")
    st.divider()
    cycle_options = {"文件循环号": "file", "充电开始新循环": "chg", "放电开始新循环": "dchg"}
    choice = st.selectbox("循环分组", list(cycle_options), key="ndax-cycle-rule")
    cycle_mode = cycle_options[choice]
    st.caption("默认保留文件循环号。与 BTSDA 对照时，请使用相同的循环分组设置。"
               "库仑效率 = 放电容量 ÷ 充电容量 × 100%。")

st.title("新威 NDAX 数据解码")
st.caption("上传后可查看曲线与循环统计；曲线右侧支持平台拉伸、电压 offset 和独立横向平移，"
           "循环统计右侧可调整容量与效率。模拟结果可下载 CSV，原文件不修改。")
st.info("支持已验证的 NDC v5 / type 1 格式。当前提供 NDAX → CSV；CSV → NDAX 写回尚未验证，暂不提供 NDAX 导出。")

files = st.file_uploader("上传 NDAX 文件（支持多选）", type=["ndax"], accept_multiple_files=True,
                         key="ndax-uploads")
exports = []
for position, upload in enumerate(files or []):
    raw = upload.getvalue()
    stem = Path(upload.name).stem
    identity = hashlib.sha256(raw).hexdigest()[:12]
    key = f"ndax-{position}-{identity}-{cycle_mode}"
    with st.container(border=True):
        st.subheader(upload.name)
        try:
            dataset = decode_upload(raw, cycle_mode)
        except (NdaxFormatError, ValueError) as e:
            st.error(f"解码失败：{e}")
            continue
        df, meta = dataset.data, dataset.metadata
        metrics = st.columns(5)
        metrics[0].metric("测量记录", f"{meta['records']:,}")
        metrics[1].metric("工步数", meta["steps"])
        metrics[2].metric("循环数", meta["cycles"])
        metrics[3].metric("累计测试时长", f"{meta['duration_h']:.2f} h")
        metrics[4].metric("单元 / 通道", f"{meta.get('UnitID', '—')} / {meta.get('ChlID', '—')}")
        st.caption(f"记录时间：{meta['first_record']} → {meta['last_record']} · ZIP CRC 校验通过")
        for warning in dataset.warnings:
            st.warning(warning)
        with st.expander("工步设置与修改历史"):
            st.dataframe(dataset.recipe, hide_index=True, use_container_width=True)
        with st.expander("文件结构与测试信息"):
            st.dataframe(meta["members"], hide_index=True, use_container_width=True)
            st.json({k: v for k, v in meta.items() if k != "members"})
        area_cm2 = st.number_input("电极面积 / cm²", min_value=0.0001, value=0.18,
                                   step=0.01, format="%.4f",
                                   key=f"ndax-area-{position}-{identity}",
                                   help="用于横轴归一化：面积比容量 = Capacity_mAh ÷ 面积。每个文件可独立设置。")
        data_csv, summary_csv = render_dataset(stem, df, cycle_summary(df), key,
                                               allow_cycle_adjustments=True, area_cm2=area_cm2,
                                               allow_profile_adjustments=True)
        # Prefix batch names to preserve both uploads even when names collide.
        export_stem = f"{stem}_simulated" if b"profile_simulation" in data_csv else stem
        if data_csv:
            exports.append((f"{position + 1}_{export_stem}.csv", data_csv))
        if summary_csv:
            exports.append((f"{position + 1}_{export_stem}_cycles.csv", summary_csv))

if len(files or []) > 1 and exports:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in exports:
            archive.writestr(name, content)
    st.download_button("下载全部 CSV（ZIP）", output.getvalue(), file_name="ndax_export.zip",
                       mime="application/zip", key="ndax-batch-download")

with st.expander("NDAX 如何解码 / 数据列说明"):
    st.markdown((Path(__file__).resolve().parents[1] / "docs" / "NDAX_FORMAT.md").read_text(encoding="utf-8"))
