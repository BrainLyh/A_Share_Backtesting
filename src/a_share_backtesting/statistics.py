from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .event_study import _measure_event


def summarize_by_signal_date(events: pd.DataFrame) -> pd.DataFrame:
    """Build equal-weight portfolios for each distinct signal date."""
    filled = events.loc[events["status"].eq("filled")].copy()
    if filled.empty:
        return pd.DataFrame(columns=["variant", "horizon", "signal_date", "event_count", "portfolio_net_return", "portfolio_max_adverse_excursion"])
    return filled.groupby(["variant", "horizon", "signal_date"], as_index=False).agg(
        event_count=("event_id", "size"),
        portfolio_net_return=("net_return", "mean"),
        portfolio_max_adverse_excursion=("max_adverse_excursion", "mean"),
    )


def summarize_events(events: pd.DataFrame) -> pd.DataFrame:
    """Summarize each variant-horizon using equally weighted signal dates."""
    portfolios = summarize_by_signal_date(events)
    if portfolios.empty:
        return pd.DataFrame(columns=["variant", "horizon", "signal_date_count", "filled_event_count", "mean_net_return", "median_net_return", "win_rate", "mean_max_adverse_excursion"])
    filled = events.loc[events["status"].eq("filled")]
    result = portfolios.groupby(["variant", "horizon"], as_index=False).agg(
        signal_date_count=("signal_date", "size"),
        mean_net_return=("portfolio_net_return", "mean"),
        median_net_return=("portfolio_net_return", "median"),
        mean_max_adverse_excursion=("portfolio_max_adverse_excursion", "mean"),
    )
    counts = filled.groupby(["variant", "horizon"], as_index=False).agg(
        filled_event_count=("event_id", "size"), win_rate=("net_return", lambda values: float((values > 0).mean()))
    )
    return result.merge(counts, on=["variant", "horizon"], how="left")


def random_control_test(signals: pd.DataFrame, events: pd.DataFrame, variant: str, horizon: int, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compare a strategy's date portfolios with same-date eligible random controls."""
    strategy = events.loc[(events["variant"] == variant) & (events["horizon"] == horizon) & events["status"].eq("filled")]
    observed = summarize_by_signal_date(strategy)["portfolio_net_return"].mean()
    if strategy.empty:
        return pd.DataFrame(columns=["iteration", "control_mean_return"]), {"observed_mean": np.nan, "control_mean": np.nan, "control_percentile": np.nan, "empirical_p_value": np.nan}
    eligible = signals["eligible"] if "eligible" in signals else pd.Series(True, index=signals.index)
    rng = np.random.default_rng(int(config["random_seed"]))
    iteration_rows = []
    for iteration in range(int(config["control_iterations"])):
        returns = []
        for signal_date, day_events in strategy.groupby("signal_date"):
            candidates = signals.loc[(pd.to_datetime(signals["date"]) == pd.Timestamp(signal_date)) & eligible & ~signals["code"].isin(day_events["code"]), "code"].unique()
            if len(candidates) == 0:
                continue
            sampled = rng.choice(candidates, size=len(day_events), replace=len(candidates) < len(day_events))
            for code in sampled:
                bars = signals.loc[signals["code"].astype(str) == str(code)].sort_values("date").reset_index(drop=True)
                signal_index = bars.index[pd.to_datetime(bars["date"]).eq(pd.Timestamp(signal_date))][0]
                entry_index, exit_index = signal_index + 1, signal_index + 1 + horizon
                if exit_index < len(bars):
                    control = _measure_event(bars, signal_index, entry_index, exit_index, variant, horizon, config)
                    if control["status"] == "filled":
                        returns.append(control["net_return"])
        if returns:
            iteration_rows.append({"iteration": iteration, "control_mean_return": float(np.mean(returns))})
    distribution = pd.DataFrame(iteration_rows)
    if distribution.empty:
        return distribution, {"observed_mean": float(observed), "control_mean": np.nan, "control_percentile": np.nan, "empirical_p_value": np.nan}
    values = distribution["control_mean_return"]
    return distribution, {
        "observed_mean": float(observed), "control_mean": float(values.mean()),
        "control_percentile": float((values <= observed).mean()),
        "empirical_p_value": float((values >= observed).mean()),
    }
