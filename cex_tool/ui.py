"""Shared battery-data plots, adjustment controls and CSV exports."""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .reader import adjust_cycle_measurements, cycle_summary
from .profiles import simulate_profile, with_original_deltas

# validated categorical palette (dataviz reference instance)
C = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100",
     "magenta": "#e87ba4", "green": "#008300", "violet": "#4a3aa7", "red": "#e34948"}
SERIES = list(C.values())
GRID = "#e1e0d9"
FONT = dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", size=13)
MODE_ZH = {"Rest": "静置", "CC_DChg": "恒流放电", "CC_Chg": "恒流充电"}


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(height=height, template="plotly_white", font=FONT,
                      margin=dict(l=56, r=20, t=40, b=90), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="top", y=-0.16, x=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=True, linecolor="#c3c2b7")
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


@st.cache_data(show_spinner=False)
def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, float_format="%.12g").encode("utf-8-sig")


# ----------------------------------------------------------------------------- charts
def fig_timeseries(df: pd.DataFrame) -> go.Figure:
    stride = max(1, len(df) // 200_000)
    d = df.iloc[::stride]
    x = d["TestTime_s"] / 3600
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=("电压 Voltage / V", "电流 Current / mA"))
    fig.add_trace(go.Scattergl(x=x, y=d["Voltage_V"], mode="lines", name="电压 Voltage",
                               line=dict(width=1.5, color=C["blue"]),
                               hovertemplate="%{y:.4f} V<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scattergl(x=x, y=d["Current_mA"], mode="lines", name="电流 Current",
                               line=dict(width=1.5, color=C["orange"]),
                               hovertemplate="%{y:.4f} mA<extra></extra>"), row=2, col=1)
    fig.update_xaxes(title_text="测试时间 Test time / h", row=2, col=1)
    return _layout(fig, 540)


def fig_cycles(summ: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.62, 0.38],
                        subplot_titles=("容量 Capacity / mAh", "库伦效率 Coulombic efficiency / %"))
    common = dict(mode="lines+markers", marker=dict(size=5), line=dict(width=1.5))
    fig.add_trace(go.Scatter(x=summ["Cycle"], y=summ["DischargeCapacity_mAh"], name="放电容量 Discharge",
                             marker_color=C["blue"], line_color=C["blue"], **common,
                             hovertemplate="%{y:.5f} mAh<extra>放电</extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=summ["Cycle"], y=summ["ChargeCapacity_mAh"], name="充电容量 Charge",
                             marker_color=C["orange"], line_color=C["orange"], **common,
                             hovertemplate="%{y:.5f} mAh<extra>充电</extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=summ["Cycle"], y=summ["CoulombicEfficiency_pct"], name="库伦效率 CE",
                             marker_color=C["aqua"], line_color=C["aqua"], **common,
                             hovertemplate="%{y:.2f} %<extra>CE</extra>"), row=2, col=1)
    fig.update_xaxes(title_text="循环 Cycle", row=2, col=1)
    return _layout(fig, 520)


