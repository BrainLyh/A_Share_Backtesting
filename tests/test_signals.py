import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.signals import build_signal_variants


def baseline_config() -> dict[str, object]:
    return {
        "require_core_pool": False,
        "min_market_cap": 10000000000,
        "j_threshold": 100.0,
        "pit_lookback": 5,
        "volume_multiplier": 1.0,
    }


def rising_mainboard_bars() -> pd.DataFrame:
    rows = []
    for index, date in enumerate(pd.bdate_range("2025-10-01", periods=45)):
        close = 10 + index * 0.1
        rows.append(
            {
                "date": date,
                "code": "600000",
                "name": "示例股票",
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 10000 - index,
                "market_cap": 20000000000,
                "is_st": False,
                "is_suspended": False,
                "in_core_pool": True,
            }
        )
    return pd.DataFrame(rows)


class TestSignalVariants(unittest.TestCase):
    def test_bbi_signal_is_a_legacy_signal_with_uptrend_filter(self):
        result = build_signal_variants(rising_mainboard_bars(), baseline_config())
        self.assertTrue(result["legacy_signal"].any())
        self.assertTrue(result["bbi_signal"].any())
        self.assertTrue(result.loc[result["bbi_signal"], "legacy_signal"].all())

    def test_consecutive_signal_days_become_one_first_trigger(self):
        result = build_signal_variants(rising_mainboard_bars(), baseline_config())
        self.assertGreater(result["legacy_signal"].sum(), 1)
        self.assertEqual(result["legacy_first_trigger"].sum(), 1)

    def test_all_named_variants_have_first_trigger_columns(self):
        result = build_signal_variants(rising_mainboard_bars(), baseline_config())
        self.assertTrue({"legacy_first_trigger", "bbi_first_trigger", "b1_first_trigger"}.issubset(result.columns))


if __name__ == "__main__":
    unittest.main()
