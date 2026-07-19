from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.market_regime import (
    build_market_regime_schedule,
    load_market_regime_config,
)
from tools import summarize_active_market_cap_comparison as summary


POOLS = (
    "ai_semiconductor",
    "innovative_drug",
    "battery",
    "humanoid_robot_proxy",
)
POSITIONS = ("canonical", "risk025")
TIMINGS = ("same_day_1455", "next_session_0935")
CALENDAR = pd.to_datetime(
    [
        "2026-06-01",
        "2026-06-08",
        "2026-06-09",
        "2026-06-15",
        "2026-06-16",
        "2026-06-22",
        "2026-07-02",
        "2026-07-03",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-13",
        "2026-07-14",
        "2026-07-16",
        "2026-07-17",
    ]
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _drawdown(values: pd.Series, peaks: pd.Series | None = None) -> float:
    high_water = values.cummax() if peaks is None else peaks
    return float((values / high_water - 1.0).min())


def _write_run(
    run_dir: Path,
    *,
    total_return: float,
    drawdown: float,
    closed_count: int,
    timed: bool,
    regime_frame: pd.DataFrame | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    initial_cash = 100.0
    nav_values = pd.Series([100.0] * len(CALENDAR), dtype=float)
    nav_values.iloc[4] = initial_cash * (1.0 + drawdown)
    nav_values.iloc[-1] = initial_cash * (1.0 + total_return)
    nav_low = nav_values.copy()
    nav_low.iloc[4] -= 2.0 if closed_count else 0.0
    capital_utilization = 0.0 if closed_count == 0 else 0.25
    gross_exposure = pd.Series(
        [initial_cash * capital_utilization] * len(CALENDAR), dtype=float
    )
    nav_5m = pd.DataFrame(
        {
            "timestamp": CALENDAR + pd.Timedelta(hours=14, minutes=55),
            "date": CALENDAR,
            "cash": nav_values - gross_exposure,
            "gross_exposure": gross_exposure,
            "positions": 0 if closed_count == 0 else 1,
            "nav": nav_values,
            "nav_low": nav_low,
        }
    )
    nav_daily = nav_5m.copy()
    nav_5m.to_csv(run_dir / "nav_5m.csv", index=False)
    nav_daily.to_csv(run_dir / "nav_daily.csv", index=False)

    trade_rows = []
    for index in range(closed_count):
        net_pnl = 10.0 if index % 2 == 0 else -5.0
        trade_rows.append(
            {
                "position_id": f"position-{index}",
                "code": f"{index:06d}",
                "entry_timestamp": "2026-06-15 14:55:00",
                "exit_timestamp": "2026-06-22 14:55:00",
                "status": "closed",
                "exit_reason": (
                    "market_regime_exit" if timed and index == 0 else "expiry"
                ),
                "entry_cost": 100.0,
                "net_proceeds": 100.0 + net_pnl,
                "net_pnl": net_pnl,
                "net_return": net_pnl / 100.0,
                "holding_days": 3,
                "maximum_adverse_excursion": -0.02,
            }
        )
    trades = pd.DataFrame(trade_rows, columns=summary.TRADE_COLUMNS)
    trades.to_csv(run_dir / "trades.csv", index=False)

    fill_rows = []
    if closed_count:
        fill_rows.append(
            {
                "position_id": "position-0",
                "code": "000000",
                "timestamp": "2026-06-15 14:55:00",
                "side": "buy",
                "reason": "entry",
                "shares": 1,
                "raw_price": 100.0,
                "adjusted_price": 100.0,
                "gross_notional": 100.0,
                "commission": 0.0,
                "stamp_duty": 0.0,
                "slippage_cost": 0.0,
                "cash_delta": -100.0,
            }
        )
    fills = pd.DataFrame(fill_rows, columns=summary.FILL_COLUMNS)
    fills.to_csv(run_dir / "fills.csv", index=False)

    closed = trades.loc[trades["status"].eq("closed")]
    wins = closed.loc[closed["net_pnl"] > 0, "net_pnl"]
    losses = closed.loc[closed["net_pnl"] < 0, "net_pnl"]
    if not losses.empty:
        profit_factor = float(wins.sum() / abs(losses.sum()))
    elif not wins.empty:
        profit_factor = float("inf")
    else:
        profit_factor = float("nan")
    portfolio = pd.DataFrame(
        [
            {
                "initial_cash": initial_cash,
                "final_nav": float(nav_values.iloc[-1]),
                "total_net_return": float(nav_values.iloc[-1] / initial_cash - 1.0),
                "max_drawdown_5m": _drawdown(nav_values),
                "max_drawdown_low": _drawdown(nav_low, nav_values.cummax()),
                "max_drawdown_daily": _drawdown(nav_values),
                "capital_utilization": capital_utilization,
                "turnover": float(fills["gross_notional"].sum() / initial_cash),
            }
        ]
    )
    portfolio.to_csv(run_dir / "portfolio_summary.csv", index=False)
    trade_summary = pd.DataFrame(
        [
            {
                "closed_trade_count": closed_count,
                "open_trade_count": 0,
                "win_rate": (
                    float((closed["net_pnl"] > 0).mean())
                    if closed_count
                    else float("nan")
                ),
                "profit_factor": profit_factor,
            }
        ]
    )
    trade_summary.to_csv(run_dir / "trade_summary.csv", index=False)
    if timed:
        assert regime_frame is not None
        regime_frame.to_csv(run_dir / "market_regime.csv", index=False)


class SyntheticMatrix:
    def __init__(self, root: Path) -> None:
        self.repo_root = root
        self.matrix_root = root / "outputs" / "matrix"
        self.output_root = root / "outputs" / "summary"
        self.matrix_root.mkdir(parents=True)
        (root / "config").mkdir()
        self.config_paths = self._write_configs()
        portfolio_config = root / "config" / "portfolio.json"
        portfolio_config.write_text('{"initial_cash": 100.0}\n', encoding="utf-8")
        self.portfolio_config = portfolio_config.relative_to(root).as_posix()
        self.runs = self._write_runs()
        source_paths = [*self.config_paths.values(), self.portfolio_config]
        self.manifest = {
            "analysis_start": "2026-06-01",
            "analysis_end": "2026-07-17",
            "matrix_dimensions": {
                "pools": list(POOLS),
                "position_configs": list(POSITIONS),
                "timing_modes": list(TIMINGS),
            },
            "runs": self.runs,
            "source_sha256": {
                path: _sha256(root / path) for path in sorted(source_paths)
            },
        }
        self.manifest_path = self.matrix_root / "run_sources.json"
        self._save_manifest()

    def _write_configs(self) -> dict[tuple[str, str], str]:
        common_events = [
            ("2026-06-08", "down"),
            ("2026-06-15", "up"),
            ("2026-07-02", "down"),
            ("2026-07-07", "down"),
            ("2026-07-08", "down"),
            ("2026-07-13", "down"),
            ("2026-07-16", "down"),
            ("2026-07-17", "down"),
        ]
        paths: dict[tuple[str, str], str] = {}
        for definition in ("single_day_4pct", "two_day_total_4pct"):
            for timing in TIMINGS:
                events = list(common_events)
                if definition == "two_day_total_4pct":
                    events.insert(2, ("2026-06-22", "up"))
                payload: dict[str, object] = {
                    "timing_definition": definition,
                    "observation_start": "2026-06-01",
                    "initial_state": "risk_off",
                    "execution_mode": timing,
                    "events": [
                        {
                            "signal_date": date,
                            "event": event,
                            "label": f"{definition}_{event}_{date}",
                        }
                        for date, event in events
                    ],
                }
                if timing == "next_session_0935":
                    payload["calendar_extension_dates"] = ["2026-07-20"]
                    payload["calendar_extension_source"] = "https://example.test/calendar"
                relative = (
                    f"config/active_market_cap_{definition}_{timing}_20260719.json"
                )
                (self.repo_root / relative).write_text(
                    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                )
                paths[(definition, timing)] = relative
        return paths

    def _schedule(self, timing: str) -> pd.DataFrame:
        path = self.repo_root / self.config_paths[("single_day_4pct", timing)]
        config = load_market_regime_config(path)
        dates = list(CALENDAR)
        dates.extend(pd.to_datetime(config.get("calendar_extension_dates", [])))
        return build_market_regime_schedule(config, dates).timeline

    def _write_runs(self) -> list[dict[str, str]]:
        pool_values = {
            "ai_semiconductor": (0.05, 0.08, 0.06, -0.10, 3),
            "innovative_drug": (0.01, 0.00, 0.00, -0.04, 0),
            "battery": (-0.08, -0.02, -0.03, -0.14, 4),
            "humanoid_robot_proxy": (0.12, 0.02, 0.03, -0.16, 2),
        }
        runs: list[dict[str, str]] = []
        for pool in POOLS:
            baseline_return, same_return, next_return, baseline_dd, timed_count = (
                pool_values[pool]
            )
            for position_index, position in enumerate(POSITIONS):
                offset = position_index * 0.005
                baseline = (
                    f"outputs/baselines/{pool}__{position}"
                )
                _write_run(
                    self.repo_root / baseline,
                    total_return=baseline_return - offset,
                    drawdown=baseline_dd + offset,
                    closed_count=8,
                    timed=False,
                )
                for timing, timing_return in zip(TIMINGS, (same_return, next_return)):
                    run_key = f"{pool}__{position}__{timing}"
                    regime_path = self.config_paths[("single_day_4pct", timing)]
                    runs.append(
                        {
                            "pool": pool,
                            "position_config": position,
                            "timing_mode": timing,
                            "run_key": run_key,
                            "baseline": baseline,
                            "baseline_calendar": f"{baseline}/nav_daily.csv",
                            "config": self.portfolio_config,
                            "market_regime": regime_path,
                            "two_day_equality_source": self.config_paths[
                                ("two_day_total_4pct", timing)
                            ],
                        }
                    )
                    _write_run(
                        self.matrix_root / run_key,
                        total_return=timing_return - offset,
                        drawdown=(baseline_dd / 2.0) + offset,
                        closed_count=timed_count,
                        timed=True,
                        regime_frame=self._schedule(timing),
                    )
        return runs

    def _save_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class MetricRecomputationTests(unittest.TestCase):
    def test_recomputes_metrics_and_preserves_valid_infinite_profit_factor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            _write_run(
                run_dir,
                total_return=0.10,
                drawdown=-0.10,
                closed_count=1,
                timed=False,
            )

            metrics = summary.recompute_run_metrics(run_dir)

            self.assertAlmostEqual(metrics["total_net_return"], 0.10)
            self.assertAlmostEqual(metrics["max_drawdown_5m"], -0.10)
            self.assertAlmostEqual(metrics["max_drawdown_low"], -0.12)
            self.assertAlmostEqual(metrics["max_drawdown_daily"], -0.10)
            self.assertEqual(metrics["closed_trade_count"], 1)
            self.assertEqual(metrics["open_trade_count"], 0)
            self.assertEqual(metrics["win_rate_denominator"], 1)
            self.assertEqual(metrics["win_rate"], 1.0)
            self.assertTrue(math.isinf(metrics["profit_factor"]))
            self.assertAlmostEqual(metrics["capital_utilization"], 0.25)
            self.assertAlmostEqual(metrics["turnover"], 1.0)

    def test_source_summary_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            _write_run(
                run_dir,
                total_return=0.10,
                drawdown=-0.10,
                closed_count=2,
                timed=False,
            )
            portfolio = pd.read_csv(run_dir / "portfolio_summary.csv")
            portfolio.loc[0, "total_net_return"] = 0.99
            portfolio.to_csv(run_dir / "portfolio_summary.csv", index=False)

            with self.assertRaisesRegex(ValueError, "total_net_return"):
                summary.recompute_run_metrics(run_dir)


class CompactSummaryIntegrationTests(unittest.TestCase):
    def test_writes_exact_matrix_deltas_timeline_report_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticMatrix(Path(temporary))

            summary.summarize(
                repo_root=fixture.repo_root,
                matrix_root=fixture.matrix_root,
                output_root=fixture.output_root,
            )

            comparison = pd.read_csv(fixture.output_root / "timing_comparison.csv")
            self.assertEqual(len(comparison), 24)
            self.assertEqual(comparison["comparison_key"].nunique(), 24)
            self.assertEqual(
                set(comparison["timing_variant"]),
                {"baseline", "same_day_1455", "next_session_0935"},
            )
            ai = comparison.loc[
                (comparison["pool"] == "ai_semiconductor")
                & (comparison["position_config"] == "canonical")
            ].set_index("timing_variant")
            self.assertAlmostEqual(ai.loc["same_day_1455", "return_delta_vs_baseline"], 0.03)
            self.assertAlmostEqual(
                ai.loc["same_day_1455", "same_day_minus_next_session_return"],
                0.02,
            )
            self.assertTrue(
                comparison.loc[
                    (comparison["timing_variant"] != "baseline")
                    & (comparison["closed_trade_count"].between(2, 6)),
                    "low_trade_count_flag",
                ].all()
            )
            drug_timed = comparison.loc[
                (comparison["pool"] == "innovative_drug")
                & (comparison["timing_variant"] != "baseline")
            ]
            self.assertTrue(drug_timed["zero_trade_count_flag"].all())
            self.assertTrue((drug_timed["capital_utilization"] == 0.0).all())

            timeline = pd.read_csv(
                fixture.output_root / "regime_timeline_comparison.csv"
            )
            self.assertTrue(timeline["state_windows_equal"].all())
            self.assertEqual(set(timeline["timing_definition"]), {
                "single_day_4pct",
                "two_day_total_4pct",
            })
            self.assertEqual(
                len(timeline.loc[timeline["timing_definition"] == "two_day_total_4pct"]),
                len(timeline.loc[timeline["timing_definition"] == "single_day_4pct"]) + 2,
            )
            terminal = timeline.loc[
                (timeline["execution_mode"] == "next_session_0935")
                & (timeline["signal_date"] == "2026-07-17")
            ]
            self.assertEqual(set(terminal["effective_timestamp"]), {"2026-07-20 09:35:00"})

            report = (fixture.output_root / "report.md").read_text(encoding="utf-8")
            for phrase in (
                "look-ahead",
                "no exposure",
                "2-6 closed trades",
                "post-hoc",
                "manually supplied",
                "no threshold optimization",
            ):
                self.assertIn(phrase, report)
            self.assertIn("8.00%", report)
            self.assertIn("6.00%", report)

            provenance_path = fixture.output_root / "run_sources.json"
            provenance_text = provenance_path.read_text(encoding="utf-8")
            provenance = json.loads(provenance_text)
            self.assertNotIn(str(fixture.repo_root), provenance_text)
            self.assertEqual(
                provenance["full_matrix_source_manifest"]["path"],
                "outputs/matrix/run_sources.json",
            )
            for name in (
                "timing_comparison.csv",
                "regime_timeline_comparison.csv",
                "report.md",
            ):
                self.assertEqual(
                    provenance["generated_sha256"][name],
                    _sha256(fixture.output_root / name),
                )
            expected_consumed = (
                "outputs/baselines/ai_semiconductor__canonical/nav_5m.csv"
            )
            self.assertIn(expected_consumed, provenance["source_sha256"])

    def test_duplicate_and_missing_matrix_runs_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticMatrix(Path(temporary))
            fixture.manifest["runs"].append(dict(fixture.manifest["runs"][0]))
            fixture._save_manifest()
            with self.assertRaisesRegex(ValueError, "duplicate"):
                summary.summarize(
                    repo_root=fixture.repo_root,
                    matrix_root=fixture.matrix_root,
                    output_root=fixture.output_root,
                )

            fixture.manifest["runs"] = fixture.manifest["runs"][:-2]
            fixture._save_manifest()
            with self.assertRaisesRegex(ValueError, "missing"):
                summary.summarize(
                    repo_root=fixture.repo_root,
                    matrix_root=fixture.matrix_root,
                    output_root=fixture.output_root,
                )

    def test_disagreeing_baseline_calendars_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticMatrix(Path(temporary))
            path = (
                fixture.repo_root
                / "outputs/baselines/ai_semiconductor__canonical/nav_daily.csv"
            )
            calendar = pd.read_csv(path)
            calendar.iloc[:-1].to_csv(path, index=False)

            with self.assertRaisesRegex(ValueError, "baseline calendars differ"):
                summary.summarize(
                    repo_root=fixture.repo_root,
                    matrix_root=fixture.matrix_root,
                    output_root=fixture.output_root,
                )


if __name__ == "__main__":
    unittest.main()
