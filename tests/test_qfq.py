import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from a_share_backtesting.qfq import apply_qfq_adjustment
from a_share_backtesting.qfq_run import main as qfq_main


class TestQfqAdjustment(unittest.TestCase):
    def test_scales_prior_rows_when_preclose_differs_from_raw_previous_close(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "date": "2026-06-10",
                    "code": "688200",
                    "open": 456.00,
                    "high": 480.00,
                    "low": 448.04,
                    "close": 467.46,
                    "preclose": 463.00,
                },
                {
                    "date": "2026-06-11",
                    "code": "688200",
                    "open": 312.58,
                    "high": 333.00,
                    "low": 304.73,
                    "close": 315.00,
                    "preclose": 315.047287,
                },
            ]
        )

        adjusted = apply_qfq_adjustment(frame)
        scale = 315.047287 / 467.46

        self.assertAlmostEqual(adjusted.loc[0, "qfq_scale"], scale)
        self.assertAlmostEqual(adjusted.loc[0, "qfq_close"], 467.46 * scale)
        self.assertAlmostEqual(adjusted.loc[1, "qfq_scale"], 1.0)
        self.assertAlmostEqual(adjusted.loc[1, "qfq_close"], 315.00)
        self.assertTrue(bool(adjusted.loc[1, "adjustment_jump"]))
        self.assertAlmostEqual(adjusted.loc[1, "raw_gap_return"], 315.00 / 467.46 - 1.0)
        self.assertAlmostEqual(adjusted.loc[1, "adjusted_day_return"], 315.00 / 315.047287 - 1.0)

    def test_cli_writes_adjusted_rows_and_jump_audit(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
            root = Path(directory)
            input_path = root / "rustdx.csv"
            output_path = root / "qfq.csv"
            audit_path = root / "audit.csv"
            pd.DataFrame(
                [
                    {"date": "2026-06-10", "code": "688200", "open": 456.0, "high": 480.0, "low": 448.04, "close": 467.46, "preclose": 463.0},
                    {"date": "2026-06-11", "code": "688200", "open": 312.58, "high": 333.0, "low": 304.73, "close": 315.0, "preclose": 315.047287},
                ]
            ).to_csv(input_path, index=False)

            self.assertEqual(qfq_main(["--input", str(input_path), "--output", str(output_path), "--audit", str(audit_path)]), 0)

            adjusted = pd.read_csv(output_path, dtype={"code": str})
            audit = pd.read_csv(audit_path, dtype={"code": str})
            self.assertIn("qfq_close", adjusted.columns)
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit.loc[0, "date"], "2026-06-11")
            self.assertEqual(audit.loc[0, "code"], "688200")


if __name__ == "__main__":
    unittest.main()
