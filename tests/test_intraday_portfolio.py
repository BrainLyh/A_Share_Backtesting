import unittest

import pandas as pd

from a_share_backtesting.intraday_execution import ExecutionConfig
from a_share_backtesting.intraday_portfolio import (
    PortfolioResult,
    cached_scan_candidate_provider,
    run_intraday_portfolio,
    summarize_portfolio,
)


def daily_frame(code: str, dates: list[str], qfq_scales: list[float] | None = None) -> pd.DataFrame:
    scales = qfq_scales or [1.0] * len(dates)
    rows = []
    for date, scale in zip(dates, scales):
        raw = 10.0 if scale == 0.5 else 5.0 if scale == 1.0 and scales[0] == 0.5 else 10.0
        rows.append(
            {
                "date": pd.Timestamp(date),
                "code": code,
                "name": code,
                "open": raw * scale,
                "high": raw * scale * 1.02,
                "low": raw * scale * 0.98,
                "close": raw * scale,
                "raw_open": raw,
                "raw_high": raw * 1.02,
                "raw_low": raw * 0.98,
                "raw_close": raw,
                "preclose": raw,
                "qfq_scale": scale,
                "volume": 1_000_000,
                "market_cap": 0,
                "is_st": False,
                "is_suspended": False,
                "in_core_pool": False,
            }
        )
    return pd.DataFrame(rows)


def minute_frame(code: str, dates: list[str], prices: dict[tuple[str, str], tuple[float, float, float, float]] | None = None) -> pd.DataFrame:
    rows = []
    prices = prices or {}
    for date in dates:
        for time in ["14:40", "14:45", "14:50", "14:55", "15:00"]:
            open_, high, low, close = prices.get((date, time), (10.0, 10.1, 9.9, 10.0))
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"{date} {time}"),
                    "date": pd.Timestamp(date),
                    "time": time,
                    "code": code,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1_000_000,
                    "preclose": 10.0,
                    "qfq_scale": 1.0,
                }
            )
    return pd.DataFrame(rows)


def candidates_for(day_codes: dict[str, list[str]]):
    def provider(date: pd.Timestamp, held_codes: set[str]) -> pd.DataFrame:
        rows = []
        for index, code in enumerate(day_codes.get(f"{date:%Y-%m-%d}", [])):
            if code in held_codes:
                continue
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "scan_time": "14:50",
                    "first_trigger_time": "14:40",
                    "signal_strength": 10.0 - index,
                    "atr14": 0.5,
                    "qfq_scale": 1.0,
                }
            )
        return pd.DataFrame(rows)

    return provider


