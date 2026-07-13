import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.indicators import tdx_sma
from a_share_backtesting.signals import build_signals


class TestCoreRules(unittest.TestCase):
    def test_tdx_sma_uses_recursive_definition(self):
        result = tdx_sma(pd.Series([10.0, 16.0, 16.0]), 3, 1)
        self.assertEqual(result.round(6).tolist(), [10.0, 12.0, 13.333333])

    def test_original_formula_excludes_non_mainboard_and_st(self):
        dates = pd.bdate_range("2024-01-01", periods=30)
        rows = []
        for code, name in [("600000", "正常股"), ("300001", "创业板"), ("000002", "ST 测试")]:
            for index, date in enumerate(dates):
                close = 10 + index * 0.2
                rows.append({"date": date, "code": code, "name": name, "open": close - 0.1, "high": close + 0.2, "low": close - 0.3, "close": close, "volume": 1000 - index, "market_cap": 20000000000, "is_st": False, "is_suspended": False, "in_core_pool": True})
        config = {"min_market_cap": 10000000000, "require_core_pool": True, "j_threshold": 100, "pit_lookback": 5, "volume_multiplier": 1.0}
        signals = build_signals(pd.DataFrame(rows), config)
        selected = signals.loc[signals["legacy_pullback_signal"], "code"].unique().tolist()
        self.assertEqual(selected, ["600000"])


if __name__ == "__main__":
    unittest.main()
