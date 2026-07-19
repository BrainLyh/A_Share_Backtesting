from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class ExecutionConfig:
    initial_cash: float = 1_000_000.0
    max_positions: int = 3
    target_fraction: float = 1.0 / 3.0
    lot_size: int = 100
    participation_rate: float = 0.10
    buy_slippage_bps: float = 5.0
    sell_slippage_bps: float = 5.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    sell_stamp_duty_rate: float = 0.0005
    atr_multiple: float = 1.5
    atr_min_stop: float = 0.06
    atr_max_stop: float = 0.10
    take_profit_1: float = 0.10
    take_profit_2: float = 0.20
    residual_drawdown: float = 0.15
    horizon_days: int = 5


def validate_execution_config(config: ExecutionConfig) -> None:
    if not 1 <= config.max_positions <= 3:
        raise ValueError("max_positions must be between 1 and 3")
    if not 0 < config.participation_rate <= 0.10:
        raise ValueError("participation_rate must be greater than 0 and no more than 0.10")


@dataclass(frozen=True)
class Fill:
    code: str
    timestamp: pd.Timestamp
    side: str
    reason: str
    shares: int
    raw_price: float
    adjusted_price: float
    gross_notional: float
    commission: float
    stamp_duty: float
    slippage_cost: float
    cash_delta: float


@dataclass(frozen=True)
class Position:
    position_id: str
    code: str
    entry_timestamp: pd.Timestamp
    entry_date: pd.Timestamp
    original_shares: int
    remaining_shares: int
    entry_raw_price: float
    adjusted_entry_price: float
    entry_qfq_scale: float
    stop_adjusted_price: float
    tp1_adjusted_price: float
    tp2_adjusted_price: float
    tp1_target_shares: int
    tp2_target_shares: int
    tp1_sold_shares: int
    tp2_sold_shares: int
    peak_adjusted_close: float
    entry_commission: float


@dataclass(frozen=True)
class PendingExit:
    reason: str
    remaining_shares: int
    trigger_adjusted_price: float
    triggered_timestamp: pd.Timestamp


@dataclass(frozen=True)
class EntryResult:
    fill: Fill | None
    position: Position | None
    rejection: str | None


@dataclass(frozen=True)
class ExitResult:
    position: Position
    pending: list[PendingExit]
    fills: list[Fill]
    rejections: list[str]


def commission(notional: float, config: ExecutionConfig) -> float:
    return round(max(float(notional) * config.commission_rate, config.minimum_commission), 2)


