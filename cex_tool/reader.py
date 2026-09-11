"""Parse LAND ``.cex`` files into numpy / pandas structures."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import format as F


class CexFormatError(ValueError):
    pass


@dataclass
class Block:
    id: int
    offset: int  # offset of the block *data* inside the file
    size: int


@dataclass
class RecipeStep:
    number: int  # 1-based step number as used by the data section
    offset: int  # absolute offset of the 56-byte entry
    mode: int
    current_a: float
    cond_kind: int
    cond_sub: int
    cond_value: float

    @property
    def mode_name(self) -> str:
        return F.mode_name(self.mode)

    def describe(self) -> str:
        if self.cond_kind == F.COND_TIME:
            cond = f"{self.cond_value:g} s"
        elif self.cond_kind == F.COND_VOLTAGE:
            cond = f"{'≥' if self.cond_sub else '≤'} {self.cond_value:g} V"
        else:
            cond = f"kind={self.cond_kind:#x} value={self.cond_value:g}"
        cur = "" if self.mode == F.MODE_REST else f", {self.current_a * 1e3:g} mA"
        return f"{self.mode_name}{cur}, end: {cond}"


@dataclass
class StepData:
    seq: int  # 0-based position in the file
    step_no: int  # recipe step number (1-based)
    mode: int
    ts: int  # unix seconds at step start
    flag_b9: int
    flag_b10: int
    goto_flag: int  # from preceding 0x44 event (1 when jumping to loop start)
    cycle_raw: int  # LAND's own counter from the 0x44 event
    records: np.ndarray  # RECORD_DTYPE

    @property
    def mode_name(self) -> str:
        return F.mode_name(self.mode)


@dataclass
class CexFile:
    raw: bytes
    blocks: list[Block]
    header_end: int  # offset where the event / data section begins
    data_start: int  # offset of the first CD CC step header
    channel: int
    unit: int
    start_ts: int
    save_ts: int | None
    create_ts: int | None
    recipe: list[RecipeStep]
    recipe_meta_offset: int | None
    steps: list[StepData]
    warnings: list[str] = field(default_factory=list)

    # -- convenience -----------------------------------------------------------
    @property
    def n_records(self) -> int:
        return sum(len(s.records) for s in self.steps)

    def block(self, bid: int) -> Block | None:
        return next((b for b in self.blocks if b.id == bid), None)

    def checksums_ok(self) -> dict[str, bool]:
        d = self.raw
        out = {"header": struct.unpack_from("<I", d, F.OFF_HEADER_CHECKSUM)[0] == F.word_sum(d[: F.OFF_HEADER_CHECKSUM])}
        info = self.block(F.BLOCK_ID_INFO)
        if info:
            o = info.offset
            out["info"] = struct.unpack_from("<I", d, o + F.INFO_CHECKSUM)[0] == F.word_sum(d[o : o + F.INFO_CHECKSUM])
        rec = self.block(F.BLOCK_ID_RECIPE)
        if rec:
            o = rec.offset
            out["recipe"] = struct.unpack_from("<I", d, o + F.RECIPE_CHECKSUM)[0] == F.word_sum(d[o + F.RECIPE_BODY : o + rec.size])
        return out


# -----------------------------------------------------------------------------
def _walk_blocks(data: bytes):
    """Walk the AA..BB block chain that follows the 64-byte file header."""
    pos = F.FIRST_BLOCK
    blocks: list[Block] = []
    while pos + 16 <= len(data):
        m = data[pos : pos + 4]
        if m == F.BLOCK_BEGIN:
            bid, size = struct.unpack_from("<HH", data, pos + 4)
            doff = pos + 16
            end = doff + size
            if data[end : end + 4] != F.BLOCK_END:
                raise CexFormatError(f"block {bid:#x} at {pos:#x} has no end marker")
            blocks.append(Block(bid, doff, size))
            pos = end + 16
        elif m == F.EVENT and data[pos + 4] not in (F.EVENT_TEST_START, F.EVENT_GOTO_STEP):
            pos += 16  # e.g. the empty CC CC FF FF 88 00 .. entry between blocks
        else:
            break
    return blocks, pos


def _parse_recipe(data: bytes, blk: Block):
    """Return (steps, meta_offset) from the recipe block's table of contents."""
    base = blk.offset + F.RECIPE_BODY
    steps: list[RecipeStep] = []
    meta_off = None
    pos = base
    n = 0
    while pos + 4 <= blk.offset + blk.size:
        off, typ, sentinel = struct.unpack_from("<HBB", data, pos)
        pos += 8
        if typ == F.TOC_TYPE_END or sentinel != 0xFF:
            break
        entry = base + off
        if typ == F.TOC_TYPE_STEP:
            n += 1
            mode, cur = struct.unpack_from("<If", data, entry)
            kind, sub, val = struct.unpack_from("<HHf", data, entry + F.STEP_COND_KIND)
            steps.append(RecipeStep(n, entry, mode, cur, kind, sub, val))
        elif typ == F.TOC_TYPE_META:
            meta_off = entry
    return steps, meta_off