def fig_profiles(df: pd.DataFrame, cycles: list[int], area_cm2: float | None = None,
                 reference_df: pd.DataFrame | None = None) -> go.Figure:
    if area_cm2 is not None and (not math.isfinite(area_cm2) or area_cm2 <= 0):
        raise ValueError("电极面积必须是大于 0 的有限数值。")
    divisor = area_cm2 if area_cm2 is not None else 1.0
    unit = "mAh/cm²" if area_cm2 is not None else "mAh"
    fig = go.Figure()
    if reference_df is not None:
        for trace in fig_profiles(reference_df, cycles, area_cm2).data:
            trace.name += "（原始测量）"
            trace.line.color = "#9299a3"
            trace.opacity = .45
            fig.add_trace(trace)
    for k, cyc in enumerate(cycles):
        color = SERIES[k % len(SERIES)]
        d = df[df["Cycle"] == cyc]
        for mode, dash, zh in (("CC_DChg", "solid", "放电"), ("CC_Chg", "dot", "充电")):
            dd = d[d["Mode"].astype(str).str.endswith("_" + mode.split("_", 1)[1])]
            if len(dd):
                x = (dd["PlotSpecificCapacity_mAh_cm2"] if area_cm2 is not None and
                     "PlotSpecificCapacity_mAh_cm2" in dd else dd["Capacity_mAh"] / divisor)
                customdata = None
                hover = "%{x:.5f} " + unit + " · %{y:.4f} V"
                if area_cm2 is not None and "Delta_PlotSpecificCapacity_mAh_cm2" in dd:
                    customdata = dd[["Original_SpecificCapacity_mAh_cm2", "Original_Voltage_V",
                                     "Delta_PlotSpecificCapacity_mAh_cm2", "Delta_Voltage_V"]].to_numpy()
                    hover += ("<br>原始：%{customdata[0]:.5f} mAh/cm² · %{customdata[1]:.4f} V"
                              "<br>Δ横轴：%{customdata[2]:+.5f} mAh/cm² · Δ电压：%{customdata[3]:+.4f} V")
                fig.add_trace(go.Scattergl(x=x, y=dd["Voltage_V"], mode="lines",
                                           name=f"第 {cyc} 圈 {zh}", legendgroup=str(cyc),
                                           line=dict(color=color, width=1.5, dash=dash),
                                           customdata=customdata,
                                           hovertemplate=hover + f"<extra>C{cyc} {zh}</extra>"))
    x_title = "面积比容量 Specific capacity / mAh/cm²" if area_cm2 is not None else "容量 Capacity / mAh"
    fig.update_layout(xaxis_title=x_title, yaxis_title="电压 Voltage / V")
    fig = _layout(fig, 480)
    fig.update_layout(hovermode="closest")
    return fig


def _profile_controls(df: pd.DataFrame, chosen: list[int], area: float, key: str):
    """NDAX-only controls; all transforms restart from this rerun's baseline."""
    st.markdown("##### 平台模拟调整")
    enabled = st.checkbox("启用平台 / 横向调整", key=f"profile-enabled-{key}")
    if not enabled:
        return df, False
    phase = st.selectbox("作用方向", ["放电", "充电", "充电和放电"], key=f"profile-phase-{key}")
    st.caption("仅作用于左侧选中的循环。区间按平台调整前的横轴填写。")
    suffix = {"放电": ("_DChg",), "充电": ("_Chg",), "充电和放电": ("_Chg", "_DChg")}[phase]
    target = df[df.Cycle.isin(chosen) & df.Mode.astype(str).str.endswith(suffix)]
    maximum = float(target.Capacity_mAh.max() / area) if len(target) else 1.
    maximum = max(maximum, .0001)
    start = st.number_input("平台起点 / mAh/cm²", value=0., min_value=0., step=.01,
                            format="%.5f", key=f"profile-start-{key}")
    end = st.number_input("平台终点 / mAh/cm²", value=maximum, min_value=.000001, step=.01,
                          format="%.5f", key=f"profile-end-{key}")
    stretch = st.number_input("平台长度 / %", value=100., min_value=.1, step=5.,
                              key=f"profile-stretch-{key}",
                              help="100% 不变，120% 拉长，80% 缩短；后续曲线连续平移。")
    voltage = st.number_input("平台电压 offset / V", value=0., step=.01, format="%.4f",
                              key=f"profile-voltage-{key}")
    edge = st.number_input("电压边缘过渡 / %", value=5., min_value=0., max_value=50., step=1.,
                           key=f"profile-edge-{key}", help="在区间两端平滑衔接电压 offset；0 为直接阶跃。")
    st.markdown("##### 独立横向平移")
    shift = st.number_input("面积比容量左右 offset / mAh/cm²", value=0., step=.01, format="%.5f",
                            key=f"profile-x-{key}",
                            help="正数向右、负数向左。只改变绘图坐标，不改变累计容量、电流或循环统计。")
    show_original = st.checkbox("叠加原始测量曲线", value=True, key=f"profile-reference-{key}")

    def reset():
        for name, value in (("start", 0.), ("end", maximum), ("stretch", 100.),
                            ("voltage", 0.), ("x", 0.), ("edge", 5.)):
            st.session_state[f"profile-{name}-{key}"] = value

    st.button("恢复平台调整", key=f"profile-reset-{key}", on_click=reset)
    st.caption("保持采样时间；拉伸后反算区间等效电流与能量。此功能用于模拟，不是实验校正。"
               "横移后的坐标单独导出为 PlotSpecificCapacity_mAh_cm2。")
    adjusted = simulate_profile(df, cycles=chosen,
                                phase={"放电": "discharge", "充电": "charge", "充电和放电": "both"}[phase],
                                area_cm2=area, start=start, end=end, stretch_pct=stretch,
                                voltage_offset_v=voltage, x_offset=shift, edge_pct=edge)
    return adjusted, show_original


