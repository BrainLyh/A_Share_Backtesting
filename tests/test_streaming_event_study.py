import struct
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.streaming_event_study import collect_signal_events, iter_tdx_mainboard_bars


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


if __name__ == "__main__":
    unittest.main()
