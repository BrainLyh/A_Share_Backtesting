import struct
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.streaming_event_study import collect_control_events, collect_signal_events, iter_tdx_mainboard_bars, sample_control_distribution


class TestStreamingEventStudy(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.source = Path(self.temp_dir.name) / "tdx_raw"

    def write_day(self, relative_path: str, code_date: int) -> None:
        path = self.source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(struct.pack("<IIIIIfII", code_date, 1000, 1010, 990, 1005, 0.0, 1, 0))

    def test_iterator_yields_one_normalized_code_frame_at_a_time(self) -> None:
        self.write_day("sh/lday/sh600000.day", 20250102)
        self.write_day("sz/lday/sz000001.day", 20250102)
        self.write_day("sh/lday/sh688001.day", 20250102)

        frames = list(iter_tdx_mainboard_bars(self.source, pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-31")))

        self.assertEqual([frame["code"].iat[0] for frame in frames], ["600000", "000001"])
        self.assertTrue(all(frame["code"].nunique() == 1 for frame in frames))
        self.assertTrue(all(frame.loc[0, "market_cap"] == 0 for frame in frames))

    def test_collects_events_without_returning_daily_bar_frames(self) -> None:
        records = []
        for index, date in enumerate(pd.bdate_range("2025-10-01", periods=45)):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 20, price - 20, price + 10, 0.0, 10000 - index, 0))
        path = self.source / "sh" / "lday" / "sh600000.day"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(struct.pack("<IIIIIfII", *record) for record in records))
        config = {"analysis_start": "2025-10-01", "analysis_end": "2025-12-31", "variants": ["legacy"], "horizons": [2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0}

        events, metadata = collect_signal_events(self.source, config)

        self.assertFalse(events.empty)
        self.assertEqual(set(events["code"]), {"600000"})
        self.assertEqual(metadata["processed_code_count"], 1)

    def test_control_collection_is_empty_when_no_signal_dates_exist(self) -> None:
        self.write_day("sh/lday/sh600000.day", 20250102)
        config = {"analysis_start": "2025-01-01", "analysis_end": "2025-01-31", "variants": ["legacy"], "horizons": [2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 15.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0}

        controls = collect_control_events(self.source, config, {})

        self.assertTrue(controls.empty)

    def test_control_collection_measures_a_non_signal_code_on_requested_date(self) -> None:
        records = []
        dates = pd.bdate_range("2025-10-01", periods=45)
        for index, date in enumerate(dates):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 20, price - 20, price + 10, 0.0, 10000 - index, 0))
        path = self.source / "sh" / "lday" / "sh600000.day"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(struct.pack("<IIIIIfII", *record) for record in records))
        config = {"analysis_start": "2025-10-01", "analysis_end": "2025-12-31", "variants": ["legacy"], "horizons": [2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": -100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0}
        date = dates[20]

        controls = collect_control_events(self.source, config, {("legacy", 2): {date}})

        self.assertEqual(controls.loc[0, "code"], "600000")
        self.assertEqual(controls.loc[0, "signal_date"], date)

    def test_control_sampling_is_seeded_and_matches_signal_date_counts(self) -> None:
        observed = pd.DataFrame({"variant": ["legacy", "legacy"], "horizon": [2, 2], "signal_date": [pd.Timestamp("2025-01-02")] * 2, "status": ["filled", "filled"], "net_return": [0.01, 0.03]})
        candidates = pd.DataFrame({"variant": ["legacy"] * 3, "horizon": [2] * 3, "signal_date": [pd.Timestamp("2025-01-02")] * 3, "status": ["filled"] * 3, "net_return": [0.0, 0.02, 0.04]})

        first = sample_control_distribution(observed, candidates, iterations=3, random_seed=7)
        second = sample_control_distribution(observed, candidates, iterations=3, random_seed=7)

        self.assertEqual(first.to_dict("records"), second.to_dict("records"))
        self.assertEqual(len(first), 3)


if __name__ == "__main__":
    unittest.main()
