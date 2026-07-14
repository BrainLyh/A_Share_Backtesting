from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from .data_contract import normalize_daily_bars
from .event_study import measure_events
from .signals import build_signal_variants
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


def collect_signal_events(source_root: Path, config: dict[str, object]) -> tuple[pd.DataFrame, dict[str, object]]:
    """Measure frozen signal events one code at a time and retain no daily-bar universe."""
    start, end = pd.Timestamp(config["analysis_start"]), pd.Timestamp(config["analysis_end"])
    event_frames: list[pd.DataFrame] = []
    processed_code_count = 0
    for bars in iter_tdx_mainboard_bars(source_root, start, end):
        processed_code_count += 1
        signals = build_signal_variants(bars, config)
        for variant in config["variants"]:
            for horizon in config["horizons"]:
                event_frames.append(measure_events(signals, str(variant), int(horizon), config))
    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
    if not events.empty:
        events = events.loc[events["signal_date"].between(start, end)].reset_index(drop=True)
    return events, {"processed_code_count": processed_code_count, "data_scope_label": "technical_only_no_historical_market_cap_or_st"}
