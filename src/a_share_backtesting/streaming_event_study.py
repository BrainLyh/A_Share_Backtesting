from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import numpy as np

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


def collect_control_events(
    source_root: Path,
    config: dict[str, object],
    signal_dates: dict[tuple[str, int], set[pd.Timestamp]],
) -> pd.DataFrame:
    """Collect same-date non-signal candidates in a second, per-code pass."""
    if not signal_dates:
        return pd.DataFrame()
    start, end = pd.Timestamp(config["analysis_start"]), pd.Timestamp(config["analysis_end"])
    candidates: list[pd.DataFrame] = []
    for bars in iter_tdx_mainboard_bars(source_root, start, end):
        signals = build_signal_variants(bars, config)
        for (variant, horizon), dates in signal_dates.items():
            trigger = f"{variant}_first_trigger"
            candidate_dates = signals["date"].isin(dates) & ~signals[trigger]
            if not candidate_dates.any():
                continue
            candidate_signals = signals.copy()
            candidate_signals[trigger] = candidate_dates
            measured = measure_events(candidate_signals, variant, horizon, config)
            if not measured.empty:
                candidates.append(measured.loc[measured["signal_date"].isin(dates)])
    return pd.concat(candidates, ignore_index=True) if candidates else pd.DataFrame()


def sample_control_distribution(
    observed_events: pd.DataFrame, candidate_events: pd.DataFrame, iterations: int, random_seed: int
) -> pd.DataFrame:
    """Sample same-date candidate returns with the observed event count per group."""
    rng = np.random.default_rng(random_seed)
    observed = observed_events.loc[observed_events["status"].eq("filled")]
    candidates = candidate_events.loc[candidate_events["status"].eq("filled")]
    groups = list(observed.groupby(["variant", "horizon", "signal_date"], sort=True))
    rows = []
    for iteration in range(iterations):
        sampled_returns = []
        for key, group in groups:
            pool = candidates.loc[(candidates["variant"] == key[0]) & (candidates["horizon"] == key[1]) & (candidates["signal_date"] == key[2]), "net_return"].to_numpy()
            if len(pool) < len(group):
                continue
            sampled_returns.extend(rng.choice(pool, size=len(group), replace=False))
        rows.append({"iteration": iteration, "control_mean": float(np.mean(sampled_returns)) if sampled_returns else np.nan})
    return pd.DataFrame(rows)
