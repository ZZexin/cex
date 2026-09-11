import io
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cex_tool import format as F
from cex_tool.reader import (_read_records, adjust_cycle_measurements, assign_cycles,
                             cycle_summary, parse_cex, to_dataframe)
from cex_tool.writer import (build_cex, detect_columns, load_template, normalize_table,
                             segment_table, template_from_cex)

SAMPLES = sorted(Path(__file__).resolve().parent.parent.joinpath("samples").glob("*.cex"))
needs_samples = pytest.mark.skipif(not SAMPLES, reason="no sample .cex files in samples/")


# --------------------------------------------------------------------------- reader
@needs_samples
@pytest.mark.parametrize("path", SAMPLES, ids=[p.stem for p in SAMPLES])
def test_parse_samples(path):
    cex = parse_cex(path.read_bytes())
    assert not cex.warnings, cex.warnings
    assert all(cex.checksums_ok().values()), cex.checksums_ok()
    assert cex.n_records > 60_000
    assert len(cex.steps) > 900
    assert [s.mode for s in cex.recipe] == [F.MODE_REST, F.MODE_CC_DCHG, F.MODE_CC_CHG]
    assert cex.recipe[1].current_a == pytest.approx(4e-5, rel=1e-6)
    assert cex.recipe[1].cond_value == pytest.approx(0.8, rel=1e-6)
    assert cex.recipe[2].cond_value == pytest.approx(1.8, rel=1e-6)
    # step timestamps are start + first record time (10 ms ticks)
    for s in cex.steps[1:20]:
        assert abs((s.ts - cex.start_ts) - s.records["t"][0] * F.T_UNIT) < 1.0

    df = to_dataframe(cex)
    assert list(df.columns)[:5] == ["Index", "Cycle", "Step", "StepSeq", "Mode"]
    assert 0.78 < df["Voltage_V"].min() < 0.83
    assert 1.78 < df["Voltage_V"].max() < 1.83
    chg = df[df["Mode"] == "CC_Chg"]
    assert chg["Current_mA"].median() == pytest.approx(0.04, rel=0.02)
    assert (df[df["Mode"] == "CC_DChg"]["Current_mA"] < 0).all()
    # capacity increments agree with current * dt
    d = chg[chg["StepSeq"] == chg["StepSeq"].iloc[0]]
    dq = np.diff(d["Capacity_mAh"].to_numpy())
    dt = np.diff(d["TestTime_s"].to_numpy()) / 3600
    assert np.median(dq / dt) == pytest.approx(0.04, rel=0.02)
    assert df["StepTime_s"].min() == 0
    assert df["Cycle"].max() > 400

    summ = cycle_summary(df)
    assert len(summ) == df["Cycle"].max()
    assert summ["CoulombicEfficiency_pct"].dropna().between(50, 150).all()


def test_assign_cycles():
    assert assign_cycles([1, 2, 3, 2, 3, 2, 3]) == [1, 1, 1, 2, 2, 3, 3]
    assert assign_cycles([2, 3, 4, 5]) == [1, 1, 1, 1]
    assert assign_cycles([]) == []


