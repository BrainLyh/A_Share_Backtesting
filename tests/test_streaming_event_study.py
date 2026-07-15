import struct
import tempfile
import unittest
import json
import io
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

from a_share_backtesting.streaming_event_study import collect_control_events, collect_signal_events, iter_tdx_mainboard_bars, sample_control_distribution
from a_share_backtesting.streaming_event_study_run import _measure_close_entry_returns, _measure_staged_exit_returns, _summarize_staged_exit_events, main as streaming_main


class TestStreamingEventStudy(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.source = Path(self.temp_dir.name) / "tdx_raw"

    def write_day(self, relative_path: str, code_date: int) -> None:
        path = self.source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(struct.pack("<IIIIIfII", code_date, 1000, 1010, 990, 1005, 0.0, 1, 0))

    def write_records(self, relative_path: str, records: list[tuple[int, int, int, int, int, float, int, int]]) -> None:
        path = self.source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(struct.pack("<IIIIIfII", *record) for record in records))

    def test_iterator_yields_one_normalized_code_frame_at_a_time(self) -> None:
        self.write_day("sh/lday/sh600000.day", 20250102)
        self.write_day("sz/lday/sz000001.day", 20250102)
        self.write_day("sh/lday/sh688001.day", 20250102)

        frames = list(iter_tdx_mainboard_bars(self.source, pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-31")))

        self.assertEqual([frame["code"].iat[0] for frame in frames], ["600000", "000001"])
        self.assertTrue(all(frame["code"].nunique() == 1 for frame in frames))
        self.assertTrue(all(frame.loc[0, "market_cap"] == 0 for frame in frames))


    def test_iterator_stock_pool_includes_non_mainboard_codes(self) -> None:
        self.write_day("sh/lday/sh688001.day", 20250102)
        self.write_day("sz/lday/sz300001.day", 20250102)
        self.write_day("sh/lday/sh600000.day", 20250102)

        frames = list(iter_tdx_mainboard_bars(self.source, pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-31"), code_filter={"688001", "300001"}))

        self.assertEqual([frame["code"].iat[0] for frame in frames], ["688001", "300001"])

    def test_iterator_stock_pool_rejects_wrong_market_duplicate_paths(self) -> None:
        self.write_day("sh/lday/sh000021.day", 20250102)
        self.write_day("sz/lday/sz000021.day", 20250102)

        frames = list(iter_tdx_mainboard_bars(self.source, pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-31"), code_filter={"000021"}))

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["code"].iat[0], "000021")

    def test_iterator_skips_code_frames_outside_warmup_window(self) -> None:
        self.write_day("sh/lday/sh600000.day", 20200102)
        self.write_day("sz/lday/sz000001.day", 20250102)

        frames = list(iter_tdx_mainboard_bars(self.source, pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-31")))

        self.assertEqual([frame["code"].iat[0] for frame in frames], ["000001"])

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

    def test_streaming_cli_writes_research_artifacts_and_metadata(self) -> None:
        records = []
        for index, date in enumerate(pd.bdate_range("2025-10-01", periods=45)):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 20, price - 20, price + 10, 0.0, 10000 - index, 0))
        self.write_records("sh/lday/sh600000.day", records)
        self.write_day("sz/lday/sz000001.day", 20200102)
        config = {"analysis_start": "2025-10-01", "analysis_end": "2025-12-31", "variants": ["legacy"], "horizons": [2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0, "control_iterations": 2, "random_seed": 7, "data_scope_label": "technical_only_no_historical_market_cap_or_st", "price_adjustment": "unadjusted"}
        config_path = Path(self.temp_dir.name) / "config.json"
        output_path = Path(self.temp_dir.name) / "output"
        config_path.write_text(json.dumps(config), encoding="utf-8-sig")

        self.assertEqual(streaming_main(["--source", str(self.source), "--config", str(config_path), "--output", str(output_path)]), 0)

        expected = {"signal_audit.csv", "events.csv", "date_portfolios.csv", "summary.csv", "control_distribution.csv", "control_summary.json", "report.md", "streaming_metadata.json"}
        self.assertTrue(expected.issubset({path.name for path in output_path.iterdir()}))
        metadata = json.loads((output_path / "streaming_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["processed_code_count"], 1)
        self.assertIn("suspension_status_unavailable", metadata["field_limitations"])
        report = (output_path / "report.md").read_text(encoding="utf-8")
        self.assertIn("technical-only", report)
        self.assertIn("suspension_status_unavailable", report)

    def test_streaming_cli_reports_progress_to_stdout_and_jsonl(self) -> None:
        records = []
        for index, date in enumerate(pd.bdate_range("2025-10-01", periods=45)):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 20, price - 20, price + 10, 0.0, 10000 - index, 0))
        self.write_records("sh/lday/sh600000.day", records)
        self.write_day("sz/lday/sz000001.day", 20200102)
        config = {"analysis_start": "2025-10-01", "analysis_end": "2025-12-31", "variants": ["legacy"], "horizons": [2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0, "control_iterations": 2, "random_seed": 7, "data_scope_label": "technical_only_no_historical_market_cap_or_st", "price_adjustment": "unadjusted"}
        config_path = Path(self.temp_dir.name) / "config.json"
        output_path = Path(self.temp_dir.name) / "output"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            self.assertEqual(streaming_main(["--source", str(self.source), "--config", str(config_path), "--output", str(output_path), "--progress-interval-seconds", "0"]), 0)

        self.assertIn("progress", stdout.getvalue())
        progress_records = [json.loads(line) for line in (output_path / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue({"signal_audit", "signal_events", "control_events", "sampling_and_writing"}.issubset({record["stage"] for record in progress_records}))
        self.assertEqual(progress_records[-1]["overall_percent"], 100.0)
        self.assertIn("elapsed_seconds", progress_records[-1])
        metadata = json.loads((output_path / "streaming_metadata.json").read_text(encoding="utf-8"))
        self.assertIn("total_elapsed_seconds", metadata)
        self.assertTrue({"signal_audit", "signal_events", "control_events", "sampling_and_writing"}.issubset(metadata["stage_durations_seconds"]))


    def test_close_entry_returns_use_signal_day_close_and_intraday_low_drawdown(self) -> None:
        signals = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-29", "2026-06-30", "2026-07-01"]),
                "code": ["600000", "600000", "600000"],
                "name": ["600000", "600000", "600000"],
                "open": [9.8, 10.8, 8.8],
                "high": [10.2, 11.2, 9.2],
                "low": [9.7, 10.4, 8.0],
                "close": [10.0, 11.0, 9.0],
                "b1_first_trigger": [True, False, False],
            }
        )

        result = _measure_close_entry_returns(signals, [1, 2], pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30"))

        self.assertEqual(result.loc[0, "buy_close"], 10.0)
        self.assertEqual(result.loc[0, "exit_close"], 11.0)
        self.assertAlmostEqual(result.loc[0, "net_return"], 0.1)
        self.assertAlmostEqual(result.loc[1, "net_return"], -0.1)
        self.assertAlmostEqual(result.loc[1, "max_intraday_drawdown"], -0.2)
        self.assertAlmostEqual(result.loc[1, "max_close_drawdown"], -0.1)

    def test_staged_exit_takes_first_profit_level_only(self) -> None:
        signals = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-29", "2026-06-30"]),
                "code": ["600000", "600000"],
                "name": ["600000", "600000"],
                "open": [10.0, 10.0],
                "high": [10.0, 10.6],
                "low": [10.0, 10.1],
                "close": [10.0, 10.2],
                "b1_first_trigger": [True, False],
            }
        )

        events, fills = _measure_staged_exit_returns(
            signals, [1], pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30")
        )

        self.assertAlmostEqual(events.loc[0, "net_return"], (1 / 3) * 0.05 + (2 / 3) * 0.02)
        self.assertEqual(fills.loc[0, "fill_type"], "take_profit")
        self.assertAlmostEqual(fills.loc[0, "sold_fraction"], 1 / 3)
        self.assertAlmostEqual(fills.loc[0, "fill_price"], 10.5)

    def test_staged_exit_same_day_stop_loss_precedes_take_profit(self) -> None:
        signals = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-29", "2026-06-30"]),
                "code": ["600000", "600000"],
                "name": ["600000", "600000"],
                "open": [10.0, 10.0],
                "high": [10.0, 10.8],
                "low": [10.0, 9.4],
                "close": [10.0, 10.2],
                "b1_first_trigger": [True, False],
            }
        )

        events, fills = _measure_staged_exit_returns(
            signals, [1], pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30")
        )

        self.assertAlmostEqual(events.loc[0, "net_return"], -0.05)
        self.assertTrue(bool(events.loc[0, "stop_loss_triggered"]))
        self.assertEqual(events.loc[0, "exit_reason"], "stop_loss")
        self.assertEqual(fills.loc[0, "fill_type"], "stop_loss")
        self.assertAlmostEqual(fills.loc[0, "fill_price"], 9.5)

    def test_staged_exit_fills_multiple_profit_levels_then_expires_remainder(self) -> None:
        signals = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-29", "2026-06-30"]),
                "code": ["600000", "600000"],
                "name": ["600000", "600000"],
                "open": [10.0, 10.0],
                "high": [10.0, 11.2],
                "low": [10.0, 10.4],
                "close": [10.0, 10.3],
                "b1_first_trigger": [True, False],
            }
        )

        events, fills = _measure_staged_exit_returns(
            signals, [1], pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30")
        )

        self.assertAlmostEqual(events.loc[0, "net_return"], (1 / 3) * 0.05 + (1 / 3) * 0.10 + (1 / 3) * 0.03)
        self.assertEqual(fills["fill_type"].tolist(), ["take_profit", "take_profit", "expiry"])
        self.assertEqual(events.loc[0, "take_profit_fill_count"], 2)
        self.assertAlmostEqual(events.loc[0, "remaining_fraction_at_expiry"], 1 / 3)

    def test_staged_exit_summary_reports_rates_and_drawdowns(self) -> None:
        events = pd.DataFrame(
            {
                "horizon": [1, 1, 1],
                "event_id": ["a", "b", "c"],
                "net_return": [0.05, -0.05, 0.01],
                "win": [True, False, True],
                "max_intraday_drawdown": [-0.01, -0.05, -0.02],
                "position_weighted_drawdown": [-0.01, -0.05, -0.01],
                "take_profit_fill_count": [1, 0, 0],
                "stop_loss_triggered": [False, True, False],
                "exit_reason": ["expiry", "stop_loss", "expiry"],
                "status": ["filled", "filled", "filled"],
            }
        )

        summary = _summarize_staged_exit_events(events)

        self.assertEqual(summary.loc[0, "event_count"], 3)
        self.assertAlmostEqual(summary.loc[0, "win_rate"], 2 / 3)
        self.assertAlmostEqual(summary.loc[0, "stop_loss_rate"], 1 / 3)
        self.assertAlmostEqual(summary.loc[0, "expiry_exit_rate"], 2 / 3)
        self.assertAlmostEqual(summary.loc[0, "worst_intraday_drawdown"], -0.05)

    def test_streaming_cli_writes_close_entry_backtest_outputs(self) -> None:
        records = []
        for index, date in enumerate(pd.bdate_range("2026-05-20", periods=45)):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 20, price - 20, price + 10, 0.0, 10000 + index * 100, 0))
        self.write_records("sh/lday/sh600000.day", records)
        config = {"analysis_start": "2026-01-01", "analysis_end": "2026-12-31", "variants": ["legacy", "bbi", "b1"], "horizons": [1, 2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0, "control_iterations": 2, "random_seed": 7, "data_scope_label": "technical_only_no_historical_market_cap_or_st", "price_adjustment": "unadjusted"}
        config_path = Path(self.temp_dir.name) / "config.json"
        output_path = Path(self.temp_dir.name) / "close_entry_output"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        self.assertEqual(
            streaming_main(
                [
                    "--source", str(self.source),
                    "--config", str(config_path),
                    "--output", str(output_path),
                    "--mode", "close-entry-b1",
                    "--analysis-start", "2026-06-01",
                    "--analysis-end", "2026-06-30",
                    "--horizons", "1", "2",
                ]
            ),
            0,
        )

        self.assertTrue((output_path / "close_entry_events.csv").exists())
        self.assertTrue((output_path / "close_entry_summary.csv").exists())
        metadata = json.loads((output_path / "close_entry_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["mode"], "close-entry-b1")
        self.assertEqual(metadata["analysis_start"], "2026-06-01")
        self.assertEqual(metadata["analysis_end"], "2026-06-30")

    def test_streaming_cli_writes_staged_exit_backtest_outputs(self) -> None:
        records = []
        for index, date in enumerate(pd.bdate_range("2026-05-20", periods=45)):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 80, price - 20, price + 10, 0.0, 10000 + index * 100, 0))
        self.write_records("sh/lday/sh600000.day", records)
        config = {"analysis_start": "2026-01-01", "analysis_end": "2026-12-31", "variants": ["legacy", "bbi", "b1"], "horizons": [1, 2], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0, "control_iterations": 2, "random_seed": 7, "data_scope_label": "technical_only_no_historical_market_cap_or_st", "price_adjustment": "unadjusted"}
        config_path = Path(self.temp_dir.name) / "config.json"
        output_path = Path(self.temp_dir.name) / "staged_exit_output"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        self.assertEqual(
            streaming_main(
                [
                    "--source", str(self.source),
                    "--config", str(config_path),
                    "--output", str(output_path),
                    "--mode", "staged-exit-b1",
                    "--analysis-start", "2026-06-01",
                    "--analysis-end", "2026-06-30",
                    "--horizons", "1", "2",
                ]
            ),
            0,
        )

        expected = {"staged_exit_events.csv", "staged_exit_fills.csv", "staged_exit_summary.csv", "staged_exit_metadata.json", "staged_exit_report.md"}
        self.assertTrue(expected.issubset({path.name for path in output_path.iterdir()}))
        metadata = json.loads((output_path / "staged_exit_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["mode"], "staged-exit-b1")
        self.assertEqual(metadata["analysis_start"], "2026-06-01")
        self.assertEqual(metadata["analysis_end"], "2026-06-30")
        self.assertIn("suspension_status_unavailable", metadata["field_limitations"])

    def test_close_entry_cli_uses_stock_pool(self) -> None:
        records = []
        for index, date in enumerate(pd.bdate_range("2026-05-20", periods=45)):
            price = 1000 + index * 10
            records.append((int(date.strftime("%Y%m%d")), price, price + 20, price - 20, price + 10, 0.0, 10000 + index * 100, 0))
        self.write_records("sh/lday/sh688001.day", records)
        self.write_records("sh/lday/sh600000.day", records)
        pool_path = Path(self.temp_dir.name) / "pool.csv"
        pool_path.write_text("code\n688001\n", encoding="utf-8")
        config = {"analysis_start": "2026-01-01", "analysis_end": "2026-12-31", "variants": ["legacy", "bbi", "b1"], "horizons": [1], "require_core_pool": False, "min_market_cap": 0, "j_threshold": 100.0, "pit_lookback": 5, "volume_multiplier": 1.0, "event_notional": 100000, "lot_size": 100, "commission_rate": 0.0, "minimum_commission": 0.0, "sell_stamp_duty_rate": 0.0, "control_iterations": 2, "random_seed": 7, "data_scope_label": "technical_only_no_historical_market_cap_or_st", "price_adjustment": "unadjusted"}
        config_path = Path(self.temp_dir.name) / "config.json"
        output_path = Path(self.temp_dir.name) / "pooled_output"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        self.assertEqual(streaming_main(["--source", str(self.source), "--config", str(config_path), "--output", str(output_path), "--mode", "close-entry-b1", "--analysis-start", "2026-06-01", "--analysis-end", "2026-06-30", "--horizons", "1", "--stock-pool", str(pool_path)]), 0)

        metadata = json.loads((output_path / "close_entry_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["stock_pool_count"], 1)
        events = pd.read_csv(output_path / "close_entry_events.csv", dtype={"code": str})
        self.assertEqual(set(events["code"]), {"688001"})
if __name__ == "__main__":
    unittest.main()
