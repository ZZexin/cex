"""Build LAND ``.cex`` files from tabular data (CSV / DataFrame).

The header (file header, info block, recipe) is taken from a *template* — either
the built-in one (extracted from a real CT2001A file) or any user supplied
``.cex`` — and the data section is regenerated from the table.  Timestamps,
channel number, recipe currents / cut-offs and all three checksums are patched.
"""
from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass
from importlib import resources

import numpy as np
import pandas as pd

from . import format as F
from .reader import CexFile, RecipeStep, parse_cex

# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------

def load_template() -> bytes:
    """Header bytes of the built-in template (everything before the first event)."""
    return resources.files(__package__).joinpath("template_header.bin").read_bytes()


def template_from_cex(data: bytes) -> bytes:
    """Use an existing .cex file's header as template."""
    return data[: parse_cex(data).header_end]


# ---------------------------------------------------------------------------
# column detection
# ---------------------------------------------------------------------------
ROLES = ("time", "voltage", "current", "capacity", "energy", "step", "mode")

UNIT_FACTORS = {  # multiply to reach canonical unit (s, V, mA, mAh, mWh)
    "time": {"s": 1.0, "ms": 1e-3, "min": 60.0, "h": 3600.0},
    "voltage": {"V": 1.0, "mV": 1e-3},
    "current": {"mA": 1.0, "A": 1e3, "µA": 1e-3},
    "capacity": {"mAh": 1.0, "Ah": 1e3},
    "energy": {"mWh": 1.0, "Wh": 1e3},
}


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-/()\[\]（）·]", "", str(name)).lower()


def _guess_unit(name: str, role: str) -> str:
    n = _norm(name)
    if role == "time":
        if n.endswith("ms"):
            return "ms"
        if n.endswith("min"):
            return "min"
        if n.endswith("h") or n.endswith("hr") or n.endswith("hour"):
            return "h"
        return "s"
    if role == "voltage":
        return "mV" if n.endswith("mv") else "V"
    if role == "current":
        if n.endswith("ua") or n.endswith("μa") or n.endswith("µa"):
            return "µA"
        if n.endswith("ma"):
            return "mA"
        if n.endswith("a") and not n.endswith("ma"):
            return "A"
        return "mA"
    if role == "capacity":
        return "Ah" if (n.endswith("ah") and not n.endswith("mah")) else "mAh"
    if role == "energy":
        return "Wh" if (n.endswith("wh") and not n.endswith("mwh")) else "mWh"
    return ""


def detect_columns(columns) -> dict[str, str | None]:
    """Best-effort mapping role -> column name (None when not found)."""
    cols = list(columns)
    normed = {c: _norm(c) for c in cols}
    found: dict[str, str | None] = {r: None for r in ROLES}

    def pick(role, pred):
        for c in cols:
            if c in found.values():
                continue
            if pred(normed[c]):
                found[role] = c
                return

    # exact canonical names first (files produced by this tool round-trip perfectly)
    canon = {"time": "testtime_s", "voltage": "voltage_v", "current": "current_ma",
             "capacity": "capacity_mah", "energy": "energy_mwh", "step": "stepseq", "mode": "mode"}
    for role, name in canon.items():
        pick(role, lambda n, name=name: n == name)

    pick("time", lambda n: n.startswith("testtime") or n.startswith("totaltime") or n in ("time", "times", "t", "测试时间", "时间") or ("time" in n and "step" not in n and "date" not in n))
    pick("voltage", lambda n: "volt" in n or n.startswith("电压") or n in ("v", "u", "vv") or n.startswith("v") and len(n) <= 3)
    pick("current", lambda n: "curr" in n or n.startswith("电流") or n in ("i", "ia", "ima", "a") or (n.startswith("i") and len(n) <= 3))
    pick("capacity", lambda n: ("cap" in n or "容量" in n) and "spe" not in n and "比" not in n and not n.endswith("g"))
    pick("energy", lambda n: ("energy" in n or "能量" in n or n.endswith("wh")) and "spe" not in n and "比" not in n)
    pick("step", lambda n: n in ("step", "stepno", "stepnumber", "stepindex", "stepid", "工步", "工步号", "工步序号") or (n.startswith("step") and "time" not in n))
    pick("mode", lambda n: n in ("mode", "state", "status", "steptype", "type", "工步类型", "状态", "模式"))
    return found


