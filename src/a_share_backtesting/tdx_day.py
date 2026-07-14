from __future__ import annotations

import re
import struct
from pathlib import Path

import pandas as pd


_RECORD = struct.Struct("<IIIIIfII")
_TARGET_PREFIXES = {"sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002"}
_FILENAME = re.compile(r"^(?:sh|sz|bj)(\d{6})$", re.IGNORECASE)


def is_target_mainboard_path(path: Path) -> bool:
    """Return whether a Tongdaxin filename belongs to the requested mainboard universe."""
    return path.suffix.lower() == ".day" and path.stem.lower()[:5] in _TARGET_PREFIXES


def _code_from_path(path: Path) -> str:
    match = _FILENAME.fullmatch(path.stem)
    if match is None:
        raise ValueError(f"{path}: filename must be exchange prefix plus six-digit code")
    return match.group(1)


def read_tdx_day_file(path: Path) -> pd.DataFrame:
    """Parse a Tongdaxin 32-byte daily-bar file into unadjusted OHLCV rows."""
    raw = path.read_bytes()
    if not raw or len(raw) % _RECORD.size:
        raise ValueError(f"{path}: byte length must be a non-zero multiple of 32")
    code = _code_from_path(path)
    rows: list[dict[str, object]] = []
    for offset in range(0, len(raw), _RECORD.size):
        date, open_, high, low, close, _amount, volume, _reserved = _RECORD.unpack_from(raw, offset)
        timestamp = pd.to_datetime(str(date), format="%Y%m%d", errors="coerce")
        if pd.isna(timestamp):
            raise ValueError(f"{path}: invalid date at byte offset {offset}")
        if min(open_, high, low, close) <= 0 or low > min(open_, close) or high < max(open_, close):
            raise ValueError(f"{path}: invalid prices at byte offset {offset}")
        rows.append(
            {
                "date": timestamp,
                "code": code,
                "open": open_ / 100,
                "high": high / 100,
                "low": low / 100,
                "close": close / 100,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)
