from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from a_share_backtesting.market_regime import build_market_regime_schedule
from tools import run_active_market_cap_comparison as driver


class MatrixDefinitionTests(unittest.TestCase):
    def test_matrix_has_sixteen_deterministic_unique_run_keys(self) -> None:
        first = driver.build_matrix()
        second = driver.build_matrix()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertEqual(len({job.run_key for job in first}), 16)
        self.assertEqual(
            [job.run_key for job in first],
            [
                f"{pool}__{position}__{timing}"
                for pool in (
                    "ai_semiconductor",
                    "innovative_drug",
                    "battery",
                    "humanoid_robot_proxy",
                )
                for position in ("canonical", "risk025")
                for timing in ("same_day_1455", "next_session_0935")
            ],
        )

    def test_frozen_pool_position_and_baseline_mappings_are_explicit(self) -> None:
        expected_pools = {
            "ai_semiconductor": (
                "outputs/qfq_ai_semiconductor_20260718/qfq_bars.csv",
                "config/ai_semiconductor_stock_pool_20260715.csv",
                "outputs/intraday_b1_warmup180_20260718/ai_semiconductor/signal_scans.csv",
            ),
            "innovative_drug": (
                "outputs/qfq_sector_pools_20260718/qfq_bars.csv",
                "config/innovative_drug_931440_stock_pool_20260630.csv",
                "outputs/intraday_b1_warmup180_20260718/innovative_drug/signal_scans.csv",
            ),
            "battery": (
                "outputs/qfq_sector_pools_20260718/qfq_bars.csv",
                "config/battery_931719_stock_pool_20260630.csv",
                "outputs/intraday_b1_warmup180_20260718/battery/signal_scans.csv",
            ),
            "humanoid_robot_proxy": (
                "outputs/qfq_sector_pools_20260718/qfq_bars.csv",
                "config/humanoid_robot_proxy_980022_stock_pool_20260717.csv",
                "outputs/intraday_b1_warmup180_20260718/humanoid_robot_proxy/signal_scans.csv",
            ),
        }
        actual_pools = {
            key: (value.qfq_source, value.stock_pool, value.scan_source)
            for key, value in driver.POOL_SOURCES.items()
        }
        self.assertEqual(actual_pools, expected_pools)
        self.assertEqual(
            {key: value.config for key, value in driver.POSITION_CONFIGS.items()},
            {
                "canonical": "config/intraday_portfolio_20260718.json",
                "risk025": "config/intraday_portfolio_risk_controlled_20260718.json",
            },
        )
        self.assertEqual(
            driver.BASELINE_SOURCES,
            {
                (pool, position): (
                    f"outputs/intraday_b1_final_verified_20260718/"
                    f"{pool if pool != 'ai_semiconductor' else 'ai'}_{position}_20260717"
                )
                for pool in expected_pools
                for position in ("canonical", "risk025")
            },
        )

    def test_jobs_execute_single_day_config_with_tested_cli_arguments(self) -> None:
        job = driver.build_matrix()[0]
        argv = driver.cli_arguments(
            job,
            minute_root=Path("D:/minute"),
            output_root=Path("C:/matrix"),
            repo_root=Path("C:/repo"),
        )

        self.assertEqual(
            argv,
            [
                "--minute-root",
                str(Path("D:/minute")),
                "--qfq-source",
                str(Path("C:/repo/outputs/qfq_ai_semiconductor_20260718/qfq_bars.csv")),
                "--stock-pool",
                str(Path("C:/repo/config/ai_semiconductor_stock_pool_20260715.csv")),
                "--config",
                str(Path("C:/repo/config/intraday_portfolio_20260718.json")),
                "--scan-source",
                str(
                    Path(
                        "C:/repo/outputs/intraday_b1_warmup180_20260718/"
                        "ai_semiconductor/signal_scans.csv"
                    )
                ),
                "--market-regime",
                str(
                    Path(
                        "C:/repo/config/"
                        "active_market_cap_single_day_4pct_same_day_20260719.json"
                    )
                ),
                "--output",
                str(Path("C:/matrix") / job.run_key),
                "--analysis-start",
                "2026-06-01",
                "--analysis-end",
                "2026-07-17",
            ],
        )
        self.assertNotIn("two_day", " ".join(argv))


