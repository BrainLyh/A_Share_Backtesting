from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from .intraday_execution import (
    ExecutionConfig,
    Fill,
    PendingExit,
    Position,
    commission,
    entry_fill,
    process_exit_bar,
    validate_execution_config,
)
from .intraday_signals import scan_intraday_b1, select_scheme_a_candidates
from .market_regime import RISK_OFF, MarketRegimeSchedule
from .signals import build_signals


CandidateProvider = Callable[[pd.Timestamp, set[str]], pd.DataFrame]


@dataclass
class PortfolioResult:
    scans: pd.DataFrame
    candidates: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    nav_5m: pd.DataFrame
    nav_daily: pd.DataFrame
    rejections: pd.DataFrame
    data_audit: pd.DataFrame
    market_regime: pd.DataFrame
    open_positions: dict[str, Position] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "PortfolioResult":
        return cls(*(pd.DataFrame() for _ in range(11)), open_positions={})


def _records(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _fill_record(fill: Fill, position_id: str) -> dict[str, object]:
    return {"position_id": position_id, **asdict(fill)}


def _bar_at(day: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, object] | None:
    row = day.loc[pd.to_datetime(day["timestamp"]).eq(timestamp)]
    return None if row.empty else row.iloc[-1].to_dict()


def _adjusted_value(position: Position, bar: Mapping[str, object], price_column: str = "close") -> float:
    scale = float(bar.get("qfq_scale", 1.0))
    adjusted_price = float(bar.get(f"qfq_{price_column}", float(bar[price_column]) * scale))
    economic_units = position.remaining_shares / position.entry_qfq_scale
    return economic_units * adjusted_price


def _economic_sell_fill(fill: Fill, position: Position, bar: Mapping[str, object], config: ExecutionConfig) -> Fill:
    scale_ratio = float(bar.get("qfq_scale", 1.0)) / position.entry_qfq_scale
    gross = fill.gross_notional * scale_ratio
    fee = commission(gross, config)
    tax = round(gross * config.sell_stamp_duty_rate, 2)
    return replace(
        fill,
        gross_notional=gross,
        commission=fee,
        stamp_duty=tax,
        slippage_cost=fill.slippage_cost * scale_ratio,
        cash_delta=gross - fee - tax,
    )


def _full_daily_b1_states(daily_by_code: Mapping[str, pd.DataFrame], config: dict[str, Any]) -> dict[str, pd.Series]:
    states: dict[str, pd.Series] = {}
    for code, frame in daily_by_code.items():
        signals = build_signals(frame.copy(), config)
        states[code] = signals.set_index(pd.to_datetime(signals["date"]))["b1_entry_signal"].astype(bool)
    return states


def _prior_state(states: pd.Series, date: pd.Timestamp) -> bool | None:
    prior = states.loc[states.index < date]
    return bool(prior.iloc[-1]) if not prior.empty else None


def cached_scan_candidate_provider(
    scans: pd.DataFrame,
    daily_by_code: Mapping[str, pd.DataFrame],
    signal_config: dict[str, Any],
) -> CandidateProvider:
    """Build a dynamic candidate provider from frozen per-code scan results."""
    required = {"date", "code", "scan_time", "b1_signal", "signal_strength", "atr14"}
    missing = required - set(scans.columns)
    if missing:
        raise ValueError(f"scan source missing columns: {', '.join(sorted(missing))}")
    cached = scans.copy()
    cached["date"] = pd.to_datetime(cached["date"]).dt.normalize()
    cached["code"] = cached["code"].astype(str).str.strip().str.zfill(6)
    cached["b1_signal"] = cached["b1_signal"].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})
    daily = {
        str(code).zfill(6): frame.sort_values("date").reset_index(drop=True)
        for code, frame in daily_by_code.items()
    }
    daily_states = _full_daily_b1_states(daily, signal_config)

    def provider(date: pd.Timestamp, held_codes: set[str]) -> pd.DataFrame:
        normalized_date = pd.Timestamp(date).normalize()
        day_scans = cached.loc[cached["date"].eq(normalized_date)].copy()
        if day_scans.empty:
            return pd.DataFrame(columns=[*cached.columns, "first_trigger_time"])
        prior_states = {
            code: _prior_state(daily_states[code], normalized_date)
            for code in day_scans["code"].drop_duplicates()
            if code in daily_states
        }
        return select_scheme_a_candidates(day_scans, prior_states, held_codes)

    return provider


