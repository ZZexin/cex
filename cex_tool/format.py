"""Binary layout of LAND (蓝电) ``.cex`` battery-test files.

Everything here was reverse-engineered from CT2001A-style ``.cex`` files
(5 V / 10 mA channels).  See README.md for a human-readable description.

File layout
-----------
::

    0x0000  40-byte file header      (magic 10 11 09 88 ...; u16-word-sum checksum at 0x3c)
    0x0040  blocks: AA AA FF FF <id:u16> <size:u16> <8 bytes> <size bytes> BB BB FF FF <same 12 bytes>
              id 0xAA (64 B)  test info      (last-save timestamp @+8, checksum @+60)
              id 0x55 (16 B)  zeros
              id 0x78 (384 B) zeros
              id 0x13         recipe / 工步 (sub-header, then TOC + step entries; checksum @+0x30)
    ....    events  CC CC FF FF <id:u8> ...   (0x33 = test start, 0x44 = goto step)
    ....    steps   CD CC FF FF 22 00 <step|0x8000:u16> <mode:u8> 05 <81|00> 00 <unix ts:u32>
                    followed by 16-byte records until the next marker
    record: <time:u32 x10ms> <voltage:u16> <current:i16> <capacity Ah:f32> <energy Wh:f32>
"""
from __future__ import annotations

import struct

import numpy as np

MAGIC = b"\x10\x11\x09\x88"

# ---- markers -----------------------------------------------------------------
BLOCK_BEGIN = b"\xaa\xaa\xff\xff"
BLOCK_END = b"\xbb\xbb\xff\xff"
EVENT = b"\xcc\xcc\xff\xff"
STEP_START = b"\xcd\xcc\xff\xff"
MARKERS = (BLOCK_BEGIN, BLOCK_END, EVENT, STEP_START)
MARKER_U32 = np.array([struct.unpack("<I", m)[0] for m in MARKERS], dtype=np.uint32)

EVENT_TEST_START = 0x33
EVENT_GOTO_STEP = 0x44
STEP_RECORD_ID = 0x22

BLOCK_ID_INFO = 0xAA
BLOCK_ID_RECIPE = 0x13

# ---- data records ------------------------------------------------------------
RECORD_DTYPE = np.dtype(
    [("t", "<u4"), ("v", "<u2"), ("i", "<i2"), ("cap", "<f4"), ("en", "<f4")]
)
RECORD_SIZE = RECORD_DTYPE.itemsize  # 16

# Physical scale of the raw integer fields.  Calibrated on real data three
# independent ways (charge/discharge cut-off voltages, energy/capacity ratio,
# capacity increment vs. current); all agree to <0.05 %.
V_LSB = 0.155e-3  # volts per LSB   (≈ 5.08 V / 32768)
I_LSB = 0.31e-6  # amperes per LSB (≈ 10.16 mA / 32768)
T_UNIT = 0.01  # seconds per tick

# ---- step modes --------------------------------------------------------------
MODE_REST = 0x70
MODE_CC_DCHG = 0x02
MODE_CC_CHG = 0x03
MODE_NAMES = {MODE_REST: "Rest", MODE_CC_DCHG: "CC_DChg", MODE_CC_CHG: "CC_Chg"}
MODE_NAMES_ZH = {MODE_REST: "静置", MODE_CC_DCHG: "恒流放电", MODE_CC_CHG: "恒流充电"}


def mode_name(code: int) -> str:
    return MODE_NAMES.get(code, f"Mode_{code:#04x}")


# ---- file header offsets -----------------------------------------------------
OFF_CHANNEL = 0x08  # u8, zero-based channel index
OFF_UNIT = 0x09  # u8, device / unit index
OFF_START_TS = (0x10, 0x30, 0x34)  # u32 unix seconds, repeated
OFF_HEADER_CHECKSUM = 0x3C  # u32 = word_sum(data[0:0x3c])
FIRST_BLOCK = 0x40

# ---- info block (id 0xAA, 64 bytes) relative offsets --------------------------
INFO_SAVE_TS = 0x08  # u32 unix seconds of last save
INFO_CHECKSUM = 0x3C  # u32 = word_sum(block[0:0x3c])

# ---- recipe block (id 0x13) relative offsets ---------------------------------
RECIPE_CHECKSUM = 0x30  # u32 = word_sum(block[0x40:])
RECIPE_BODY = 0x40  # TOC starts here; TOC offsets are relative to this
STEP_ENTRY_SIZE = 56
TOC_TYPE_CONTROL = 0x01
TOC_TYPE_STEP = 0x02
TOC_TYPE_NAME = 0x05
TOC_TYPE_LOOP = 0x0C
TOC_TYPE_META = 0x13  # holds the creation timestamp at +0x30
TOC_TYPE_END = 0xFD
META_CREATE_TS = 0x30

# step entry fields (relative to entry start)
STEP_MODE = 0  # u32
STEP_CURRENT = 4  # f32 amperes
STEP_COND_KIND = 40  # u16: 0x0100 time, 0x0200 voltage
STEP_COND_SUB = 42  # u16: 6 = time, 0 = "<= V", 1 = ">= V"
STEP_COND_VALUE = 44  # f32 (seconds or volts)
COND_TIME = 0x0100
COND_VOLTAGE = 0x0200


def word_sum(buf: bytes) -> int:
    """Checksum used throughout the format: sum of little-endian u16 words."""
    if len(buf) % 2:
        buf = buf + b"\x00"
    return int(np.frombuffer(buf, dtype="<u2").astype(np.uint64).sum() & 0xFFFFFFFF)