# ---------------------------------------------------------------------------
# normalisation & segmentation
# ---------------------------------------------------------------------------
_MODE_CODES = {F.MODE_REST: F.MODE_REST, F.MODE_CC_DCHG: F.MODE_CC_DCHG, F.MODE_CC_CHG: F.MODE_CC_CHG}


def mode_from_text(s) -> int | None:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    t = str(s).strip().lower()
    if not t:
        return None
    if any(k in t for k in ("dchg", "discharge", "放电", "d_cc", "dis")):
        return F.MODE_CC_DCHG
    if any(k in t for k in ("chg", "charge", "充电", "c_cc")):
        return F.MODE_CC_CHG
    if any(k in t for k in ("rest", "静置", "idle", "ocv")) or t in ("r", "0"):
        return F.MODE_REST
    try:
        return _MODE_CODES.get(int(float(t)))
    except ValueError:
        return None


def normalize_table(df: pd.DataFrame, mapping: dict[str, str | None] | None = None,
                    units: dict[str, str] | None = None) -> pd.DataFrame:
    """Return a DataFrame with canonical columns:
    time_s, voltage_v, current_ma, [capacity_mah], [energy_mwh], [step], [mode]."""
    mapping = dict(mapping or detect_columns(df.columns))
    units = dict(units or {})
    if not mapping.get("time") or not mapping.get("voltage"):
        raise ValueError("需要至少包含 时间(TestTime) 和 电压(Voltage) 两列 / need at least time and voltage columns")

    out = pd.DataFrame(index=df.index)

    def num(col):
        return pd.to_numeric(df[col], errors="coerce").astype(float)

    for role, canon in (("time", "time_s"), ("voltage", "voltage_v"), ("current", "current_ma"),
                        ("capacity", "capacity_mah"), ("energy", "energy_mwh")):
        col = mapping.get(role)
        if not col:
            continue
        unit = units.get(role) or _guess_unit(col, role)
        out[canon] = num(col) * UNIT_FACTORS[role].get(unit, 1.0)
    if "current_ma" not in out:
        out["current_ma"] = 0.0
    if mapping.get("step"):
        out["step"] = pd.to_numeric(df[mapping["step"]], errors="coerce")
    if mapping.get("mode"):
        out["mode"] = df[mapping["mode"]].map(mode_from_text)

    out = out.dropna(subset=["time_s", "voltage_v"]).reset_index(drop=True)
    if len(out) == 0:
        raise ValueError("no valid rows")
    # time must be monotonic within the file
    if (np.diff(out["time_s"].to_numpy()) < 0).any():
        raise ValueError("时间列必须单调递增（需要累计测试时间，而非工步时间）/ time column must be non-decreasing (use total test time, not step time)")
    out["current_ma"] = out["current_ma"].fillna(0.0)
    return out


@dataclass
class Segment:
    start: int  # row index (inclusive)
    stop: int  # row index (exclusive)
    mode: int

    @property
    def n(self) -> int:
        return self.stop - self.start


def segment_table(t: pd.DataFrame, rest_threshold_frac: float = 0.02) -> list[Segment]:
    """Split the normalised table into steps."""
    n = len(t)
    cur = t["current_ma"].to_numpy()
    imax = np.nanmax(np.abs(cur)) if n else 0.0
    thr = max(imax * rest_threshold_frac, 1e-6)
    sign = np.where(cur > thr, 1, np.where(cur < -thr, -1, 0))
    sign_mode = {1: F.MODE_CC_CHG, -1: F.MODE_CC_DCHG, 0: F.MODE_REST}

    if "step" in t and t["step"].notna().all():
        key = t["step"].to_numpy()
    elif "mode" in t and t["mode"].notna().all():
        key = t["mode"].to_numpy()
    else:
        key = sign
    # boundaries where the key changes
    change = np.flatnonzero(key[1:] != key[:-1]) + 1
    bounds = [0, *change.tolist(), n]
    segs: list[Segment] = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if "mode" in t and t["mode"].iloc[a:b].notna().any():
            mode = int(t["mode"].iloc[a:b].mode().iloc[0])
        else:
            s = sign[a:b]
            nz = s[s != 0]
            mode = sign_mode[int(np.sign(nz.sum()))] if len(nz) else F.MODE_REST
        segs.append(Segment(a, b, mode))
    return segs


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