def test_adjust_cycle_measurements_updates_capacity_and_efficiency():
    rows = []
    for cyc, qd, qc in ((1, 8.0, 10.0), (2, 9.0, 10.0)):
        for mode, q in (("CC_DChg", qd), ("CC_Chg", qc)):
            for value in (0.0, q):
                rows.append({"Cycle": cyc, "StepSeq": len(rows) // 2 + 1, "Mode": mode,
                             "Capacity_mAh": value, "Energy_mWh": value,
                             "Voltage_V": 1.0, "DateTime": pd.Timestamp("2026-01-01"),
                             "TestTime_s": float(len(rows))})
    df = pd.DataFrame(rows)

    adjusted = adjust_cycle_measurements(
        df, capacity_scale_pct=110, capacity_offset_mah=1,
        efficiency_scale_pct=90, efficiency_offset_pct=2,
    )
    summary = cycle_summary(adjusted)

    # Charge data receives the direct capacity transform.
    assert adjusted.loc[adjusted["Mode"] == "CC_Chg", "Capacity_mAh"].max() == pytest.approx(12.0)
    # Capacity transform gives 81.667 % / 90.833 %, then CE ×90 % +2 points.
    np.testing.assert_allclose(summary["CoulombicEfficiency_pct"], [75.5, 83.75])
    assert not adjusted["Capacity_mAh"].equals(df["Capacity_mAh"])
    assert df["Capacity_mAh"].iloc[0] == 0.0  # input is not mutated

    capacity_only = adjust_cycle_measurements(df, capacity_scale_pct=110, capacity_offset_mah=1)
    expected = cycle_summary(df)
    actual = cycle_summary(capacity_only)
    for col in ("DischargeCapacity_mAh", "ChargeCapacity_mAh"):
        np.testing.assert_allclose(actual[col], expected[col] * 1.1 + 1)
    assert (capacity_only.groupby("StepSeq")["Capacity_mAh"].first() == 0).all()
    pd.testing.assert_frame_equal(adjust_cycle_measurements(df), df)


@pytest.mark.parametrize("offset", [0.01, -0.001])
def test_adjusted_csv_cex_roundtrip_and_integrals(offset):
    raw = _synthetic()
    # Unequal charge/discharge capacity is essential to detect CE distortion.
    raw.loc[raw["Current/mA"] < 0, "Current/mA"] *= 0.8
    original = to_dataframe(parse_cex(build_cex(normalize_table(raw), start_ts=1_800_000_000)))
    snapshot = original.copy(deep=True)
    adjusted = adjust_cycle_measurements(original, capacity_scale_pct=130,
                                         capacity_offset_mah=offset,
                                         efficiency_scale_pct=97, efficiency_offset_pct=2)
    before = cycle_summary(original).iloc[0]
    after = cycle_summary(adjusted).iloc[0]
    qc = before["ChargeCapacity_mAh"] * 1.3 + offset
    qd = before["DischargeCapacity_mAh"] * 1.3 + offset
    assert after["ChargeCapacity_mAh"] == pytest.approx(qc)
    assert after["CoulombicEfficiency_pct"] == pytest.approx(qd / qc * 100 * .97 + 2)
    pd.testing.assert_frame_equal(original, snapshot)
    pd.testing.assert_frame_equal(adjusted[adjusted.Mode == "Rest"], original[original.Mode == "Rest"])

    for _, step in adjusted[adjusted.Mode != "Rest"].groupby("StepSeq"):
        q = step.Capacity_mAh.to_numpy()
        v = step.Voltage_V.to_numpy()
        t = step.TestTime_s.to_numpy()
        i = abs(step.Current_mA.to_numpy())
        assert q[0] == 0
        assert q[-1] == pytest.approx(np.sum((i[1:] + i[:-1]) / 2 * np.diff(t)) / 3600)
        np.testing.assert_allclose(step.Energy_mWh,
                                   np.r_[0., np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(q))])

    csv = pd.read_csv(io.StringIO(adjusted.to_csv(index=False, float_format="%.12g")))
    encoded = parse_cex(build_cex(normalize_table(csv), start_ts=1_800_000_000))
    assert all(encoded.checksums_ok().values())
    back = to_dataframe(encoded)
    for col in ("Capacity_mAh", "Energy_mWh"):
        np.testing.assert_allclose(back[col], adjusted[col], rtol=1e-6, atol=1e-10)
    np.testing.assert_allclose(back.Current_mA, adjusted.Current_mA, atol=F.I_LSB * 1e3 / 2)
    np.testing.assert_allclose(cycle_summary(back).CoulombicEfficiency_pct,
                               cycle_summary(adjusted).CoulombicEfficiency_pct, rtol=1e-6)


