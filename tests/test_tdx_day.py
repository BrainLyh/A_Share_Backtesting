import struct
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.tdx_day import is_target_mainboard_path, read_tdx_day_file


class TestTdxDayReader(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def write_day(self, filename: str, records: list[tuple[object, ...]]) -> Path:
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(struct.pack("<IIIIIfII", *record) for record in records))
        return path

    def test_reads_one_32_byte_record_and_scales_prices(self) -> None:
        path = self.write_day("sh600000.day", [(20260105, 1001, 1020, 990, 1015, 123.0, 4567, 0)])

        actual = read_tdx_day_file(path)

        self.assertEqual(actual.loc[0, "code"], "600000")
        self.assertEqual(actual.loc[0, "date"], pd.Timestamp("2026-01-05"))
        self.assertAlmostEqual(actual.loc[0, "open"], 10.01)
        self.assertAlmostEqual(actual.loc[0, "close"], 10.15)
        self.assertEqual(actual.loc[0, "volume"], 4567)

    def test_rejects_file_whose_length_is_not_a_multiple_of_32(self) -> None:
        path = self.root / "sh600000.day"
        path.write_bytes(b"bad")

        with self.assertRaisesRegex(ValueError, "multiple of 32"):
            read_tdx_day_file(path)

    def test_filters_only_requested_mainboard_file_prefixes(self) -> None:
        self.assertTrue(is_target_mainboard_path(Path("sh/lday/sh603000.day")))
        self.assertTrue(is_target_mainboard_path(Path("sz/lday/sz002001.day")))
        self.assertFalse(is_target_mainboard_path(Path("sh/lday/sh688001.day")))
        self.assertFalse(is_target_mainboard_path(Path("bj/lday/bj920001.day")))


if __name__ == "__main__":
    unittest.main()