def _cumtrapz(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.zeros_like(y, dtype=np.float64)
    if len(y) > 1:
        out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))
    return out


def _step_numbers(recipe: list[RecipeStep]) -> dict[int, int]:
    """mode -> recipe step number, falling back to the classic 1=rest 2=dchg 3=chg."""
    m = {}
    for s in recipe:
        m.setdefault(s.mode, s.number)
    m.setdefault(F.MODE_REST, 1)
    m.setdefault(F.MODE_CC_DCHG, 2)
    m.setdefault(F.MODE_CC_CHG, 3)
    return m


def build_cex(table: pd.DataFrame, *, template: bytes | None = None, start_ts: int | None = None,
              channel: int | None = None, unit: int | None = None, patch_recipe: bool = True,
              v_lsb: float = F.V_LSB, i_lsb: float = F.I_LSB, save_ts: int | None = None,
              create_ts: int | None = None) -> bytes:
    """Create .cex bytes from a normalised table (see :func:`normalize_table`).

    ``create_ts`` is the recipe-creation time stored inside the recipe block
    (defaults to a few seconds before ``start_ts``)."""
    header = bytearray(template if template is not None else load_template())
    tpl = parse_cex(bytes(header) + b"")  # header only: parses blocks & recipe, zero steps
    segs = segment_table(table)
    if not segs:
        raise ValueError("no data")

    t_s = table["time_s"].to_numpy(dtype=np.float64)
    v = table["voltage_v"].to_numpy(dtype=np.float64)
    i_ma = table["current_ma"].to_numpy(dtype=np.float64)
    start_ts = int(start_ts if start_ts is not None else time.time() - t_s[-1])
    save_ts = int(save_ts if save_ts is not None else max(start_ts + t_s[-1] + 1, time.time()))

    step_of = _step_numbers(tpl.recipe)
    loop_start = min((step_of[m] for m in (F.MODE_CC_DCHG, F.MODE_CC_CHG)), default=2)

    # ---- data section ---------------------------------------------------------
    out = bytearray(header)
    out += F.EVENT + bytes([F.EVENT_TEST_START, 0, 0, 0, 1, 2, 0, 0]) + struct.pack("<I", start_ts)
    loops_entered = 0
    for seg in segs:
        sl = slice(seg.start, seg.stop)
        step_no = step_of[seg.mode]
        if step_no == loop_start:
            loops_entered += 1
        cyc = max(loops_entered - (1 if step_no == loop_start else 0), 0)
        out += F.EVENT + struct.pack("<HHIHH", F.EVENT_GOTO_STEP, 0, int(step_no == loop_start), step_no | 0x8000, cyc)

        ts = start_ts + int(round(t_s[seg.start]))
        b10 = 0x00 if seg.mode == F.MODE_REST else 0x81
        out += F.STEP_START + struct.pack("<HHBBBBI", F.STEP_RECORD_ID, step_no | 0x8000, seg.mode, 5, b10, 0, ts)

        tt, vv, ii = t_s[sl], v[sl], i_ma[sl] * 1e-3  # A
        if seg.mode == F.MODE_REST:
            cap = np.zeros(seg.n); en = np.zeros(seg.n)
        else:
            if "capacity_mah" in table and table["capacity_mah"].iloc[sl].notna().all():
                c = table["capacity_mah"].to_numpy(dtype=np.float64)[sl] * 1e-3
                cap = np.abs(c - c[0])
            else:
                cap = _cumtrapz(np.abs(ii), tt) / 3600.0
            if "energy_mwh" in table and table["energy_mwh"].iloc[sl].notna().all():
                e = table["energy_mwh"].to_numpy(dtype=np.float64)[sl] * 1e-3
                en = np.abs(e - e[0])
            else:
                en = _cumtrapz(np.abs(ii) * vv, tt) / 3600.0
        rec = np.empty(seg.n, dtype=F.RECORD_DTYPE)
        rec["t"] = np.round(tt / F.T_UNIT).astype(np.uint32)
        rec["v"] = np.clip(np.round(vv / v_lsb), 0, 65535).astype(np.uint16)
        rec["i"] = np.clip(np.round(ii / i_lsb), -32768, 32767).astype(np.int16)
        rec["cap"] = cap.astype(np.float32)
        rec["en"] = en.astype(np.float32)
        out += rec.tobytes()

    # ---- header patches -------------------------------------------------------
    if channel is not None:
        out[F.OFF_CHANNEL] = int(channel) & 0xFF
    if unit is not None:
        out[F.OFF_UNIT] = int(unit) & 0xFF
    for off in F.OFF_START_TS:
        struct.pack_into("<I", out, off, start_ts)
    struct.pack_into("<I", out, F.OFF_HEADER_CHECKSUM, F.word_sum(bytes(out[: F.OFF_HEADER_CHECKSUM])))

    info = tpl.block(F.BLOCK_ID_INFO)
    if info:
        struct.pack_into("<I", out, info.offset + F.INFO_SAVE_TS, save_ts)
        struct.pack_into("<I", out, info.offset + F.INFO_CHECKSUM,
                         F.word_sum(bytes(out[info.offset : info.offset + F.INFO_CHECKSUM])))

    rec_blk = tpl.block(F.BLOCK_ID_RECIPE)
    if rec_blk:
        if tpl.recipe_meta_offset is not None:
            struct.pack_into("<I", out, tpl.recipe_meta_offset + F.META_CREATE_TS,
                             int(create_ts) if create_ts is not None else max(start_ts - 7, 0))
        if patch_recipe:
            _patch_recipe(out, tpl.recipe, table, segs)
        struct.pack_into("<I", out, rec_blk.offset + F.RECIPE_CHECKSUM,
                         F.word_sum(bytes(out[rec_blk.offset + F.RECIPE_BODY : rec_blk.offset + rec_blk.size])))
    return bytes(out)