def _read_records(data: bytes, start: int) -> np.ndarray:
    """Read consecutive 16-byte records starting at *start* until a marker."""
    n_avail = (len(data) - start) // F.RECORD_SIZE
    if n_avail <= 0:
        return np.empty(0, dtype=F.RECORD_DTYPE)
    words = np.frombuffer(data, dtype="<u4", count=n_avail * 4, offset=start).reshape(-1, 4)[:, 0]
    hits = np.flatnonzero(np.isin(words, F.MARKER_U32))
    n = int(hits[0]) if len(hits) else n_avail
    return np.frombuffer(data, dtype=F.RECORD_DTYPE, count=n, offset=start)


def parse_cex(data: bytes) -> CexFile:
    if len(data) < 0x40 + 16:
        raise CexFormatError("file too small to be a .cex file")
    warnings: list[str] = []
    if data[:4] != F.MAGIC:
        warnings.append(f"unexpected magic {data[:4].hex()} (expected {F.MAGIC.hex()})")

    blocks, header_end = _walk_blocks(data)
    channel, unit = data[F.OFF_CHANNEL], data[F.OFF_UNIT]
    start_ts = struct.unpack_from("<I", data, F.OFF_START_TS[0])[0]

    save_ts = None
    info = next((b for b in blocks if b.id == F.BLOCK_ID_INFO), None)
    if info:
        save_ts = struct.unpack_from("<I", data, info.offset + F.INFO_SAVE_TS)[0]

    recipe: list[RecipeStep] = []
    meta_off = None
    create_ts = None
    rec = next((b for b in blocks if b.id == F.BLOCK_ID_RECIPE), None)
    if rec:
        recipe, meta_off = _parse_recipe(data, rec)
        if meta_off is not None:
            create_ts = struct.unpack_from("<I", data, meta_off + F.META_CREATE_TS)[0]

    # ---- events + steps -------------------------------------------------------
    steps: list[StepData] = []
    pending = (0, 0)  # (goto_flag, cycle_raw) from the last 0x44 event
    pos = header_end
    data_start = None
    while pos + 16 <= len(data):
        m = data[pos : pos + 4]
        if m == F.STEP_START:
            if data_start is None:
                data_start = pos
            _, sno, mode, b9, b10, _b11, ts = struct.unpack_from("<HHBBBBI", data, pos + 4)
            pos += 16
            recs = _read_records(data, pos)
            pos += len(recs) * F.RECORD_SIZE
            steps.append(StepData(len(steps), sno & 0x7FFF, mode, ts, b9, b10, pending[0], pending[1], recs))
            pending = (0, 0)
        elif m == F.EVENT:
            eid = data[pos + 4]
            if eid == F.EVENT_GOTO_STEP:
                _, _, flag, _nxt, cyc = struct.unpack_from("<HHIHH", data, pos + 4)
                pending = (flag, cyc)
            elif eid == F.EVENT_TEST_START:
                ts = struct.unpack_from("<I", data, pos + 12)[0]
                if ts and ts != start_ts:
                    warnings.append(f"test-start event time {ts} differs from header {start_ts}")
            pos += 16
        else:
            warnings.append(f"unknown bytes at {pos:#x}: {data[pos:pos + 16].hex()} — stopped parsing")
            break
    if pos < len(data) and len(data) - pos < 16:
        warnings.append(f"{len(data) - pos} trailing bytes ignored (partial record)")
    if data_start is None:
        data_start = header_end

    return CexFile(
        raw=data, blocks=blocks, header_end=header_end, data_start=data_start,
        channel=channel, unit=unit, start_ts=start_ts, save_ts=save_ts, create_ts=create_ts,
        recipe=recipe, recipe_meta_offset=meta_off, steps=steps, warnings=warnings,
    )