def render_dataset(stem: str, df: pd.DataFrame, summ: pd.DataFrame, key: str,
                   allow_cycle_adjustments: bool = False,
                   area_cm2: float | None = None,
                   allow_profile_adjustments: bool = False) -> tuple[bytes, bytes]:
    """预览 / 曲线 / 循环统计 tabs + CSV download buttons. Returns (data_csv, cycles_csv)."""
    if area_cm2 is not None:
        if not math.isfinite(area_cm2) or area_cm2 <= 0:
            st.error("电极面积必须是大于 0 的有限数值。")
            return b"", b""
        t_plot, t_prev, t_cyc = st.tabs(["📈 电压–面积比容量", "📋 数据预览", "🔁 循环统计"])
    else:
        t_prev, t_plot, t_cyc = st.tabs(["📋 数据预览", "📈 曲线", "🔁 循环统计"])

    adjusted_df, adjusted_summ = df, summ
    with t_cyc:
        if len(adjusted_summ):
            chart_col, controls_col = st.columns([4.8, 1.2], gap="large")
            if allow_cycle_adjustments:
                with controls_col:
                    st.markdown("##### Capacity")
                    cap_scale = st.number_input("百分比缩放 / %", value=100.0, step=1.0,
                                                format="%.3f", key=f"cap-scale-{key}")
                    cap_offset = st.number_input("固定 offset / mAh", value=0.0, step=0.001,
                                                 format="%.6f", key=f"cap-offset-{key}")
                    st.markdown("##### 库仑效率 CE")
                    ce_scale = st.number_input("百分比缩放 / %", value=100.0, step=1.0,
                                               format="%.3f", key=f"ce-scale-{key}")
                    ce_offset = st.number_input("固定 offset / 百分点", value=0.0, step=0.1,
                                                format="%.3f", key=f"ce-offset-{key}")
                    st.caption("先调整每圈充、放电总容量，再调整 CE（放电容量 ÷ 充电容量）。"
                               "容量 offset 为每圈增减量；CE offset 为百分点。电流与能量同步反算。")
                try:
                    adjusted_df = adjust_cycle_measurements(
                        df,
                        capacity_scale_pct=cap_scale,
                        capacity_offset_mah=cap_offset,
                        efficiency_scale_pct=ce_scale,
                        efficiency_offset_pct=ce_offset,
                    )
                except ValueError as e:
                    st.error(str(e))
                    return b"", b""
                adjusted_summ = cycle_summary(adjusted_df)
        else:
            st.info("没有可统计的循环。")

    if area_cm2 is not None:
        adjusted_df = adjusted_df.copy()
        adjusted_df["ElectrodeArea_cm2"] = area_cm2
        adjusted_df["SpecificCapacity_mAh_cm2"] = adjusted_df["Capacity_mAh"] / area_cm2

    profile_active = False
    with t_plot:
        if area_cm2 is None:
            st.plotly_chart(fig_timeseries(adjusted_df), use_container_width=True, key=f"ts-{key}")
        else:
            st.caption(f"面积比容量 = 容量 ÷ 电极面积（{area_cm2:g} cm²），单位 mAh/cm²。")
        cyc_all = sorted(int(c) for c in adjusted_df.loc[adjusted_df["Mode"] != "Rest", "Cycle"].unique())
        if cyc_all:
            default = sorted({cyc_all[0], cyc_all[len(cyc_all) // 2], cyc_all[-1]})
            chosen = st.multiselect("充放电曲线 – 选择循环", cyc_all, default=default, max_selections=8, key=f"cyc-{key}")
            if chosen:
                baseline = adjusted_df
                reference = None
                if allow_profile_adjustments and area_cm2 is not None:
                    profile_plot, profile_controls = st.columns([3.5, 1.3], gap="large")
                    with profile_controls:
                        try:
                            adjusted_df, show_reference = _profile_controls(baseline, chosen, area_cm2, key)
                        except ValueError as e:
                            st.error(str(e))
                            return b"", b""
                    profile_active = "ProfileAdjusted" in adjusted_df and bool(adjusted_df.ProfileAdjusted.any())
                    if profile_active:
                        for col in ("Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh"):
                            adjusted_df[f"Baseline_{col}"] = baseline[col].to_numpy()
                        adjusted_df = with_original_deltas(adjusted_df, df, area_cm2)
                        adjusted_summ = cycle_summary(adjusted_df)
                        raw_summary = cycle_summary(df).set_index("Cycle")
                        for col in ("DischargeCapacity_mAh", "ChargeCapacity_mAh", "CoulombicEfficiency_pct"):
                            adjusted_summ[f"Original_{col}"] = adjusted_summ.Cycle.map(raw_summary[col])
                            adjusted_summ[f"Delta_{col}"] = adjusted_summ[col] - adjusted_summ[f"Original_{col}"]
                        adjusted_summ["DataKind"] = "profile_simulation"
                        reference = df if show_reference else None
                    with profile_plot:
                        if profile_active:
                            st.warning("当前为模拟调整曲线，非原始测量。启用对照时灰线为原始测量。")
                        st.plotly_chart(fig_profiles(adjusted_df, chosen, area_cm2, reference),
                                        use_container_width=True, key=f"pr-{key}")
                        if profile_active:
                            st.markdown("##### 相对原始值的变化")
                            fields = {"面积比容量 / mAh/cm²": "SpecificCapacity_mAh_cm2",
                                      "横轴显示坐标 / mAh/cm²": "PlotSpecificCapacity_mAh_cm2",
                                      "电压 / V": "Voltage_V", "电流 / mA": "Current_mA",
                                      "容量 / mAh": "Capacity_mAh", "能量 / mWh": "Energy_mWh"}
                            field = fields[st.selectbox("变化对象", list(fields), key=f"profile-delta-{key}")]
                            ids = [c for c in ("Index", "Cycle", "Mode") if c in adjusted_df]
                            columns = ids + [f"Original_{field}", field, f"Delta_{field}", f"ChangePct_{field}"]
                            comparison_rows = adjusted_df.Cycle.isin(chosen)
                            if st.checkbox("仅显示有变化的记录", value=True, key=f"profile-changed-only-{key}"):
                                comparison_rows &= adjusted_df[f"Delta_{field}"].abs() > 1e-12
                            changes = adjusted_df.loc[comparison_rows, columns].rename(columns={
                                f"Original_{field}": "原始值", field: "调整后值", f"Delta_{field}": "变化量 Δ",
                                f"ChangePct_{field}": "变化率 / %"})
                            st.caption("变化量 = 调整后 − 原始；变化率 = 变化量 ÷ |原始值| × 100%，原始为 0 时留空。"
                                       "横轴显示坐标包含独立平移，面积比容量不包含。CSV 同时保留所有变化列。")
                            if changes.empty:
                                st.info("当前指标没有发生变化，可切换变化对象或显示全部记录。")
                            st.dataframe(changes, height=240, use_container_width=True, hide_index=True)
                else:
                    st.plotly_chart(fig_profiles(adjusted_df, chosen, area_cm2), use_container_width=True, key=f"pr-{key}")
        if area_cm2 is not None:
            with st.expander("电压 / 电流随时间变化"):
                st.plotly_chart(fig_timeseries(adjusted_df), use_container_width=True, key=f"ts-{key}")

    with t_prev:
        st.dataframe(adjusted_df, height=420, use_container_width=True, hide_index=True)
    if len(adjusted_summ):
        with t_cyc:
            with chart_col:
                st.plotly_chart(fig_cycles(adjusted_summ), use_container_width=True, key=f"cy-{key}")
            st.dataframe(adjusted_summ, height=320, use_container_width=True, hide_index=True)

    b = st.columns([1, 1, 4])
    data_csv = csv_bytes(adjusted_df)
    summ_csv = csv_bytes(adjusted_summ) if len(adjusted_summ) else b""
    export_stem = f"{stem}_simulated" if profile_active else stem
    b[0].download_button("⬇️ 下载模拟数据 CSV" if profile_active else "⬇️ 下载数据 CSV", data_csv,
                         file_name=f"{export_stem}.csv", mime="text/csv", key=f"d-{key}")
    if summ_csv:
        b[1].download_button("⬇️ 下载循环统计 CSV", summ_csv, file_name=f"{export_stem}_cycles.csv", mime="text/csv", key=f"s-{key}")
    return data_csv, summ_csv