class PortfolioChronologyTests(unittest.TestCase):
    def test_runtime_rejects_strategy_hard_limit_violations(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_positions"):
            run_intraday_portfolio(
                {}, {}, {}, ExecutionConfig(max_positions=4),
                pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-06"),
            )
        with self.assertRaisesRegex(ValueError, "participation_rate"):
            run_intraday_portfolio(
                {}, {}, {}, ExecutionConfig(participation_rate=0.11),
                pd.Timestamp("2026-07-06"), pd.Timestamp("2026-07-06"),
            )

    def test_cached_scans_reselect_against_current_holdings(self) -> None:
        date = pd.Timestamp("2026-07-06")
        rows = []
        for code, strength in (("600001", 5.0), ("600002", 4.0)):
            for time in ("14:40", "14:45", "14:50"):
                rows.append(
                    {
                        "date": date,
                        "code": code,
                        "scan_time": time,
                        "b1_signal": True,
                        "signal_strength": strength,
                        "atr14": 0.5,
                    }
                )
        daily = {
            code: daily_frame(code, ["2026-07-03", "2026-07-06"])
            for code in ("600001", "600002")
        }

        provider = cached_scan_candidate_provider(
            pd.DataFrame(rows),
            daily,
            {
                "min_market_cap": 0,
                "require_core_pool": False,
                "j_threshold": 15.0,
                "volume_multiplier": 1.0,
            },
        )

        selected = provider(date, {"600001"})
        self.assertEqual(selected["code"].tolist(), ["600002"])

    def test_maximum_three_positions_uses_one_nav_snapshot_and_no_entry_day_sale(self) -> None:
        codes = ["600001", "600002", "600003", "600004"]
        dates = ["2026-07-06"]
        result = run_intraday_portfolio(
            {code: daily_frame(code, dates) for code in codes},
            {code: minute_frame(code, dates, {(dates[0], "15:00"): (10.0, 12.5, 8.0, 10.0)}) for code in codes},
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[0]),
            candidate_provider=candidates_for({dates[0]: codes}),
        )

        buys = result.fills.loc[result.fills["side"].eq("buy")]
        self.assertEqual(buys["code"].tolist(), codes[:3])
        self.assertEqual(len(result.open_positions), 3)
        self.assertFalse(result.fills["side"].eq("sell").any())
        self.assertIn("capacity", set(result.rejections["reason"]))
        self.assertLess((buys["gross_notional"].max() - buys["gross_notional"].min()), 1.0)

    def test_exit_before_1455_entry_releases_slot_and_cash(self) -> None:
        codes = ["600001", "600002", "600003", "600004"]
        dates = ["2026-07-06", "2026-07-07"]
        minutes = {code: minute_frame(code, dates) for code in codes}
        stop_prices = {(dates[1], "14:55"): (9.0, 9.1, 8.8, 9.0)}
        minutes["600001"] = minute_frame("600001", dates, stop_prices)
        result = run_intraday_portfolio(
            {code: daily_frame(code, dates) for code in codes},
            minutes,
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[1]),
            candidate_provider=candidates_for({dates[0]: codes[:3], dates[1]: [codes[3]]}),
        )

        at_1455 = result.fills.loc[result.fills["timestamp"].eq(pd.Timestamp("2026-07-07 14:55"))]
        self.assertEqual(at_1455["side"].tolist(), ["sell", "buy"])
        self.assertEqual(set(result.open_positions), {"600002", "600003", "600004"})

    def test_same_day_exit_cannot_reenter_before_a_completed_false_day(self) -> None:
        code = "600001"
        dates = ["2026-07-06", "2026-07-07"]
        prices = {(dates[1], "14:55"): (9.0, 9.1, 8.8, 9.0)}

        result = run_intraday_portfolio(
            {code: daily_frame(code, dates)},
            {code: minute_frame(code, dates, prices)},
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[1]),
            candidate_provider=candidates_for({dates[0]: [code], dates[1]: [code]}),
        )

        buys = result.fills.loc[result.fills["side"].eq("buy")]
        self.assertEqual(len(buys), 1)
        self.assertIn("rearm_required", set(result.rejections["reason"]))

    def test_missing_expiry_day_bar_exits_at_next_executable_open(self) -> None:
        code = "600001"
        calendar_code = "600002"
        dates = ["2026-07-06", "2026-07-07", "2026-07-08"]
        traded_minutes = minute_frame(code, [dates[0], dates[2]])
        calendar_minutes = minute_frame(calendar_code, dates)

        result = run_intraday_portfolio(
            {
                code: daily_frame(code, dates),
                calendar_code: daily_frame(calendar_code, dates),
            },
            {code: traded_minutes, calendar_code: calendar_minutes},
            {},
            ExecutionConfig(horizon_days=1),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[-1]),
            candidate_provider=candidates_for({dates[0]: [code]}),
        )

        sells = result.fills.loc[result.fills["side"].eq("sell")]
        self.assertEqual(sells["reason"].tolist(), ["overtime_exit"])
        self.assertEqual(sells.iloc[0]["timestamp"], pd.Timestamp("2026-07-08 14:40"))

    def test_qfq_scale_keeps_marked_value_continuous(self) -> None:
        code = "600001"
        dates = ["2026-07-06", "2026-07-07"]
        minutes = minute_frame(code, dates)
        minutes.loc[minutes["date"].eq(pd.Timestamp(dates[0])), "qfq_scale"] = 0.5
        minutes.loc[minutes["date"].eq(pd.Timestamp(dates[1])), ["open", "high", "low", "close"]] /= 2.0
        result = run_intraday_portfolio(
            {code: daily_frame(code, dates, [0.5, 1.0])},
            {code: minutes},
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[1]),
            candidate_provider=candidates_for({dates[0]: [code]}),
        )

        day_nav = result.nav_daily.set_index("date")["nav"]
        self.assertAlmostEqual(day_nav.loc[pd.Timestamp(dates[0])], day_nav.loc[pd.Timestamp(dates[1])], places=6)

    def test_trade_mae_uses_five_minute_low_not_close(self) -> None:
        code = "600001"
        dates = ["2026-07-06", "2026-07-07"]
        prices = {(dates[1], "14:40"): (10.0, 10.1, 9.5, 10.0)}

        result = run_intraday_portfolio(
            {code: daily_frame(code, dates)},
            {code: minute_frame(code, dates, prices)},
            {},
            ExecutionConfig(horizon_days=1),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[1]),
            candidate_provider=candidates_for({dates[0]: [code]}),
        )

        self.assertLess(result.trades.iloc[0]["maximum_adverse_excursion"], -0.05)
        self.assertGreater(result.trades.iloc[0]["maximum_adverse_excursion"], -0.06)


