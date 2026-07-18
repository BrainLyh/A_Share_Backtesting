import json
import struct
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.intraday_portfolio_run import REQUIRED_OUTPUTS, main


def encoded_date(date: pd.Timestamp) -> int:
    return (date.year - 2004) * 2048 + date.month * 100 + date.day


def trading_times() -> list[str]:
    morning = pd.date_range("2026-07-17 09:35", "2026-07-17 11:30", freq="5min")
    afternoon = pd.date_range("2026-07-17 13:05", "2026-07-17 15:00", freq="5min")
    return [timestamp.strftime("%H:%M") for timestamp in [*morning, *afternoon]]


class IntradayPortfolioCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.minute_root = self.root / "vipdoc"
        self.qfq_path = self.root / "qfq.csv"
        self.pool_path = self.root / "pool.csv"
        self.config_path = self.root / "config.json"
        self.output = self.root / "output"

    def write_inputs(self) -> None:
        date = pd.Timestamp("2026-07-17")
        lc5 = self.minute_root / "sh" / "fzline" / "sh600001.lc5"
        lc5.parent.mkdir(parents=True)
        records = []
        for time in trading_times():
            hour, minute = (int(part) for part in time.split(":"))
            records.append(
                struct.pack(
                    "<HHfffffII",
                    encoded_date(date),
                    hour * 60 + minute,
                    10.0,
                    10.1,
                    9.9,
                    10.0,
                    1_000_000.0,
                    100_000,
                    0,
                )
            )
        lc5.write_bytes(b"".join(records))
        daily_rows = []
        for daily_date in pd.bdate_range(end=date, periods=60):
            daily_rows.append(
                {
                    "date": daily_date,
                    "code": "600001",
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.0,
                    "preclose": 10.0,
                    "volume": 4_800_000,
                    "qfq_scale": 1.0,
                    "qfq_open": 10.0,
                    "qfq_high": 10.1,
                    "qfq_low": 9.9,
                    "qfq_close": 10.0,
                    "adjustment_jump": False,
                }
            )
        pd.DataFrame(daily_rows).to_csv(self.qfq_path, index=False)
        pd.DataFrame({"code": ["600001"]}).to_csv(self.pool_path, index=False)
        self.config_path.write_text(
            json.dumps(
                {
                    "min_market_cap": 0,
                    "require_core_pool": False,
                    "j_threshold": 15.0,
                    "volume_multiplier": 1.0,
                    "commission_rate": 0.0003,
                    "minimum_commission": 5.0,
                    "sell_stamp_duty_rate": 0.0005,
                    "lot_size": 100,
                }
            ),
            encoding="utf-8",
        )

    def test_cli_writes_complete_reconciled_artifacts(self) -> None:
        self.write_inputs()

        exit_code = main(
            [
                "--minute-root",
                str(self.minute_root),
                "--qfq-source",
                str(self.qfq_path),
                "--stock-pool",
                str(self.pool_path),
                "--config",
                str(self.config_path),
                "--output",
                str(self.output),
                "--analysis-start",
                "2026-07-17",
                "--analysis-end",
                "2026-07-17",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(set(REQUIRED_OUTPUTS), {path.name for path in self.output.iterdir()})
        summary = pd.read_csv(self.output / "portfolio_summary.csv")
        self.assertAlmostEqual(summary.loc[0, "initial_cash"], 1_000_000.0)
        self.assertAlmostEqual(summary.loc[0, "final_nav"], 1_000_000.0)
        manifest = json.loads((self.output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stock_pool_count"], 1)
        self.assertEqual(manifest["minute_file_count"], 1)
        self.assertEqual(len(manifest["qfq_source_sha256"]), 64)
        self.assertEqual(len(manifest["stock_pool_sha256"]), 64)
        self.assertIn("historical_st_status_unavailable", manifest["limitations"])


if __name__ == "__main__":
    unittest.main()
