"""Explicit what-if curve transformations, never a correction of experiments."""
from __future__ import annotations

import numpy as np
import pandas as pd


def with_original_deltas(adjusted: pd.DataFrame, original: pd.DataFrame, area_cm2: float) -> pd.DataFrame:
    """Compare matching measurement rows, including separate physical/plot x deltas."""
    if len(adjusted) != len(original) or not adjusted.index.equals(original.index):
        raise ValueError("调整数据与原始记录未对齐，无法计算变化量。")
    out = adjusted.copy()
    for col in ("Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh"):
        out[f"Original_{col}"] = original[col].to_numpy()
    out["Original_SpecificCapacity_mAh_cm2"] = original.Capacity_mAh.to_numpy() / area_cm2
    out["SpecificCapacity_mAh_cm2"] = out.Capacity_mAh / area_cm2
    out["Original_PlotSpecificCapacity_mAh_cm2"] = out.Original_SpecificCapacity_mAh_cm2
    if "PlotSpecificCapacity_mAh_cm2" not in out:
        out["PlotSpecificCapacity_mAh_cm2"] = out.SpecificCapacity_mAh_cm2
    for col in ("Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh",
                "SpecificCapacity_mAh_cm2", "PlotSpecificCapacity_mAh_cm2"):
        out[f"Delta_{col}"] = out[col] - out[f"Original_{col}"]
        denominator = out[f"Original_{col}"].abs().replace(0., np.nan)
        out[f"ChangePct_{col}"] = out[f"Delta_{col}"] / denominator * 100
    return out


def simulate_profile(
    df: pd.DataFrame, *, cycles: list[int], phase: str, area_cm2: float,
    start: float, end: float, stretch_pct: float = 100.,
    voltage_offset_v: float = 0., x_offset: float = 0., edge_pct: float = 5.,
) -> pd.DataFrame:
    """Warp an areal-capacity interval, with continuous capacity at both edges.

    Sampling times are retained. Changed capacity intervals imply right-endpoint
    equivalent currents (not instantaneous instrument samples). Energy uses
    trapezoidal voltage integration against capacity. Horizontal translation is
    a separate plotting coordinate, and does not change physical capacity.
    """
    parameters = [area_cm2, start, end, stretch_pct, voltage_offset_v, x_offset, edge_pct]
    if not np.isfinite(parameters).all():
        raise ValueError("平台调整参数必须是有限数值。")
    if area_cm2 <= 0 or stretch_pct <= 0:
        raise ValueError("面积和平台长度比例必须大于 0。")
    if start < 0 or end <= start or not 0 <= edge_pct <= 50:
        raise ValueError("平台区间需满足 0 ≤ 起点 < 终点；边缘过渡比例应为 0–50%。")
    if phase not in ("charge", "discharge", "both"):
        raise ValueError("未知的充放电方向。")
    out = df.copy(deep=True)
    if stretch_pct == 100 and voltage_offset_v == 0 and x_offset == 0:
        return out
    original_index = out.index
    out = out.reset_index(drop=True)
    for col in ("Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh"):
        out[f"Original_{col}"] = out[col]
    out["ProfileAdjusted"] = False
    out["ProfileXOffset_mAh_cm2"] = 0.
    out["CurrentRepresentation"] = "baseline_sample"
    out["ProfileStart_mAh_cm2"] = np.nan
    out["ProfileEnd_mAh_cm2"] = np.nan
    out["ProfileStretch_pct"] = 100.
    out["ProfileVoltageOffset_V"] = 0.
    out["ProfileEdge_pct"] = edge_pct
    suffix = {"charge": ("_Chg",), "discharge": ("_DChg",), "both": ("_Chg", "_DChg")}[phase]
    selected = out.Cycle.isin(cycles) & out.Mode.astype(str).str.endswith(suffix)
    if not selected.any():
        raise ValueError("所选循环没有对应方向的记录。")
    a, b, scale = start * area_cm2, end * area_cm2, stretch_pct / 100.
    overlaps = False
    for _, step in out.loc[selected].groupby(["Cycle", "StepSeq"], sort=False):
        idx = step.index
        q = step.Capacity_mAh.to_numpy(dtype=float)
        v = step.Voltage_V.to_numpy(dtype=float)
        if not np.isfinite(q).all() or not np.isfinite(v).all() or np.any(q < 0) or np.any(np.diff(q) < 0):
            raise ValueError("所选工步容量必须为非负、单调递增的有限值，电压必须有限。")
        overlaps |= bool(q[-1] > a and q[0] < b)
        warped_q = q + (scale - 1) * np.clip(q - a, 0, b - a)
        weight = ((q >= a) & (q <= b)).astype(float)
        if edge_pct:
            width = (b - a) * edge_pct / 100.
            ramp = np.clip(np.minimum((q - a) / width, (b - q) / width), 0, 1)
            weight = ramp * ramp * (3 - 2 * ramp)
        warped_v = v + voltage_offset_v * weight
        if not np.isfinite(warped_q).all() or not np.isfinite(warped_v).all():
            raise ValueError("调整结果超出数值范围，请减小参数。")
        q_changed = not np.array_equal(q, warped_q)
        v_changed = not np.array_equal(v, warped_v)
        if q_changed:
            t = step.StepTime_s.to_numpy(dtype=float)
            dt = np.diff(t, prepend=0.)
            dq = np.diff(warped_q, prepend=0.)
            if not np.isfinite(dt).all() or np.any(dt < 0) or np.any((dt == 0) & (dq > 1e-12)):
                raise ValueError("存在非递增工步时间或零时长容量增量，无法反算等效电流。")
            current = step.Current_mA.to_numpy(dtype=float).copy()
            sign = -1 if str(step.Mode.iloc[0]).endswith("_DChg") else 1
            np.divide(sign * 3600 * dq, dt, out=current, where=dt > 0)
            out.loc[idx, "Current_mA"] = current
            out.loc[idx, "CurrentRepresentation"] = "interval_equivalent_right_endpoint"
        if q_changed or v_changed:
            energy = np.r_[warped_q[0] * warped_v[0],
                           (warped_v[1:] + warped_v[:-1]) * .5 * np.diff(warped_q)].cumsum()
            out.loc[idx, "Energy_mWh"] = energy
        out.loc[idx, "Capacity_mAh"] = warped_q
        out.loc[idx, "Voltage_V"] = warped_v
        out.loc[idx, "ProfileAdjusted"] = q_changed or v_changed or x_offset != 0
        out.loc[idx, "ProfileXOffset_mAh_cm2"] = x_offset
        out.loc[idx, "ProfileStart_mAh_cm2"] = start
        out.loc[idx, "ProfileEnd_mAh_cm2"] = end
        out.loc[idx, "ProfileStretch_pct"] = stretch_pct
        out.loc[idx, "ProfileVoltageOffset_V"] = voltage_offset_v
    if not overlaps and (stretch_pct != 100 or voltage_offset_v != 0):
        raise ValueError("平台区间与所选曲线没有重叠，请根据调整前的横轴修改起点和终点。")
    out["ElectrodeArea_cm2"] = area_cm2
    out["SpecificCapacity_mAh_cm2"] = out.Capacity_mAh / area_cm2
    out["PlotSpecificCapacity_mAh_cm2"] = out.SpecificCapacity_mAh_cm2 + out.ProfileXOffset_mAh_cm2
    out["DataKind"] = "profile_simulation"
    out.index = original_index
    return out
