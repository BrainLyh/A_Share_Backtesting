import struct
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.tdx_lc5 import audit_lc5_frame, find_lc5_path, read_tdx_lc5_file


def encoded_date(year: int, month: int, day: int) -> int:
    return (year - 2004) * 2048 + month * 100 + day


class TestTdxLc5Reader(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def write_lc5(self, filename: str, records: list[tuple[object, ...]]) -> Path:
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(struct.pack("<HHfffffII", *record) for record in records))
        return path

    def record(
        self,
        hour: int = 14,
        minute: int = 55,
        open_: float = 10.0,
        high: float = 10.3,
        low: float = 9.9,
        close: float = 10.2,
        volume: int = 123400,
    ) -> tuple[object, ...]:
        return (encoded_date(2026, 7, 17), hour * 60 + minute, open_, high, low, close, 1_250_000.0, volume, 0)

    def test_reads_one_record_and_ignores_amount(self) -> None:
        path = self.write_lc5("sh600246.lc5", [self.record()])

        actual = read_tdx_lc5_file(path)

        self.assertEqual(actual.loc[0, "code"], "600246")
        self.assertEqual(actual.loc[0, "timestamp"], pd.Timestamp("2026-07-17 14:55"))
        self.assertEqual(actual.loc[0, "date"], pd.Timestamp("2026-07-17"))
        self.assertEqual(actual.loc[0, "time"], "14:55")
        self.assertAlmostEqual(actual.loc[0, "open"], 10.0)
        self.assertAlmostEqual(actual.loc[0, "close"], 10.2, places=5)
        self.assertEqual(actual.loc[0, "volume"], 123400)
        self.assertNotIn("amount", actual.columns)

    def test_rejects_invalid_length_filename_duplicate_and_ohlc(self) -> None:
        bad_length = self.root / "sh600246.lc5"
        bad_length.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "multiple of 32"):
            read_tdx_lc5_file(bad_length)

        bad_name = self.write_lc5("600246.lc5", [self.record()])
        with self.assertRaisesRegex(ValueError, "exchange prefix"):
            read_tdx_lc5_file(bad_name)

        duplicate = self.write_lc5("sz000001.lc5", [self.record(), self.record()])
        with self.assertRaisesRegex(ValueError, "duplicate timestamp"):
            read_tdx_lc5_file(duplicate)

        invalid_ohlc = self.write_lc5("bj920001.lc5", [self.record(high=9.8)])
        with self.assertRaisesRegex(ValueError, "invalid prices"):
            read_tdx_lc5_file(invalid_ohlc)

    def test_finds_market_specific_path(self) -> None:
        expected = self.root / "vipdoc" / "sz" / "fzline" / "sz300001.lc5"
        expected.parent.mkdir(parents=True)
        expected.write_bytes(b"record")

        self.assertEqual(find_lc5_path(self.root / "vipdoc", "300001"), expected)
        self.assertIsNone(find_lc5_path(self.root / "vipdoc", "688001"))

    def test_audit_reports_incomplete_day_and_missing_scan_bar(self) -> None:
        path = self.write_lc5(
            "sh600246.lc5",
            [self.record(hour=14, minute=40), self.record(hour=14, minute=50), self.record(hour=14, minute=55)],
        )
        frame = read_tdx_lc5_file(path)

        errors = audit_lc5_frame(frame)

        self.assertIn("600246 2026-07-17: expected 48 bars, found 3", errors)
        self.assertIn("600246 2026-07-17: missing required bars 14:45", errors)


if __name__ == "__main__":
    unittest.main()