def _patch_recipe(out: bytearray, recipe: list[RecipeStep], table: pd.DataFrame, segs: list[Segment]) -> None:
    """Make the recipe's currents / cut-offs reflect the data (display only)."""
    v = table["voltage_v"].to_numpy(dtype=np.float64)
    i_ma = table["current_ma"].to_numpy(dtype=np.float64)
    t = table["time_s"].to_numpy(dtype=np.float64)
    by_mode: dict[int, list[Segment]] = {}
    for s in segs:
        by_mode.setdefault(s.mode, []).append(s)
    done = set()
    for rs in recipe:
        if rs.mode in done or rs.mode not in by_mode:
            continue
        done.add(rs.mode)
        rows = np.concatenate([np.arange(s.start, s.stop) for s in by_mode[rs.mode]])
        if rs.mode in (F.MODE_CC_DCHG, F.MODE_CC_CHG):
            cur = float(np.nanmedian(np.abs(i_ma[rows]))) * 1e-3
            struct.pack_into("<f", out, rs.offset + F.STEP_CURRENT, cur)
            if rs.cond_kind == F.COND_VOLTAGE:
                val = float(np.nanmin(v[rows])) if rs.mode == F.MODE_CC_DCHG else float(np.nanmax(v[rows]))
                struct.pack_into("<f", out, rs.offset + F.STEP_COND_VALUE, round(val, 3))
        elif rs.mode == F.MODE_REST and rs.cond_kind == F.COND_TIME:
            s0 = by_mode[rs.mode][0]
            dur = float(t[s0.stop - 1] - t[s0.start]) if s0.n > 1 else rs.cond_value
            if dur > 0:
                struct.pack_into("<f", out, rs.offset + F.STEP_COND_VALUE, dur)


def dataframe_from_cex_export(df: pd.DataFrame) -> pd.DataFrame:
    """Shortcut: normalise a CSV produced by this tool's exporter."""
    return normalize_table(df)


__all__ = ["load_template", "template_from_cex", "detect_columns", "normalize_table",
           "segment_table", "build_cex", "Segment", "ROLES", "UNIT_FACTORS", "mode_from_text"]
