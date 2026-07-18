import unittest

import pandas as pd

from a_share_backtesting.intraday_execution import (
    ExecutionConfig,
    commission,
    entry_fill,
    is_one_price_limit,
    process_exit_bar,
)


def candidate(atr14: float = 0.5) -> dict[str, object]:
    return {
        "date": pd.Timestamp("2026-07-06"),
        "code": "600001",
        "atr14": atr14,
        "qfq_scale": 1.0,
    }


def bar(
    timestamp: str,
    open_: float = 10.0,
    high: float = 10.2,
    low: float = 9.8,
    close: float = 10.0,
    volume: int = 1_000_000,
    preclose: float = 10.0,
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "timestamp": pd.Timestamp(timestamp),
        "date": pd.Timestamp(timestamp).normalize(),
        "code": "600001",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "preclose": preclose,
        "qfq_scale": 1.0,
    }
    row.update(extra)
    return row


def opened_position(nav: float = 300_000.0, volume: int = 1_000_000):
    result = entry_fill(candidate(), bar("2026-07-06 14:55", volume=volume), nav, nav, ExecutionConfig())
    if result.position is None:
        raise AssertionError(result.rejection)
    return result.position


class EntryExecutionTests(unittest.TestCase):
    def test_commission_uses_rate_and_minimum(self) -> None:
        config = ExecutionConfig()
        self.assertEqual(commission(1_000, config), 5.0)
        self.assertEqual(commission(100_000, config), 30.0)

    def test_entry_targets_one_third_nav_with_lots_slippage_and_fees(self) -> None:
        result = entry_fill(candidate(), bar("2026-07-06 14:55"), 1_000_000.0, 1_000_000.0, ExecutionConfig())

        self.assertIsNone(result.rejection)
        self.assertEqual(result.fill.shares, 33_300)
        self.assertAlmostEqual(result.fill.raw_price, 10.005)
        self.assertAlmostEqual(result.fill.commission, round(result.fill.gross_notional * 0.0003, 2))
        self.assertAlmostEqual(result.fill.stamp_duty, 0.0)
        self.assertAlmostEqual(result.fill.cash_delta, -(result.fill.gross_notional + result.fill.commission))
        self.assertEqual(result.position.remaining_shares, 33_300)
        self.assertEqual(result.position.tp1_target_shares, 11_100)
        self.assertEqual(result.position.tp2_target_shares, 11_100)

    def test_entry_honors_volume_cap_and_available_cash(self) -> None:
        limited = entry_fill(candidate(), bar("2026-07-06 14:55", volume=5_000), 1_000_000.0, 1_000_000.0, ExecutionConfig())
        self.assertEqual(limited.fill.shares, 500)

        cash_limited = entry_fill(candidate(), bar("2026-07-06 14:55"), 1_000_000.0, 10_000.0, ExecutionConfig())
        self.assertEqual(cash_limited.fill.shares, 900)
        self.assertGreaterEqual(10_000.0 + cash_limited.fill.cash_delta, 0.0)

        no_lot = entry_fill(candidate(), bar("2026-07-06 14:55", volume=999), 1_000_000.0, 1_000_000.0, ExecutionConfig())
        self.assertEqual(no_lot.rejection, "volume_cap_below_one_lot")

    def test_one_price_upper_limit_blocks_entry(self) -> None:
        locked = bar("2026-07-06 14:55", open_=11.0, high=11.0, low=11.0, close=11.0, preclose=10.0)
        self.assertTrue(is_one_price_limit(locked, "buy"))

        result = entry_fill(candidate(), locked, 1_000_000.0, 1_000_000.0, ExecutionConfig())

        self.assertEqual(result.rejection, "upper_limit_lock")
        self.assertIsNone(result.fill)


