import unittest

import pandas as pd

from a_share_backtesting.intraday_signals import (
    build_provisional_daily_bar,
    scan_intraday_b1,
    select_scheme_a_candidates,
)


def minute_day() -> pd.DataFrame:
    rows = []
    for index, time in enumerate(["14:35", "14:40", "14:45", "14:50", "14:55"]):
        close = 10.0 + index
        rows.append(
            {
                "timestamp": pd.Timestamp(f"2026-07-17 {time}"),
                "date": pd.Timestamp("2026-07-17"),
                "time": time,
                "code": "600001",
                "open": close - 0.2,
                "high": close + 0.3,
                "low": close - 0.4,
                "close": close,
                "volume": 1000 * (index + 1),
            }
        )
    return pd.DataFrame(rows)


def daily_history(periods: int = 40) -> pd.DataFrame:
    rows = []
    for index, date in enumerate(pd.bdate_range("2026-05-20", periods=periods)):
        close = 10.0 + index * 0.02
        rows.append(
            {
                "date": date,
                "code": "600001",
                "name": "600001",
                "open": close - 0.05,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": 10_000,
                "market_cap": 0,
                "is_st": False,
                "is_suspended": False,
                "in_core_pool": False,
            }
        )
    return pd.DataFrame(rows)


def signal_config() -> dict[str, object]:
    return {
        "stock_pool_codes": ["600001"],
        "min_market_cap": 0,
        "require_core_pool": False,
        "j_threshold": 15.0,
        "volume_multiplier": 1.0,
    }


class IntradaySignalTests(unittest.TestCase):
    def test_provisional_bar_does_not_use_future_bars(self) -> None:
        bar = build_provisional_daily_bar(minute_day(), "14:40", qfq_scale=0.5)

        self.assertAlmostEqual(bar["open"], 4.9)
        self.assertAlmostEqual(bar["high"], 5.65)
        self.assertAlmostEqual(bar["low"], 4.8)
        self.assertAlmostEqual(bar["close"], 5.5)
        self.assertEqual(bar["volume"], 3000)
        self.assertEqual(bar["date"], pd.Timestamp("2026-07-17"))
        self.assertEqual(bar["code"], "600001")

    def test_scan_uses_completed_volume_at_each_timestamp(self) -> None:
        scans = scan_intraday_b1(daily_history(), minute_day(), signal_config(), qfq_scale=1.0)

        self.assertEqual(scans["scan_time"].tolist(), ["14:40", "14:45", "14:50"])
        self.assertEqual(scans["volume"].tolist(), [3000, 6000, 10000])
        self.assertTrue({"b1_signal", "signal_strength", "atr14", "j", "bbi", "dif"}.issubset(scans.columns))

    def test_scheme_a_requires_final_confirmation_and_prior_day_false(self) -> None:
        scans = pd.DataFrame(
            [
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:40", "b1_signal": True, "signal_strength": 1.0},
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:45", "b1_signal": False, "signal_strength": 2.0},
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:50", "b1_signal": True, "signal_strength": 3.0},
                {"date": "2026-07-17", "code": "600002", "scan_time": "14:40", "b1_signal": True, "signal_strength": 5.0},
                {"date": "2026-07-17", "code": "600002", "scan_time": "14:50", "b1_signal": False, "signal_strength": 6.0},
                {"date": "2026-07-17", "code": "600003", "scan_time": "14:45", "b1_signal": True, "signal_strength": 7.0},
                {"date": "2026-07-17", "code": "600003", "scan_time": "14:50", "b1_signal": True, "signal_strength": 8.0},
            ]
        )

        selected = select_scheme_a_candidates(scans, {"600001": False, "600002": False, "600003": True}, set())

        self.assertEqual(selected["code"].tolist(), ["600001"])
        self.assertEqual(selected.loc[0, "first_trigger_time"], "14:40")

    def test_scheme_a_excludes_held_codes_and_sorts_deterministically(self) -> None:
        scans = pd.DataFrame(
            [
                {"date": "2026-07-17", "code": "600003", "scan_time": "14:40", "b1_signal": True, "signal_strength": 1.0},
                {"date": "2026-07-17", "code": "600003", "scan_time": "14:50", "b1_signal": True, "signal_strength": 9.0},
                {"date": "2026-07-17", "code": "600002", "scan_time": "14:45", "b1_signal": True, "signal_strength": 2.0},
                {"date": "2026-07-17", "code": "600002", "scan_time": "14:50", "b1_signal": True, "signal_strength": 8.0},
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:45", "b1_signal": True, "signal_strength": 2.0},
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:50", "b1_signal": True, "signal_strength": 8.0},
                {"date": "2026-07-17", "code": "600004", "scan_time": "14:45", "b1_signal": True, "signal_strength": 4.0},
                {"date": "2026-07-17", "code": "600004", "scan_time": "14:50", "b1_signal": True, "signal_strength": 10.0},
            ]
        )

        selected = select_scheme_a_candidates(
            scans,
            {code: False for code in ["600001", "600002", "600003", "600004"]},
            {"600004"},
        )

        self.assertEqual(selected["code"].tolist(), ["600003", "600001", "600002"])

    def test_scheme_a_rejects_missing_prior_day_state(self) -> None:
        scans = pd.DataFrame(
            [
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:40", "b1_signal": True, "signal_strength": 1.0},
                {"date": "2026-07-17", "code": "600001", "scan_time": "14:50", "b1_signal": True, "signal_strength": 2.0},
            ]
        )

        selected = select_scheme_a_candidates(scans, {}, set())

        self.assertTrue(selected.empty)
        self.assertEqual(selected.attrs["rejections"][0]["reason"], "missing_prior_day_state")


if __name__ == "__main__":
    unittest.main()
