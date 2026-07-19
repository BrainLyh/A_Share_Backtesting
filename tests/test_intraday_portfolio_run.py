import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import a_share_backtesting.intraday_portfolio_run as cli_module

from a_share_backtesting.intraday_portfolio_run import (
    REQUIRED_OUTPUTS,
    _build_cli_market_regime,
    _execution_config,
    _load_minutes,
    _load_qfq,
    main,
)


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

    def write_inputs(self, minute_dates: tuple[str, ...] = ("2026-07-17",)) -> None:
        dates = [pd.Timestamp(value) for value in minute_dates]
        date = max(dates)
        lc5 = self.minute_root / "sh" / "fzline" / "sh600001.lc5"
        lc5.parent.mkdir(parents=True)
        records = []
        for minute_date in dates:
            for time in trading_times():
                hour, minute = (int(part) for part in time.split(":"))
                records.append(
                    struct.pack(
                        "<HHfffffII",
                        encoded_date(minute_date),
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

    def test_qfq_loader_keeps_180_actual_warmup_rows_across_calendar_gaps(self) -> None:
        analysis_date = pd.Timestamp("2026-07-17")
        dates = list(pd.bdate_range(end=analysis_date, periods=230))
        dates = [date for index, date in enumerate(dates) if index % 6 != 0 or date == analysis_date]
        rows = [
            {
                "date": date,
                "code": "600001",
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "preclose": 10.0,
                "volume": 1_000_000,
                "qfq_scale": 1.0,
                "qfq_open": 10.0,
                "qfq_high": 10.1,
                "qfq_low": 9.9,
                "qfq_close": 10.0,
            }
            for date in dates
        ]
        pd.DataFrame(rows).to_csv(self.qfq_path, index=False)

        loaded = _load_qfq(self.qfq_path, {"600001"}, analysis_date, analysis_date)["600001"]

        self.assertEqual(int((loaded["date"] < analysis_date).sum()), 180)
        self.assertEqual(int((loaded["date"] == analysis_date).sum()), 1)

    def test_loader_preserves_explicit_price_limits_on_minute_bars(self) -> None:
        self.write_inputs()
        source = pd.read_csv(self.qfq_path, dtype={"code": str})
        source["upper_limit"] = 11.0
        source["lower_limit"] = 9.0
        source.to_csv(self.qfq_path, index=False)
        daily = _load_qfq(
            self.qfq_path,
            {"600001"},
            pd.Timestamp("2026-07-17"),
            pd.Timestamp("2026-07-17"),
        )

        minutes, audit, _ = _load_minutes(
            self.minute_root,
            ["600001"],
            daily,
            pd.Timestamp("2026-07-17"),
            pd.Timestamp("2026-07-17"),
        )

        self.assertTrue(audit.empty)
        self.assertEqual(minutes["600001"].loc[0, "upper_limit"], 11.0)
        self.assertEqual(minutes["600001"].loc[0, "lower_limit"], 9.0)

    def test_execution_config_rejects_hard_limit_violations(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_positions"):
            _execution_config({"max_positions": 4})
        with self.assertRaisesRegex(ValueError, "participation_rate"):
            _execution_config({"participation_rate": 0.11})

    def test_cli_audits_bad_lc5_instead_of_aborting(self) -> None:
        self.write_inputs()
        lc5 = self.minute_root / "sh" / "fzline" / "sh600001.lc5"
        lc5.write_bytes(b"bad")

        exit_code = main(
            [
                "--minute-root", str(self.minute_root),
                "--qfq-source", str(self.qfq_path),
                "--stock-pool", str(self.pool_path),
                "--config", str(self.config_path),
                "--output", str(self.output),
                "--analysis-start", "2026-07-17",
                "--analysis-end", "2026-07-17",
            ]
        )

        self.assertEqual(exit_code, 0)
        audit = pd.read_csv(self.output / "data_audit.csv")
        self.assertEqual(audit.loc[0, "reason"], "lc5_parse_error")
        summary = pd.read_csv(self.output / "portfolio_summary.csv")
        self.assertIn("capital_utilization", summary.columns)
        self.assertEqual(summary.loc[0, "final_nav"], 1_000_000.0)

    def test_loader_audits_incomplete_lc5_day_structurally(self) -> None:
        self.write_inputs()
        lc5 = self.minute_root / "sh" / "fzline" / "sh600001.lc5"
        lc5.write_bytes(lc5.read_bytes()[:-32])
        daily = _load_qfq(
            self.qfq_path,
            {"600001"},
            pd.Timestamp("2026-07-17"),
            pd.Timestamp("2026-07-17"),
        )

        minutes, audit, _ = _load_minutes(
            self.minute_root,
            ["600001"],
            daily,
            pd.Timestamp("2026-07-17"),
            pd.Timestamp("2026-07-17"),
        )

        self.assertNotIn("600001", minutes)
        self.assertEqual(audit["date"].dropna().tolist(), [pd.Timestamp("2026-07-17")] * 3)
        self.assertEqual(
            set(audit["reason"]),
            {"unexpected_bar_count", "invalid_trading_time_grid", "missing_required_bars"},
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
        for path in self.output.glob("*.csv"):
            pd.read_csv(path)
        self.assertTrue((self.output / "rejections.csv").exists())
        self.assertEqual(
            pd.read_csv(self.output / "rejections.csv").columns.tolist(),
            ["timestamp", "code", "side", "reason"],
        )
        summary = pd.read_csv(self.output / "portfolio_summary.csv")
        self.assertAlmostEqual(summary.loc[0, "initial_cash"], 1_000_000.0)
        self.assertAlmostEqual(summary.loc[0, "final_nav"], 1_000_000.0)
        manifest = json.loads((self.output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest),
            {
                "mode",
                "analysis_start",
                "analysis_end",
                "stock_pool_count",
                "processed_code_count",
                "minute_file_count",
                "qfq_source",
                "qfq_source_sha256",
                "stock_pool_sha256",
                "config_sha256",
                "scan_source",
                "scan_source_sha256",
                "minute_source_sha256",
                "last_minute_date",
                "git_revision",
                "git_dirty",
                "python_version",
                "execution_config",
                "limitations",
            },
        )
        self.assertEqual(manifest["stock_pool_count"], 1)
        self.assertEqual(manifest["minute_file_count"], 1)
        self.assertEqual(len(manifest["qfq_source_sha256"]), 64)
        self.assertEqual(len(manifest["stock_pool_sha256"]), 64)
        self.assertIn("retrospective_stock_pool_snapshot", manifest["limitations"])
        self.assertIn("historical_st_status_unavailable", manifest["limitations"])
        self.assertIsInstance(manifest["git_dirty"], bool)
        self.assertFalse((self.output / "market_regime.csv").exists())
        self.assertNotIn("market_regime_source", manifest)
        self.assertNotIn("market_regime_source_sha256", manifest)
        self.assertNotIn("outputs", manifest)
        report = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertEqual(
            report,
            "# Intraday B1 Portfolio Backtest\n"
            "\n"
            "- Total net return: 0.0000%\n"
            "- Five-minute maximum drawdown: 0.0000%\n"
            "- Conservative low maximum drawdown: 0.0000%\n"
            "- Closed trades: 0\n"
            "- Net win rate: nan%\n"
            "- Data audit issues: 0\n"
            "\n"
            "## Limitations\n"
            "\n"
            "- retrospective_stock_pool_snapshot\n"
            "- historical_st_status_unavailable\n"
            "- historical_market_cap_unavailable\n"
            "- five_minute_intrabar_order_unknown_stop_first\n"
            "- order_book_queue_unavailable\n",
        )

    def test_untimed_rerun_removes_only_stale_market_regime_artifact(self) -> None:
        self.write_inputs()
        regime_path = self.root / "market_regime.json"
        regime_path.write_text(
            json.dumps(
                {
                    "observation_start": "2026-07-17",
                    "initial_state": "risk_on",
                    "execution_mode": "same_day_1455",
                    "events": [
                        {"signal_date": "2026-07-17", "event": "down", "label": "risk_off"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        common_args = [
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

        self.assertEqual(main([*common_args, "--market-regime", str(regime_path)]), 0)
        self.assertTrue((self.output / "market_regime.csv").exists())
        sentinel = self.output / "preserve.me"
        sentinel.write_text("keep", encoding="utf-8")

        self.assertEqual(main(common_args), 0)

        self.assertFalse((self.output / "market_regime.csv").exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertTrue(set(REQUIRED_OUTPUTS).issubset({path.name for path in self.output.iterdir()}))

    def test_market_regime_manifest_hash_uses_the_parsed_source_snapshot(self) -> None:
        self.write_inputs()
        regime_path = self.root / "market_regime.json"
        original_payload = {
            "observation_start": "2026-07-17",
            "initial_state": "risk_on",
            "execution_mode": "same_day_1455",
            "events": [
                {"signal_date": "2026-07-17", "event": "down", "label": "frozen_snapshot"}
            ],
        }
        original_bytes = json.dumps(original_payload, indent=2).encode("utf-8")
        regime_path.write_bytes(original_bytes)
        mutated_bytes = json.dumps(
            {
                **original_payload,
                "events": [
                    {"signal_date": "2026-07-17", "event": "down", "label": "mutated_source"}
                ],
            },
            indent=2,
        ).encode("utf-8")
        original_write_csv = cli_module._write_csv
        source_mutated = False

        def mutate_source_then_write(frame: pd.DataFrame, path: Path) -> None:
            nonlocal source_mutated
            if not source_mutated:
                regime_path.write_bytes(mutated_bytes)
                source_mutated = True
            original_write_csv(frame, path)

        with patch.object(cli_module, "_write_csv", side_effect=mutate_source_then_write):
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
                    "--market-regime",
                    str(regime_path),
                    "--output",
                    str(self.output),
                    "--analysis-start",
                    "2026-07-17",
                    "--analysis-end",
                    "2026-07-17",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(pd.read_csv(self.output / "market_regime.csv").loc[0, "label"], "frozen_snapshot")
        manifest = json.loads((self.output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["market_regime_source_sha256"],
            hashlib.sha256(original_bytes).hexdigest(),
        )
        self.assertNotEqual(
            manifest["market_regime_source_sha256"],
            hashlib.sha256(regime_path.read_bytes()).hexdigest(),
        )

    def test_market_regime_source_cannot_alias_generated_timeline(self) -> None:
        self.write_inputs()
        self.output.mkdir(parents=True)
        regime_path = self.output / "market_regime.csv"
        source_bytes = json.dumps(
            {
                "observation_start": "2026-07-17",
                "initial_state": "risk_on",
                "execution_mode": "same_day_1455",
                "events": [
                    {"signal_date": "2026-07-17", "event": "down", "label": "risk_off"}
                ],
            }
        ).encode("utf-8")
        regime_path.write_bytes(source_bytes)

        with self.assertRaisesRegex(ValueError, "must not alias output market_regime.csv"):
            main(
                [
                    "--minute-root",
                    str(self.minute_root),
                    "--qfq-source",
                    str(self.qfq_path),
                    "--stock-pool",
                    str(self.pool_path),
                    "--config",
                    str(self.config_path),
                    "--market-regime",
                    str(regime_path),
                    "--output",
                    str(self.output),
                    "--analysis-start",
                    "2026-07-17",
                    "--analysis-end",
                    "2026-07-17",
                ]
            )

        self.assertEqual(regime_path.read_bytes(), source_bytes)

    def test_cli_writes_conditional_market_regime_artifact_and_provenance(self) -> None:
        self.write_inputs(("2026-07-16", "2026-07-17"))
        scan_path = self.root / "scans.csv"
        pd.DataFrame(
            [
                {
                    "date": date,
                    "code": "600001",
                    "scan_time": time,
                    "b1_signal": True,
                    "signal_strength": 5.0,
                    "atr14": 0.5,
                }
                for date in ("2026-07-16", "2026-07-17")
                for time in ("14:40", "14:45", "14:50")
            ]
        ).to_csv(scan_path, index=False)
        regime_path = self.root / "market_regime.json"
        regime_path.write_text(
            json.dumps(
                {
                    "observation_start": "2026-07-16",
                    "initial_state": "risk_on",
                    "execution_mode": "next_session_0935",
                    "events": [
                        {"signal_date": "2026-07-16", "event": "down", "label": "risk_off"},
                        {"signal_date": "2026-07-17", "event": "down", "label": "terminal_risk_off"},
                    ],
                    "calendar_extension_dates": ["2026-07-20"],
                    "calendar_extension_source": "https://example.test/exchange-calendar",
                }
            ),
            encoding="utf-8",
        )

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
                "--scan-source",
                str(scan_path),
                "--market-regime",
                str(regime_path),
                "--output",
                str(self.output),
                "--analysis-start",
                "2026-07-16",
                "--analysis-end",
                "2026-07-17",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            set(REQUIRED_OUTPUTS) | {"market_regime.csv"},
            {path.name for path in self.output.iterdir()},
        )
        timeline = pd.read_csv(self.output / "market_regime.csv")
        self.assertEqual(
            timeline.columns.tolist(),
            [
                "signal_date",
                "effective_timestamp",
                "event",
                "label",
                "prior_state",
                "resulting_state",
                "execution_mode",
            ],
        )
        self.assertEqual(
            timeline.to_dict("records"),
            [
                {
                    "signal_date": "2026-07-16",
                    "effective_timestamp": "2026-07-17 09:35:00",
                    "event": "down",
                    "label": "risk_off",
                    "prior_state": "risk_on",
                    "resulting_state": "risk_off",
                    "execution_mode": "next_session_0935",
                },
                {
                    "signal_date": "2026-07-17",
                    "effective_timestamp": "2026-07-20 09:35:00",
                    "event": "down",
                    "label": "terminal_risk_off",
                    "prior_state": "risk_off",
                    "resulting_state": "risk_off",
                    "execution_mode": "next_session_0935",
                },
            ],
        )
        self.assertIn("market_regime_exit", set(pd.read_csv(self.output / "fills.csv")["reason"]))
        self.assertIn("market_regime_exit", set(pd.read_csv(self.output / "trades.csv")["exit_reason"]))
        self.assertIn("market_regime_off", set(pd.read_csv(self.output / "rejections.csv")["reason"]))
        nav_dates = pd.to_datetime(pd.read_csv(self.output / "nav_5m.csv")["date"])
        fill_times = pd.to_datetime(pd.read_csv(self.output / "fills.csv")["timestamp"])
        self.assertLessEqual(nav_dates.max(), pd.Timestamp("2026-07-17"))
        self.assertLessEqual(fill_times.max(), pd.Timestamp("2026-07-17 15:00"))
        manifest = json.loads((self.output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["market_regime_source"], str(regime_path.resolve()))
        self.assertEqual(
            manifest["market_regime_source_sha256"],
            hashlib.sha256(regime_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["outputs"], [*REQUIRED_OUTPUTS, "market_regime.csv"])
        report = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertIn("Market-regime dates were manually supplied.", report)
        self.assertIn("Market-regime thresholds are post-hoc.", report)
        self.assertIn("`same_day_1455` assumes the full signal is observable by 14:55.", report)

    def test_market_regime_calendar_extensions_are_explicitly_validated(self) -> None:
        minutes = {"600001": pd.DataFrame({"date": [pd.Timestamp("2026-07-17")]})}
        base = {
            "observation_start": "2026-07-17",
            "initial_state": "risk_off",
            "execution_mode": "next_session_0935",
            "events": [
                {"signal_date": "2026-07-17", "event": "down", "label": "terminal_risk_off"}
            ],
        }
        invalid_cases = [
            (
                {"calendar_extension_dates": "2026-07-20", "calendar_extension_source": "https://example.test"},
                "calendar_extension_dates must be a non-empty list",
            ),
            (
                {"calendar_extension_dates": ["07/20/2026"], "calendar_extension_source": "https://example.test"},
                "calendar_extension_dates entries must be ISO dates",
            ),
            (
                {
                    "calendar_extension_dates": ["2026-07-20", "2026-07-20"],
                    "calendar_extension_source": "https://example.test",
                },
                "calendar_extension_dates must not contain duplicates",
            ),
            (
                {"calendar_extension_dates": ["2026-07-20"]},
                "calendar_extension_source must be a non-empty string",
            ),
            (
                {"calendar_extension_dates": ["2026-07-20"], "calendar_extension_source": "  "},
                "calendar_extension_source must be a non-empty string",
            ),
            (
                {"calendar_extension_source": "https://example.test"},
                "calendar_extension_source requires calendar_extension_dates",
            ),
            (
                {
                    "execution_mode": "same_day_1455",
                    "calendar_extension_dates": ["2026-07-20"],
                    "calendar_extension_source": "https://example.test",
                },
                "calendar extensions require next_session_0935 execution",
            ),
            (
                {"calendar_extension_dates": ["2026-07-17"], "calendar_extension_source": "https://example.test"},
                "calendar extension dates must follow in-window minute trading dates",
            ),
        ]
        for index, (updates, message) in enumerate(invalid_cases):
            with self.subTest(index=index):
                path = self.root / f"invalid_regime_{index}.json"
                path.write_text(json.dumps({**base, **updates}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    _build_cli_market_regime(path, minutes)

    def test_cli_accepts_frozen_scan_source(self) -> None:
        self.write_inputs()
        scan_path = self.root / "scans.csv"
        pd.DataFrame(
            [
                {
                    "date": "2026-07-17",
                    "code": "600001",
                    "scan_time": time,
                    "b1_signal": True,
                    "signal_strength": 5.0,
                    "atr14": 0.5,
                }
                for time in ("14:40", "14:45", "14:50")
            ]
        ).to_csv(scan_path, index=False)

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
                "--scan-source",
                str(scan_path),
                "--output",
                str(self.output),
                "--analysis-start",
                "2026-07-17",
                "--analysis-end",
                "2026-07-17",
            ]
        )

        self.assertEqual(exit_code, 0)
        fills = pd.read_csv(self.output / "fills.csv")
        self.assertEqual(fills.loc[fills["side"].eq("buy"), "code"].astype(str).str.zfill(6).tolist(), ["600001"])
        manifest = json.loads((self.output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["scan_source"], str(scan_path.resolve()))
        self.assertEqual(len(manifest["scan_source_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