# -----------------------------------------------------------------------------
COLUMNS = [
    "Index", "Cycle", "Step", "StepSeq", "Mode", "TestTime_s", "StepTime_s",
    "Voltage_V", "Current_mA", "Capacity_mAh", "Energy_mWh", "DateTime",
]


def assign_cycles(step_numbers: list[int]) -> list[int]:
    """Cycle = 1 at the start; +1 every time the recipe step number does not increase."""
    cycles, cyc, prev = [], 1, None
    for s in step_numbers:
        if prev is not None and s <= prev:
            cyc += 1
        cycles.append(cyc)
        prev = s
    return cycles


def to_dataframe(cex: CexFile, v_lsb: float = F.V_LSB, i_lsb: float = F.I_LSB) -> pd.DataFrame:
    steps = [s for s in cex.steps if len(s.records)]
    if not steps:
        return pd.DataFrame(columns=COLUMNS)
    counts = np.array([len(s.records) for s in steps])
    recs = np.concatenate([s.records for s in steps])
    cycles = assign_cycles([s.step_no for s in steps])

    t = recs["t"].astype(np.float64) * F.T_UNIT
    t0 = np.repeat(np.array([s.records["t"][0] for s in steps], dtype=np.float64) * F.T_UNIT, counts)
    df = pd.DataFrame({
        "Index": np.arange(1, len(recs) + 1),
        "Cycle": np.repeat(cycles, counts),
        "Step": np.repeat([s.step_no for s in steps], counts),
        "StepSeq": np.repeat([s.seq + 1 for s in steps], counts),
        "Mode": pd.Categorical(np.repeat([s.mode_name for s in steps], counts)),
        "TestTime_s": t,
        "StepTime_s": t - t0,
        "Voltage_V": recs["v"].astype(np.float64) * v_lsb,
        "Current_mA": recs["i"].astype(np.float64) * i_lsb * 1e3,
        "Capacity_mAh": recs["cap"].astype(np.float64) * 1e3,
        "Energy_mWh": recs["en"].astype(np.float64) * 1e3,
    })
    df["DateTime"] = pd.Timestamp(cex.start_ts, unit="s") + pd.to_timedelta(t, unit="s")
    return df


def cycle_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-cycle capacities / energies / coulombic efficiency."""
    if df.empty:
        return pd.DataFrame()
    rows = []
    for cyc, d in df.groupby("Cycle", sort=True):
        dch = d[d["Mode"] == "CC_DChg"]
        chg = d[d["Mode"] == "CC_Chg"]

        def _step_max(x: pd.DataFrame, col: str) -> float:
            return float(x.groupby("StepSeq")[col].max().sum()) if len(x) else np.nan

        qd, qc = _step_max(dch, "Capacity_mAh"), _step_max(chg, "Capacity_mAh")
        rows.append({
            "Cycle": cyc,
            "DischargeCapacity_mAh": qd,
            "ChargeCapacity_mAh": qc,
            "CoulombicEfficiency_pct": qd / qc * 100 if qc and qc > 0 else np.nan,
            "DischargeEnergy_mWh": _step_max(dch, "Energy_mWh"),
            "ChargeEnergy_mWh": _step_max(chg, "Energy_mWh"),
            "MeanDischargeVoltage_V": float(dch["Voltage_V"].mean()) if len(dch) else np.nan,
            "MeanChargeVoltage_V": float(chg["Voltage_V"].mean()) if len(chg) else np.nan,
            "Start": d["DateTime"].iloc[0],
            "Duration_h": float((d["TestTime_s"].iloc[-1] - d["TestTime_s"].iloc[0]) / 3600),
        })
    return pd.DataFrame(rows)
