from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from a_share_backtesting.intraday_portfolio_run import (
    EMPTY_CSV_COLUMNS,
    REQUIRED_OUTPUTS as CLI_REQUIRED_OUTPUTS,
    main as intraday_cli_main,
)
from a_share_backtesting.market_regime import (
    MarketRegimeSchedule,
    build_market_regime_schedule,
    load_market_regime_config,
)
from a_share_backtesting.trade_reconciliation import (
    TradeEconomicsError,
    reconcile_trade_economics as _reconcile_trade_economics,
    reconciled_trade_metrics,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_START = "2026-06-01"
ANALYSIS_END = "2026-07-17"
RUN_SOURCE_MANIFEST = "run_sources.json"


@dataclass(frozen=True)
class PoolSources:
    qfq_source: str
    stock_pool: str
    scan_source: str


@dataclass(frozen=True)
class PositionSources:
    config: str
    target_fraction: float


@dataclass(frozen=True)
class TimingSources:
    single_day_config: str
    two_day_config: str


@dataclass(frozen=True)
class MatrixRun:
    pool: str
    position: str
    timing: str
    qfq_source: str
    stock_pool: str
    scan_source: str
    baseline: str
    config: str
    single_day_config: str
    two_day_config: str

    @property
    def run_key(self) -> str:
        return f"{self.pool}__{self.position}__{self.timing}"


POOL_ORDER = (
    "ai_semiconductor",
    "innovative_drug",
    "battery",
    "humanoid_robot_proxy",
)
POSITION_ORDER = ("canonical", "risk025")
TIMING_ORDER = ("same_day_1455", "next_session_0935")

POOL_SOURCES: dict[str, PoolSources] = {
    "ai_semiconductor": PoolSources(
        qfq_source="outputs/qfq_ai_semiconductor_20260718/qfq_bars.csv",
        stock_pool="config/ai_semiconductor_stock_pool_20260715.csv",
        scan_source="outputs/intraday_b1_warmup180_20260718/ai_semiconductor/signal_scans.csv",
    ),
    "innovative_drug": PoolSources(
        qfq_source="outputs/qfq_sector_pools_20260718/qfq_bars.csv",
        stock_pool="config/innovative_drug_931440_stock_pool_20260630.csv",
        scan_source="outputs/intraday_b1_warmup180_20260718/innovative_drug/signal_scans.csv",
    ),
    "battery": PoolSources(
        qfq_source="outputs/qfq_sector_pools_20260718/qfq_bars.csv",
        stock_pool="config/battery_931719_stock_pool_20260630.csv",
        scan_source="outputs/intraday_b1_warmup180_20260718/battery/signal_scans.csv",
    ),
    "humanoid_robot_proxy": PoolSources(
        qfq_source="outputs/qfq_sector_pools_20260718/qfq_bars.csv",
        stock_pool="config/humanoid_robot_proxy_980022_stock_pool_20260717.csv",
        scan_source="outputs/intraday_b1_warmup180_20260718/humanoid_robot_proxy/signal_scans.csv",
    ),
}

POSITION_CONFIGS: dict[str, PositionSources] = {
    "canonical": PositionSources(
        config="config/intraday_portfolio_20260718.json",
        target_fraction=1.0 / 3.0,
    ),
    "risk025": PositionSources(
        config="config/intraday_portfolio_risk_controlled_20260718.json",
        target_fraction=0.25,
    ),
}

TIMING_CONFIGS: dict[str, TimingSources] = {
    "same_day_1455": TimingSources(
        single_day_config=(
            "config/active_market_cap_single_day_4pct_same_day_20260719.json"
        ),
        two_day_config=(
            "config/active_market_cap_two_day_4pct_same_day_20260719.json"
        ),
    ),
    "next_session_0935": TimingSources(
        single_day_config=(
            "config/active_market_cap_single_day_4pct_next_session_20260719.json"
        ),
        two_day_config=(
            "config/active_market_cap_two_day_4pct_next_session_20260719.json"
        ),
    ),
}

BASELINE_SOURCES: dict[tuple[str, str], str] = {
    ("ai_semiconductor", "canonical"): (
        "outputs/intraday_b1_final_verified_20260718/ai_canonical_20260717"
    ),
    ("ai_semiconductor", "risk025"): (
        "outputs/intraday_b1_final_verified_20260718/ai_risk025_20260717"
    ),
    ("innovative_drug", "canonical"): (
        "outputs/intraday_b1_final_verified_20260718/innovative_drug_canonical_20260717"
    ),
    ("innovative_drug", "risk025"): (
        "outputs/intraday_b1_final_verified_20260718/innovative_drug_risk025_20260717"
    ),
    ("battery", "canonical"): (
        "outputs/intraday_b1_final_verified_20260718/battery_canonical_20260717"
    ),
    ("battery", "risk025"): (
        "outputs/intraday_b1_final_verified_20260718/battery_risk025_20260717"
    ),
    ("humanoid_robot_proxy", "canonical"): (
        "outputs/intraday_b1_final_verified_20260718/"
        "humanoid_robot_proxy_canonical_20260717"
    ),
    ("humanoid_robot_proxy", "risk025"): (
        "outputs/intraday_b1_final_verified_20260718/"
        "humanoid_robot_proxy_risk025_20260717"
    ),
}

REQUIRED_OUTPUTS = CLI_REQUIRED_OUTPUTS

_PORTFOLIO_SUMMARY_COLUMNS = [
    "initial_cash",
    "final_nav",
    "total_net_return",
    "max_drawdown_5m",
    "max_drawdown_low",
    "max_drawdown_daily",
    "average_exposure",
    "max_exposure",
    "capital_utilization",
    "max_positions",
    "turnover",
    "commission",
    "stamp_duty",
    "slippage_cost",
]
CSV_SCHEMAS: dict[str, list[str]] = {
    "data_audit.csv": ["code", "date", "reason"],
    **{name: list(columns) for name, columns in EMPTY_CSV_COLUMNS.items()},
    "portfolio_summary.csv": _PORTFOLIO_SUMMARY_COLUMNS,
    "trade_summary.csv": [
        "closed_trade_count",
        "open_trade_count",
        "win_rate",
        "mean_net_return",
        "median_net_return",
        "profit_factor",
        "payoff_ratio",
        "expectancy",
        "average_holding_days",
        "maximum_consecutive_losses",
        "take_profit_trade_rate",
        "stop_exit_rate",
        "residual_exit_rate",
        "expiry_exit_rate",
        "overtime_exit_rate",
        "mean_maximum_adverse_excursion",
        "worst_maximum_adverse_excursion",
    ],
    "comparison.csv": [*_PORTFOLIO_SUMMARY_COLUMNS, "mode", "start", "end"],
    "market_regime.csv": [
        "signal_date",
        "effective_timestamp",
        "event",
        "label",
        "prior_state",
        "resulting_state",
        "execution_mode",
    ],
}
_FINITE_ECONOMIC_COLUMNS: dict[str, list[str]] = {
    "fills.csv": [
        "shares",
        "raw_price",
        "adjusted_price",
        "gross_notional",
        "commission",
        "stamp_duty",
        "slippage_cost",
        "cash_delta",
    ],
    "positions.csv": [
        "remaining_shares",
        "market_value",
        "position_return",
        "position_return_low",
    ],
    "trades.csv": [
        "entry_cost",
        "net_proceeds",
        "net_pnl",
        "net_return",
        "holding_days",
        "maximum_adverse_excursion",
    ],
    "nav_5m.csv": ["cash", "gross_exposure", "positions", "nav", "nav_low"],
    "nav_daily.csv": ["cash", "gross_exposure", "positions", "nav", "nav_low"],
    "portfolio_summary.csv": _PORTFOLIO_SUMMARY_COLUMNS,
    "trade_summary.csv": [
        column for column in CSV_SCHEMAS["trade_summary.csv"] if column != "profit_factor"
    ],
    "comparison.csv": _PORTFOLIO_SUMMARY_COLUMNS,
}


class ReconciliationError(ValueError):
    pass


def build_matrix() -> tuple[MatrixRun, ...]:
    runs: list[MatrixRun] = []
    for pool in POOL_ORDER:
        pool_sources = POOL_SOURCES[pool]
        for position in POSITION_ORDER:
            position_sources = POSITION_CONFIGS[position]
            for timing in TIMING_ORDER:
                timing_sources = TIMING_CONFIGS[timing]
                runs.append(
                    MatrixRun(
                        pool=pool,
                        position=position,
                        timing=timing,
                        qfq_source=pool_sources.qfq_source,
                        stock_pool=pool_sources.stock_pool,
                        scan_source=pool_sources.scan_source,
                        baseline=BASELINE_SOURCES[(pool, position)],
                        config=position_sources.config,
                        single_day_config=timing_sources.single_day_config,
                        two_day_config=timing_sources.two_day_config,
                    )
                )
    return tuple(runs)


def cli_arguments(
    job: MatrixRun,
    *,
    minute_root: Path,
    output_root: Path,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    source = lambda value: str(repo_root / Path(value))
    return [
        "--minute-root",
        str(minute_root),
        "--qfq-source",
        source(job.qfq_source),
        "--stock-pool",
        source(job.stock_pool),
        "--config",
        source(job.config),
        "--scan-source",
        source(job.scan_source),
        "--market-regime",
        source(job.single_day_config),
        "--output",
        str(output_root / job.run_key),
        "--analysis-start",
        ANALYSIS_START,
        "--analysis-end",
        ANALYSIS_END,
    ]


def _state_window_signature(schedule: MarketRegimeSchedule) -> tuple[object, ...]:
    timeline = schedule.timeline
    if timeline.empty:
        return (schedule.state_at(pd.Timestamp(ANALYSIS_START)), ())
    initial_state = str(timeline.iloc[0]["prior_state"])
    changes = tuple(
        (pd.Timestamp(row.effective_timestamp).isoformat(), str(row.resulting_state))
        for row in timeline.itertuples(index=False)
        if row.prior_state != row.resulting_state
    )
    return initial_state, changes


def assert_equal_state_windows(
    single_day: MarketRegimeSchedule,
    two_day: MarketRegimeSchedule,
) -> None:
    single_signature = _state_window_signature(single_day)
    two_day_signature = _state_window_signature(two_day)
    if single_signature != two_day_signature:
        raise ValueError(
            "single-day and two-day state windows differ: "
            f"{single_signature!r} != {two_day_signature!r}"
        )


def _config_calendar(
    config: Mapping[str, object], trading_dates: Sequence[object]
) -> list[pd.Timestamp]:
    dates = list(pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize())
    extensions = config.get("calendar_extension_dates", [])
    if extensions:
        if not isinstance(extensions, list):
            raise ValueError("calendar_extension_dates must be a list")
        dates.extend(pd.Timestamp(value).normalize() for value in extensions)
    return sorted(set(dates))


def validate_schedule_pair(
    single_day_path: Path,
    two_day_path: Path,
    trading_dates: Sequence[object],
) -> tuple[MarketRegimeSchedule, MarketRegimeSchedule]:
    single_config = load_market_regime_config(single_day_path)
    two_day_config = load_market_regime_config(two_day_path)
    single = build_market_regime_schedule(
        single_config, _config_calendar(single_config, trading_dates)
    )
    two_day = build_market_regime_schedule(
        two_day_config, _config_calendar(two_day_config, trading_dates)
    )
    assert_equal_state_windows(single, two_day)
    return single, two_day


def _baseline_trading_dates(job: MatrixRun, repo_root: Path) -> list[pd.Timestamp]:
    path = repo_root / job.baseline / "nav_daily.csv"
    try:
        frame = pd.read_csv(path, usecols=["date"])
    except Exception as error:
        raise ValueError(f"cannot read frozen baseline calendar {path}: {error}") from error
    dates = pd.to_datetime(frame["date"], errors="raise").dt.normalize().drop_duplicates()
    if dates.empty:
        raise ValueError(f"frozen baseline calendar is empty: {path}")
    return dates.tolist()


def validate_all_schedule_pairs(
    jobs: Sequence[MatrixRun], repo_root: Path = REPO_ROOT
) -> dict[str, tuple[MarketRegimeSchedule, MarketRegimeSchedule]]:
    validated: dict[str, tuple[MarketRegimeSchedule, MarketRegimeSchedule]] = {}
    for job in jobs:
        validated[job.run_key] = validate_schedule_pair(
            repo_root / job.single_day_config,
            repo_root / job.two_day_config,
            _baseline_trading_dates(job, repo_root),
        )
    return validated


def frozen_source_paths(jobs: Sequence[MatrixRun]) -> tuple[str, ...]:
    paths: set[str] = set()
    for job in jobs:
        paths.update(
            {
                job.qfq_source,
                job.stock_pool,
                job.scan_source,
                job.config,
                job.single_day_config,
                job.two_day_config,
                f"{job.baseline}/nav_daily.csv",
                f"{job.baseline}/run_manifest.json",
            }
        )
    return tuple(sorted(paths))


def timed_run_manifest_paths(jobs: Sequence[MatrixRun]) -> tuple[str, ...]:
    return tuple(sorted(f"{job.run_key}/run_manifest.json" for job in jobs))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def serialize_run_source_manifest(
    jobs: Sequence[MatrixRun], source_hashes: Mapping[str, str]
) -> str:
    expected_paths = frozen_source_paths(jobs)
    timed_manifest_paths = timed_run_manifest_paths(jobs)
    missing = sorted(
        (set(expected_paths) | set(timed_manifest_paths)) - set(source_hashes)
    )
    if missing:
        raise ValueError(f"missing source hashes: {missing}")
    payload = {
        "analysis_end": ANALYSIS_END,
        "analysis_start": ANALYSIS_START,
        "matrix_dimensions": {
            "pools": list(POOL_ORDER),
            "position_configs": list(POSITION_ORDER),
            "timing_modes": list(TIMING_ORDER),
        },
        "runs": [
            {
                "baseline": job.baseline,
                "baseline_calendar": f"{job.baseline}/nav_daily.csv",
                "config": job.config,
                "market_regime": job.single_day_config,
                "pool": job.pool,
                "position_config": job.position,
                "qfq_source": job.qfq_source,
                "run_key": job.run_key,
                "scan_source": job.scan_source,
                "stock_pool": job.stock_pool,
                "timing_mode": job.timing,
                "two_day_equality_source": job.two_day_config,
            }
            for job in jobs
        ],
        "source_sha256": {path: source_hashes[path] for path in expected_paths},
        "timed_run_manifest_sha256": {
            path: source_hashes[path] for path in timed_manifest_paths
        },
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def write_run_source_manifest(
    output_root: Path,
    jobs: Sequence[MatrixRun],
    repo_root: Path = REPO_ROOT,
) -> Path:
    hashes = {
        relative: _sha256_file(repo_root / relative)
        for relative in frozen_source_paths(jobs)
    }
    hashes.update(
        {
            relative: _sha256_file(output_root / relative)
            for relative in timed_run_manifest_paths(jobs)
        }
    )
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / RUN_SOURCE_MANIFEST
    path.write_text(serialize_run_source_manifest(jobs, hashes), encoding="utf-8")
    return path


def _numeric(frame: pd.DataFrame, columns: Sequence[str], artifact: str) -> pd.DataFrame:
    converted = frame.copy()
    for column in columns:
        converted[column] = pd.to_numeric(converted[column], errors="coerce")
        if converted[column].isna().any() or not np.isfinite(converted[column]).all():
            raise ReconciliationError(f"{artifact} has invalid numeric {column}")
    return converted


def _reject_infinite_economics(frames: Mapping[str, pd.DataFrame]) -> None:
    for artifact, columns in _FINITE_ECONOMIC_COLUMNS.items():
        frame = frames[artifact]
        for column in columns:
            values = pd.to_numeric(frame[column], errors="coerce")
            if np.isinf(values).any():
                raise ReconciliationError(f"{artifact} has infinite {column}")


def _timestamps(
    frame: pd.DataFrame,
    columns: Sequence[str],
    artifact: str,
    *,
    nullable: Sequence[str] = (),
) -> pd.DataFrame:
    converted = frame.copy()
    nullable_columns = set(nullable)
    for column in columns:
        values = pd.to_datetime(converted[column], errors="coerce")
        invalid = converted[column].notna() & values.isna()
        if invalid.any():
            raise ReconciliationError(f"{artifact} has invalid timestamp {column}")
        if column not in nullable_columns and values.isna().any():
            raise ReconciliationError(f"{artifact} has null required timestamp {column}")
        converted[column] = values
    return converted


def _runner_file_source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _require_manifest_value(
    manifest: Mapping[str, object],
    field: str,
    expected: object,
    *,
    artifact: str = "run_manifest.json",
) -> None:
    if manifest.get(field) != expected:
        raise ReconciliationError(
            f"{artifact} manifest mismatch for {field}: "
            f"{manifest.get(field)!r} != {expected!r}"
        )


def _validate_manifest_target(
    manifest: Mapping[str, object],
    expected_target: float,
    *,
    artifact: str,
) -> None:
    execution_config = manifest.get("execution_config")
    target = (
        execution_config.get("target_fraction")
        if isinstance(execution_config, Mapping)
        else None
    )
    try:
        matches_target = math.isclose(
            float(target), expected_target, rel_tol=1e-12, abs_tol=1e-12
        )
    except (TypeError, ValueError):
        matches_target = False
    if not matches_target:
        raise ReconciliationError(
            f"{artifact} target fraction mismatch: "
            f"{target!r} != {expected_target!r}"
        )


def _validate_clean_revision(
    manifest: Mapping[str, object], *, artifact: str
) -> None:
    if manifest.get("git_dirty") is not False:
        raise ReconciliationError(f"{artifact} git_dirty must be false")
    revision = manifest.get("git_revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ReconciliationError(f"{artifact} git_revision must be non-empty")


def _validate_run_manifest(
    manifest: object,
    job: MatrixRun,
    repo_root: Path,
) -> None:
    if not isinstance(manifest, Mapping):
        raise ReconciliationError("run_manifest.json schema drift")
    qfq = repo_root / job.qfq_source
    pool = repo_root / job.stock_pool
    config = repo_root / job.config
    scan = repo_root / job.scan_source
    regime = repo_root / job.single_day_config
    baseline_manifest_path = repo_root / job.baseline / "run_manifest.json"
    try:
        baseline_manifest = json.loads(
            baseline_manifest_path.read_text(encoding="utf-8")
        )
    except Exception as error:
        raise ReconciliationError(
            f"cannot parse frozen baseline run_manifest.json: {error}"
        ) from error
    if not isinstance(baseline_manifest, Mapping):
        raise ReconciliationError("frozen baseline run_manifest.json schema drift")
    common_expected = {
        "mode": "intraday-b1-portfolio",
        "analysis_start": ANALYSIS_START,
        "analysis_end": ANALYSIS_END,
        "qfq_source": str(qfq.resolve()),
        "qfq_source_sha256": _runner_file_source_sha256(qfq),
        "stock_pool_sha256": _sha256_file(pool),
        "config_sha256": _sha256_file(config),
        "scan_source": str(scan.resolve()),
        "scan_source_sha256": _sha256_file(scan),
    }
    baseline_artifact = "frozen baseline run_manifest.json"
    for field, value in common_expected.items():
        _require_manifest_value(
            baseline_manifest,
            field,
            value,
            artifact=baseline_artifact,
        )
    expected_target = POSITION_CONFIGS[job.position].target_fraction
    _validate_manifest_target(
        baseline_manifest,
        expected_target,
        artifact=baseline_artifact,
    )
    _validate_clean_revision(baseline_manifest, artifact=baseline_artifact)
    baseline_minute_hash = (
        baseline_manifest.get("minute_source_sha256")
    )
    if not isinstance(baseline_minute_hash, str) or not baseline_minute_hash:
        raise ReconciliationError(
            "frozen baseline run_manifest.json lacks minute_source_sha256"
        )
    expected = {
        **common_expected,
        "market_regime_source": str(regime.resolve()),
        "market_regime_source_sha256": _sha256_file(regime),
        "minute_source_sha256": baseline_minute_hash,
        "outputs": [*REQUIRED_OUTPUTS, "market_regime.csv"],
    }
    for field, value in expected.items():
        _require_manifest_value(manifest, field, value)
    _validate_manifest_target(
        manifest,
        expected_target,
        artifact="run_manifest.json",
    )
    _validate_clean_revision(manifest, artifact="run_manifest.json")
    regime_config = load_market_regime_config(regime)
    if regime_config.get("execution_mode") != job.timing:
        raise ReconciliationError("market-regime source mode does not match matrix job")


def _validate_artifact_timestamps(frames: Mapping[str, pd.DataFrame]) -> None:
    for artifact in ("fills.csv", "nav_5m.csv", "nav_daily.csv", "positions.csv"):
        _timestamps(frames[artifact], ["timestamp"], artifact)
    trades = _timestamps(
        frames["trades.csv"],
        ["entry_timestamp", "exit_timestamp"],
        "trades.csv",
        nullable=["exit_timestamp"],
    )
    closed_without_exit = trades["status"].eq("closed") & trades["exit_timestamp"].isna()
    if closed_without_exit.any():
        raise ReconciliationError("trades.csv closed trade exit timestamp is required")
    _timestamps(
        frames["market_regime.csv"],
        ["effective_timestamp"],
        "market_regime.csv",
    )


def parse_run_artifacts(
    run_dir: Path,
    job: MatrixRun,
    repo_root: Path = REPO_ROOT,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for filename, expected_columns in CSV_SCHEMAS.items():
        path = run_dir / filename
        if not path.is_file():
            raise ReconciliationError(f"missing artifact: {filename}")
        try:
            frame = pd.read_csv(path, dtype={"code": str, "position_id": str})
        except Exception as error:
            raise ReconciliationError(f"cannot parse {filename}: {error}") from error
        if frame.columns.tolist() != expected_columns:
            raise ReconciliationError(
                f"{filename} schema drift: {frame.columns.tolist()} != {expected_columns}"
            )
        frames[filename] = frame

    _validate_artifact_timestamps(frames)

    for filename in (
        "market_regime.csv",
        "nav_5m.csv",
        "nav_daily.csv",
        "portfolio_summary.csv",
        "trade_summary.csv",
        "comparison.csv",
    ):
        if frames[filename].empty:
            raise ReconciliationError(f"{filename} must not be empty")
    timeline_modes = set(frames["market_regime.csv"]["execution_mode"].astype(str))
    if timeline_modes != {job.timing}:
        raise ReconciliationError(
            f"market_regime.csv timeline mode mismatch: {timeline_modes!r} != {job.timing!r}"
        )

    manifest_path = run_dir / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ReconciliationError(f"cannot parse run_manifest.json: {error}") from error
    _validate_run_manifest(manifest, job, repo_root)
    try:
        (run_dir / "report.md").read_text(encoding="utf-8")
    except Exception as error:
        raise ReconciliationError(f"cannot parse report.md: {error}") from error
    return frames


def reconcile_nav(frames: Mapping[str, pd.DataFrame]) -> None:
    nav = _timestamps(frames["nav_5m.csv"], ["timestamp"], "nav_5m.csv")
    nav = _numeric(nav, ["cash", "gross_exposure", "positions", "nav"], "nav_5m.csv")
    if nav.empty:
        raise ReconciliationError("nav_5m.csv must not be empty")
    ending = nav.sort_values("timestamp").iloc[-1]
    if not math.isclose(
        float(ending.cash) + float(ending.gross_exposure),
        float(ending.nav),
        rel_tol=1e-12,
        abs_tol=1e-6,
    ):
        raise ReconciliationError("ending cash plus exposure does not equal NAV")
    summary = _numeric(
        frames["portfolio_summary.csv"], ["final_nav"], "portfolio_summary.csv"
    )
    if len(summary) != 1 or not math.isclose(
        float(summary.iloc[0]["final_nav"]),
        float(ending.nav),
        rel_tol=1e-12,
        abs_tol=1e-6,
    ):
        raise ReconciliationError("portfolio summary final NAV does not reconcile")


def reconcile_activity_completeness(frames: Mapping[str, pd.DataFrame]) -> None:
    nav = _timestamps(frames["nav_5m.csv"], ["timestamp"], "nav_5m.csv")
    nav = _numeric(nav, ["positions", "gross_exposure"], "nav_5m.csv")
    trade_summary = _numeric(
        frames["trade_summary.csv"],
        ["open_trade_count", "closed_trade_count"],
        "trade_summary.csv",
    )
    if len(trade_summary) != 1:
        raise ReconciliationError("trade_summary.csv must contain exactly one row")
    open_count = int(trade_summary.iloc[0]["open_trade_count"])
    closed_count = int(trade_summary.iloc[0]["closed_trade_count"])
    if open_count < 0 or closed_count < 0:
        raise ReconciliationError("trade summary counts must not be negative")
    nav_reports_activity = bool(
        (nav["positions"] > 0).any()
        or (nav["gross_exposure"].abs() > 1e-6).any()
    )
    if nav_reports_activity or open_count > 0 or closed_count > 0:
        empty_ledgers = [
            artifact
            for artifact in ("fills.csv", "trades.csv", "positions.csv")
            if frames[artifact].empty
        ]
        if empty_ledgers:
            raise ReconciliationError(
                f"reported activity requires nonempty core ledgers: {empty_ledgers}"
            )

    positions = _timestamps(frames["positions.csv"], ["timestamp"], "positions.csv")
    positions = _numeric(positions, ["market_value"], "positions.csv")
    trades = _timestamps(
        frames["trades.csv"],
        ["entry_timestamp", "exit_timestamp"],
        "trades.csv",
        nullable=["exit_timestamp"],
    )
    actual_open = set(
        trades.loc[trades["status"].eq("open"), "position_id"].astype(str)
    )
    actual_closed = set(
        trades.loc[trades["status"].eq("closed"), "position_id"].astype(str)
    )
    if len(actual_open) != open_count or len(actual_closed) != closed_count:
        raise ReconciliationError("trade summary counts do not match trade ledger")

    ending = nav.sort_values("timestamp").iloc[-1]
    final_positions = positions.loc[positions["timestamp"].eq(ending.timestamp)]
    final_ids = set(final_positions["position_id"].astype(str))
    nav_position_count = int(ending.positions)
    if final_ids != actual_open:
        raise ReconciliationError("final open trade IDs do not match position snapshots")
    if len(final_positions) != nav_position_count or len(actual_open) != nav_position_count:
        raise ReconciliationError(
            "final holding count does not match nav.positions"
        )
    final_market_value = float(final_positions["market_value"].sum())
    if not math.isclose(
        final_market_value,
        float(ending.gross_exposure),
        rel_tol=1e-12,
        abs_tol=1e-6,
    ):
        raise ReconciliationError(
            "final position market_value does not match NAV gross exposure"
        )


def _normalized_fills(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    fills = _timestamps(frames["fills.csv"], ["timestamp"], "fills.csv")
    fills = _numeric(fills, ["shares"], "fills.csv")
    if fills.empty:
        return fills
    if not fills["side"].isin({"buy", "sell"}).all():
        raise ReconciliationError("fills.csv has invalid side")
    if (fills["shares"] <= 0).any() or not np.equal(
        fills["shares"], np.floor(fills["shares"])
    ).all():
        raise ReconciliationError("fills.csv shares must be positive integers")
    return fills


def reconcile_share_balances(frames: Mapping[str, pd.DataFrame]) -> None:
    fills = _normalized_fills(frames)
    nav = _timestamps(frames["nav_5m.csv"], ["timestamp"], "nav_5m.csv")
    final_timestamp = nav["timestamp"].max()
    positions = _timestamps(frames["positions.csv"], ["timestamp"], "positions.csv")
    positions = _numeric(positions, ["remaining_shares"], "positions.csv")
    if positions.duplicated(["timestamp", "position_id"]).any():
        raise ReconciliationError("duplicate position snapshot")
    final_positions = positions.loc[positions["timestamp"].eq(final_timestamp)]
    remainder = final_positions.set_index("position_id")["remaining_shares"].to_dict()

    trades = _timestamps(
        frames["trades.csv"],
        ["entry_timestamp", "exit_timestamp"],
        "trades.csv",
        nullable=["exit_timestamp"],
    )
    if trades["position_id"].duplicated().any():
        raise ReconciliationError("trades.csv has duplicate position_id")
    trade_status = trades.set_index("position_id")["status"].to_dict()
    fill_ids = set(fills["position_id"].astype(str))
    if set(trade_status) != fill_ids:
        raise ReconciliationError("fills and trades position IDs do not reconcile")
    if set(remainder) - fill_ids:
        raise ReconciliationError("final positions contain unknown position IDs")

    for position_id, group in fills.groupby("position_id", sort=True):
        bought = float(group.loc[group["side"].eq("buy"), "shares"].sum())
        sold = float(group.loc[group["side"].eq("sell"), "shares"].sum())
        if bought <= 0:
            raise ReconciliationError(f"position {position_id} has no entry fill")
        if sold > bought:
            raise ReconciliationError(
                f"position {position_id}: sold shares exceed bought shares"
            )
        if group["code"].astype(str).str.zfill(6).nunique() != 1:
            raise ReconciliationError(f"position {position_id} changes code")
        final_remainder = float(remainder.get(position_id, 0.0))
        status = trade_status[position_id]
        if status == "closed" and final_remainder != 0.0:
            raise ReconciliationError(
                f"position {position_id}: closed trade has final remainder"
            )
        if status == "open" and final_remainder <= 0.0:
            raise ReconciliationError(
                f"position {position_id}: open trade has no final remainder"
            )
        if status not in {"open", "closed"}:
            raise ReconciliationError(f"position {position_id}: invalid trade status {status}")
        if not math.isclose(
            bought,
            sold + final_remainder,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ReconciliationError(
                f"position {position_id}: share balance does not reconcile "
                f"({bought} != {sold} + {final_remainder})"
            )


def reconcile_trade_economics(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    nav = _timestamps(frames["nav_5m.csv"], ["timestamp"], "nav_5m.csv")
    try:
        reconciled = _reconcile_trade_economics(
            frames["fills.csv"],
            frames["trades.csv"],
            frames["positions.csv"],
            nav["timestamp"].max(),
        )
        metrics = reconciled_trade_metrics(reconciled)
    except TradeEconomicsError as error:
        raise ReconciliationError(str(error)) from error

    summary = frames["trade_summary.csv"]
    if len(summary) != 1:
        raise ReconciliationError("trade_summary.csv must contain exactly one row")
    for field in ("closed_trade_count", "open_trade_count"):
        try:
            reported = int(summary.iloc[0][field])
        except (TypeError, ValueError, OverflowError) as error:
            raise ReconciliationError(f"trade_summary.csv has invalid {field}") from error
        if reported != metrics[field]:
            raise ReconciliationError(f"trade_summary.csv {field} mismatch")
    for field in ("win_rate", "profit_factor"):
        try:
            reported = float(summary.iloc[0][field])
        except (TypeError, ValueError) as error:
            raise ReconciliationError(f"trade_summary.csv has invalid {field}") from error
        expected = float(metrics[field])
        matches = (
            math.isnan(reported) and math.isnan(expected)
        ) or (
            math.isinf(expected) and reported == expected
        ) or (
            math.isfinite(reported)
            and math.isfinite(expected)
            and math.isclose(reported, expected, rel_tol=1e-10, abs_tol=1e-10)
        )
        if not matches:
            raise ReconciliationError(f"trade_summary.csv {field} mismatch")
    return reconciled


def reconcile_position_constraints(frames: Mapping[str, pd.DataFrame]) -> None:
    nav = _numeric(frames["nav_5m.csv"], ["positions"], "nav_5m.csv")
    if (nav["positions"] > 3).any():
        raise ReconciliationError("portfolio has more than 3 holdings")
    if (nav["positions"] < 0).any() or not np.equal(
        nav["positions"], np.floor(nav["positions"])
    ).all():
        raise ReconciliationError("nav position count is invalid")

    positions = _timestamps(frames["positions.csv"], ["timestamp"], "positions.csv")
    if not positions.empty:
        overlap = positions.groupby(["timestamp", "code"])["position_id"].nunique()
        if (overlap > 1).any():
            raise ReconciliationError("same-code overlap in position snapshots")
        holdings = positions.groupby("timestamp")["position_id"].nunique()
        if (holdings > 3).any():
            raise ReconciliationError("position snapshots have more than 3 holdings")

    trades = _timestamps(
        frames["trades.csv"],
        ["entry_timestamp", "exit_timestamp"],
        "trades.csv",
        nullable=["exit_timestamp"],
    )
    for code, group in trades.groupby("code", sort=True):
        prior_exit: pd.Timestamp | None = None
        for row in group.sort_values("entry_timestamp").itertuples(index=False):
            entry = pd.Timestamp(row.entry_timestamp)
            if prior_exit is not None:
                if pd.isna(prior_exit) or entry < prior_exit:
                    raise ReconciliationError(f"same-code overlap for {code}")
            prior_exit = row.exit_timestamp


def _validated_regime_timeline(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    timeline = _timestamps(
        frames["market_regime.csv"], ["effective_timestamp"], "market_regime.csv"
    ).sort_values("effective_timestamp")
    previous: str | None = None
    for row in timeline.itertuples(index=False):
        if row.prior_state not in {"risk_off", "risk_on"} or row.resulting_state not in {
            "risk_off",
            "risk_on",
        }:
            raise ReconciliationError("market regime has invalid state")
        if previous is not None and row.prior_state != previous:
            raise ReconciliationError("market regime state chain does not reconcile")
        expected = "risk_on" if row.event == "up" else "risk_off" if row.event == "down" else None
        if expected is None or row.resulting_state != expected:
            raise ReconciliationError("market regime event does not reconcile to state")
        previous = row.resulting_state
    return timeline


def reconcile_regime_liquidation_intent(frames: Mapping[str, pd.DataFrame]) -> None:
    fills = _normalized_fills(frames)
    timeline = _validated_regime_timeline(frames)
    if timeline.empty and not fills.loc[fills["side"].eq("buy")].empty:
        raise ReconciliationError("market regime timeline is empty with entry fills")
    if timeline.empty:
        return

    state = str(timeline.iloc[0]["prior_state"])
    balances: dict[str, float] = {}
    targeted: set[str] = set()
    fills = fills.assign(_row_order=np.arange(len(fills)))
    timestamps = sorted(
        set(timeline["effective_timestamp"]).union(set(fills["timestamp"]))
    )
    for timestamp in timestamps:
        transitions = timeline.loc[timeline["effective_timestamp"].eq(timestamp)]
        for transition in transitions.itertuples(index=False):
            state = str(transition.resulting_state)
            if transition.event == "down":
                targeted.update(
                    position_id
                    for position_id, shares in balances.items()
                    if shares > 0.0
                )

        timestamp_fills = fills.loc[fills["timestamp"].eq(timestamp)].sort_values(
            "_row_order"
        )
        for fill in timestamp_fills.itertuples(index=False):
            position_id = str(fill.position_id)
            shares = float(fill.shares)
            if fill.side == "buy":
                pending = sorted(
                    targeted_id
                    for targeted_id in targeted
                    if balances.get(targeted_id, 0.0) > 0.0
                )
                if pending:
                    raise ReconciliationError(
                        f"entry while regime liquidation remains: {pending}"
                    )
                if state == "risk_off":
                    raise ReconciliationError(
                        f"entry fill in risk_off: {position_id} at {timestamp}"
                    )
                balances[position_id] = balances.get(position_id, 0.0) + shares
            else:
                if (
                    position_id in targeted
                    and balances.get(position_id, 0.0) > 0.0
                    and fill.reason != "market_regime_exit"
                ):
                    raise ReconciliationError(
                        f"position {position_id}: targeted sell must be market_regime_exit"
                    )
                balances[position_id] = balances.get(position_id, 0.0) - shares
                if balances[position_id] <= 0.0:
                    targeted.discard(position_id)


def reconcile_regime_exits(frames: Mapping[str, pd.DataFrame]) -> None:
    fills = _normalized_fills(frames)
    if fills.empty:
        return
    regime_ids = set(
        fills.loc[
            fills["side"].eq("sell") & fills["reason"].eq("market_regime_exit"),
            "position_id",
        ].astype(str)
    )
    if not regime_ids:
        return

    nav = _timestamps(frames["nav_5m.csv"], ["timestamp"], "nav_5m.csv")
    final_timestamp = nav["timestamp"].max()
    positions = _timestamps(frames["positions.csv"], ["timestamp"], "positions.csv")
    positions = _numeric(positions, ["remaining_shares"], "positions.csv")
    final_positions = positions.loc[positions["timestamp"].eq(final_timestamp)]
    remainder = final_positions.groupby("position_id")["remaining_shares"].sum().to_dict()

    for position_id in sorted(regime_ids):
        group = fills.loc[fills["position_id"].astype(str).eq(position_id)].sort_values(
            "timestamp"
        )
        first_regime = group.loc[
            group["side"].eq("sell") & group["reason"].eq("market_regime_exit"),
            "timestamp",
        ].min()
        bought = float(group.loc[group["side"].eq("buy"), "shares"].sum())
        sold_before = float(
            group.loc[
                group["side"].eq("sell") & (group["timestamp"] < first_regime), "shares"
            ].sum()
        )
        after = group.loc[group["side"].eq("sell") & (group["timestamp"] >= first_regime)]
        if not after["reason"].eq("market_regime_exit").all():
            raise ReconciliationError(
                f"position {position_id}: non-regime sell follows regime exit"
            )
        regime_sold = float(after["shares"].sum())
        final_remainder = float(remainder.get(position_id, 0.0))
        expected = bought - sold_before
        if not math.isclose(
            regime_sold + final_remainder,
            expected,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ReconciliationError(
                f"position {position_id}: regime shares do not reconcile "
                f"({regime_sold} + {final_remainder} != {expected})"
            )


def reconcile_frames(frames: Mapping[str, pd.DataFrame]) -> None:
    _reject_infinite_economics(frames)
    reconcile_nav(frames)
    reconcile_activity_completeness(frames)
    reconcile_share_balances(frames)
    reconcile_trade_economics(frames)
    reconcile_position_constraints(frames)
    reconcile_regime_liquidation_intent(frames)
    reconcile_regime_exits(frames)


def reconcile_run_artifacts(
    run_dir: Path,
    job: MatrixRun,
    repo_root: Path = REPO_ROOT,
) -> None:
    reconcile_frames(parse_run_artifacts(run_dir, job, repo_root))


def run_matrix(
    minute_root: Path,
    output_root: Path,
    *,
    repo_root: Path = REPO_ROOT,
    cli_main: Callable[[list[str]], int] = intraday_cli_main,
) -> int:
    jobs = build_matrix()
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / RUN_SOURCE_MANIFEST).unlink(missing_ok=True)
    validate_all_schedule_pairs(jobs, repo_root)
    for job in jobs:
        argv = cli_arguments(
            job,
            minute_root=minute_root,
            output_root=output_root,
            repo_root=repo_root,
        )
        exit_code = cli_main(argv)
        if exit_code != 0:
            raise RuntimeError(f"{job.run_key}: intraday CLI returned exit code {exit_code}")
        reconcile_run_artifacts(output_root / job.run_key, job, repo_root)
    write_run_source_manifest(output_root, jobs, repo_root)
    return len(jobs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen active-market-cap timing comparison matrix."
    )
    parser.add_argument("--minute-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    minute_root = Path(args.minute_root)
    output = Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    run_matrix(minute_root, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