class ScheduleSafetyTests(unittest.TestCase):
    def _config(self, events: list[dict[str, str]]) -> dict[str, object]:
        return {
            "observation_start": "2026-06-01",
            "initial_state": "risk_off",
            "execution_mode": "same_day_1455",
            "events": events,
        }

    def test_state_window_equality_ignores_idempotent_confirmation(self) -> None:
        dates = pd.bdate_range("2026-06-01", "2026-06-30")
        single = build_market_regime_schedule(
            self._config([{"signal_date": "2026-06-15", "event": "up", "label": "up"}]),
            dates,
        )
        two_day = build_market_regime_schedule(
            self._config(
                [
                    {"signal_date": "2026-06-15", "event": "up", "label": "up"},
                    {"signal_date": "2026-06-22", "event": "up", "label": "confirmation"},
                ]
            ),
            dates,
        )

        driver.assert_equal_state_windows(single, two_day)

    def test_state_window_inequality_refuses_execution(self) -> None:
        dates = pd.bdate_range("2026-06-01", "2026-06-30")
        single = build_market_regime_schedule(
            self._config([{"signal_date": "2026-06-15", "event": "up", "label": "up"}]),
            dates,
        )
        two_day = build_market_regime_schedule(
            self._config([{"signal_date": "2026-06-16", "event": "up", "label": "late"}]),
            dates,
        )

        with self.assertRaisesRegex(ValueError, "state windows differ"):
            driver.assert_equal_state_windows(single, two_day)

    def test_all_schedule_validation_finishes_before_first_cli_call(self) -> None:
        cli = Mock(return_value=0)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                patch.object(driver, "validate_all_schedule_pairs", side_effect=ValueError("state windows differ")),
                patch.object(driver, "write_run_source_manifest"),
            ):
                with self.assertRaisesRegex(ValueError, "state windows differ"):
                    driver.run_matrix(Path("D:/minute"), output, cli_main=cli)

        cli.assert_not_called()


class DriverFailureTests(unittest.TestCase):
    def _run_with_cli(self, cli: Mock) -> int:
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(driver, "validate_all_schedule_pairs"),
                patch.object(driver, "write_run_source_manifest"),
                patch.object(driver, "reconcile_run_artifacts"),
            ):
                return driver.run_matrix(Path("D:/minute"), Path(temporary), cli_main=cli)

    def test_nonzero_cli_exit_fails_fast(self) -> None:
        cli = Mock(side_effect=[0, 7, 0])

        with self.assertRaisesRegex(RuntimeError, "exit code 7"):
            self._run_with_cli(cli)

        self.assertEqual(cli.call_count, 2)

    def test_cli_exception_propagates_and_stops_matrix(self) -> None:
        cli = Mock(side_effect=OSError("minute source unavailable"))

        with self.assertRaisesRegex(OSError, "minute source unavailable"):
            self._run_with_cli(cli)

        self.assertEqual(cli.call_count, 1)


class ManifestTests(unittest.TestCase):
    def test_run_source_manifest_is_deterministic_and_repository_relative(self) -> None:
        jobs = driver.build_matrix()
        paths = driver.frozen_source_paths(jobs)
        hashes = {path: f"sha256-{index:02d}" for index, path in enumerate(reversed(paths))}

        first = driver.serialize_run_source_manifest(jobs, hashes)
        second = driver.serialize_run_source_manifest(jobs, dict(reversed(list(hashes.items()))))

        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(len(payload["runs"]), 16)
        self.assertEqual(list(payload["source_sha256"]), sorted(paths))
        self.assertTrue(all(not Path(path).is_absolute() for path in payload["source_sha256"]))
        self.assertNotIn("generated_at", payload)


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def valid_frames() -> dict[str, pd.DataFrame]:
    schemas = driver.CSV_SCHEMAS
    frames = {name: _empty(columns) for name, columns in schemas.items()}
    frames["fills.csv"] = pd.DataFrame(
        [
            {
                "position_id": "000001:202606021455",
                "code": "000001",
                "timestamp": "2026-06-02 14:55:00",
                "side": "buy",
                "reason": "entry",
                "shares": 100,
                "raw_price": 10.0,
                "adjusted_price": 10.0,
                "gross_notional": 1000.0,
                "commission": 0.0,
                "stamp_duty": 0.0,
                "slippage_cost": 0.0,
                "cash_delta": -1000.0,
            },
            {
                "position_id": "000001:202606021455",
                "code": "000001",
                "timestamp": "2026-06-03 14:55:00",
                "side": "sell",
                "reason": "market_regime_exit",
                "shares": 60,
                "raw_price": 10.0,
                "adjusted_price": 10.0,
                "gross_notional": 600.0,
                "commission": 0.0,
                "stamp_duty": 0.0,
                "slippage_cost": 0.0,
                "cash_delta": 600.0,
            },
        ],
        columns=schemas["fills.csv"],
    )
    frames["positions.csv"] = pd.DataFrame(
        [
            {
                "timestamp": "2026-06-02 14:55:00",
                "position_id": "000001:202606021455",
                "code": "000001",
                "remaining_shares": 100,
                "market_value": 1000.0,
                "position_return": 0.0,
                "position_return_low": 0.0,
            },
            {
                "timestamp": "2026-06-03 15:00:00",
                "position_id": "000001:202606021455",
                "code": "000001",
                "remaining_shares": 40,
                "market_value": 400.0,
                "position_return": 0.0,
                "position_return_low": 0.0,
            },
        ],
        columns=schemas["positions.csv"],
    )
    frames["trades.csv"] = pd.DataFrame(
        [
            {
                "position_id": "000001:202606021455",
                "code": "000001",
                "entry_timestamp": "2026-06-02 14:55:00",
                "exit_timestamp": pd.NA,
                "status": "open",
                "exit_reason": "open_at_end",
                "entry_cost": 1000.0,
                "net_proceeds": 600.0,
                "net_pnl": 0.0,
                "net_return": 0.0,
                "holding_days": 1,
                "maximum_adverse_excursion": 0.0,
            }
        ],
        columns=schemas["trades.csv"],
    )
    nav = pd.DataFrame(
        [
            {
                "timestamp": "2026-06-03 15:00:00",
                "date": "2026-06-03",
                "cash": 600.0,
                "gross_exposure": 400.0,
                "positions": 1,
                "nav": 1000.0,
                "nav_low": 1000.0,
            }
        ],
        columns=schemas["nav_5m.csv"],
    )
    frames["nav_5m.csv"] = nav
    frames["nav_daily.csv"] = nav.copy()
    frames["portfolio_summary.csv"] = pd.DataFrame(
        [[1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.4, 0.4, 1, 1.6, 0.0, 0.0, 0.0]],
        columns=schemas["portfolio_summary.csv"],
    )
    frames["comparison.csv"] = frames["portfolio_summary.csv"].assign(
        mode="intraday_portfolio", start="2026-06-01", end="2026-06-03"
    )
    frames["market_regime.csv"] = pd.DataFrame(
        [
            {
                "signal_date": "2026-06-01",
                "effective_timestamp": "2026-06-01 14:55:00",
                "event": "down",
                "label": "closed",
                "prior_state": "risk_off",
                "resulting_state": "risk_off",
                "execution_mode": "same_day_1455",
            },
            {
                "signal_date": "2026-06-02",
                "effective_timestamp": "2026-06-02 14:55:00",
                "event": "up",
                "label": "open",
                "prior_state": "risk_off",
                "resulting_state": "risk_on",
                "execution_mode": "same_day_1455",
            },
            {
                "signal_date": "2026-06-03",
                "effective_timestamp": "2026-06-03 14:55:00",
                "event": "down",
                "label": "close",
                "prior_state": "risk_on",
                "resulting_state": "risk_off",
                "execution_mode": "same_day_1455",
            },
        ],
        columns=schemas["market_regime.csv"],
    )
    return frames


