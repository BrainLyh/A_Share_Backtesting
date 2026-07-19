from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd


class TradeEconomicsError(ValueError):
    pass


RECONCILED_COLUMNS = [
    "position_id",
    "code",
    "entry_timestamp",
    "exit_timestamp",
    "status",
    "exit_reason",
    "entry_cost",
    "net_proceeds",
    "net_pnl",
    "net_return",
    "final_remainder",
    "final_market_value",
]

_FILL_NUMERIC_COLUMNS = [
    "shares",
    "raw_price",
    "adjusted_price",
    "gross_notional",
    "commission",
    "stamp_duty",
    "slippage_cost",
    "cash_delta",
]
_TRADE_NUMERIC_COLUMNS = [
    "entry_cost",
    "net_proceeds",
    "net_pnl",
    "net_return",
    "holding_days",
    "maximum_adverse_excursion",
]
_POSITION_NUMERIC_COLUMNS = [
    "remaining_shares",
    "market_value",
    "position_return",
    "position_return_low",
]


def _require_columns(frame: pd.DataFrame, columns: list[str], artifact: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise TradeEconomicsError(f"{artifact} is missing columns: {missing}")


def _finite_numeric(
    frame: pd.DataFrame, columns: list[str], artifact: str
) -> pd.DataFrame:
    result = frame.copy()
    _require_columns(result, columns, artifact)
    for column in columns:
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values).all():
            raise TradeEconomicsError(f"{artifact} has invalid numeric {column}")
        result[column] = values
    return result


def _timestamp_column(
    frame: pd.DataFrame,
    column: str,
    artifact: str,
    *,
    nullable: bool = False,
) -> pd.DataFrame:
    result = frame.copy()
    _require_columns(result, [column], artifact)
    values = pd.to_datetime(result[column], errors="coerce")
    invalid = result[column].notna() & values.isna()
    if invalid.any() or (not nullable and values.isna().any()):
        raise TradeEconomicsError(f"{artifact} has invalid timestamp {column}")
    result[column] = values
    return result


def _normalized_identifier(frame: pd.DataFrame, column: str, artifact: str) -> pd.Series:
    _require_columns(frame, [column], artifact)
    if frame[column].isna().any():
        raise TradeEconomicsError(f"{artifact} has null {column}")
    values = frame[column].astype(str).str.strip()
    if values.eq("").any():
        raise TradeEconomicsError(f"{artifact} has empty {column}")
    return values


def _assert_number(field: str, reported: object, expected: float) -> None:
    try:
        actual = float(reported)
    except (TypeError, ValueError) as error:
        raise TradeEconomicsError(f"trades.csv has invalid {field}") from error
    if not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=1e-10, abs_tol=1e-6
    ):
        raise TradeEconomicsError(
            f"trades.csv {field} mismatch: reported={actual!r}, rebuilt={expected!r}"
        )


def _finite_sum(values: pd.Series, field: str) -> float:
    try:
        total = math.fsum(float(value) for value in values)
    except OverflowError as error:
        raise TradeEconomicsError(f"non-finite rebuilt {field}") from error
    if not math.isfinite(total):
        raise TradeEconomicsError(f"non-finite rebuilt {field}")
    return total


