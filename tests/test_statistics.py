import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.statistics import summarize_by_signal_date


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


if __name__ == "__main__":
    unittest.main()
