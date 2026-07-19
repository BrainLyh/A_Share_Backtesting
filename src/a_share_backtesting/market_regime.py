from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


RISK_OFF = "risk_off"
RISK_ON = "risk_on"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXECUTION_TIMES = {
    "same_day_1455": "14:55",
    "next_session_0935": "09:35",
}


@dataclass(frozen=True)
class RegimeTransition:
    signal_date: pd.Timestamp
    effective_timestamp: pd.Timestamp
    event: str
    label: str
    prior_state: str
    resulting_state: str
    execution_mode: str


class MarketRegimeSchedule:
    def __init__(self, initial_state: str, transitions: Sequence[RegimeTransition]) -> None:
        self._initial_state = initial_state
        self._transitions = tuple(transitions)
        self._by_timestamp = {transition.effective_timestamp: transition for transition in transitions}
        self.timeline = pd.DataFrame(
            [
                {
                    "signal_date": transition.signal_date,
                    "effective_timestamp": transition.effective_timestamp,
                    "event": transition.event,
                    "label": transition.label,
                    "prior_state": transition.prior_state,
                    "resulting_state": transition.resulting_state,
                    "execution_mode": transition.execution_mode,
                }
                for transition in transitions
            ],
            columns=[
                "signal_date",
                "effective_timestamp",
                "event",
                "label",
                "prior_state",
                "resulting_state",
                "execution_mode",
            ],
        )

    def state_at(self, timestamp: pd.Timestamp) -> str:
        state = self._initial_state
        instant = pd.Timestamp(timestamp)
        for transition in self._transitions:
            if transition.effective_timestamp > instant:
                break
            state = transition.resulting_state
        return state

    def event_at(self, timestamp: pd.Timestamp) -> RegimeTransition | None:
        return self._by_timestamp.get(pd.Timestamp(timestamp))


def load_market_regime_config(path: str | Path) -> dict[str, object]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("market regime config must be a JSON object")
    return payload


def _iso_date(value: object, field: str) -> pd.Timestamp:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        return pd.Timestamp(value).normalize()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)") from error


def _trading_date_index(trading_dates: Sequence[object]) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize().unique().sort_values()
    if dates.empty:
        raise ValueError("trading_dates must not be empty")
    return dates


def _effective_timestamp(signal_date: pd.Timestamp, mode: str, trading_dates: pd.DatetimeIndex) -> pd.Timestamp:
    if mode == "same_day_1455":
        if signal_date not in trading_dates:
            raise ValueError(f"signal date {signal_date:%Y-%m-%d} is not a supplied trading date")
        effective_date = signal_date
    else:
        future_dates = trading_dates[trading_dates > signal_date]
        if future_dates.empty:
            raise ValueError(f"no future trading session after {signal_date:%Y-%m-%d}")
        effective_date = future_dates[0]
    return pd.Timestamp(f"{effective_date:%Y-%m-%d} {_EXECUTION_TIMES[mode]}")


def build_market_regime_schedule(
    config: Mapping[str, object],
    trading_dates: Sequence[object],
) -> MarketRegimeSchedule:
    if not isinstance(config, Mapping):
        raise ValueError("market regime config must be an object")
    initial_state = config.get("initial_state")
    if initial_state not in {RISK_OFF, RISK_ON}:
        raise ValueError("initial_state must be 'risk_off' or 'risk_on'")
    observation_start = _iso_date(config.get("observation_start"), "observation_start")
    mode = config.get("execution_mode")
    if mode not in _EXECUTION_TIMES:
        raise ValueError("execution_mode must be 'same_day_1455' or 'next_session_0935'")
    raw_events = config.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("events must be a list")

    dates = _trading_date_index(trading_dates)
    observations: list[tuple[pd.Timestamp, str, str]] = []
    observed_dates: set[pd.Timestamp] = set()
    for raw_event in raw_events:
        if not isinstance(raw_event, Mapping):
            raise ValueError("each event must be an object")
        signal_date = _iso_date(raw_event.get("signal_date"), "event signal_date")
        if signal_date < observation_start:
            raise ValueError("event signal_date must not precede observation_start")
        if signal_date not in dates:
            raise ValueError(f"signal date {signal_date:%Y-%m-%d} is not a supplied trading date")
        if signal_date in observed_dates:
            raise ValueError(f"duplicate or conflicting event observation on {signal_date:%Y-%m-%d}")
        observed_dates.add(signal_date)
        event = raw_event.get("event")
        if event not in {"up", "down"}:
            raise ValueError("event must be 'up' or 'down'")
        label = raw_event.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("event label must be a non-empty string")
        observations.append((signal_date, event, label))

    state = initial_state
    transitions: list[RegimeTransition] = []
    effective_timestamps: set[pd.Timestamp] = set()
    for signal_date, event, label in sorted(observations, key=lambda item: item[0]):
        resulting_state = RISK_ON if event == "up" else RISK_OFF
        effective_timestamp = _effective_timestamp(signal_date, mode, dates)
        if effective_timestamp in effective_timestamps:
            raise ValueError(f"multiple events resolve to {effective_timestamp:%Y-%m-%d %H:%M}")
        effective_timestamps.add(effective_timestamp)
        transitions.append(
            RegimeTransition(
                signal_date=signal_date,
                effective_timestamp=effective_timestamp,
                event=event,
                label=label,
                prior_state=state,
                resulting_state=resulting_state,
                execution_mode=mode,
            )
        )
        state = resulting_state
    return MarketRegimeSchedule(initial_state, transitions)
