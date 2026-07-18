from __future__ import annotations

import math
import re
import struct
from pathlib import Path

import pandas as pd


_RECORD = struct.Struct("<HHfffffII")
_FILENAME = re.compile(r"^(sh|sz|bj)(\d{6})$", re.IGNORECASE)
_EXPECTED_TIMES = {
    f"{minute // 60:02d}:{minute % 60:02d}"
    for start, stop in ((9 * 60 + 35, 11 * 60 + 30), (13 * 60 + 5, 15 * 60))
    for minute in range(start, stop + 1, 5)
}
_REQUIRED_TIMES = {"14:40", "14:45", "14:50", "14:55", "15:00"}


def _market_for_code(code: str) -> str | None:
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    return None


def _code_from_path(path: Path) -> str:
    match = _FILENAME.fullmatch(path.stem)
    if match is None:
        raise ValueError(f"{path}: filename must be exchange prefix plus six-digit code")
    market, code = match.groups()
    expected = _market_for_code(code)
    if expected is not None and market.lower() != expected:
        raise ValueError(f"{path}: exchange prefix does not match code")
    return code


def _decode_date(raw_date: int, path: Path, offset: int) -> pd.Timestamp:
    year = raw_date // 2048 + 2004
    month_day = raw_date % 2048
    month = month_day // 100
    day = month_day % 100
    try:
        return pd.Timestamp(year=year, month=month, day=day)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid date at byte offset {offset}") from exc


def read_tdx_lc5_file(path: Path) -> pd.DataFrame:
    """Parse Tongdaxin 32-byte five-minute records into raw OHLCV bars."""
    raw = path.read_bytes()
    if not raw or len(raw) % _RECORD.size:
        raise ValueError(f"{path}: byte length must be a non-zero multiple of 32")
    code = _code_from_path(path)
    rows: list[dict[str, object]] = []
    previous_timestamp: pd.Timestamp | None = None
    for offset in range(0, len(raw), _RECORD.size):
        raw_date, raw_time, open_, high, low, close, _amount, volume, _reserved = _RECORD.unpack_from(raw, offset)
        date = _decode_date(raw_date, path, offset)
        hour, minute = divmod(int(raw_time), 60)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"{path}: invalid time at byte offset {offset}")
        timestamp = date + pd.Timedelta(hours=hour, minutes=minute)
        prices = (float(open_), float(high), float(low), float(close))
        if (
            not all(math.isfinite(value) and value > 0 for value in prices)
            or low > min(open_, close)
            or high < max(open_, close)
        ):
            raise ValueError(f"{path}: invalid prices at byte offset {offset}")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            reason = "duplicate timestamp" if timestamp == previous_timestamp else "timestamps not increasing"
            raise ValueError(f"{path}: {reason} at byte offset {offset}")
        previous_timestamp = timestamp
        rows.append(
            {
                "timestamp": timestamp,
                "date": date,
                "time": f"{hour:02d}:{minute:02d}",
                "code": code,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": int(volume),
            }
        )
    return pd.DataFrame(rows)


def find_lc5_path(root: Path, code: str) -> Path | None:
    normalized = str(code).strip().zfill(6)
    market = _market_for_code(normalized)
    if market is None:
        return None
    path = root / market / "fzline" / f"{market}{normalized}.lc5"
    return path if path.is_file() else None


def audit_lc5_frame(frame: pd.DataFrame) -> list[str]:
    """Return completeness issues without mutating or synthesizing minute bars."""
    errors: list[str] = []
    for (code, date), day in frame.groupby(["code", "date"], sort=True):
        label = f"{code} {pd.Timestamp(date):%Y-%m-%d}"
        if len(day) != 48:
            errors.append(f"{label}: expected 48 bars, found {len(day)}")
        actual_times = set(day["time"].astype(str))
        missing_grid = sorted(_EXPECTED_TIMES - actual_times)
        unexpected_grid = sorted(actual_times - _EXPECTED_TIMES)
        if missing_grid or unexpected_grid:
            missing_text = ",".join(missing_grid) or "-"
            unexpected_text = ",".join(unexpected_grid) or "-"
            errors.append(
                f"{label}: invalid trading time grid missing={missing_text} unexpected={unexpected_text}"
            )
        missing = sorted(_REQUIRED_TIMES - actual_times)
        if missing:
            errors.append(f"{label}: missing required bars {','.join(missing)}")
    return errors
