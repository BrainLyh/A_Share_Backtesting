import unittest

import pandas as pd

from a_share_backtesting.intraday_execution import ExecutionConfig
from a_share_backtesting.market_regime import build_market_regime_schedule
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


def minute_frame(
    code: str,
    dates: list[str],
    prices: dict[tuple[str, str], tuple[float, float, float, float]] | None = None,
    times: list[str] | None = None,
) -> pd.DataFrame:
    rows = []
    prices = prices or {}
    times = times or ["14:40", "14:45", "14:50", "14:55", "15:00"]
    for date in dates:
        for time in times:
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
    def test_same_day_regime_liquidates_before_ordinary_exits_and_rejects_candidates(self) -> None:
        held_code = "600001"
        risk_off_codes = ["600002", "600003"]
        dates = ["2026-06-15", "2026-07-02"]
        codes = [held_code, *risk_off_codes]
        prices = {
            (dates[1], "14:55"): (8.5, 12.5, 8.0, 10.3),
        }
        schedule = build_market_regime_schedule(
            {
                "observation_start": dates[0],
                "initial_state": "risk_off",
                "execution_mode": "same_day_1455",
                "events": [
                    {"signal_date": dates[0], "event": "up", "label": "activation"},
                    {"signal_date": dates[1], "event": "down", "label": "risk_off"},
                ],
            },
            pd.to_datetime(dates),
        )

        result = run_intraday_portfolio(
            {code: daily_frame(code, dates) for code in codes},
            {
                code: minute_frame(code, dates, prices if code == held_code else None)
                for code in codes
            },
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[-1]),
            candidate_provider=candidates_for(
                {dates[0]: [held_code], dates[1]: risk_off_codes}
            ),
            market_regime=schedule,
        )

        sells = result.fills.loc[result.fills["side"].eq("sell")]
        self.assertEqual(sells["reason"].tolist(), ["market_regime_exit"])
        self.assertEqual(sells.iloc[0]["timestamp"], pd.Timestamp("2026-07-02 14:55"))
        self.assertAlmostEqual(sells.iloc[0]["adjusted_price"], 10.3 * 0.9995)
        self.assertEqual(
            result.candidates.loc[result.candidates["date"].eq(pd.Timestamp(dates[1])), "code"].tolist(),
            risk_off_codes,
        )
        risk_off_rejections = result.rejections.loc[
            result.rejections["reason"].eq("market_regime_off")
        ]
        self.assertEqual(risk_off_rejections["code"].tolist(), risk_off_codes)
        self.assertFalse(
            result.fills.loc[result.fills["timestamp"].eq(pd.Timestamp("2026-07-02 14:55")), "side"]
            .eq("buy")
            .any()
        )
        pd.testing.assert_frame_equal(result.market_regime, schedule.timeline)

    def test_next_session_regime_uses_open_after_allowing_signal_day_entry(self) -> None:
        held_code, blocked_code = "600001", "600002"
        dates = ["2026-07-02", "2026-07-03"]
        times = ["09:35", "14:40", "14:45", "14:50", "14:55", "15:00"]
        prices = {(dates[1], "09:35"): (9.4, 10.8, 9.0, 10.6)}
        schedule = build_market_regime_schedule(
            {
                "observation_start": dates[0],
                "initial_state": "risk_on",
                "execution_mode": "next_session_0935",
                "events": [
                    {"signal_date": dates[0], "event": "down", "label": "risk_off"},
                ],
            },
            pd.to_datetime(dates),
        )

        result = run_intraday_portfolio(
            {code: daily_frame(code, dates) for code in (held_code, blocked_code)},
            {
                held_code: minute_frame(held_code, dates, prices, times),
                blocked_code: minute_frame(blocked_code, dates, times=times),
            },
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[-1]),
            candidate_provider=candidates_for(
                {dates[0]: [held_code], dates[1]: [blocked_code]}
            ),
            market_regime=schedule,
        )

        buys = result.fills.loc[result.fills["side"].eq("buy")]
        self.assertEqual(buys["code"].tolist(), [held_code])
        sell = result.fills.loc[result.fills["side"].eq("sell")].iloc[0]
        self.assertEqual(sell["timestamp"], pd.Timestamp("2026-07-03 09:35"))
        self.assertEqual(sell["reason"], "market_regime_exit")
        self.assertAlmostEqual(sell["adjusted_price"], 9.4 * 0.9995)
        self.assertIn(blocked_code, result.candidates["code"].tolist())
        self.assertIn("market_regime_off", set(result.rejections["reason"]))

    def test_regime_remainder_survives_repeated_down_and_up_before_entries_resume(self) -> None:
        held_code, candidate_code = "600001", "600002"
        dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]
        prices = {(dates[2], "14:55"): (9.4, 11.0, 9.0, 10.6)}
        held_minutes = minute_frame(held_code, dates, prices)
        low_volume = (
            (held_minutes["date"].eq(pd.Timestamp(dates[1])) & held_minutes["time"].isin(["14:55", "15:00"]))
            | held_minutes["date"].eq(pd.Timestamp(dates[2]))
            | (held_minutes["date"].eq(pd.Timestamp(dates[3])) & held_minutes["time"].ne("15:00"))
        )
        held_minutes.loc[low_volume, "volume"] = 1_000
        schedule = build_market_regime_schedule(
            {
                "observation_start": dates[0],
                "initial_state": "risk_on",
                "execution_mode": "same_day_1455",
                "events": [
                    {"signal_date": dates[1], "event": "down", "label": "risk_off"},
                    {"signal_date": dates[2], "event": "down", "label": "risk_off_confirmation"},
                    {"signal_date": dates[3], "event": "up", "label": "risk_on"},
                ],
            },
            pd.to_datetime(dates),
        )

        result = run_intraday_portfolio(
            {
                held_code: daily_frame(held_code, dates),
                candidate_code: daily_frame(candidate_code, dates),
            },
            {
                held_code: held_minutes,
                candidate_code: minute_frame(candidate_code, dates),
            },
            {},
            ExecutionConfig(),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[-1]),
            candidate_provider=candidates_for(
                {
                    dates[0]: [held_code],
                    dates[3]: [candidate_code],
                    dates[4]: [candidate_code],
                }
            ),
            market_regime=schedule,
        )

        repeated_down_fill = result.fills.loc[
            result.fills["timestamp"].eq(pd.Timestamp("2026-07-03 14:55"))
            & result.fills["side"].eq("sell")
        ].iloc[0]
        self.assertEqual(repeated_down_fill["reason"], "market_regime_exit")
        self.assertAlmostEqual(repeated_down_fill["adjusted_price"], 9.4 * 0.9995)
        candidate_buys = result.fills.loc[
            result.fills["side"].eq("buy") & result.fills["code"].eq(candidate_code)
        ]
        self.assertEqual(candidate_buys["timestamp"].tolist(), [pd.Timestamp("2026-07-05 14:55")])
        up_day_rejection = result.rejections.loc[
            result.rejections["timestamp"].eq(pd.Timestamp("2026-07-04 14:55"))
            & result.rejections["code"].eq(candidate_code)
        ]
        self.assertEqual(up_day_rejection["reason"].tolist(), ["market_regime_off"])

    def test_repeated_up_confirmation_preserves_position_and_pending_exit_state(self) -> None:
        code = "600001"
        dates = ["2026-07-06", "2026-07-07"]
        prices = {
            (dates[1], "14:50"): (10.0, 11.2, 9.9, 10.6),
            (dates[1], "14:55"): (10.4, 10.9, 10.3, 10.8),
        }
        minutes = minute_frame(code, dates, prices)
        minutes.loc[
            minutes["timestamp"].isin(
                [pd.Timestamp("2026-07-07 14:50"), pd.Timestamp("2026-07-07 14:55")]
            ),
            "volume",
        ] = 1_000
        schedule = build_market_regime_schedule(
            {
                "observation_start": dates[0],
                "initial_state": "risk_on",
                "execution_mode": "same_day_1455",
                "events": [
                    {"signal_date": dates[0], "event": "up", "label": "activation"},
                    {"signal_date": dates[1], "event": "up", "label": "confirmation"},
                ],
            },
            pd.to_datetime(dates),
        )

        result = run_intraday_portfolio(
            {code: daily_frame(code, dates)},
            {code: minutes},
            {},
            ExecutionConfig(horizon_days=5),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[-1]),
            candidate_provider=candidates_for({dates[0]: [code]}),
            market_regime=schedule,
        )

        buy = result.fills.loc[result.fills["side"].eq("buy")].iloc[0]
        position = result.open_positions[code]
        self.assertEqual(position.position_id, buy["position_id"])
        self.assertEqual(position.entry_timestamp, pd.Timestamp("2026-07-06 14:55"))
        self.assertAlmostEqual(position.peak_adjusted_close, 10.8)
        self.assertEqual(
            result.fills.loc[
                result.fills["timestamp"].eq(pd.Timestamp("2026-07-07 14:55")), "reason"
            ].tolist(),
            ["take_profit_10"],
        )

    def test_repeated_up_confirmation_preserves_expiry_and_holding_days(self) -> None:
        code = "600001"
        dates = ["2026-07-06", "2026-07-07", "2026-07-08"]
        schedule = build_market_regime_schedule(
            {
                "observation_start": dates[0],
                "initial_state": "risk_on",
                "execution_mode": "same_day_1455",
                "events": [
                    {"signal_date": dates[1], "event": "up", "label": "confirmation"},
                ],
            },
            pd.to_datetime(dates),
        )

        result = run_intraday_portfolio(
            {code: daily_frame(code, dates)},
            {code: minute_frame(code, dates)},
            {},
            ExecutionConfig(horizon_days=2),
            pd.Timestamp(dates[0]),
            pd.Timestamp(dates[-1]),
            candidate_provider=candidates_for({dates[0]: [code]}),
            market_regime=schedule,
        )

        trade = result.trades.iloc[0]
        self.assertEqual(trade["exit_timestamp"], pd.Timestamp("2026-07-08 15:00"))
        self.assertEqual(trade["exit_reason"], "expiry")
        self.assertEqual(trade["holding_days"], 2)

    def test_none_market_regime_preserves_all_legacy_frames_and_state(self) -> None:
        frame_names = [
            "scans", "candidates", "orders", "fills", "positions", "trades",
            "nav_5m", "nav_daily", "rejections", "data_audit",
        ]
        fixtures = [
            (["2026-07-06"], ExecutionConfig(horizon_days=5)),
            (["2026-07-06", "2026-07-07"], ExecutionConfig(horizon_days=1)),
        ]
        for dates, config in fixtures:
            with self.subTest(dates=dates):
                code = "600001"
                args = (
                    {code: daily_frame(code, dates)},
                    {code: minute_frame(code, dates)},
                    {},
                    config,
                    pd.Timestamp(dates[0]),
                    pd.Timestamp(dates[-1]),
                )
                provider = candidates_for({dates[0]: [code]})
                omitted = run_intraday_portfolio(*args, candidate_provider=provider)
                explicit_none = run_intraday_portfolio(
                    *args, candidate_provider=provider, market_regime=None
                )

                for frame_name in frame_names:
                    pd.testing.assert_frame_equal(
                        getattr(omitted, frame_name), getattr(explicit_none, frame_name)
                    )
                self.assertEqual(omitted.open_positions, explicit_none.open_positions)
                self.assertTrue(omitted.market_regime.empty)
                self.assertTrue(explicit_none.market_regime.empty)

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