def _default_candidates(
    date: pd.Timestamp,
    held_codes: set[str],
    daily_by_code: Mapping[str, pd.DataFrame],
    minute_days: Mapping[str, pd.DataFrame],
    signal_config: dict[str, Any],
    daily_states: Mapping[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scan_frames: list[pd.DataFrame] = []
    prior_states: dict[str, bool | None] = {}
    for code in sorted(minute_days):
        daily = daily_by_code.get(code)
        minute_day = minute_days[code]
        if daily is None or daily.empty or minute_day.empty:
            continue
        scale_rows = daily.loc[pd.to_datetime(daily["date"]).eq(date), "qfq_scale"]
        if scale_rows.empty:
            continue
        scans = scan_intraday_b1(daily, minute_day, signal_config, qfq_scale=float(scale_rows.iloc[-1]))
        scans["qfq_scale"] = float(scale_rows.iloc[-1])
        scan_frames.append(scans)
        prior_states[code] = _prior_state(daily_states[code], date)
    all_scans = pd.concat(scan_frames, ignore_index=True) if scan_frames else pd.DataFrame()
    selected = select_scheme_a_candidates(all_scans, prior_states, held_codes) if not all_scans.empty else pd.DataFrame()
    return all_scans, selected


def _drawdown(values: pd.Series, peaks: pd.Series | None = None) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return float("nan")
    reference = numeric.cummax() if peaks is None else pd.to_numeric(peaks, errors="coerce").reindex(numeric.index).cummax()
    return float((numeric / reference - 1.0).min())


def run_intraday_portfolio(
    daily_by_code: Mapping[str, pd.DataFrame],
    minute_by_code: Mapping[str, pd.DataFrame],
    signal_config: dict[str, Any],
    execution_config: ExecutionConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    candidate_provider: CandidateProvider | None = None,
    market_regime: MarketRegimeSchedule | None = None,
) -> PortfolioResult:
    validate_execution_config(execution_config)
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    daily = {str(code).zfill(6): frame.sort_values("date").reset_index(drop=True) for code, frame in daily_by_code.items()}
    minutes = {str(code).zfill(6): frame.sort_values("timestamp").reset_index(drop=True) for code, frame in minute_by_code.items()}
    all_dates = sorted(
        {
            pd.Timestamp(date).normalize()
            for frame in minutes.values()
            for date in pd.to_datetime(frame["date"]).unique()
            if start <= pd.Timestamp(date).normalize() <= end
        }
    )
    daily_states = _full_daily_b1_states(daily, signal_config) if candidate_provider is None else {}
    cash = float(execution_config.initial_cash)
    open_positions: dict[str, Position] = {}
    pending: dict[str, list[PendingExit]] = {}
    expiry_dates: dict[str, pd.Timestamp | None] = {}
    entry_fills: dict[str, Fill] = {}
    sell_fills: dict[str, list[Fill]] = {}
    last_bars: dict[str, dict[str, object]] = {}
    scan_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    rejection_rows: list[dict[str, object]] = []
    nav_rows: list[dict[str, object]] = []

    date_index = {date: index for index, date in enumerate(all_dates)}
    regime_transitions = market_regime.transitions if market_regime is not None else ()
    next_regime_transition = 0
    for date in all_dates:
        exited_today: set[str] = set()
        minute_days = {
            code: frame.loc[pd.to_datetime(frame["date"]).eq(date)].copy()
            for code, frame in minutes.items()
            if pd.to_datetime(frame["date"]).eq(date).any()
        }
        timestamps = sorted({pd.Timestamp(ts) for frame in minute_days.values() for ts in pd.to_datetime(frame["timestamp"])})
        day_candidates: pd.DataFrame | None = None
        for timestamp in timestamps:
            newly_entered: set[str] = set()
            crossed_transitions = []
            while (
                next_regime_transition < len(regime_transitions)
                and regime_transitions[next_regime_transition].effective_timestamp <= timestamp
            ):
                crossed_transitions.append(regime_transitions[next_regime_transition])
                next_regime_transition += 1
            for regime_transition in crossed_transitions:
                if regime_transition.event != "down":
                    continue
                trigger_column = "close" if regime_transition.execution_mode == "same_day_1455" else "open"
                for code, position in open_positions.items():
                    position_pending = pending.get(position.position_id, [])
                    if any(order.reason == "market_regime_exit" for order in position_pending):
                        continue
                    raw_bar = None
                    if regime_transition.effective_timestamp == timestamp and code in minute_days:
                        raw_bar = _bar_at(minute_days[code], timestamp)
                    # A deferred order keeps the event timestamp and prices from its next bar's open.
                    trigger_price = float("nan")
                    if raw_bar is not None:
                        current_scale = float(raw_bar.get("qfq_scale", 1.0))
                        trigger_price = float(
                            raw_bar.get(
                                f"qfq_{trigger_column}",
                                float(raw_bar[trigger_column]) * current_scale,
                            )
                        )
                    pending[position.position_id] = [
                        PendingExit(
                            "market_regime_exit",
                            position.remaining_shares,
                            trigger_price,
                            regime_transition.effective_timestamp,
                        )
                    ]
            for code in sorted(list(open_positions)):
                raw_bar = _bar_at(minute_days.get(code, pd.DataFrame()), timestamp) if code in minute_days else None
                if raw_bar is None:
                    continue
                last_bars[code] = raw_bar
                position = open_positions[code]
                current_scale = float(raw_bar.get("qfq_scale", 1.0))
                execution_bar = dict(raw_bar)
                execution_bar["volume"] = int(float(raw_bar["volume"]) * position.entry_qfq_scale / current_scale)
                execution_bar["is_expiry_close"] = bool(
                    expiry_dates.get(position.position_id) == date and timestamp.strftime("%H:%M") == "15:00"
                )
                position_pending = pending.get(position.position_id, [])
                expiry_date = expiry_dates.get(position.position_id)
                if (
                    expiry_date is not None
                    and date > expiry_date
                    and not any(order.reason == "expiry" for order in position_pending)
                ):
                    adjusted_open = float(raw_bar["open"]) * current_scale
                    position_pending = [
                        *position_pending,
                        PendingExit(
                            "expiry",
                            position.remaining_shares,
                            adjusted_open,
                            pd.Timestamp(expiry_date) + pd.Timedelta(hours=15),
                        ),
                    ]
                result = process_exit_bar(position, position_pending, execution_bar, execution_config)
                for reason in result.rejections:
                    rejection_rows.append({"timestamp": timestamp, "code": code, "side": "sell", "reason": reason})
                for raw_fill in result.fills:
                    fill = _economic_sell_fill(raw_fill, position, raw_bar, execution_config)
                    cash += fill.cash_delta
                    fill_rows.append(_fill_record(fill, position.position_id))
                    order_rows.append(
                        {"timestamp": timestamp, "code": code, "side": "sell", "reason": fill.reason, "status": "filled"}
                    )
                    sell_fills.setdefault(position.position_id, []).append(fill)
                open_positions[code] = result.position
                pending[position.position_id] = result.pending
                if result.position.remaining_shares <= 0:
                    buy = entry_fills[position.position_id]
                    exits = sell_fills.get(position.position_id, [])
                    proceeds = sum(fill.cash_delta for fill in exits)
                    entry_cost = -buy.cash_delta
                    exit_date = exits[-1].timestamp.normalize() if exits else timestamp.normalize()
                    trade_rows.append(
                        {
                            "position_id": position.position_id,
                            "code": code,
                            "entry_timestamp": position.entry_timestamp,
                            "exit_timestamp": exits[-1].timestamp if exits else timestamp,
                            "status": "closed",
                            "exit_reason": exits[-1].reason if exits else "unknown",
                            "entry_cost": entry_cost,
                            "net_proceeds": proceeds,
                            "net_pnl": proceeds - entry_cost,
                            "net_return": proceeds / entry_cost - 1.0,
                            "holding_days": date_index.get(exit_date, 0) - date_index.get(position.entry_date, 0),
                        }
                    )
                    del open_positions[code]
                    pending.pop(position.position_id, None)
                    exited_today.add(code)

            time_label = timestamp.strftime("%H:%M")
            if time_label == "14:55":
                if candidate_provider is None:
                    scans, day_candidates = _default_candidates(
                        date, set(open_positions), daily, minute_days, signal_config, daily_states
                    )
                    scan_rows.extend(scans.to_dict("records"))
                else:
                    day_candidates = candidate_provider(date, set(open_positions))
                if day_candidates is None:
                    day_candidates = pd.DataFrame()
                for selection_rejection in day_candidates.attrs.get("rejections", []):
                    rejection_rows.append(
                        {
                            "timestamp": timestamp,
                            "code": str(selection_rejection["code"]).zfill(6),
                            "side": "buy",
                            "reason": selection_rejection["reason"],
                        }
                    )
                if not day_candidates.empty:
                    day_candidates = day_candidates.copy()
                    day_candidates["code"] = day_candidates["code"].astype(str).str.zfill(6)
                    candidate_rows.extend(day_candidates.to_dict("records"))
                market_value = sum(
                    _adjusted_value(position, last_bars[code])
                    for code, position in open_positions.items()
                    if code in last_bars
                )
                pre_entry_nav = cash + market_value
                regime_blocks_entries = market_regime is not None and (
                    market_regime.state_at(timestamp) == RISK_OFF
                    or any(
                        order.reason == "market_regime_exit"
                        for orders in pending.values()
                        for order in orders
                    )
                )
                for _, candidate in day_candidates.iterrows() if not day_candidates.empty else []:
                    code = str(candidate["code"]).zfill(6)
                    if regime_blocks_entries:
                        rejection_rows.append(
                            {"timestamp": timestamp, "code": code, "side": "buy", "reason": "market_regime_off"}
                        )
                        continue
                    if code in exited_today:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "rearm_required"})
                        continue
                    if code in open_positions:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "position_already_open"})
                        continue
                    if len(open_positions) >= execution_config.max_positions:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "capacity"})
                        continue
                    day = minute_days.get(code)
                    raw_bar = _bar_at(day, timestamp) if day is not None else None
                    if raw_bar is None:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": "missing_entry_bar"})
                        continue
                    last_bars[code] = raw_bar
                    entry_candidate = candidate.to_dict()
                    entry_candidate["qfq_scale"] = float(raw_bar.get("qfq_scale", 1.0))
                    result = entry_fill(entry_candidate, raw_bar, pre_entry_nav, cash, execution_config)
                    order_rows.append(
                        {
                            "timestamp": timestamp,
                            "code": code,
                            "side": "buy",
                            "reason": "entry",
                            "status": "rejected" if result.rejection else "filled",
                        }
                    )
                    if result.rejection is not None or result.position is None or result.fill is None:
                        rejection_rows.append({"timestamp": timestamp, "code": code, "side": "buy", "reason": result.rejection})
                        continue
                    cash += result.fill.cash_delta
                    if cash < -0.01:
                        raise ValueError("cash reconciliation failed: negative cash")
                    open_positions[code] = result.position
                    if len(open_positions) > 3:
                        raise AssertionError("open position count exceeded the hard limit of 3")
                    pending[result.position.position_id] = []
                    horizon_index = date_index[date] + execution_config.horizon_days
                    expiry_dates[result.position.position_id] = all_dates[horizon_index] if horizon_index < len(all_dates) else None
                    entry_fills[result.position.position_id] = result.fill
                    sell_fills[result.position.position_id] = []
                    fill_rows.append(_fill_record(result.fill, result.position.position_id))
                    newly_entered.add(code)

            for code, day in minute_days.items():
                current_bar = _bar_at(day, timestamp)
                if current_bar is not None:
                    last_bars[code] = current_bar
            marked = 0.0
            marked_low = 0.0
            for code, position in open_positions.items():
                current_bar = last_bars.get(code)
                if current_bar is None:
                    continue
                market_value = _adjusted_value(position, current_bar, "close")
                marked += market_value
                low_column = "close" if code in newly_entered else "low"
                low_market_value = _adjusted_value(position, current_bar, low_column)
                marked_low += low_market_value
                entry_cost = -entry_fills[position.position_id].cash_delta
                realized = sum(fill.cash_delta for fill in sell_fills.get(position.position_id, []))
                position_rows.append(
                    {
                        "timestamp": timestamp,
                        "position_id": position.position_id,
                        "code": code,
                        "remaining_shares": position.remaining_shares,
                        "market_value": market_value,
                        "position_return": (realized + market_value) / entry_cost - 1.0,
                        "position_return_low": (realized + low_market_value) / entry_cost - 1.0,
                    }
                )
            nav = cash + marked
            if cash < -0.01 or not np.isfinite(nav):
                raise ValueError("cash or NAV invariant failed")
            nav_rows.append(
                {
                    "timestamp": timestamp,
                    "date": date,
                    "cash": cash,
                    "gross_exposure": marked,
                    "positions": len(open_positions),
                    "nav": nav,
                    "nav_low": cash + marked_low,
                }
            )

    nav_5m = _records(nav_rows)
    nav_daily = (
        nav_5m.sort_values("timestamp").groupby("date", as_index=False).tail(1).reset_index(drop=True)
        if not nav_5m.empty
        else pd.DataFrame()
    )
    for code, position in open_positions.items():
        buy = entry_fills[position.position_id]
        exits = sell_fills.get(position.position_id, [])
        proceeds = sum(fill.cash_delta for fill in exits)
        marked = _adjusted_value(position, last_bars[code]) if code in last_bars else 0.0
        entry_cost = -buy.cash_delta
        trade_rows.append(
            {
                "position_id": position.position_id,
                "code": code,
                "entry_timestamp": position.entry_timestamp,
                "exit_timestamp": pd.NaT,
                "status": "open",
                "exit_reason": "open_at_end",
                "entry_cost": entry_cost,
                "net_proceeds": proceeds,
                "net_pnl": proceeds + marked - entry_cost,
                "net_return": (proceeds + marked) / entry_cost - 1.0,
                "holding_days": date_index.get(all_dates[-1], 0) - date_index.get(position.entry_date, 0) if all_dates else 0,
            }
        )
    positions_frame = _records(position_rows)
    trades_frame = _records(trade_rows)
    if not trades_frame.empty:
        path_mae = (
            positions_frame.groupby("position_id")["position_return_low"].min()
            if not positions_frame.empty and "position_return_low" in positions_frame
            else pd.Series(dtype=float)
        )
        trades_frame["maximum_adverse_excursion"] = [
            min(float(row.net_return), float(path_mae.get(row.position_id, row.net_return)))
            for row in trades_frame.itertuples()
        ]
    return PortfolioResult(
        scans=_records(scan_rows),
        candidates=_records(candidate_rows),
        orders=_records(order_rows),
        fills=_records(fill_rows),
        positions=positions_frame,
        trades=trades_frame,
        nav_5m=nav_5m,
        nav_daily=nav_daily,
        rejections=_records(rejection_rows).reindex(columns=["timestamp", "code", "side", "reason"]),
        data_audit=pd.DataFrame(),
        market_regime=market_regime.timeline.copy() if market_regime is not None else pd.DataFrame(),
        open_positions=dict(open_positions),
    )