class PortfolioMetricTests(unittest.TestCase):
    def test_empty_summary_has_stable_portfolio_schema(self) -> None:
        empty, _ = summarize_portfolio(PortfolioResult.empty(), initial_cash=100.0)
        expected = {
            "initial_cash", "final_nav", "total_net_return", "max_drawdown_5m",
            "max_drawdown_low", "max_drawdown_daily", "average_exposure",
            "max_exposure", "capital_utilization", "max_positions", "turnover",
            "commission", "stamp_duty", "slippage_cost",
        }

        self.assertEqual(set(empty.columns), expected)
        self.assertEqual(empty.loc[0, "final_nav"], 100.0)
        self.assertEqual(empty.loc[0, "total_net_return"], 0.0)

    def test_summaries_use_account_nav_and_closed_net_trades(self) -> None:
        nav_5m = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-07-01 14:55", "2026-07-02 14:55", "2026-07-03 14:55"]),
                "date": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
                "nav": [100.0, 110.0, 88.0],
                "nav_low": [100.0, 100.0, 80.0],
                "cash": [100.0, 100.0, 88.0],
                "gross_exposure": [50.0, 55.0, 44.0],
                "positions": [0, 0, 0],
            }
        )
        trades = pd.DataFrame(
            [
                {"position_id": "a", "entry_timestamp": "2026-07-01", "status": "closed", "exit_reason": "expiry", "net_pnl": 10.0, "net_return": 0.10, "holding_days": 2, "maximum_adverse_excursion": -0.03},
                {"position_id": "b", "entry_timestamp": "2026-07-02", "status": "closed", "exit_reason": "stop_loss", "net_pnl": -5.0, "net_return": -0.05, "holding_days": 3, "maximum_adverse_excursion": -0.08},
                {"position_id": "c", "entry_timestamp": "2026-07-03", "status": "closed", "exit_reason": "stop_loss", "net_pnl": -2.0, "net_return": -0.02, "holding_days": 1, "maximum_adverse_excursion": -0.04},
                {"position_id": "d", "entry_timestamp": "2026-07-04", "status": "open", "exit_reason": "open_at_end", "net_pnl": 20.0, "net_return": 0.20, "holding_days": 1, "maximum_adverse_excursion": -0.01},
            ]
        )
        result = PortfolioResult.empty()
        result.nav_5m = nav_5m
        result.nav_daily = nav_5m.groupby("date", as_index=False).tail(1).reset_index(drop=True)
        result.trades = trades
        result.fills = pd.DataFrame(
            [
                {"position_id": "a", "side": "buy", "reason": "entry", "gross_notional": 50.0, "commission": 1.0, "stamp_duty": 0.0, "slippage_cost": 0.5},
                {"position_id": "a", "side": "sell", "reason": "take_profit_10", "gross_notional": 20.0, "commission": 1.0, "stamp_duty": 0.1, "slippage_cost": 0.1},
            ]
        )

        portfolio, trade = summarize_portfolio(result, initial_cash=100.0)

        self.assertAlmostEqual(portfolio.loc[0, "total_net_return"], -0.12)
        self.assertAlmostEqual(portfolio.loc[0, "max_drawdown_5m"], -0.20)
        self.assertAlmostEqual(portfolio.loc[0, "max_drawdown_low"], 80.0 / 110.0 - 1.0)
        self.assertAlmostEqual(portfolio.loc[0, "max_drawdown_daily"], -0.20)
        self.assertAlmostEqual(portfolio.loc[0, "average_exposure"], 0.5)
        self.assertAlmostEqual(portfolio.loc[0, "capital_utilization"], 149.0 / 300.0)
        self.assertEqual(trade.loc[0, "closed_trade_count"], 3)
        self.assertAlmostEqual(trade.loc[0, "win_rate"], 1.0 / 3.0)
        self.assertAlmostEqual(trade.loc[0, "profit_factor"], 10.0 / 7.0)
        self.assertAlmostEqual(trade.loc[0, "payoff_ratio"], 10.0 / 3.5)
        self.assertEqual(trade.loc[0, "maximum_consecutive_losses"], 2)
        self.assertAlmostEqual(trade.loc[0, "take_profit_trade_rate"], 1.0 / 3.0)
        self.assertAlmostEqual(trade.loc[0, "stop_exit_rate"], 2.0 / 3.0)
        self.assertAlmostEqual(trade.loc[0, "mean_maximum_adverse_excursion"], -0.05)
        self.assertAlmostEqual(trade.loc[0, "worst_maximum_adverse_excursion"], -0.08)


if __name__ == "__main__":
    unittest.main()
