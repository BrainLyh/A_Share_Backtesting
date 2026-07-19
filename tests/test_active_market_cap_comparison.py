from __future__ import annotations

import hashlib
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
            {key: value.target_fraction for key, value in driver.POSITION_CONFIGS.items()},
            {"canonical": 1.0 / 3.0, "risk025": 0.25},
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
        self.assertIn(
            "outputs/intraday_b1_final_verified_20260718/"
            "ai_canonical_20260717/nav_daily.csv",
            payload["source_sha256"],
        )
        self.assertEqual(
            payload["runs"][0]["baseline_calendar"],
            "outputs/intraday_b1_final_verified_20260718/"
            "ai_canonical_20260717/nav_daily.csv",
        )
        self.assertNotIn("generated_at", payload)


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def valid_frames(execution_mode: str = "same_day_1455") -> dict[str, pd.DataFrame]:
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
    frames["trade_summary.csv"] = pd.DataFrame(
        [
            {
                "closed_trade_count": 0,
                "open_trade_count": 1,
                "win_rate": float("nan"),
                "mean_net_return": float("nan"),
                "median_net_return": float("nan"),
                "profit_factor": float("nan"),
                "payoff_ratio": float("nan"),
                "expectancy": float("nan"),
                "average_holding_days": float("nan"),
                "maximum_consecutive_losses": 0,
                "take_profit_trade_rate": float("nan"),
                "stop_exit_rate": float("nan"),
                "residual_exit_rate": float("nan"),
                "expiry_exit_rate": float("nan"),
                "overtime_exit_rate": float("nan"),
                "mean_maximum_adverse_excursion": float("nan"),
                "worst_maximum_adverse_excursion": float("nan"),
            }
        ],
        columns=schemas["trade_summary.csv"],
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
                "execution_mode": execution_mode,
            },
            {
                "signal_date": "2026-06-02",
                "effective_timestamp": "2026-06-02 14:55:00",
                "event": "up",
                "label": "open",
                "prior_state": "risk_off",
                "resulting_state": "risk_on",
                "execution_mode": execution_mode,
            },
            {
                "signal_date": "2026-06-03",
                "effective_timestamp": "2026-06-03 14:55:00",
                "event": "down",
                "label": "close",
                "prior_state": "risk_on",
                "resulting_state": "risk_off",
                "execution_mode": execution_mode,
            },
        ],
        columns=schemas["market_regime.csv"],
    )
    return frames


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runner_file_source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(bytes.fromhex(_file_sha256(path)))
    return digest.hexdigest()


def prepare_frozen_repo(root: Path) -> None:
    jobs = driver.build_matrix()
    for relative in driver.frozen_source_paths(jobs):
        _write(root / relative, "synthetic-source\n")

    for position, sources in driver.POSITION_CONFIGS.items():
        _write(
            root / sources.config,
            json.dumps(
                {
                    "target_fraction": 1.0 / 3.0 if position == "canonical" else 0.25,
                }
            ),
        )

    events = [
        {"signal_date": "2026-06-01", "event": "down", "label": "closed"},
        {"signal_date": "2026-06-02", "event": "up", "label": "open"},
        {"signal_date": "2026-06-03", "event": "down", "label": "closed_again"},
    ]
    for timing, sources in driver.TIMING_CONFIGS.items():
        payload = {
            "observation_start": "2026-06-01",
            "initial_state": "risk_off",
            "execution_mode": timing,
            "events": events,
        }
        _write(root / sources.single_day_config, json.dumps(payload))
        _write(root / sources.two_day_config, json.dumps(payload))

    calendar = pd.DataFrame(
        {"date": pd.bdate_range("2026-06-01", "2026-07-20").strftime("%Y-%m-%d")}
    ).to_csv(index=False)
    for baseline in driver.BASELINE_SOURCES.values():
        _write(root / baseline / "nav_daily.csv", calendar)
        _write(root / baseline / "run_manifest.json", "{}\n")


def valid_manifest(job: driver.MatrixRun, repo_root: Path) -> dict[str, object]:
    qfq = repo_root / job.qfq_source
    pool = repo_root / job.stock_pool
    config = repo_root / job.config
    scan = repo_root / job.scan_source
    regime = repo_root / job.single_day_config
    return {
        "mode": "intraday-b1-portfolio",
        "analysis_start": driver.ANALYSIS_START,
        "analysis_end": driver.ANALYSIS_END,
        "qfq_source": str(qfq.resolve()),
        "qfq_source_sha256": _runner_file_source_sha256(qfq),
        "stock_pool_sha256": _file_sha256(pool),
        "config_sha256": _file_sha256(config),
        "scan_source": str(scan.resolve()),
        "scan_source_sha256": _file_sha256(scan),
        "execution_config": {
            "target_fraction": driver.POSITION_CONFIGS[job.position].target_fraction,
        },
        "market_regime_source": str(regime.resolve()),
        "market_regime_source_sha256": _file_sha256(regime),
        "outputs": [*driver.REQUIRED_OUTPUTS, "market_regime.csv"],
    }