def test_capacity_offset_is_per_cycle_not_per_step():
    df = to_dataframe(parse_cex(build_cex(normalize_table(_synthetic()), start_ts=1_800_000_000)))
    # Two discharge steps in the same cycle must share one offset.
    extra = df[df.Mode == "CC_DChg"].copy()
    extra["StepSeq"] = 4
    df = pd.concat([df, extra], ignore_index=True)
    adjusted = adjust_cycle_measurements(df, capacity_offset_mah=.01)
    before, after = cycle_summary(df).iloc[0], cycle_summary(adjusted).iloc[0]
    assert after.DischargeCapacity_mAh == pytest.approx(before.DischargeCapacity_mAh + .01)
    assert after.ChargeCapacity_mAh == pytest.approx(before.ChargeCapacity_mAh + .01)
    with pytest.raises(ValueError, match="目标容量"):
        adjust_cycle_measurements(df, capacity_offset_mah=-1)
    with pytest.raises(ValueError, match="目标库仑效率"):
        adjust_cycle_measurements(df, efficiency_offset_pct=-1000)


# --------------------------------------------------------------------------- writer
@needs_samples
def test_roundtrip_sample():
    src = SAMPLES[0].read_bytes()
    cex = parse_cex(src)
    df = to_dataframe(cex)
    table = normalize_table(df)  # auto-detect canonical column names
    out = build_cex(table, template=template_from_cex(src), start_ts=cex.start_ts,
                    channel=cex.channel, unit=cex.unit, save_ts=cex.save_ts, create_ts=cex.create_ts,
                    patch_recipe=False)
    back = parse_cex(out)
    assert not back.warnings
    assert all(back.checksums_ok().values())
    assert back.start_ts == cex.start_ts and back.channel == cex.channel
    assert len(back.steps) == len(cex.steps)
    assert back.n_records == cex.n_records
    for a, b in zip(cex.steps, back.steps):
        assert (a.step_no, a.mode, a.goto_flag, a.cycle_raw) == (b.step_no, b.mode, b.goto_flag, b.cycle_raw)
        assert abs(a.ts - b.ts) <= 1  # LAND stamps steps from the wall clock: ±1 s jitter vs. the tick counter
        assert np.array_equal(a.records["t"], b.records["t"])
        assert np.array_equal(a.records["v"], b.records["v"])
        assert np.array_equal(a.records["i"], b.records["i"])
        np.testing.assert_allclose(a.records["cap"], b.records["cap"], rtol=1e-5, atol=1e-12)
        np.testing.assert_allclose(a.records["en"], b.records["en"], rtol=1e-5, atol=1e-12)
    # header byte-identical; body identical apart from the ±1 s step timestamps
    assert out[: cex.header_end] == src[: cex.header_end]
    assert len(out) == len(src)
    diff = np.flatnonzero(np.frombuffer(out, np.uint8) != np.frombuffer(src, np.uint8))
    step_ts_bytes = {off + k for off in _step_header_offsets(out) for k in range(12, 16)}
    assert set(diff.tolist()) <= step_ts_bytes, f"{len(diff)} unexpected differing bytes"


def _step_header_offsets(data: bytes) -> list[int]:
    """Absolute offsets of every CD CC step header in *data*."""
    offs, pos = [], parse_cex(data).header_end
    while pos + 16 <= len(data):
        m = data[pos : pos + 4]
        if m == F.STEP_START:
            offs.append(pos)
            pos += 16 + len(_read_records(data, pos + 16)) * F.RECORD_SIZE
        elif m == F.EVENT:
            pos += 16
        else:
            break
    return offs


