import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.statistics import random_control_test, summarize_by_signal_date


def control_config() -> dict[str, object]:
    return {"event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0, "control_iterations": 5, "random_seed": 7}


def control_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for code, prices, eligible in [("600000", [9.5, 10.0, 11.0, 12.0], True), ("000001", [8.5, 10.0, 10.5, 11.0], True)]:
        for date, price in zip(pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]), prices):
            rows.append({"date": date, "code": code, "open": price, "high": price + 0.5, "low": price - 0.5, "close": price + 0.1, "is_suspended": False, "upper_limit": None, "lower_limit": None, "eligible": eligible})
    events = pd.DataFrame({"event_id": ["strategy"], "code": ["600000"], "variant": ["legacy"], "horizon": [2], "signal_date": pd.to_datetime(["2026-01-02"]), "status": ["filled"], "net_return": [0.2], "max_adverse_excursion": [-0.02]})
    return pd.DataFrame(rows), events


class TestStatistics(unittest.TestCase):
    def test_signal_dates_have_equal_weight(self):
        events = pd.DataFrame(
            {
                "variant": ["legacy", "legacy", "legacy"],
                "horizon": [5, 5, 5],
                "signal_date": pd.to_datetime(["2026-01-02", "2026-01-02", "2026-01-05"]),
                "event_id": ["a", "b", "c"],
                "status": ["filled", "filled", "filled"],
                "net_return": [0.01, 0.03, 0.05],
                "max_adverse_excursion": [-0.02, -0.04, -0.01],
            }
        )
        portfolios = summarize_by_signal_date(events)
        self.assertAlmostEqual(portfolios["portfolio_net_return"].mean(), 0.035)
        self.assertEqual(portfolios["event_count"].tolist(), [2, 1])

    def test_random_control_is_reproducible_and_excludes_signal_code(self):
        signals, events = control_inputs()
        first = random_control_test(signals, events, "legacy", 2, control_config())
        second = random_control_test(signals, events, "legacy", 2, control_config())
        pd.testing.assert_frame_equal(first[0], second[0])
        self.assertEqual(len(first[0]), 5)
        self.assertLess(first[1]["control_mean"], first[1]["observed_mean"])

    def test_empty_control_pool_reports_nan_statistics(self):
        signals, events = control_inputs()
        signals.loc[signals["code"] == "000001", "eligible"] = False
        distribution, summary = random_control_test(signals, events, "legacy", 2, control_config())
        self.assertTrue(distribution.empty)
        self.assertTrue(pd.isna(summary["empirical_p_value"]))


if __name__ == "__main__":
    unittest.main()