def summarize_portfolio(result: PortfolioResult, initial_cash: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if result.nav_5m.empty:
        portfolio = pd.DataFrame(
            [
                {
                    "initial_cash": initial_cash,
                    "final_nav": initial_cash,
                    "total_net_return": 0.0,
                    "max_drawdown_5m": 0.0,
                    "max_drawdown_low": 0.0,
                    "max_drawdown_daily": 0.0,
                    "average_exposure": 0.0,
                    "max_exposure": 0.0,
                    "capital_utilization": 0.0,
                    "max_positions": 0,
                    "turnover": 0.0,
                    "commission": 0.0,
                    "stamp_duty": 0.0,
                    "slippage_cost": 0.0,
                }
            ]
        )
    else:
        nav = result.nav_5m["nav"].astype(float)
        close_peaks = nav.cummax()
        fills = result.fills if not result.fills.empty else pd.DataFrame()
        gross = float(fills["gross_notional"].sum()) if "gross_notional" in fills else 0.0
        commission_cost = float(fills["commission"].sum()) if "commission" in fills else 0.0
        stamp_cost = float(fills["stamp_duty"].sum()) if "stamp_duty" in fills else 0.0
        slippage_cost = float(fills["slippage_cost"].sum()) if "slippage_cost" in fills else 0.0
        exposure = result.nav_5m["gross_exposure"].astype(float) / nav.replace(0, np.nan)
        portfolio = pd.DataFrame(
            [
                {
                    "initial_cash": initial_cash,
                    "final_nav": float(nav.iloc[-1]),
                    "total_net_return": float(nav.iloc[-1] / initial_cash - 1.0),
                    "max_drawdown_5m": _drawdown(nav),
                    "max_drawdown_low": _drawdown(result.nav_5m["nav_low"].astype(float), close_peaks),
                    "max_drawdown_daily": _drawdown(result.nav_daily["nav"].astype(float)),
                    "average_exposure": float(exposure.mean()),
                    "max_exposure": float(exposure.max()),
                    "capital_utilization": float(result.nav_5m["gross_exposure"].astype(float).mean() / initial_cash),
                    "max_positions": int(result.nav_5m["positions"].max()),
                    "turnover": gross / initial_cash,
                    "commission": commission_cost,
                    "stamp_duty": stamp_cost,
                    "slippage_cost": slippage_cost,
                }
            ]
        )
    trades = result.trades if not result.trades.empty else pd.DataFrame()
    closed = trades.loc[trades["status"].eq("closed")].copy() if "status" in trades else pd.DataFrame()
    wins = closed.loc[closed["net_pnl"] > 0, "net_pnl"] if not closed.empty else pd.Series(dtype=float)
    losses = closed.loc[closed["net_pnl"] < 0, "net_pnl"] if not closed.empty else pd.Series(dtype=float)
    ordered = closed.sort_values("entry_timestamp") if "entry_timestamp" in closed else closed
    maximum_consecutive_losses = 0
    current_loss_run = 0
    for is_loss in ordered["net_pnl"].lt(0) if not ordered.empty else []:
        current_loss_run = current_loss_run + 1 if is_loss else 0
        maximum_consecutive_losses = max(maximum_consecutive_losses, current_loss_run)
    fill_ids: set[str] = set()
    if not result.fills.empty and {"position_id", "reason"}.issubset(result.fills.columns):
        fill_ids = set(
            result.fills.loc[
                result.fills["reason"].astype(str).str.startswith("take_profit_"), "position_id"
            ].astype(str)
        )
    closed_ids = set(closed["position_id"].astype(str)) if "position_id" in closed else set()
    mae = pd.to_numeric(closed.get("maximum_adverse_excursion", pd.Series(dtype=float)), errors="coerce").dropna()
    exit_reason = closed.get("exit_reason", pd.Series(index=closed.index, dtype=str)).astype(str)
    trade = pd.DataFrame(
        [
            {
                "closed_trade_count": int(len(closed)),
                "open_trade_count": int((trades["status"] == "open").sum()) if "status" in trades else 0,
                "win_rate": float((closed["net_pnl"] > 0).mean()) if not closed.empty else float("nan"),
                "mean_net_return": float(closed["net_return"].mean()) if not closed.empty else float("nan"),
                "median_net_return": float(closed["net_return"].median()) if not closed.empty else float("nan"),
                "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else float("inf") if not wins.empty else float("nan"),
                "payoff_ratio": float(wins.mean() / abs(losses.mean())) if not wins.empty and not losses.empty else float("nan"),
                "expectancy": float(closed["net_pnl"].mean()) if not closed.empty else float("nan"),
                "average_holding_days": float(closed["holding_days"].mean()) if not closed.empty else float("nan"),
                "maximum_consecutive_losses": maximum_consecutive_losses,
                "take_profit_trade_rate": float(len(fill_ids & closed_ids) / len(closed)) if not closed.empty else float("nan"),
                "stop_exit_rate": float(exit_reason.eq("stop_loss").mean()) if not closed.empty else float("nan"),
                "residual_exit_rate": float(exit_reason.eq("residual_drawdown").mean()) if not closed.empty else float("nan"),
                "expiry_exit_rate": float(exit_reason.eq("expiry").mean()) if not closed.empty else float("nan"),
                "overtime_exit_rate": float(exit_reason.eq("overtime_exit").mean()) if not closed.empty else float("nan"),
                "mean_maximum_adverse_excursion": float(mae.mean()) if not mae.empty else float("nan"),
                "worst_maximum_adverse_excursion": float(mae.min()) if not mae.empty else float("nan"),
            }
        ]
    )
    return portfolio, trade