@needs_samples
def test_measured_only_csv_reproduces_instrument_values():
    """Only (time, V, I) in → same steps/cycles, capacity & energy within 0.2 % of the tester's own."""
    ref = to_dataframe(parse_cex(SAMPLES[0].read_bytes()))
    meas = pd.DataFrame({"Time(s)": ref["TestTime_s"], "Voltage(V)": ref["Voltage_V"], "Current(mA)": ref["Current_mA"]})
    df = to_dataframe(parse_cex(build_cex(normalize_table(meas), start_ts=1_784_175_647)))
    assert len(df) == len(ref)
    assert (df["Step"].to_numpy() == ref["Step"].to_numpy()).all()
    assert (df["Mode"].astype(str).to_numpy() == ref["Mode"].astype(str).to_numpy()).all()
    assert df["Cycle"].max() == ref["Cycle"].max()
    for col in ("Capacity_mAh", "Energy_mWh"):
        assert (df[col] - ref[col]).abs().max() < 0.002 * ref[col].abs().max()
    s1, s2 = cycle_summary(df), cycle_summary(ref)
    assert (s1["CoulombicEfficiency_pct"] - s2["CoulombicEfficiency_pct"]).abs().max() < 0.3


def _synthetic():
    t = np.arange(0, 3 * 600, 60, dtype=float)  # 30 points
    v = np.concatenate([np.full(10, 1.4), np.linspace(1.4, 0.8, 10), np.linspace(0.8, 1.8, 10)])
    i = np.concatenate([np.zeros(10), np.full(10, -0.04), np.full(10, 0.04)])
    return pd.DataFrame({"Time/s": t, "Voltage/V": v, "Current/mA": i})


def test_build_from_synthetic_csv():
    raw = _synthetic()
    mapping = detect_columns(raw.columns)
    assert mapping["time"] == "Time/s" and mapping["voltage"] == "Voltage/V" and mapping["current"] == "Current/mA"
    table = normalize_table(raw)
    segs = segment_table(table)
    assert [s.mode for s in segs] == [F.MODE_REST, F.MODE_CC_DCHG, F.MODE_CC_CHG]

    out = build_cex(table, start_ts=1_800_000_000, channel=4)
    cex = parse_cex(out)
    assert not cex.warnings
    assert all(cex.checksums_ok().values())
    assert cex.channel == 4 and cex.start_ts == 1_800_000_000
    assert [s.step_no for s in cex.steps] == [1, 2, 3]
    assert [s.cycle_raw for s in cex.steps] == [0, 0, 1]
    assert [s.goto_flag for s in cex.steps] == [0, 1, 0]
    df = to_dataframe(cex)
    assert len(df) == 30
    np.testing.assert_allclose(df["Voltage_V"], raw["Voltage/V"], atol=F.V_LSB)
    np.testing.assert_allclose(df["Current_mA"], raw["Current/mA"], atol=F.I_LSB * 1e3)
    # integrated capacity: 0.04 mA over 9 min = 0.006 mAh
    assert df[df["Mode"] == "CC_Chg"]["Capacity_mAh"].max() == pytest.approx(0.04 * 9 / 60, rel=1e-3)
    # recipe patched to the data
    assert cex.recipe[1].current_a == pytest.approx(4e-5, rel=1e-6)
    assert cex.recipe[1].cond_value == pytest.approx(0.8, abs=1e-3)
    assert cex.recipe[2].cond_value == pytest.approx(1.8, abs=1e-3)
    assert cex.recipe[0].cond_value == pytest.approx(540.0)


def test_units_and_alt_names():
    raw = _synthetic().rename(columns={"Time/s": "TestTime(min)", "Voltage/V": "电压(mV)", "Current/mA": "Current(A)"})
    raw["TestTime(min)"] /= 60
    raw["电压(mV)"] *= 1000
    raw["Current(A)"] /= 1000
    table = normalize_table(raw)
    ref = normalize_table(_synthetic())
    for c in ("time_s", "voltage_v", "current_ma"):
        np.testing.assert_allclose(table[c], ref[c], rtol=1e-9, atol=1e-9)


def test_template_checksums_valid():
    tpl = parse_cex(load_template())
    assert all(tpl.checksums_ok().values())
    assert tpl.header_end == len(load_template())
    assert struct.unpack_from("<I", load_template(), F.OFF_START_TS[0])[0] == tpl.start_ts
