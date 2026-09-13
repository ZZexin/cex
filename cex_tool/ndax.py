"""Read the NDC v5/type 1 layout inside Neware NDAX archives.

Layout reference: https://github.com/d-cogswell/NewareNDA
This reader is limited to the self-contained data.ndc variant verified against
the supplied BTS 8 files. No temporary extraction or guessed range factors.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

STATES = {1: "CC_Chg", 2: "CC_DChg", 3: "CV_Chg", 4: "Rest", 5: "Cycle",
          6: "End", 7: "CCCV_Chg", 8: "CP_DChg", 9: "CP_Chg", 10: "CR_DChg",
          13: "Pause", 16: "Pulse", 17: "SIM", 19: "CV_DChg", 20: "CCCV_DChg",
          21: "Control", 22: "OCV", 26: "CPCV_DChg", 27: "CPCV_Chg"}
# Factors convert the per-record current integer to mA (not the XML range).
CURRENT_FACTORS = {
    **dict.fromkeys((-1, -2, -5), 1e-5),
    **dict.fromkeys((-10, -20, -25, -50, 1, 2, 5), 1e-4),
    **dict.fromkeys((-100, -500, 10, 20, 25, 50), 1e-3),
    **dict.fromkeys((-1000, -2000, -3000, -5000, -6000, -10000, -12000,
                     -20000, -30000, -40000, -50000, -60000, -100000, -200000,
                     100, 200, 250, 500), 1e-2),
    **dict.fromkeys((1000, 6000, 10000, 12000, 20000, 30000, 40000,
                     50000, 60000, 100000, 200000), 1e-1),
    -100000000: 10.,
}
PAGE_SIZE = 4096
RECORD_SIZE = 87
MAX_MEMBER_SIZE = 256 * 1024 * 1024


class NdaxFormatError(ValueError):
    """Invalid or unsupported NDAX data; do not return a partial decode."""


@dataclass
class NdaxDataset:
    data: pd.DataFrame
    metadata: dict
    recipe: pd.DataFrame
    warnings: list[str]


def _xml(data: bytes) -> ET.Element:
    match = re.search(br'encoding=[\"\x27]([^\"\x27]+)', data[:160], re.I)
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    if encoding.lower() in ("gb2312", "gbk"):
        encoding = "gb18030"
    try:
        return ET.fromstring(data.decode(encoding))
    except (UnicodeError, LookupError, ET.ParseError) as e:
        raise NdaxFormatError(f"NDAX XML 无法解析：{e}") from e


def _recipes(zf: zipfile.ZipFile) -> pd.DataFrame:
    rows = []
    files = sorted((n for n in zf.namelist() if re.fullmatch(r"Step\d*\.xml", n)),
                   key=lambda n: int(n[4:-4] or 0))
    for name in files:
        root = _xml(zf.read(name))
        for node in root.findall("./config/Step_Info/*"):
            def value(path, scale=1.):
                child = node.find(path)
                return float(child.get("Value")) * scale if child is not None and child.get("Value") else None
            code = int(node.get("Step_Type", "0"))
            rows.append({"配置文件": name, "工步": int(node.get("Step_ID", "0")),
                         "类型": STATES.get(code, f"Unknown_{code}"),
                         "电流 mA": value("Limit/Main/Curr"),
                         "截止电压 V": value("Limit/Main/Stop_Volt", 1e-4),
                         "记录间隔 s": value("Record/Main/Time", 1e-3),
                         "循环起始工步": value("Limit/Other/Start_Step"),
                         "循环次数": value("Limit/Other/Cycle_Count")})
    return pd.DataFrame(rows)


def _cycles(df: pd.DataFrame, mode: str) -> np.ndarray:
    if mode == "file":
        return df["CycleRaw"].to_numpy(dtype=np.int64) + 1
    if mode not in ("chg", "dchg"):
        raise ValueError("循环分组必须是 file、chg 或 dchg。")
    begin = "_Chg" if mode == "chg" else "_DChg"
    other = "_DChg" if mode == "chg" else "_Chg"
    cycle, seen_other, result = 1, False, []
    for state in df["Mode"]:
        if state.endswith(begin) and seen_other:
            cycle += 1
            seen_other = False
        elif state.endswith(other):
            seen_other = True
        result.append(cycle)
    return np.array(result, dtype=np.int64)


def parse_ndax(data: bytes, cycle_mode: str = "file") -> NdaxDataset:
    """Decode an NDAX upload to the shared measurement schema, in memory.

    DateTime preserves the file's local calendar values. TestTime_s is the sum
    of step elapsed times, excluding gaps while the test was paused. CycleRaw
    always preserves the instrument counter, regardless of the display rule.
    """
    warnings = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if len(names) != len(set(names)):
                raise NdaxFormatError("NDAX 内含重名成员，无法确定数据来源。")
            if any(i.file_size > MAX_MEMBER_SIZE for i in zf.infolist()) or sum(i.file_size for i in zf.infolist()) > 2 * MAX_MEMBER_SIZE:
                raise NdaxFormatError("NDAX 解压数据超过支持的大小（单成员 256 MiB）。")
            if "data.ndc" not in names:
                raise NdaxFormatError("NDAX 中缺少 data.ndc。")
            ndc = zf.read("data.ndc")
            if len(ndc) < PAGE_SIZE or len(ndc) % PAGE_SIZE:
                raise NdaxFormatError("data.ndc 长度不是完整的 4096 字节分页，文件可能被截断。")
            if (ndc[0], ndc[2]) != (1, 5) or "data_runInfo.ndc" in names or "data_step.ndc" in names:
                raise NdaxFormatError(f"当前支持 NDC v5 / type 1 单数据文件；此文件为 v{ndc[2]} / type {ndc[0]}。")
            info = _xml(zf.read("TestInfo.xml")).find("./config/TestInfo") if "TestInfo.xml" in names else None
            metadata = dict(info.attrib) if info is not None else {}
            recipe = _recipes(zf)
            # Reading all members also verifies the archive's CRCs.
            bad = zf.testzip()
            if bad:
                raise NdaxFormatError(f"NDAX ZIP CRC 校验失败：{bad}")
            metadata.update(ndc_version=5, ndc_type=1, crc_ok=True,
                            members=[{"文件": i.filename, "解压字节数": i.file_size} for i in zf.infolist()])
            if any(n.startswith("data_AUX") for n in names):
                warnings.append("本页解码主通道测量数据；该文件的辅助通道尚未导出。")
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError) as e:
        raise NdaxFormatError(f"NDAX 容器读取失败：{e}") from e

    rows = []
    for page in range(PAGE_SIZE, len(ndc), PAGE_SIZE):
        for offset in range(page + 125, page + 4040, RECORD_SIZE):
            if ndc[offset + 7] != 0x55:
                if ndc[offset + 7] != 0:
                    raise NdaxFormatError(f"data.ndc 在 {offset:#x} 出现不支持的记录类型。")
                continue
            index, cycle, step, status = struct.unpack_from("<IIBB", ndc, offset + 8)
            if not index:
                raise NdaxFormatError("测量记录序号为零。")
            elapsed, voltage, current = struct.unpack_from("<Qii", ndc, offset + 23)
            qc, qd, ec, ed = struct.unpack_from("<qqqq", ndc, offset + 43)
            date_fields = struct.unpack_from("<HBBBBB", ndc, offset + 75)
            range_code = struct.unpack_from("<i", ndc, offset + 82)[0]
            if range_code not in CURRENT_FACTORS:
                raise NdaxFormatError(f"不支持电流量程码 {range_code}，不能安全猜测换算系数。")
            factor = CURRENT_FACTORS[range_code]
            if status not in STATES:
                raise NdaxFormatError(f"不支持工步状态码 {status}。")
            state = STATES[status]
            if state in ("Pulse", "SIM", "Control"):
                raise NdaxFormatError(f"当前未支持 {state} 工步的容量统计。")
            if state.endswith("_Chg"):
                capacity, energy = qc, ec
            elif state.endswith("_DChg"):
                capacity, energy = qd, ed
            else:
                capacity, energy = qc + qd, ec + ed
            try:
                timestamp = datetime(*date_fields)
            except ValueError as e:
                raise NdaxFormatError(f"记录 {index} 的日期无效：{date_fields}") from e
            rows.append((index, cycle, step, state, elapsed / 1000., voltage / 10000.,
                         current * factor, capacity * factor / 3600., energy * factor / 3600.,
                         timestamp, range_code, status))
    if not rows:
        raise NdaxFormatError("NDAX 中没有测量记录。")
    df = pd.DataFrame(rows, columns=["Index", "CycleRaw", "Step", "Mode", "StepTime_s",
                                     "Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh",
                                     "DateTime", "RangeCode", "StatusCode"])
    if df["Index"].duplicated().any():
        raise NdaxFormatError("测量记录序号重复，无法保证数据对应关系。")
    df = df.sort_values("Index", kind="stable").reset_index(drop=True)
    if (df["Index"].diff().dropna() != 1).any():
        warnings.append("测量记录序号不连续，文件可能只包含部分记录。")
    boundary = (df[["Step", "CycleRaw", "Mode"]].ne(df[["Step", "CycleRaw", "Mode"]].shift()).any(axis=1)
                | df["StepTime_s"].diff().lt(0))
    df["StepSeq"] = boundary.cumsum()
    durations = df.groupby("StepSeq", sort=True)["StepTime_s"].max()
    offsets = durations.cumsum().shift(fill_value=0)
    df["TestTime_s"] = df["StepTime_s"] + df["StepSeq"].map(offsets)
    df["Cycle"] = _cycles(df, cycle_mode)
    df = df[["Index", "Cycle", "Step", "StepSeq", "Mode", "TestTime_s", "StepTime_s",
             "Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh", "DateTime",
             "CycleRaw", "RangeCode", "StatusCode"]]
    metadata.update(records=len(df), steps=int(df["StepSeq"].max()), cycles=df["Cycle"].nunique(),
                    first_record=str(df["DateTime"].iloc[0]), last_record=str(df["DateTime"].iloc[-1]),
                    duration_h=float(df["TestTime_s"].iloc[-1] / 3600), cycle_mode=cycle_mode,
                    range_codes=sorted(df["RangeCode"].unique().tolist()))
    last = df.iloc[-1]
    # All revisions are shown; use the latest recorded recipe for this hint.
    cutoff = recipe.loc[recipe["工步"] == last["Step"], "截止电压 V"].dropna() if not recipe.empty else pd.Series(dtype=float)
    if len(cutoff):
        limit = float(cutoff.iloc[-1])
        if ((last["Mode"].endswith("_Chg") and last["Voltage_V"] < limit - .01)
                or (last["Mode"].endswith("_DChg") and last["Voltage_V"] > limit + .01)):
            warnings.append(f"末工步截止电压设为 {limit:g} V，最后记录为 {last['Voltage_V']:.4f} V；"
                            "末圈可能未完成，效率按现有记录计算。")
    if int(metadata.get("ModifyCount", 0)):
        warnings.append(f"测试包含 {metadata['ModifyCount']} 次工步配置修改；实际测量以 data.ndc 为准，配置历史见下方。")
    if metadata.get("EndTime"):
        end = pd.to_datetime(metadata["EndTime"], errors="coerce")
        if pd.notna(end) and (end - df["DateTime"].iloc[-1]).total_seconds() > 60:
            warnings.append(f"测试信息的结束时间为 {end}，但测量记录只到 {df['DateTime'].iloc[-1]}。")
    return NdaxDataset(df, metadata, recipe, warnings)