class ExitExecutionTests(unittest.TestCase):
    def test_t_plus_one_blocks_entry_day_exit(self) -> None:
        position = opened_position()
        result = process_exit_bar(position, [], bar("2026-07-06 15:00", high=12.5, low=8.0), ExecutionConfig())

        self.assertEqual(result.fills, [])
        self.assertEqual(result.position.remaining_shares, position.remaining_shares)

    def test_gap_stop_fills_at_open_and_stop_wins_conflict(self) -> None:
        position = opened_position()
        result = process_exit_bar(
            position,
            [],
            bar("2026-07-07 09:35", open_=9.0, high=12.5, low=8.9, close=11.0),
            ExecutionConfig(),
        )

        self.assertEqual([fill.reason for fill in result.fills], ["stop_loss"])
        self.assertAlmostEqual(result.fills[0].raw_price, 9.0 * 0.9995)
        self.assertEqual(result.position.remaining_shares, 0)
        self.assertGreater(result.fills[0].stamp_duty, 0.0)

    def test_gap_above_both_profit_levels_sells_two_slices_at_open(self) -> None:
        position = opened_position()
        result = process_exit_bar(
            position,
            [],
            bar("2026-07-07 09:35", open_=12.5, high=12.6, low=10.0, close=12.0),
            ExecutionConfig(),
        )

        self.assertEqual([fill.reason for fill in result.fills], ["take_profit_10", "take_profit_20"])
        self.assertTrue(all(abs(fill.raw_price - 12.5 * 0.9995) < 1e-9 for fill in result.fills))
        self.assertEqual(result.position.remaining_shares, position.original_shares - position.tp1_target_shares - position.tp2_target_shares)

    def test_partial_take_profit_persists_and_uses_next_open(self) -> None:
        position = opened_position()
        first = process_exit_bar(
            position,
            [],
            bar("2026-07-07 10:00", open_=10.5, high=11.2, low=10.4, close=10.8, volume=10_000),
            ExecutionConfig(),
        )
        self.assertEqual(first.fills[0].shares, 1_000)
        self.assertEqual(first.pending[0].reason, "take_profit_10")

        second = process_exit_bar(
            first.position,
            first.pending,
            bar("2026-07-07 10:05", open_=10.7, high=10.8, low=10.6, close=10.7, volume=10_000),
            ExecutionConfig(),
        )

        self.assertEqual(second.fills[0].reason, "take_profit_10")
        self.assertAlmostEqual(second.fills[0].raw_price, 10.7 * 0.9995)

    def test_lower_limit_lock_preserves_stop_order(self) -> None:
        position = opened_position()
        locked = bar("2026-07-07 09:35", open_=9.0, high=9.0, low=9.0, close=9.0, preclose=10.0)
        self.assertTrue(is_one_price_limit(locked, "sell"))

        result = process_exit_bar(position, [], locked, ExecutionConfig())

        self.assertEqual(result.fills, [])
        self.assertEqual(result.pending[0].reason, "stop_loss")
        self.assertEqual(result.rejections, ["lower_limit_lock"])

    def test_residual_drawdown_uses_only_prior_completed_close_peak(self) -> None:
        position = opened_position()
        first = process_exit_bar(
            position,
            [],
            bar("2026-07-07 10:00", open_=10.5, high=12.2, low=10.1, close=12.0),
            ExecutionConfig(),
        )
        self.assertEqual([fill.reason for fill in first.fills], ["take_profit_10", "take_profit_20"])
        self.assertGreater(first.position.remaining_shares, 0)
        self.assertAlmostEqual(first.position.peak_adjusted_close, 12.0)

        second = process_exit_bar(
            first.position,
            first.pending,
            bar("2026-07-07 10:05", open_=11.0, high=11.1, low=10.1, close=10.5),
            ExecutionConfig(),
        )

        self.assertEqual([fill.reason for fill in second.fills], ["residual_drawdown"])
        self.assertAlmostEqual(second.fills[0].adjusted_price, 12.0 * 0.85 * 0.9995)

    def test_expiry_partial_fill_becomes_overtime_on_next_bar(self) -> None:
        position = opened_position()
        expiry = process_exit_bar(
            position,
            [],
            bar("2026-07-13 15:00", volume=10_000, is_expiry_close=True),
            ExecutionConfig(),
        )
        self.assertEqual(expiry.fills[0].reason, "expiry")
        self.assertTrue(expiry.pending)

        overtime = process_exit_bar(
            expiry.position,
            expiry.pending,
            bar("2026-07-14 09:35", volume=10_000),
            ExecutionConfig(),
        )
        self.assertEqual(overtime.fills[0].reason, "overtime_exit")


if __name__ == "__main__":
    unittest.main()