class ArtifactReconciliationTests(unittest.TestCase):
    def test_valid_partial_regime_exit_reconciles_with_final_open_remainder(self) -> None:
        frames = valid_frames()

        driver.reconcile_frames(frames)

    def test_ending_cash_plus_exposure_must_equal_nav(self) -> None:
        frames = valid_frames()
        frames["nav_5m.csv"].loc[0, "nav"] = 999.0

        with self.assertRaisesRegex(driver.ReconciliationError, "cash plus exposure"):
            driver.reconcile_nav(frames)

    def test_sold_shares_cannot_exceed_bought_shares(self) -> None:
        frames = valid_frames()
        frames["fills.csv"].loc[1, "shares"] = 101

        with self.assertRaisesRegex(driver.ReconciliationError, "sold shares exceed bought"):
            driver.reconcile_share_balances(frames)

    def test_same_code_positions_cannot_overlap(self) -> None:
        frames = valid_frames()
        duplicate = frames["positions.csv"].iloc[-1].copy()
        duplicate["position_id"] = "000001:202606031455"
        frames["positions.csv"] = pd.concat(
            [frames["positions.csv"], duplicate.to_frame().T], ignore_index=True
        )

        with self.assertRaisesRegex(driver.ReconciliationError, "same-code overlap"):
            driver.reconcile_position_constraints(frames)

    def test_portfolio_cannot_exceed_three_holdings(self) -> None:
        frames = valid_frames()
        frames["nav_5m.csv"].loc[0, "positions"] = 4

        with self.assertRaisesRegex(driver.ReconciliationError, "more than 3 holdings"):
            driver.reconcile_position_constraints(frames)

    def test_entry_fill_is_forbidden_during_risk_off(self) -> None:
        frames = valid_frames()
        frames["fills.csv"].loc[0, "timestamp"] = "2026-06-01 14:55:00"

        with self.assertRaisesRegex(driver.ReconciliationError, "entry fill in risk_off"):
            driver.reconcile_risk_off_entries(frames)

    def test_regime_exit_requires_exact_final_remainder(self) -> None:
        frames = valid_frames()
        frames["positions.csv"].loc[1, "remaining_shares"] = 39

        with self.assertRaisesRegex(driver.ReconciliationError, "regime shares do not reconcile"):
            driver.reconcile_regime_exits(frames)

    def test_artifact_parser_rejects_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            frames = valid_frames()
            frames["fills.csv"] = frames["fills.csv"].drop(columns="cash_delta")
            for name, frame in frames.items():
                frame.to_csv(run_dir / name, index=False)
            (run_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "mode": "intraday-b1-portfolio",
                        "analysis_start": "2026-06-01",
                        "analysis_end": "2026-06-03",
                        "market_regime_source": "synthetic.json",
                        "market_regime_source_sha256": "0" * 64,
                        "outputs": [*driver.REQUIRED_OUTPUTS, "market_regime.csv"],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "report.md").write_text("synthetic\n", encoding="utf-8")

            with self.assertRaisesRegex(driver.ReconciliationError, "fills.csv schema drift"):
                driver.parse_run_artifacts(run_dir)


if __name__ == "__main__":
    unittest.main()
