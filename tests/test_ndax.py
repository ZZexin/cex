import io
import struct
import zipfile

import numpy as np
import pandas as pd
import pytest

from cex_tool.ndax import NdaxFormatError, parse_ndax
from cex_tool.reader import adjust_cycle_measurements, cycle_summary


def make_ndax(*, count=12, range_code=-1, version=5, status_override=None):
    """Independent fixture with 1 mA charge and 0.5 mA discharge, 20 s samples."""
    pages = (count + 44) // 45
    ndc = bytearray((pages + 1) * 4096)
    ndc[0], ndc[2] = 1, version
    for n in range(count):
        offset = (n // 45 + 1) * 4096 + 125 + n % 45 * 87
        step = n // 3 % 2 + 1
        status = status_override if status_override is not None and step == 1 else step
        ndc[offset + 7] = 0x55
        struct.pack_into("<IIBB", ndc, offset + 8, n + 1, n // 6, step, status)
        seconds = n % 3 * 20
        struct.pack_into("<Qii", ndc, offset + 23, seconds * 1000, 15000,
                         100000 if step == 1 else -50000)
        q = seconds * (100000 if step == 1 else 50000)
        struct.pack_into("<qqqq", ndc, offset + 43,
                         q if step == 1 else 0, q if step == 2 else 0,
                         q * 3 // 2 if step == 1 else 0, q * 3 // 2 if step == 2 else 0)
        struct.pack_into("<HBBBBB", ndc, offset + 75, 2026, 7, 31, n // 180, n // 3 % 60, n % 3 * 20)
        struct.pack_into("<i", ndc, offset + 82, range_code)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("data.ndc", ndc)
        z.writestr("TestInfo.xml", ('<?xml version="1.0" encoding="GB2312"?>'
                   '<root><config><TestInfo UnitID="11" ChlID="1" ModifyCount="0" '
                   'SN="中文样本" StartTime="2026-07-31 00:00:00" /></config></root>').encode("gb2312"))
        z.writestr("Step.xml", '<root><config><Step_Info>'
                   '<Step1 Step_ID="1" Step_Type="1"><Limit><Main><Curr Value="1" />'
                   '<Stop_Volt Value="18000" /></Main></Limit></Step1>'
                   '<Step2 Step_ID="2" Step_Type="2"><Limit><Main><Curr Value="0.5" />'
                   '<Stop_Volt Value="8000" /></Main></Limit></Step2>'
                   '</Step_Info></config></root>')
    return stream.getvalue()


def test_ndax_measurement_units_cycles_and_metadata():
    parsed = parse_ndax(make_ndax())
    d = parsed.data
    assert len(d) == 12
    assert parsed.metadata["SN"] == "中文样本"
    assert parsed.metadata["crc_ok"]
    assert parsed.metadata["steps"] == 4
    assert parsed.metadata["cycles"] == 2
    assert d.DateTime.iloc[0] == pd.Timestamp("2026-07-31")
    np.testing.assert_array_equal(d.CycleRaw, [0] * 6 + [1] * 6)
    np.testing.assert_array_equal(d.Cycle, [1] * 6 + [2] * 6)
    np.testing.assert_allclose(d.Current_mA, [1.] * 3 + [-.5] * 3 + [1.] * 3 + [-.5] * 3)
    np.testing.assert_allclose(d.Voltage_V, 1.5)
    np.testing.assert_allclose(d.TestTime_s[:6], [0, 20, 40, 40, 60, 80])
    np.testing.assert_allclose(d.Capacity_mAh[:3], [0, 20 / 3600, 40 / 3600])
    np.testing.assert_allclose(d.Energy_mWh, d.Capacity_mAh * 1.5)
    np.testing.assert_allclose(cycle_summary(d).CoulombicEfficiency_pct, 50.)
    assert any("末圈" in w for w in parsed.warnings)


def test_ndax_page_boundaries_and_cycle_choice():
    raw = make_ndax(count=48)
    d = parse_ndax(raw).data
    assert len(d) == 48
    np.testing.assert_array_equal(d.Index, np.arange(1, 49))
    chg = parse_ndax(raw, "chg").data
    np.testing.assert_array_equal(chg.Cycle, d.Cycle)
    discharge = parse_ndax(raw, "dchg").data
    assert discharge.Cycle.iloc[0] == 1
    assert discharge.Cycle.iloc[3] == 2
    np.testing.assert_array_equal(discharge.CycleRaw, d.CycleRaw)
    with pytest.raises(ValueError, match="循环分组"):
        parse_ndax(raw, "invalid")


@pytest.mark.parametrize("kwargs, message", [({"version": 14}, "当前支持"),
                                             ({"range_code": -3}, "量程码"),
                                             ({"status_override": 99}, "状态码")])
def test_ndax_unknown_layout_range_and_status_are_rejected(kwargs, message):
    with pytest.raises(NdaxFormatError, match=message):
        parse_ndax(make_ndax(**kwargs))


def test_ndax_crc_and_nonzip_rejected():
    with pytest.raises(NdaxFormatError, match="容器"):
        parse_ndax(b"this is not an NDAX")
    data = bytearray(make_ndax())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        member = z.getinfo("data.ndc")
        payload_start = member.header_offset + 30 + len(member.filename) + len(member.extra)
    data[payload_start + 5000] ^= 1
    with pytest.raises(NdaxFormatError, match="CRC"):
        parse_ndax(bytes(data))


@pytest.mark.parametrize("status", [1, 3, 7])
def test_ndax_adjustments_export_targets_without_changing_source(status):
    raw = make_ndax(status_override=status)
    d = parse_ndax(raw).data
    before = d.copy(deep=True)
    adjusted = adjust_cycle_measurements(d, capacity_scale_pct=120, capacity_offset_mah=.01,
                                         efficiency_scale_pct=95, efficiency_offset_pct=1)
    exported = pd.read_csv(io.StringIO(adjusted.to_csv(index=False, float_format="%.12g")))
    s = cycle_summary(exported)
    qc = 40 / 3600 * 1.2 + .01
    qd = 20 / 3600 * 1.2 + .01
    np.testing.assert_allclose(s.ChargeCapacity_mAh, qc)
    np.testing.assert_allclose(s.CoulombicEfficiency_pct, qd / qc * 95 + 1)
    np.testing.assert_allclose(exported.groupby("StepSeq").Capacity_mAh.first(), 0.)
    pd.testing.assert_frame_equal(d, before)
    pd.testing.assert_frame_equal(parse_ndax(raw).data, before)
