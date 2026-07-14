from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from .data_contract import normalize_daily_bars
from .tdx_day import is_target_mainboard_path, read_tdx_day_file


def iter_tdx_mainboard_bars(source_root: Path, start: pd.Timestamp, end: pd.Timestamp) -> Iterator[pd.DataFrame]:
    """Yield one normalized technical-only mainboard frame per local TDX file."""
    warmup_start = start - pd.offsets.BDay(180)
    for path in sorted(source_root.rglob("*.day")):
        if not is_target_mainboard_path(path):
            continue
        bars = read_tdx_day_file(path).assign(
            name=lambda frame: frame["code"],
            market_cap=0,
            is_st=False,
            is_suspended=False,
        )
        bars = normalize_daily_bars(bars, require_core_pool=False)
        yield bars.loc[bars["date"].between(warmup_start, end)].copy()
