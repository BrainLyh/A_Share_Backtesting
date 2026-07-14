import sys
import unittest
import json
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.event_study import measure_events
from a_share_backtesting.event_study_run import main


def event_config() -> dict[str, object]:
    return {
        "event_notional": 100000,
        "lot_size": 100,
        "commission_rate": 0.0,
        "minimum_commission": 0.0,
        "sell_stamp_duty_rate": 0.0,
    }


def signal_frame(entry_upper_limit: float | None = None) -> pd.DataFrame:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    return pd.DataFrame(
        {
            "date": dates,
            "code": ["600000"] * len(dates),
            "open": [9.5, 10.0, 11.0, 12.0],
            "high": [10.0, 10.5, 11.5, 12.5],
            "low": [9.0, 9.8, 10.5, 11.5],
            "close": [9.8, 10.2, 11.2, 12.2],
            "is_suspended": [False] * len(dates),
            "upper_limit": [None, entry_upper_limit, None, None],
            "lower_limit": [None] * len(dates),
            "legacy_first_trigger": [True, False, False, False],
        }
    )


class TestEventStudy(unittest.TestCase):
    def test_next_open_entry_and_two_full_day_exit(self):
        event = measure_events(signal_frame(), "legacy", 2, event_config()).iloc[0]
        self.assertEqual(event["entry_date"], pd.Timestamp("2026-01-05"))
        self.assertEqual(event["exit_date"], pd.Timestamp("2026-01-07"))
        self.assertEqual(event["status"], "filled")
        self.assertAlmostEqual(event["gross_return"], 0.2)

    def test_limit_up_entry_is_recorded_without_return(self):
        event = measure_events(signal_frame(entry_upper_limit=10.0), "legacy", 2, event_config()).iloc[0]
        self.assertEqual(event["status"], "unfilled_entry")
        self.assertTrue(pd.isna(event["net_return"]))

    def test_second_trigger_before_exit_is_excluded(self):
        frame = signal_frame()
        frame.loc[1, "legacy_first_trigger"] = True
        events = measure_events(frame, "legacy", 2, event_config())
        self.assertEqual(len(events), 1)

    def test_max_adverse_excursion_uses_intraday_low(self):
        frame = signal_frame()
        frame.loc[1, "low"] = 8.8
        event = measure_events(frame, "legacy", 2, event_config()).iloc[0]
        self.assertAlmostEqual(event["max_adverse_excursion"], -0.12)

    def test_cli_writes_research_artifacts(self):
        rows = []
        for index, date in enumerate(pd.bdate_range("2025-10-01", periods=45)):
            close = 10 + index * 0.1
            rows.append({"date": date, "code": "600000", "name": "示例股票", "open": close - 0.05, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 10000 - index, "market_cap": 20000000000, "is_st": False, "is_suspended": False})
        config = {"analysis_start": "2025-10-01", "analysis_end": "2025-12-31", "variants": ["legacy"], "horizons": [2], "require_core_pool": False, "min_market_cap": 10000000000, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, **event_config(), "control_iterations": 2, "random_seed": 1}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
            bars_path = Path(directory) / "bars.csv"
            config_path = Path(directory) / "config.json"
            metadata_path = Path(directory) / "metadata.json"
            output_path = Path(directory) / "output"
            pd.DataFrame(rows).to_csv(bars_path, index=False)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            metadata_path.write_text(json.dumps({"data_scope_label": "technical_only_no_historical_market_cap_or_st", "date_start": "2020-01-01", "date_end": "2026-07-13", "price_adjustment": "unadjusted", "field_limitations": ["historical_market_cap_unavailable"]}), encoding="utf-8")
            self.assertEqual(main(["--data", str(bars_path), "--config", str(config_path), "--metadata", str(metadata_path), "--output", str(output_path)]), 0)
            self.assertTrue({"signal_audit.csv", "events.csv", "date_portfolios.csv", "summary.csv", "control_distribution.csv", "control_summary.json", "report.md"}.issubset({path.name for path in output_path.iterdir()}))
            self.assertIn("historical_market_cap_unavailable", (output_path / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