def reconcile_trade_economics(
    fills: pd.DataFrame,
    trades: pd.DataFrame,
    positions: pd.DataFrame,
    final_timestamp: pd.Timestamp,
) -> pd.DataFrame:
    fills = _finite_numeric(fills, _FILL_NUMERIC_COLUMNS, "fills.csv")
    fills = _timestamp_column(fills, "timestamp", "fills.csv")
    trades = _finite_numeric(trades, _TRADE_NUMERIC_COLUMNS, "trades.csv")
    trades = _timestamp_column(trades, "entry_timestamp", "trades.csv")
    trades = _timestamp_column(
        trades, "exit_timestamp", "trades.csv", nullable=True
    )
    positions = _finite_numeric(
        positions, _POSITION_NUMERIC_COLUMNS, "positions.csv"
    )
    positions = _timestamp_column(positions, "timestamp", "positions.csv")

    final_instant = pd.Timestamp(final_timestamp)
    if pd.isna(final_instant):
        raise TradeEconomicsError("final NAV timestamp is invalid")
    fills["position_id"] = _normalized_identifier(
        fills, "position_id", "fills.csv"
    )
    trades["position_id"] = _normalized_identifier(
        trades, "position_id", "trades.csv"
    )
    positions["position_id"] = _normalized_identifier(
        positions, "position_id", "positions.csv"
    )
    for frame, artifact in (
        (fills, "fills.csv"),
        (trades, "trades.csv"),
        (positions, "positions.csv"),
    ):
        frame["code"] = _normalized_identifier(frame, "code", artifact).str.zfill(6)

    if trades["position_id"].duplicated().any():
        raise TradeEconomicsError("trades.csv has duplicate position_id")
    fill_ids = set(fills["position_id"])
    trade_ids = set(trades["position_id"])
    if fill_ids != trade_ids:
        raise TradeEconomicsError("fills and trades position IDs do not reconcile")
    if (fills["timestamp"] > final_instant).any():
        raise TradeEconomicsError("fills.csv contains a fill after final NAV")
    if (positions["timestamp"] > final_instant).any():
        raise TradeEconomicsError("positions.csv contains a snapshot after final NAV")
    if not fills["side"].isin({"buy", "sell"}).all():
        raise TradeEconomicsError("fills.csv has invalid side")
    if (fills["shares"] <= 0).any() or not np.equal(
        fills["shares"], np.floor(fills["shares"])
    ).all():
        raise TradeEconomicsError("fills.csv shares must be positive integers")

    final_positions = positions.loc[positions["timestamp"].eq(final_instant)]
    if final_positions["position_id"].duplicated().any():
        raise TradeEconomicsError("duplicate final position snapshot")
    final_by_id: Mapping[str, pd.Series] = {
        str(row.position_id): pd.Series(row._asdict())
        for row in final_positions.itertuples(index=False)
    }
    unknown_final = set(final_by_id) - trade_ids
    if unknown_final:
        raise TradeEconomicsError(
            f"final positions contain unknown position IDs: {sorted(unknown_final)}"
        )

    records: list[dict[str, object]] = []
    fills = fills.assign(_row_order=np.arange(len(fills)))
    for trade in trades.itertuples(index=False):
        position_id = str(trade.position_id)
        group = fills.loc[fills["position_id"].eq(position_id)].sort_values(
            ["timestamp", "_row_order"]
        )
        buys = group.loc[group["side"].eq("buy")]
        sells = group.loc[group["side"].eq("sell")]
        if len(buys) != 1 or buys.iloc[0]["reason"] != "entry":
            raise TradeEconomicsError(
                f"position {position_id}: expected exactly one entry buy fill"
            )
        buy = buys.iloc[0]
        if group.iloc[0]["side"] != "buy":
            raise TradeEconomicsError(f"position {position_id}: entry fill is not first")
        if group["code"].nunique() != 1 or str(trade.code).zfill(6) != buy["code"]:
            raise TradeEconomicsError(f"position {position_id}: code mismatch")
        if pd.Timestamp(trade.entry_timestamp) != pd.Timestamp(buy["timestamp"]):
            raise TradeEconomicsError(f"position {position_id}: entry_timestamp mismatch")
        if not sells.empty and (sells["timestamp"] < buy["timestamp"]).any():
            raise TradeEconomicsError(f"position {position_id}: sell precedes entry")

        bought = float(buys["shares"].sum())
        sold = float(sells["shares"].sum())
        if sold > bought:
            raise TradeEconomicsError(
                f"position {position_id}: sold shares exceed bought shares"
            )
        final_position = final_by_id.get(position_id)
        final_remainder = (
            float(final_position["remaining_shares"])
            if final_position is not None
            else 0.0
        )
        if not math.isclose(
            bought, sold + final_remainder, rel_tol=0.0, abs_tol=1e-9
        ):
            raise TradeEconomicsError(
                f"position {position_id}: final remainder does not reconcile"
            )
        expected_status = "open" if final_remainder > 0.0 else "closed"
        if trade.status != expected_status:
            raise TradeEconomicsError(f"position {position_id}: status mismatch")
        if final_position is not None and str(final_position["code"]).zfill(6) != buy["code"]:
            raise TradeEconomicsError(f"position {position_id}: final position code mismatch")

        entry_cost = -float(buy["cash_delta"])
        if entry_cost <= 0.0:
            raise TradeEconomicsError(f"position {position_id}: invalid rebuilt entry_cost")
        net_proceeds = _finite_sum(sells["cash_delta"], "net_proceeds")
        final_market_value = (
            float(final_position["market_value"])
            if final_position is not None
            else 0.0
        )
        net_pnl = net_proceeds + final_market_value - entry_cost
        net_return = (net_proceeds + final_market_value) / entry_cost - 1.0
        if not math.isfinite(net_pnl) or not math.isfinite(net_return):
            raise TradeEconomicsError(f"position {position_id}: non-finite rebuilt economics")
        for field, expected in (
            ("entry_cost", entry_cost),
            ("net_proceeds", net_proceeds),
            ("net_pnl", net_pnl),
            ("net_return", net_return),
        ):
            _assert_number(field, getattr(trade, field), expected)

        if expected_status == "open":
            if pd.notna(trade.exit_timestamp):
                raise TradeEconomicsError(f"position {position_id}: exit_timestamp mismatch")
            if trade.exit_reason != "open_at_end":
                raise TradeEconomicsError(f"position {position_id}: exit_reason mismatch")
            exit_timestamp = pd.NaT
            exit_reason = "open_at_end"
        else:
            if sells.empty:
                raise TradeEconomicsError(f"position {position_id}: closed trade has no sell")
            final_sell = sells.sort_values(["timestamp", "_row_order"]).iloc[-1]
            exit_timestamp = pd.Timestamp(final_sell["timestamp"])
            exit_reason = str(final_sell["reason"])
            if pd.Timestamp(trade.exit_timestamp) != exit_timestamp:
                raise TradeEconomicsError(f"position {position_id}: exit_timestamp mismatch")
            if trade.exit_reason != exit_reason:
                raise TradeEconomicsError(f"position {position_id}: exit_reason mismatch")

        records.append(
            {
                "position_id": position_id,
                "code": str(buy["code"]),
                "entry_timestamp": pd.Timestamp(buy["timestamp"]),
                "exit_timestamp": exit_timestamp,
                "status": expected_status,
                "exit_reason": exit_reason,
                "entry_cost": entry_cost,
                "net_proceeds": net_proceeds,
                "net_pnl": net_pnl,
                "net_return": net_return,
                "final_remainder": final_remainder,
                "final_market_value": final_market_value,
            }
        )
    return pd.DataFrame.from_records(records, columns=RECONCILED_COLUMNS)


def reconciled_trade_metrics(trades: pd.DataFrame) -> dict[str, float | int]:
    closed = trades.loc[trades["status"].eq("closed")]
    opened = trades.loc[trades["status"].eq("open")]
    pnl = pd.to_numeric(closed["net_pnl"], errors="coerce")
    if pnl.isna().any() or not np.isfinite(pnl).all():
        raise TradeEconomicsError("reconciled trades contain non-finite net_pnl")
    gains = pnl.loc[pnl > 0.0]
    losses = pnl.loc[pnl < 0.0]
    gross_gain = _finite_sum(gains, "gross gains")
    gross_loss = _finite_sum(losses, "gross losses")
    if not losses.empty:
        profit_factor = gross_gain / abs(gross_loss)
        if not math.isfinite(profit_factor):
            raise TradeEconomicsError("recomputed profit_factor is non-finite with losses")
    elif gross_gain > 0.0:
        profit_factor = float("inf")
    else:
        profit_factor = float("nan")
    return {
        "closed_trade_count": int(len(closed)),
        "open_trade_count": int(len(opened)),
        "win_rate": float((pnl > 0.0).mean()) if not closed.empty else float("nan"),
        "profit_factor": profit_factor,
    }
