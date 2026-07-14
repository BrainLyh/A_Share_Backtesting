import json
import struct
import tempfile
import unittest
from pathlib import Path

from a_share_backtesting.tdx_import import import_tdx_daily_bars, main


class TestTdxImport(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "tdx_raw"
        self.csv = self.root / "output" / "daily_bars_technical.csv"
        self.metadata = self.root / "output" / "daily_bars_technical.metadata.json"

    def write_day(self, relative_path: str, records: list[tuple[object, ...]]) -> None:
        path = self.source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(struct.pack("<IIIIIfII", *record) for record in records))

    def test_imports_mainboard_rows_and_records_excluded_files(self) -> None:
        self.write_day("sh/lday/sh600000.day", [(20260105, 1000, 1010, 990, 1005, 0.0, 1, 0)])
        self.write_day("sh/lday/sh688001.day", [(20260105, 1000, 1010, 990, 1005, 0.0, 1, 0)])

        bars, metadata = import_tdx_daily_bars(self.source)

        self.assertEqual(bars["code"].tolist(), ["600000"])
        self.assertEqual(bars.loc[0, "market_cap"], 0)
        self.assertFalse(bars.loc[0, "is_st"])
        self.assertFalse(bars.loc[0, "is_suspended"])
        self.assertEqual(metadata["excluded_non_target_files"], 1)
        self.assertEqual(metadata["data_scope_label"], "technical_only_no_historical_market_cap_or_st")
        self.assertEqual(metadata["price_adjustment"], "unadjusted")

    def test_cli_writes_csv_and_metadata_after_successful_import(self) -> None:
        self.write_day("sz/lday/sz000001.day", [(20260105, 1000, 1010, 990, 1005, 0.0, 1, 0)])

        exit_code = main(["--source", str(self.source), "--output", str(self.csv), "--metadata", str(self.metadata)])

        self.assertEqual(exit_code, 0)
        self.assertTrue(self.csv.exists())
        written = json.loads(self.metadata.read_text(encoding="utf-8"))
        self.assertEqual(written["imported_code_count"], 1)
        self.assertEqual(written["imported_row_count"], 1)


if __name__ == "__main__":
    unittest.main()
