import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.data_contract import (
    normalize_daily_bars,
    validate_event_config,
    validate_technical_only_config,
)


def minimum_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-01-05",
                "code": "600000",
                "name": "示例股票",
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "volume": 100000,
                "market_cap": 20000000000,
                "is_st": False,
                "is_suspended": False,
            }
        ]
    )


def baseline_config() -> dict[str, object]:
    return {
        "analysis_start": "2020-01-01",
        "analysis_end": "2026-06-30",
        "variants": ["legacy", "bbi", "b1"],
        "horizons": [2, 5, 10, 20],
        "event_notional": 100000,
        "control_iterations": 1000,
        "random_seed": 20260713,
    }


class TestDataContract(unittest.TestCase):
    def test_technical_baseline_defaults_missing_core_pool_to_true(self):
        normalized = normalize_daily_bars(minimum_frame(), require_core_pool=False)
        self.assertTrue(normalized["in_core_pool"].eq(True).all())
        self.assertEqual(normalized.loc[0, "code"], "600000")

    def test_missing_market_cap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "market_cap"):
            normalize_daily_bars(minimum_frame().drop(columns=["market_cap"]), require_core_pool=False)

    def test_missing_core_pool_is_rejected_when_required(self):
        with self.assertRaisesRegex(ValueError, "in_core_pool"):
            normalize_daily_bars(minimum_frame(), require_core_pool=True)

    def test_invalid_variant_is_rejected(self):
        config = baseline_config() | {"variants": ["legacy", "unknown"]}
        with self.assertRaisesRegex(ValueError, "variants"):
            validate_event_config(config)

    def test_non_positive_horizon_is_rejected(self):
        config = baseline_config() | {"horizons": [2, 0]}
        with self.assertRaisesRegex(ValueError, "horizons"):
            validate_event_config(config)

    def test_technical_only_scope_rejects_a_positive_market_cap_filter(self):
        config = baseline_config() | {
            "data_scope_label": "technical_only_no_historical_market_cap_or_st",
            "price_adjustment": "unadjusted",
            "min_market_cap": 1,
        }
        with self.assertRaisesRegex(ValueError, "min_market_cap"):
            validate_technical_only_config(config)


if __name__ == "__main__":
    unittest.main()