def _lot_floor(shares: float, lot_size: int) -> int:
    if not math.isfinite(float(shares)) or shares <= 0:
        return 0
    return int(float(shares) // lot_size) * lot_size


def _same_price_bar(bar: Mapping[str, object], tolerance: float = 1e-6) -> bool:
    values = [float(bar[column]) for column in ("open", "high", "low", "close")]
    return max(values) - min(values) <= tolerance


def _near_known_limit(price: float, preclose: float, side: str) -> bool:
    direction = 1.0 if side == "buy" else -1.0
    for limit in (0.05, 0.10, 0.20, 0.30):
        theoretical = preclose * (1.0 + direction * limit)
        if abs(price - theoretical) <= 0.011:
            return True
    return False


def is_one_price_limit(bar: Mapping[str, object], side: str) -> bool:
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not _same_price_bar(bar):
        return False
    explicit = "upper_limit" if side == "buy" else "lower_limit"
    price = float(bar["close"])
    if explicit in bar and pd.notna(bar[explicit]):
        return abs(price - float(bar[explicit])) <= 0.011
    preclose = float(bar.get("preclose", 0.0))
    return preclose > 0 and _near_known_limit(price, preclose, side)


def _rejected(reason: str) -> EntryResult:
    return EntryResult(fill=None, position=None, rejection=reason)


def entry_fill(
    candidate: Mapping[str, object],
    bar: Mapping[str, object],
    nav: float,
    cash: float,
    config: ExecutionConfig,
) -> EntryResult:
    if int(bar.get("volume", 0)) <= 0:
        return _rejected("suspension_or_zero_volume")
    if is_one_price_limit(bar, "buy"):
        return _rejected("upper_limit_lock")
    raw_base = float(bar["close"])
    raw_price = raw_base * (1.0 + config.buy_slippage_bps / 10_000.0)
    if "upper_limit" in bar and pd.notna(bar["upper_limit"]):
        raw_price = min(raw_price, float(bar["upper_limit"]))
    desired = _lot_floor(float(nav) * config.target_fraction / raw_price, config.lot_size)
    volume_cap = _lot_floor(int(bar["volume"]) * config.participation_rate, config.lot_size)
    if volume_cap <= 0:
        return _rejected("volume_cap_below_one_lot")
    shares = min(desired, volume_cap)
    while shares > 0:
        notional = shares * raw_price
        if notional + commission(notional, config) <= float(cash) + 1e-9:
            break
        shares -= config.lot_size
    if shares <= 0:
        return _rejected("insufficient_cash")
    gross = shares * raw_price
    fee = commission(gross, config)
    scale = float(candidate.get("qfq_scale", bar.get("qfq_scale", 1.0)))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("qfq_scale must be finite and positive")
    adjusted_price = raw_price * scale
    atr14 = float(candidate.get("atr14", float("nan")))
    if math.isfinite(atr14):
        stop_distance = min(max(config.atr_multiple * atr14 / adjusted_price, config.atr_min_stop), config.atr_max_stop)
    else:
        stop_distance = config.atr_min_stop
    slice_shares = _lot_floor(shares / 3.0, config.lot_size)
    timestamp = pd.Timestamp(bar["timestamp"])
    code = str(candidate["code"]).zfill(6)
    fill = Fill(
        code=code,
        timestamp=timestamp,
        side="buy",
        reason="entry",
        shares=shares,
        raw_price=raw_price,
        adjusted_price=adjusted_price,
        gross_notional=gross,
        commission=fee,
        stamp_duty=0.0,
        slippage_cost=max(raw_price - raw_base, 0.0) * shares,
        cash_delta=-(gross + fee),
    )
    position = Position(
        position_id=f"{code}:{timestamp:%Y%m%d%H%M}",
        code=code,
        entry_timestamp=timestamp,
        entry_date=timestamp.normalize(),
        original_shares=shares,
        remaining_shares=shares,
        entry_raw_price=raw_price,
        adjusted_entry_price=adjusted_price,
        entry_qfq_scale=scale,
        stop_adjusted_price=adjusted_price * (1.0 - stop_distance),
        tp1_adjusted_price=adjusted_price * (1.0 + config.take_profit_1),
        tp2_adjusted_price=adjusted_price * (1.0 + config.take_profit_2),
        tp1_target_shares=slice_shares,
        tp2_target_shares=slice_shares,
        tp1_sold_shares=0,
        tp2_sold_shares=0,
        peak_adjusted_close=adjusted_price,
        entry_commission=fee,
    )
    return EntryResult(fill=fill, position=position, rejection=None)


def _adjusted_prices(bar: Mapping[str, object]) -> dict[str, float]:
    scale = float(bar.get("qfq_scale", 1.0))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("qfq_scale must be finite and positive")
    return {
        column: float(bar.get(f"qfq_{column}", float(bar[column]) * scale))
        for column in ("open", "high", "low", "close")
    }


def _sell_fill(
    position: Position,
    shares: int,
    reason: str,
    adjusted_base: float,
    bar: Mapping[str, object],
    config: ExecutionConfig,
) -> Fill:
    scale = float(bar.get("qfq_scale", 1.0))
    raw_base = adjusted_base / scale
    raw_price = raw_base * (1.0 - config.sell_slippage_bps / 10_000.0)
    if "lower_limit" in bar and pd.notna(bar["lower_limit"]):
        raw_price = max(raw_price, float(bar["lower_limit"]))
    adjusted_price = raw_price * scale
    gross = shares * raw_price
    fee = commission(gross, config)
    tax = round(gross * config.sell_stamp_duty_rate, 2)
    return Fill(
        code=position.code,
        timestamp=pd.Timestamp(bar["timestamp"]),
        side="sell",
        reason=reason,
        shares=shares,
        raw_price=raw_price,
        adjusted_price=adjusted_price,
        gross_notional=gross,
        commission=fee,
        stamp_duty=tax,
        slippage_cost=max(raw_base - raw_price, 0.0) * shares,
        cash_delta=gross - fee - tax,
    )


def _pending_for(pending: list[PendingExit], reason: str) -> PendingExit | None:
    return next((order for order in pending if order.reason == reason), None)


def _replace_pending(pending: list[PendingExit], old: PendingExit, remaining: int) -> list[PendingExit]:
    result = [order for order in pending if order is not old]
    if remaining > 0:
        result.append(replace(old, remaining_shares=remaining))
    return result


def process_exit_bar(
    position: Position,
    pending: list[PendingExit],
    bar: Mapping[str, object],
    config: ExecutionConfig,
) -> ExitResult:
    timestamp = pd.Timestamp(bar["timestamp"])
    prices = _adjusted_prices(bar)
    current = position
    orders = list(pending)
    fills: list[Fill] = []
    rejections: list[str] = []
    regime_order = _pending_for(orders, "market_regime_exit")
    if regime_order is not None:
        orders = [regime_order]
    if timestamp.normalize() <= current.entry_date or current.remaining_shares <= 0:
        peak = max(current.peak_adjusted_close, prices["close"]) if current.remaining_shares > 0 else current.peak_adjusted_close
        return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)

    available = _lot_floor(int(bar.get("volume", 0)) * config.participation_rate, config.lot_size)
    locked_lower = is_one_price_limit(bar, "sell")

    if regime_order is not None:
        if locked_lower or available <= 0:
            rejections.append("lower_limit_lock" if locked_lower else "volume_cap_below_one_lot")
            peak = max(current.peak_adjusted_close, prices["close"])
            return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)
        base = regime_order.trigger_adjusted_price if regime_order.triggered_timestamp == timestamp else prices["open"]
        shares = min(regime_order.remaining_shares, current.remaining_shares, available)
        fill = _sell_fill(current, shares, "market_regime_exit", base, bar, config)
        fills.append(fill)
        current = replace(current, remaining_shares=current.remaining_shares - shares)
        orders = _replace_pending(orders, regime_order, regime_order.remaining_shares - shares)
        peak = max(current.peak_adjusted_close, prices["close"]) if current.remaining_shares else current.peak_adjusted_close
        return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)

    stop_order = _pending_for(orders, "stop_loss")
    if stop_order is None and prices["low"] <= current.stop_adjusted_price:
        trigger_price = prices["open"] if prices["open"] <= current.stop_adjusted_price else current.stop_adjusted_price
        stop_order = PendingExit("stop_loss", current.remaining_shares, trigger_price, timestamp)
        orders = [stop_order]
    if stop_order is not None:
        if locked_lower or available <= 0:
            rejections.append("lower_limit_lock" if locked_lower else "volume_cap_below_one_lot")
            peak = max(current.peak_adjusted_close, prices["close"])
            return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)
        base = stop_order.trigger_adjusted_price if stop_order.triggered_timestamp == timestamp else prices["open"]
        shares = min(stop_order.remaining_shares, current.remaining_shares, available)
        fill = _sell_fill(current, shares, "stop_loss", base, bar, config)
        fills.append(fill)
        current = replace(current, remaining_shares=current.remaining_shares - shares)
        orders = _replace_pending(orders, stop_order, stop_order.remaining_shares - shares)
        peak = max(current.peak_adjusted_close, prices["close"]) if current.remaining_shares else current.peak_adjusted_close
        return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)

    if locked_lower:
        if orders:
            rejections.append("lower_limit_lock")
        peak = max(current.peak_adjusted_close, prices["close"])
        return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)

    profit_specs = [
        ("take_profit_10", current.tp1_adjusted_price, current.tp1_target_shares, current.tp1_sold_shares),
        ("take_profit_20", current.tp2_adjusted_price, current.tp2_target_shares, current.tp2_sold_shares),
    ]
    for reason, threshold, target, sold in profit_specs:
        if target <= sold or _pending_for(orders, reason) is not None or prices["high"] < threshold:
            continue
        trigger_price = prices["open"] if prices["open"] >= threshold else threshold
        orders.append(PendingExit(reason, target - sold, trigger_price, timestamp))

    for reason in ("take_profit_10", "take_profit_20"):
        order = _pending_for(orders, reason)
        if order is None or available <= 0 or current.remaining_shares <= 0:
            continue
        base = order.trigger_adjusted_price if order.triggered_timestamp == timestamp else prices["open"]
        shares = min(order.remaining_shares, current.remaining_shares, available)
        fill = _sell_fill(current, shares, reason, base, bar, config)
        fills.append(fill)
        available -= shares
        if reason == "take_profit_10":
            current = replace(
                current,
                remaining_shares=current.remaining_shares - shares,
                tp1_sold_shares=current.tp1_sold_shares + shares,
            )
        else:
            current = replace(
                current,
                remaining_shares=current.remaining_shares - shares,
                tp2_sold_shares=current.tp2_sold_shares + shares,
            )
        orders = _replace_pending(orders, order, order.remaining_shares - shares)

    residual_active = (
        current.remaining_shares > 0
        and current.tp1_sold_shares >= current.tp1_target_shares
        and current.tp2_sold_shares >= current.tp2_target_shares
    )
    residual = _pending_for(orders, "residual_drawdown")
    residual_threshold = current.peak_adjusted_close * (1.0 - config.residual_drawdown)
    if residual is None and residual_active and prices["low"] <= residual_threshold:
        trigger_price = prices["open"] if prices["open"] <= residual_threshold else residual_threshold
        residual = PendingExit("residual_drawdown", current.remaining_shares, trigger_price, timestamp)
        orders.append(residual)
    if residual is not None and available > 0 and current.remaining_shares > 0:
        base = residual.trigger_adjusted_price if residual.triggered_timestamp == timestamp else prices["open"]
        shares = min(residual.remaining_shares, current.remaining_shares, available)
        fill = _sell_fill(current, shares, "residual_drawdown", base, bar, config)
        fills.append(fill)
        available -= shares
        current = replace(current, remaining_shares=current.remaining_shares - shares)
        orders = _replace_pending(orders, residual, residual.remaining_shares - shares)

    expiry = _pending_for(orders, "expiry")
    if expiry is None and bool(bar.get("is_expiry_close", False)) and current.remaining_shares > 0:
        expiry = PendingExit("expiry", current.remaining_shares, prices["close"], timestamp)
        orders.append(expiry)
    if expiry is not None and available > 0 and current.remaining_shares > 0:
        base = expiry.trigger_adjusted_price if expiry.triggered_timestamp == timestamp else prices["open"]
        reason = "expiry" if expiry.triggered_timestamp == timestamp else "overtime_exit"
        shares = min(expiry.remaining_shares, current.remaining_shares, available)
        fill = _sell_fill(current, shares, reason, base, bar, config)
        fills.append(fill)
        current = replace(current, remaining_shares=current.remaining_shares - shares)
        orders = _replace_pending(orders, expiry, expiry.remaining_shares - shares)

    if current.remaining_shares <= 0:
        orders = []
    peak = max(current.peak_adjusted_close, prices["close"]) if current.remaining_shares > 0 else current.peak_adjusted_close
    return ExitResult(replace(current, peak_adjusted_close=peak), orders, fills, rejections)
