import sys
import unittest
from unittest.mock import patch
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


def prepared_indicator_bars(j_values: list[float], bbi_values: list[float] | None = None) -> pd.DataFrame:
    rows = []
    if bbi_values is None:
        bbi_values = [9.8 + index * 0.05 for index in range(len(j_values))]
    for index, (date, j, bbi) in enumerate(zip(pd.bdate_range("2026-01-01", periods=len(j_values)), j_values, bbi_values)):
        rows.append(
            {
                "date": date,
                "code": "600001",
                "name": "600001",
                "open": 10.0 + index * 0.1,
                "high": 10.5 + index * 0.1,
                "low": 9.8 + index * 0.1,
                "close": 10.2 + index * 0.1,
                "volume": 2000 + index * 100,
                "market_cap": 20000000000,
                "is_st": False,
                "is_suspended": False,
                "in_core_pool": True,
                "rsv": 50.0,
                "k": 50.0,
                "d": 45.0,
                "j": j,
                "dif": 1.0,
                "dea": 0.5,
                "bbi": bbi,
                "volume_ma": 1000.0,
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

    def test_b1_requires_immediate_prior_j_below_threshold(self):
        bars = prepared_indicator_bars([10.0, 80.0, 90.0])

        with patch("a_share_backtesting.signals.add_grouped_indicators", return_value=bars.copy()):
            result = build_signal_variants(bars, baseline_config() | {"j_threshold": 15.0, "min_market_cap": 0})

        self.assertFalse(bool(result.loc[2, "b1_signal"]))

    def test_b1_accepts_immediate_prior_low_j_turning_up(self):
        bars = prepared_indicator_bars([50.0, 10.0, 20.0])

        with patch("a_share_backtesting.signals.add_grouped_indicators", return_value=bars.copy()):
            result = build_signal_variants(bars, baseline_config() | {"j_threshold": 15.0, "min_market_cap": 0})

        self.assertTrue(bool(result.loc[2, "b1_signal"]))
    def test_b1_accepts_close_above_bbi_before_bbi_slope_turns_up(self):
        bars = prepared_indicator_bars([50.0, 10.0, 20.0], bbi_values=[9.9, 9.8, 9.7])

        with patch("a_share_backtesting.signals.add_grouped_indicators", return_value=bars.copy()):
            result = build_signal_variants(bars, baseline_config() | {"j_threshold": 15.0, "min_market_cap": 0})

        self.assertTrue(bool(result.loc[2, "b1_signal"]))
    def test_zero_market_cap_threshold_does_not_filter_technical_only_rows(self):
        bars = rising_mainboard_bars()
        bars["market_cap"] = 0

        result = build_signal_variants(bars, baseline_config() | {"min_market_cap": 0})

        self.assertTrue(result["eligible"].any())

    def test_stock_pool_codes_define_eligible_universe(self):
        bars = prepared_indicator_bars([50.0, 10.0, 20.0])
        bars["code"] = "688001"

        with patch("a_share_backtesting.signals.add_grouped_indicators", return_value=bars.copy()):
            result = build_signal_variants(
                bars,
                baseline_config() | {"j_threshold": 15.0, "min_market_cap": 0, "stock_pool_codes": ["688001"]},
            )

        self.assertTrue(result["eligible"].all())
        self.assertTrue(bool(result.loc[2, "b1_signal"]))


if __name__ == "__main__":
    unittest.main()