def write_run_artifacts(
    run_dir: Path,
    frames: dict[str, pd.DataFrame],
    manifest: dict[str, object],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(run_dir / name, index=False)
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "report.md").write_text("synthetic\n", encoding="utf-8")


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

    def test_every_open_position_requires_exact_final_remainder_without_regime_fill(self) -> None:
        frames = valid_frames()
        frames["fills.csv"].loc[1, "reason"] = "take_profit_1"
        frames["positions.csv"].loc[1, "remaining_shares"] = 39

        with self.assertRaisesRegex(driver.ReconciliationError, "share balance does not reconcile"):
            driver.reconcile_share_balances(frames)

    def test_closed_trade_must_have_zero_final_remainder(self) -> None:
        frames = valid_frames()
        frames["fills.csv"].loc[1, "shares"] = 100
        frames["trades.csv"].loc[0, "status"] = "closed"
        frames["trades.csv"].loc[0, "exit_timestamp"] = "2026-06-03 14:55:00"

        with self.assertRaisesRegex(driver.ReconciliationError, "closed trade has final remainder"):
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
            driver.reconcile_regime_liquidation_intent(frames)

    def test_entry_after_risk_on_is_forbidden_while_prior_down_target_remains(self) -> None:
        frames = valid_frames()
        frames["market_regime.csv"] = pd.concat(
            [
                frames["market_regime.csv"],
                pd.DataFrame(
                    [
                        {
                            "signal_date": "2026-06-04",
                            "effective_timestamp": "2026-06-04 09:35:00",
                            "event": "up",
                            "label": "reopened",
                            "prior_state": "risk_off",
                            "resulting_state": "risk_on",
                            "execution_mode": "same_day_1455",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        new_buy = frames["fills.csv"].iloc[0].copy()
        new_buy["position_id"] = "000002:202606040935"
        new_buy["code"] = "000002"
        new_buy["timestamp"] = "2026-06-04 09:35:00"
        frames["fills.csv"] = pd.concat(
            [frames["fills.csv"], new_buy.to_frame().T], ignore_index=True
        )

        with self.assertRaisesRegex(
            driver.ReconciliationError, "entry while regime liquidation remains"
        ):
            driver.reconcile_regime_liquidation_intent(frames)

    def test_same_timestamp_exit_must_precede_entry_after_reopen(self) -> None:
        frames = valid_frames()
        frames["market_regime.csv"] = pd.concat(
            [
                frames["market_regime.csv"],
                pd.DataFrame(
                    [
                        {
                            "signal_date": "2026-06-04",
                            "effective_timestamp": "2026-06-04 09:35:00",
                            "event": "up",
                            "label": "reopened",
                            "prior_state": "risk_off",
                            "resulting_state": "risk_on",
                            "execution_mode": "same_day_1455",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        final_sell = frames["fills.csv"].iloc[1].copy()
        final_sell["timestamp"] = "2026-06-04 09:35:00"
        final_sell["shares"] = 40
        new_buy = frames["fills.csv"].iloc[0].copy()
        new_buy["position_id"] = "000002:202606040935"
        new_buy["code"] = "000002"
        new_buy["timestamp"] = "2026-06-04 09:35:00"
        original = frames["fills.csv"].iloc[:2]
        frames["fills.csv"] = pd.concat(
            [original, final_sell.to_frame().T, new_buy.to_frame().T], ignore_index=True
        )

        driver.reconcile_regime_liquidation_intent(frames)

        frames["fills.csv"] = pd.concat(
            [original, new_buy.to_frame().T, final_sell.to_frame().T], ignore_index=True
        )
        with self.assertRaisesRegex(
            driver.ReconciliationError, "entry while regime liquidation remains"
        ):
            driver.reconcile_regime_liquidation_intent(frames)

    def test_regime_exit_requires_exact_final_remainder(self) -> None:
        frames = valid_frames()
        frames["positions.csv"].loc[1, "remaining_shares"] = 39

        with self.assertRaisesRegex(driver.ReconciliationError, "regime shares do not reconcile"):
            driver.reconcile_regime_exits(frames)

    def test_artifact_parser_rejects_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            prepare_frozen_repo(repo_root)
            job = driver.build_matrix()[0]
            run_dir = repo_root / "run"
            frames = valid_frames()
            frames["fills.csv"] = frames["fills.csv"].drop(columns="cash_delta")
            write_run_artifacts(run_dir, frames, valid_manifest(job, repo_root))

            with self.assertRaisesRegex(driver.ReconciliationError, "fills.csv schema drift"):
                driver.parse_run_artifacts(run_dir, job, repo_root)

    def test_artifact_parser_rejects_mismatched_manifest_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            prepare_frozen_repo(repo_root)
            job = driver.build_matrix()[0]
            run_dir = repo_root / "run"
            manifest = valid_manifest(job, repo_root)
            mismatch_cases = {
                "analysis dates": ("analysis_end", "2026-07-16"),
                "qfq path": ("qfq_source", str((repo_root / "wrong.csv").resolve())),
                "qfq hash": ("qfq_source_sha256", "1" * 64),
                "stock pool hash": ("stock_pool_sha256", "2" * 64),
                "config hash": ("config_sha256", "3" * 64),
                "scan path": ("scan_source", str((repo_root / "wrong.csv").resolve())),
                "scan hash": ("scan_source_sha256", "4" * 64),
                "regime path": (
                    "market_regime_source",
                    str((repo_root / "wrong.json").resolve()),
                ),
                "regime hash": ("market_regime_source_sha256", "5" * 64),
                "outputs": ("outputs", []),
            }
            for label, (field, value) in mismatch_cases.items():
                with self.subTest(label=label):
                    bad = {**manifest, field: value}
                    write_run_artifacts(run_dir, valid_frames(), bad)
                    with self.assertRaisesRegex(driver.ReconciliationError, "manifest mismatch"):
                        driver.parse_run_artifacts(run_dir, job, repo_root)

            bad = {**manifest, "execution_config": {"target_fraction": 0.25}}
            write_run_artifacts(run_dir, valid_frames(), bad)
            with self.assertRaisesRegex(driver.ReconciliationError, "target fraction"):
                driver.parse_run_artifacts(run_dir, job, repo_root)

    def test_artifact_parser_rejects_header_only_critical_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            prepare_frozen_repo(repo_root)
            job = driver.build_matrix()[0]
            run_dir = repo_root / "run"
            for artifact in (
                "market_regime.csv",
                "nav_5m.csv",
                "nav_daily.csv",
                "portfolio_summary.csv",
                "trade_summary.csv",
                "comparison.csv",
            ):
                with self.subTest(artifact=artifact):
                    frames = valid_frames()
                    frames[artifact] = _empty(driver.CSV_SCHEMAS[artifact])
                    write_run_artifacts(run_dir, frames, valid_manifest(job, repo_root))
                    with self.assertRaisesRegex(driver.ReconciliationError, "must not be empty"):
                        driver.parse_run_artifacts(run_dir, job, repo_root)

    def test_artifact_parser_rejects_wrong_timeline_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            prepare_frozen_repo(repo_root)
            job = driver.build_matrix()[0]
            run_dir = repo_root / "run"
            frames = valid_frames("next_session_0935")
            write_run_artifacts(run_dir, frames, valid_manifest(job, repo_root))

            with self.assertRaisesRegex(driver.ReconciliationError, "timeline mode"):
                driver.parse_run_artifacts(run_dir, job, repo_root)


class SyntheticMatrixIntegrationTests(unittest.TestCase):
    def test_all_sixteen_jobs_run_through_real_validation_manifest_and_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output_root = repo_root / "matrix"
            prepare_frozen_repo(repo_root)
            jobs = {job.run_key: job for job in driver.build_matrix()}
            calls: list[str] = []

            def artifact_writing_cli(argv: list[str]) -> int:
                arguments = dict(zip(argv[::2], argv[1::2]))
                run_dir = Path(arguments["--output"])
                job = jobs[run_dir.name]
                calls.append(job.run_key)
                frames = valid_frames(job.timing)
                frames["fills.csv"] = _empty(driver.CSV_SCHEMAS["fills.csv"])
                frames["positions.csv"] = _empty(driver.CSV_SCHEMAS["positions.csv"])
                frames["trades.csv"] = _empty(driver.CSV_SCHEMAS["trades.csv"])
                frames["nav_5m.csv"].loc[:, ["cash", "nav", "nav_low"]] = 1000.0
                frames["nav_5m.csv"].loc[:, "gross_exposure"] = 0.0
                frames["nav_5m.csv"].loc[:, "positions"] = 0
                frames["nav_daily.csv"] = frames["nav_5m.csv"].copy()
                frames["portfolio_summary.csv"].loc[0, "max_positions"] = 0
                frames["trade_summary.csv"].loc[0, "open_trade_count"] = 0
                frames["comparison.csv"] = frames["portfolio_summary.csv"].assign(
                    mode="intraday_portfolio",
                    start=driver.ANALYSIS_START,
                    end=driver.ANALYSIS_END,
                )
                write_run_artifacts(
                    run_dir,
                    frames,
                    valid_manifest(job, repo_root),
                )
                return 0

            completed = driver.run_matrix(
                Path("D:/synthetic-minute-root"),
                output_root,
                repo_root=repo_root,
                cli_main=artifact_writing_cli,
            )

            self.assertEqual(completed, 16)
            self.assertEqual(calls, [job.run_key for job in driver.build_matrix()])
            self.assertTrue((output_root / driver.RUN_SOURCE_MANIFEST).is_file())
            self.assertEqual(
                len([path for path in output_root.iterdir() if path.is_dir()]),
                16,
            )


if __name__ == "__main__":
    unittest.main()
