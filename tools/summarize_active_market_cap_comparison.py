from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from a_share_backtesting.market_regime import (
    MarketRegimeSchedule,
    build_market_regime_schedule,
    load_market_regime_config,
)


POOLS = (
    "ai_semiconductor",
    "innovative_drug",
    "battery",
    "humanoid_robot_proxy",
)
POSITIONS = ("canonical", "risk025")
TIMINGS = ("same_day_1455", "next_session_0935")
VARIANTS = ("baseline", *TIMINGS)
SUMMARY_TOLERANCE = 1e-10

TRADE_COLUMNS = [
    "position_id",
    "code",
    "entry_timestamp",
    "exit_timestamp",
    "status",
    "exit_reason",
    "entry_cost",
    "net_proceeds",
    "net_pnl",
    "net_return",
    "holding_days",
    "maximum_adverse_excursion",
]
FILL_COLUMNS = [
    "position_id",
    "code",
    "timestamp",
    "side",
    "reason",
    "shares",
    "raw_price",
    "adjusted_price",
    "gross_notional",
    "commission",
    "stamp_duty",
    "slippage_cost",
    "cash_delta",
]
REGIME_COLUMNS = [
    "signal_date",
    "effective_timestamp",
    "event",
    "label",
    "prior_state",
    "resulting_state",
    "execution_mode",
]
METRIC_ARTIFACTS = (
    "nav_5m.csv",
    "nav_daily.csv",
    "fills.csv",
    "trades.csv",
    "portfolio_summary.csv",
    "trade_summary.csv",
)
DELTA_METRICS = (
    "total_net_return",
    "max_drawdown_5m",
    "max_drawdown_low",
    "max_drawdown_daily",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path, required_columns: Sequence[str]) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"missing source artifact: {path}")
    try:
        frame = pd.read_csv(path)
    except Exception as error:
        raise ValueError(f"cannot parse source artifact {path}: {error}") from error
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    return frame


def _numeric(frame: pd.DataFrame, columns: Sequence[str], path: Path) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        if result[column].isna().any():
            raise ValueError(f"{path} contains non-numeric {column}")
    return result


def _drawdown(values: pd.Series, peaks: pd.Series | None = None) -> float:
    if values.empty:
        raise ValueError("cannot compute drawdown from an empty NAV series")
    high_water = values.cummax() if peaks is None else peaks
    if len(values) != len(high_water):
        raise ValueError("NAV and peak series lengths differ")
    return float((values / high_water - 1.0).min())


def _same_number(actual: float, expected: float) -> bool:
    if math.isnan(actual) or math.isnan(expected):
        return math.isnan(actual) and math.isnan(expected)
    if math.isinf(actual) or math.isinf(expected):
        return actual == expected
    return math.isclose(
        actual,
        expected,
        rel_tol=SUMMARY_TOLERANCE,
        abs_tol=SUMMARY_TOLERANCE,
    )


def _assert_metric(
    artifact: Path,
    field: str,
    recomputed: float | int,
    reported: object,
) -> None:
    try:
        source_value = float(reported)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{artifact} has invalid {field}: {reported!r}") from error
    if not _same_number(float(recomputed), source_value):
        raise ValueError(
            f"{artifact} {field} mismatch: recomputed={recomputed!r}, "
            f"reported={source_value!r}, tolerance={SUMMARY_TOLERANCE}"
        )


def recompute_run_metrics(run_dir: str | Path) -> dict[str, float | int]:
    directory = Path(run_dir)
    nav_path = directory / "nav_5m.csv"
    daily_path = directory / "nav_daily.csv"
    fills_path = directory / "fills.csv"
    trades_path = directory / "trades.csv"
    portfolio_path = directory / "portfolio_summary.csv"
    trade_summary_path = directory / "trade_summary.csv"

    nav = _numeric(
        _read_csv(
            nav_path,
            ["timestamp", "gross_exposure", "positions", "nav", "nav_low"],
        ),
        ["gross_exposure", "positions", "nav", "nav_low"],
        nav_path,
    )
    daily = _numeric(
        _read_csv(daily_path, ["timestamp", "nav"]), ["nav"], daily_path
    )
    if nav.empty or daily.empty:
        raise ValueError(f"NAV artifacts must not be empty: {directory}")
    fills = _read_csv(fills_path, FILL_COLUMNS)
    trades = _read_csv(trades_path, TRADE_COLUMNS)
    if not fills.empty:
        fills = _numeric(fills, ["gross_notional"], fills_path)
    if not trades.empty:
        trades = _numeric(trades, ["net_pnl"], trades_path)

    portfolio = _read_csv(
        portfolio_path,
        [
            "initial_cash",
            "total_net_return",
            "max_drawdown_5m",
            "max_drawdown_low",
            "max_drawdown_daily",
            "capital_utilization",
            "turnover",
        ],
    )
    trade_summary = _read_csv(
        trade_summary_path,
        [
            "closed_trade_count",
            "open_trade_count",
            "win_rate",
            "profit_factor",
        ],
    )
    if len(portfolio) != 1 or len(trade_summary) != 1:
        raise ValueError(f"source summaries must contain exactly one row: {directory}")

    initial_cash = float(portfolio.iloc[0]["initial_cash"])
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError(f"invalid initial_cash in {portfolio_path}")
    first_nav = float(nav.iloc[0]["nav"])
    if not _same_number(first_nav, initial_cash):
        raise ValueError(
            f"{nav_path} initial NAV does not match source initial_cash: "
            f"{first_nav!r} != {initial_cash!r}"
        )

    closed = trades.loc[trades["status"].eq("closed")].copy()
    opened = trades.loc[trades["status"].eq("open")].copy()
    unknown_statuses = set(trades["status"].dropna().astype(str)) - {"closed", "open"}
    if unknown_statuses:
        raise ValueError(f"{trades_path} contains unknown statuses: {unknown_statuses}")
    wins = closed.loc[closed["net_pnl"] > 0, "net_pnl"]
    losses = closed.loc[closed["net_pnl"] < 0, "net_pnl"]
    if not losses.empty:
        profit_factor = float(wins.sum() / abs(losses.sum()))
    elif not wins.empty:
        profit_factor = float("inf")
    else:
        profit_factor = float("nan")

    close_nav = nav["nav"].astype(float)
    close_peaks = close_nav.cummax()
    metrics: dict[str, float | int] = {
        "total_net_return": float(close_nav.iloc[-1] / initial_cash - 1.0),
        "max_drawdown_5m": _drawdown(close_nav),
        "max_drawdown_low": _drawdown(nav["nav_low"].astype(float), close_peaks),
        "max_drawdown_daily": _drawdown(daily["nav"].astype(float)),
        "closed_trade_count": int(len(closed)),
        "open_trade_count": int(len(opened)),
        "win_rate_denominator": int(len(closed)),
        "win_rate": (
            float((closed["net_pnl"] > 0).mean())
            if not closed.empty
            else float("nan")
        ),
        "profit_factor": profit_factor,
        "capital_utilization": float(nav["gross_exposure"].mean() / initial_cash),
        "turnover": float(fills["gross_notional"].sum() / initial_cash),
        "regime_exit_count": int(
            closed["exit_reason"].astype(str).eq("market_regime_exit").sum()
        ),
    }
    for field in (
        "total_net_return",
        "max_drawdown_5m",
        "max_drawdown_low",
        "max_drawdown_daily",
        "capital_utilization",
        "turnover",
    ):
        _assert_metric(portfolio_path, field, metrics[field], portfolio.iloc[0][field])
    for field in (
        "closed_trade_count",
        "open_trade_count",
        "win_rate",
        "profit_factor",
    ):
        _assert_metric(
            trade_summary_path,
            field,
            metrics[field],
            trade_summary.iloc[0][field],
        )
    return metrics


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"path escapes repository root: {path}") from error


def _source_path(repo_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"source path must be a non-empty string: {relative!r}")
    supplied = Path(relative)
    if supplied.is_absolute():
        raise ValueError(f"source path must be repository-relative: {relative}")
    path = (repo_root / supplied).resolve()
    _repo_relative(path, repo_root)
    return path


def _load_manifest(matrix_root: Path) -> tuple[Path, dict[str, Any]]:
    path = matrix_root / "run_sources.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read full matrix source manifest {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("full matrix source manifest must be an object")
    return path, payload


def _validate_matrix_runs(manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    raw_runs = manifest.get("runs")
    if not isinstance(raw_runs, list):
        raise ValueError("full matrix source manifest runs must be a list")
    expected = {
        (pool, position, timing)
        for pool in POOLS
        for position in POSITIONS
        for timing in TIMINGS
    }
    indexed: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    run_keys: set[str] = set()
    for raw in raw_runs:
        if not isinstance(raw, Mapping):
            raise ValueError("every full matrix run must be an object")
        key = (
            str(raw.get("pool")),
            str(raw.get("position_config")),
            str(raw.get("timing_mode")),
        )
        run_key = raw.get("run_key")
        if key in indexed or run_key in run_keys:
            raise ValueError(f"duplicate matrix run: dimensions={key}, run_key={run_key!r}")
        indexed[key] = raw
        if not isinstance(run_key, str) or not run_key:
            raise ValueError(f"invalid matrix run_key for {key}")
        run_keys.add(run_key)
    missing = sorted(expected - set(indexed))
    extra = sorted(set(indexed) - expected)
    if missing:
        raise ValueError(f"missing matrix runs: {missing}")
    if extra:
        raise ValueError(f"unexpected matrix runs: {extra}")
    if len(indexed) != 16:
        raise ValueError(f"matrix must contain exactly 16 timed runs, found {len(indexed)}")
    return indexed


def _validate_manifest_sources(
    manifest: Mapping[str, Any], repo_root: Path
) -> dict[str, str]:
    raw_hashes = manifest.get("source_sha256")
    if not isinstance(raw_hashes, Mapping) or not raw_hashes:
        raise ValueError("full matrix source manifest source_sha256 must be non-empty")
    verified: dict[str, str] = {}
    for relative, expected_hash in sorted(raw_hashes.items()):
        path = _source_path(repo_root, relative)
        if not path.is_file():
            raise ValueError(f"missing frozen source: {relative}")
        actual_hash = _sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"frozen source hash mismatch for {relative}: "
                f"expected={expected_hash}, actual={actual_hash}"
            )
        verified[str(relative)] = actual_hash
    return verified


def _config_path_for_mode(
    indexed: Mapping[tuple[str, str, str], Mapping[str, Any]],
    field: str,
    timing: str,
) -> str:
    values = {
        str(run.get(field))
        for (pool, position, mode), run in indexed.items()
        if mode == timing
    }
    if len(values) != 1 or "None" in values:
        raise ValueError(f"matrix runs must share exactly one {field} for {timing}: {values}")
    return values.pop()


def _analysis_dates(
    indexed: Mapping[tuple[str, str, str], Mapping[str, Any]], repo_root: Path
) -> pd.DatetimeIndex:
    baseline_paths = {
        str(run.get("baseline")) for run in indexed.values()
    }
    if len(baseline_paths) != 8 or "None" in baseline_paths:
        raise ValueError(
            f"matrix must reference exactly eight unique baselines, found {len(baseline_paths)}"
        )
    expected_dates: tuple[pd.Timestamp, ...] | None = None
    for relative in sorted(baseline_paths):
        frame = _read_csv(_source_path(repo_root, relative) / "nav_daily.csv", ["date"])
        parsed = pd.to_datetime(frame["date"], errors="coerce").dropna().dt.normalize()
        if parsed.empty:
            raise ValueError(f"baseline calendar is empty: {relative}/nav_daily.csv")
        dates = tuple(pd.DatetimeIndex(parsed).unique().sort_values())
        if expected_dates is None:
            expected_dates = dates
        elif dates != expected_dates:
            raise ValueError(f"baseline calendars differ: {relative}/nav_daily.csv")
    assert expected_dates is not None
    return pd.DatetimeIndex(expected_dates)


def _state_window_signature(
    config: Mapping[str, object], schedule: MarketRegimeSchedule
) -> tuple[object, ...]:
    changes = schedule.timeline.loc[
        schedule.timeline["prior_state"] != schedule.timeline["resulting_state"]
    ]
    return (
        str(config.get("initial_state")),
        tuple(
            (
                pd.Timestamp(row.effective_timestamp).isoformat(),
                str(row.resulting_state),
            )
            for row in changes.itertuples(index=False)
        ),
    )


def _signature_hash(signature: tuple[object, ...]) -> str:
    encoded = json.dumps(signature, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_regime_timeline_comparison(
    indexed: Mapping[tuple[str, str, str], Mapping[str, Any]],
    repo_root: Path,
) -> tuple[pd.DataFrame, dict[str, int], int, dict[str, str]]:
    dates = _analysis_dates(indexed, repo_root)
    records: list[dict[str, object]] = []
    risk_on_counts: dict[str, int] = {}
    config_sources: dict[str, str] = {}
    for timing in TIMINGS:
        paths = {
            "single_day_4pct": _config_path_for_mode(
                indexed, "market_regime", timing
            ),
            "two_day_total_4pct": _config_path_for_mode(
                indexed, "two_day_equality_source", timing
            ),
        }
        schedules: dict[str, MarketRegimeSchedule] = {}
        signatures: dict[str, tuple[object, ...]] = {}
        configs: dict[str, dict[str, object]] = {}
        for definition, relative in paths.items():
            path = _source_path(repo_root, relative)
            config = load_market_regime_config(path)
            if config.get("timing_definition") != definition:
                raise ValueError(
                    f"{relative} timing_definition mismatch: "
                    f"{config.get('timing_definition')!r} != {definition!r}"
                )
            if config.get("execution_mode") != timing:
                raise ValueError(f"{relative} execution_mode does not match {timing}")
            calendar = list(dates)
            calendar.extend(pd.to_datetime(config.get("calendar_extension_dates", [])))
            schedule = build_market_regime_schedule(config, calendar)
            configs[definition] = config
            schedules[definition] = schedule
            signatures[definition] = _state_window_signature(config, schedule)
            config_sources[relative] = _sha256_file(path)
        equal = signatures["single_day_4pct"] == signatures["two_day_total_4pct"]
        if not equal:
            raise ValueError(f"supplied regime state windows differ for {timing}")
        signature_hash = _signature_hash(signatures["single_day_4pct"])
        entry_times = dates + pd.Timedelta(hours=14, minutes=55)
        risk_on_counts[timing] = sum(
            schedules["single_day_4pct"].state_at(timestamp) == "risk_on"
            for timestamp in entry_times
        )
        for definition in ("single_day_4pct", "two_day_total_4pct"):
            frame = schedules[definition].timeline
            extension_source = str(
                configs[definition].get("calendar_extension_source", "")
            )
            for ordinal, row in enumerate(frame.itertuples(index=False), start=1):
                signal_date = pd.Timestamp(row.signal_date).strftime("%Y-%m-%d")
                effective = pd.Timestamp(row.effective_timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                records.append(
                    {
                        "audit_key": (
                            f"{timing}__{definition}__{signal_date}__{ordinal:02d}"
                        ),
                        "execution_mode": timing,
                        "timing_definition": definition,
                        "signal_date": signal_date,
                        "effective_timestamp": effective,
                        "event": row.event,
                        "label": row.label,
                        "prior_state": row.prior_state,
                        "resulting_state": row.resulting_state,
                        "state_windows_equal": equal,
                        "state_window_signature_sha256": signature_hash,
                        "calendar_extension_source": extension_source,
                    }
                )
    frame = pd.DataFrame.from_records(records)
    if frame["audit_key"].duplicated().any():
        raise ValueError("duplicate regime timeline audit keys")
    return frame, risk_on_counts, len(dates), config_sources


def _assert_timed_regime_matches(run_dir: Path, schedule_rows: pd.DataFrame) -> None:
    actual = _read_csv(run_dir / "market_regime.csv", REGIME_COLUMNS).copy()
    expected = schedule_rows.loc[:, REGIME_COLUMNS].copy()
    for frame in (actual, expected):
        frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.strftime("%Y-%m-%d")
        frame["effective_timestamp"] = pd.to_datetime(
            frame["effective_timestamp"]
        ).dt.strftime("%Y-%m-%d %H:%M:%S")
        for column in set(REGIME_COLUMNS) - {"signal_date", "effective_timestamp"}:
            frame[column] = frame[column].fillna("").astype(str)
    try:
        pd.testing.assert_frame_equal(
            actual.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_dtype=False,
        )
    except AssertionError as error:
        raise ValueError(f"{run_dir / 'market_regime.csv'} differs from rebuilt config") from error


def _artifact_hashes(run_dir: Path, repo_root: Path, timed: bool) -> dict[str, str]:
    names = [*METRIC_ARTIFACTS]
    if timed:
        names.append("market_regime.csv")
    hashes: dict[str, str] = {}
    for name in names:
        path = run_dir / name
        if not path.is_file():
            raise ValueError(f"missing source artifact: {path}")
        hashes[_repo_relative(path, repo_root)] = _sha256_file(path)
    return hashes


def build_timing_comparison(
    indexed: Mapping[tuple[str, str, str], Mapping[str, Any]],
    repo_root: Path,
    matrix_root: Path,
    timeline: pd.DataFrame,
    risk_on_counts: Mapping[str, int],
    analysis_session_count: int,
) -> tuple[pd.DataFrame, dict[str, str]]:
    rows: list[dict[str, object]] = []
    source_hashes: dict[str, str] = {}
    for pool in POOLS:
        for position in POSITIONS:
            timed_runs = {
                timing: indexed[(pool, position, timing)] for timing in TIMINGS
            }
            baseline_values = {str(run.get("baseline")) for run in timed_runs.values()}
            if len(baseline_values) != 1 or "None" in baseline_values:
                raise ValueError(
                    f"timed runs disagree on baseline for {(pool, position)}: "
                    f"{baseline_values}"
                )
            baseline_relative = baseline_values.pop()
            baseline_dir = _source_path(repo_root, baseline_relative)
            metrics_by_variant: dict[str, dict[str, float | int]] = {
                "baseline": recompute_run_metrics(baseline_dir)
            }
            source_hashes.update(_artifact_hashes(baseline_dir, repo_root, timed=False))
            source_directories = {"baseline": baseline_relative}
            source_run_keys = {"baseline": f"{pool}__{position}__baseline"}
            for timing, run in timed_runs.items():
                run_key = str(run["run_key"])
                run_dir = matrix_root / run_key
                metrics_by_variant[timing] = recompute_run_metrics(run_dir)
                source_hashes.update(_artifact_hashes(run_dir, repo_root, timed=True))
                source_directories[timing] = _repo_relative(run_dir, repo_root)
                source_run_keys[timing] = run_key
                expected_timeline = timeline.loc[
                    (timeline["execution_mode"] == timing)
                    & (timeline["timing_definition"] == "single_day_4pct")
                ]
                _assert_timed_regime_matches(run_dir, expected_timeline)

            baseline_metrics = metrics_by_variant["baseline"]
            same_metrics = metrics_by_variant["same_day_1455"]
            next_metrics = metrics_by_variant["next_session_0935"]
            same_minus_next = {
                metric: float(same_metrics[metric]) - float(next_metrics[metric])
                for metric in DELTA_METRICS
            }
            for variant in VARIANTS:
                metrics = metrics_by_variant[variant]
                closed_count = int(metrics["closed_trade_count"])
                row: dict[str, object] = {
                    "comparison_key": f"{pool}__{position}__{variant}",
                    "pool": pool,
                    "position_config": position,
                    "timing_variant": variant,
                    "source_run_key": source_run_keys[variant],
                    "source_directory": source_directories[variant],
                    **metrics,
                    "analysis_session_count": analysis_session_count,
                    "risk_on_session_count": (
                        analysis_session_count
                        if variant == "baseline"
                        else int(risk_on_counts[variant])
                    ),
                    "zero_trade_count_flag": closed_count == 0,
                    "low_trade_count_flag": 2 <= closed_count <= 6,
                }
                for metric in DELTA_METRICS:
                    delta_name = (
                        "return" if metric == "total_net_return" else metric
                    )
                    row[f"{delta_name}_delta_vs_baseline"] = (
                        float(metrics[metric]) - float(baseline_metrics[metric])
                    )
                    row[f"same_day_minus_next_session_{metric.removeprefix('total_net_')}"] = (
                        same_minus_next[metric]
                    )
                rows.append(row)
    frame = pd.DataFrame.from_records(rows)
    if len(frame) != 24:
        raise ValueError(f"comparison must contain exactly 24 rows, found {len(frame)}")
    if frame["comparison_key"].duplicated().any():
        duplicates = frame.loc[frame["comparison_key"].duplicated(), "comparison_key"].tolist()
        raise ValueError(f"duplicate comparison keys: {duplicates}")
    return frame, source_hashes


def _percent(value: object) -> str:
    number = float(value)
    return "n/a" if math.isnan(number) else f"{number:.2%}"


def _percentage_points(value: object) -> str:
    number = float(value)
    return "n/a" if math.isnan(number) else f"{abs(number) * 100.0:.2f} percentage points"


def _same_day_difference(value: object) -> str:
    delta = float(value)
    if delta > SUMMARY_TOLERANCE:
        return f"a same-day advantage of {_percentage_points(delta)}"
    if delta < -SUMMARY_TOLERANCE:
        return f"a same-day disadvantage of {_percentage_points(delta)}"
    return "no same-day versus next-session return difference (0.00 percentage points)"


def _metric_line(label: str, row: pd.Series) -> str:
    return (
        f"- {label}: return {_percent(row['total_net_return'])}; "
        f"5m/low/daily drawdown {_percent(row['max_drawdown_5m'])} / "
        f"{_percent(row['max_drawdown_low'])} / {_percent(row['max_drawdown_daily'])}; "
        f"closed/open {int(row['closed_trade_count'])}/{int(row['open_trade_count'])}; "
        f"win rate {_percent(row['win_rate'])} "
        f"(denominator {int(row['win_rate_denominator'])}); "
        f"capital utilization {_percent(row['capital_utilization'])}; "
        f"turnover {float(row['turnover']):.2f}x."
    )


def _timed_rows(comparison: pd.DataFrame, pool: str | None = None) -> pd.DataFrame:
    rows = comparison.loc[comparison["timing_variant"] != "baseline"].copy()
    if pool is not None:
        rows = rows.loc[rows["pool"] == pool].copy()
    rows["total_trade_count"] = (
        rows["closed_trade_count"].astype(int) + rows["open_trade_count"].astype(int)
    )
    rows["is_zero_trade"] = rows["total_trade_count"].eq(0)
    return rows


def _baseline_row(comparison: pd.DataFrame, pool: str, position: str) -> pd.Series:
    rows = comparison.loc[
        (comparison["pool"] == pool)
        & (comparison["position_config"] == position)
        & (comparison["timing_variant"] == "baseline")
    ]
    if len(rows) != 1:
        raise ValueError(
            f"report requires one baseline row for {(pool, position)}, found {len(rows)}"
        )
    return rows.iloc[0]


def _cross_matrix_conclusions(comparison: pd.DataFrame) -> list[str]:
    timed = _timed_rows(comparison)
    zero_trade = timed.loc[timed["is_zero_trade"]]
    exposed = timed.loc[~timed["is_zero_trade"]]
    improved = exposed["return_delta_vs_baseline"].astype(float) > SUMMARY_TOLERANCE
    pool_all_improved = exposed.groupby("pool")["return_delta_vs_baseline"].apply(
        lambda values: bool((values.astype(float) > SUMMARY_TOLERANCE).all())
    )

    pair_signs: list[str] = []
    for (_, _), rows in exposed.groupby(["pool", "timing_variant"]):
        if set(rows["position_config"]) != set(POSITIONS) or len(rows) != len(POSITIONS):
            continue
        values = rows["return_delta_vs_baseline"].astype(float)
        if (values > SUMMARY_TOLERANCE).all():
            pair_signs.append("positive")
        elif (values < -SUMMARY_TOLERANCE).all():
            pair_signs.append("negative")
        elif (values.abs() <= SUMMARY_TOLERANCE).all():
            pair_signs.append("flat")
        else:
            pair_signs.append("mixed")
    consistent_count = sum(sign != "mixed" for sign in pair_signs)
    positive_count = pair_signs.count("positive")
    negative_count = pair_signs.count("negative")
    flat_count = pair_signs.count("flat")
    mixed_count = pair_signs.count("mixed")

    drawdown_counts = {
        label: int((exposed[column].astype(float) > SUMMARY_TOLERANCE).sum())
        for label, column in (
            ("5-minute", "max_drawdown_5m_delta_vs_baseline"),
            ("conservative-low", "max_drawdown_low_delta_vs_baseline"),
            ("daily", "max_drawdown_daily_delta_vs_baseline"),
        )
    }
    return [
        (
            f"Among {len(exposed)} exposed timed rows, {int(improved.sum())} improve "
            "return versus their position-matched baseline; "
            f"{int(pool_all_improved.sum())} of {len(pool_all_improved)} exposed pools "
            "improve in every timed row."
        ),
        (
            f"{len(zero_trade)} zero-trade rows are reported separately and are not "
            "counted as return improvements."
        ),
        (
            "Return direction across position sizes is consistent in "
            f"{consistent_count} of {len(pair_signs)} exposed pool/timing pairs: "
            f"{positive_count} positive, {negative_count} negative, and {flat_count} "
            f"flat; {mixed_count} pairs are mixed."
        ),
        (
            f"Drawdown improvement among {len(exposed)} exposed timed rows: "
            f"{drawdown_counts['5-minute']} improve 5-minute drawdown, "
            f"{drawdown_counts['conservative-low']} improve conservative-low drawdown, "
            f"and {drawdown_counts['daily']} improve daily drawdown."
        ),
    ]


def _battery_conclusions(comparison: pd.DataFrame) -> list[str]:
    timed = _timed_rows(comparison, "battery")
    improved_return = int(
        (timed["return_delta_vs_baseline"].astype(float) > SUMMARY_TOLERANCE).sum()
    )
    if improved_return == len(timed):
        return_conclusion = (
            f"All {len(timed)} battery timed rows improve return versus baseline."
        )
    elif improved_return == 0:
        return_conclusion = "No battery timed row improves return versus baseline."
    else:
        return_conclusion = (
            f"Battery return evidence is mixed: {improved_return} of {len(timed)} timed "
            "rows improve return versus baseline."
        )

    lower_exposure_and_trades: list[bool] = []
    for row in timed.itertuples(index=False):
        baseline = _baseline_row(comparison, row.pool, row.position_config)
        baseline_trades = int(baseline["closed_trade_count"]) + int(
            baseline["open_trade_count"]
        )
        lower_exposure_and_trades.append(
            float(row.capital_utilization) < float(baseline["capital_utilization"])
            and int(row.total_trade_count) < baseline_trades
        )
    lower_count = sum(lower_exposure_and_trades)
    if lower_count == len(timed):
        exposure_conclusion = (
            f"All {len(timed)} battery timed rows have lower capital utilization and "
            "fewer total trades than their position-matched baselines; reduced exposure "
            "is therefore material in this sample."
        )
    elif lower_count == 0:
        exposure_conclusion = (
            "No battery timed row has both lower capital utilization and fewer total "
            "trades than baseline; the exposure/trade evidence is opposite or unchanged."
        )
    else:
        exposure_conclusion = (
            f"Battery exposure/trade evidence is mixed: {lower_count} of {len(timed)} "
            "timed rows have both lower capital utilization and fewer total trades than "
            "baseline."
        )
    all_drawdowns_improved = int(
        (
            (timed["max_drawdown_5m_delta_vs_baseline"] > SUMMARY_TOLERANCE)
            & (timed["max_drawdown_low_delta_vs_baseline"] > SUMMARY_TOLERANCE)
            & (timed["max_drawdown_daily_delta_vs_baseline"] > SUMMARY_TOLERANCE)
        ).sum()
    )
    return [
        return_conclusion,
        (
            f"{all_drawdowns_improved} of {len(timed)} battery timed rows improve all "
            "three drawdown measures versus baseline."
        ),
        exposure_conclusion,
    ]


def _robot_conclusions(comparison: pd.DataFrame) -> list[str]:
    timed = _timed_rows(comparison, "humanoid_robot_proxy")
    deltas = timed["return_delta_vs_baseline"].astype(float)
    missed_count = int((deltas < -SUMMARY_TOLERANCE).sum())
    outperformed_count = int((deltas > SUMMARY_TOLERANCE).sum())
    five_minute_improved = int(
        (timed["max_drawdown_5m_delta_vs_baseline"] > SUMMARY_TOLERANCE).sum()
    )
    if missed_count == len(timed):
        return_conclusion = (
            f"All {len(timed)} robot timed rows return less than their "
            "position-matched baselines."
        )
        if five_minute_improved == len(timed):
            tradeoff_conclusion = (
                f"In this sample, all {len(timed)} robot timed rows pair missed upside "
                "with improved five-minute drawdown. Whether drawdown control compensates "
                "for missed upside is a sample-specific trade-off, not a universal conclusion."
            )
        else:
            tradeoff_conclusion = (
                f"Only {five_minute_improved} of {len(timed)} robot timed rows improve "
                "five-minute drawdown, so the sample does not show consistent drawdown "
                "control alongside missed upside."
            )
    elif outperformed_count == len(timed):
        return_conclusion = (
            f"All {len(timed)} robot timed rows outperformed their position-matched "
            "baselines; there is no missed-upside result in these rows."
        )
        tradeoff_conclusion = (
            f"{five_minute_improved} of {len(timed)} robot timed rows improve "
            "five-minute drawdown; no missed-upside compensation claim applies."
        )
    else:
        flat_count = len(timed) - missed_count - outperformed_count
        return_conclusion = (
            "Robot return evidence is mixed: "
            f"{missed_count} timed rows trail baseline, {outperformed_count} outperform, "
            f"and {flat_count} are flat."
        )
        tradeoff_conclusion = (
            f"{five_minute_improved} of {len(timed)} robot timed rows improve "
            "five-minute drawdown; the mixed sample does not support a universal "
            "missed-upside-versus-drawdown conclusion."
        )
    return [return_conclusion, tradeoff_conclusion]


def _terminal_event_conclusion(timeline: pd.DataFrame) -> str:
    signal_dates = pd.to_datetime(timeline["signal_date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    effective = pd.to_datetime(
        timeline["effective_timestamp"], errors="coerce"
    ).dt.strftime("%Y-%m-%d %H:%M:%S")
    terminal = timeline.loc[
        timeline["execution_mode"].eq("next_session_0935")
        & signal_dates.eq("2026-07-17")
        & effective.eq("2026-07-20 09:35:00")
    ]
    expected_definitions = {"single_day_4pct", "two_day_total_4pct"}
    found_definitions = set(terminal["timing_definition"].astype(str))
    complete = len(terminal) == 2 and found_definitions == expected_definitions
    if complete:
        return (
            "The audit contains both expected July 20 terminal next-session effective "
            "rows (2 of 2), one for each supplied definition."
        )
    return (
        "Terminal-event audit warning: expected 2 July 20 terminal next-session "
        f"effective rows, found {len(terminal)}; retention is missing or incomplete."
    )


def render_report(comparison: pd.DataFrame, timeline: pd.DataFrame) -> str:
    lines = [
        "# Active Market Cap Timing Comparison",
        "",
        "## Scope and metric contract",
        "",
        (
            "This compact comparison recomputes return, 5-minute/low/daily drawdown, "
            "closed/open trade counts, win rate, profit factor, capital utilization, "
            "turnover, and regime exits directly from NAV, fills, and trades. Source "
            f"summary values were accepted only within {SUMMARY_TOLERANCE:g} tolerance."
        ),
        (
            "Baseline risk-on session counts mean all analysis sessions were entry-eligible; "
            "timed counts use the supplied regime state at each 14:55 entry cycle."
        ),
        "",
        "## AI semiconductor: same-day versus next-session",
        "",
    ]
    ai = comparison.loc[comparison["pool"] == "ai_semiconductor"]
    for position in POSITIONS:
        group = ai.loc[ai["position_config"] == position].set_index("timing_variant")
        same = group.loc["same_day_1455"]
        next_row = group.loc["next_session_0935"]
        timing_delta = float(same["same_day_minus_next_session_return"])
        lines.append(
            f"- {position}: same-day {_percent(same['total_net_return'])} versus "
            f"next-session {_percent(next_row['total_net_return'])}, "
            f"{_same_day_difference(timing_delta)}; closed-trade denominators "
            f"{int(same['closed_trade_count'])} and {int(next_row['closed_trade_count'])}."
        )
    lines.extend(
        [
            (
                "The same-day 14:55 result has potential look-ahead because it assumes the "
                "full daily signal is observable and actionable before the close. The "
                "next-session control is the more conservative timing interpretation."
            ),
            "",
            "## Cross-matrix consistency",
            "",
        ]
    )
    lines.extend(_cross_matrix_conclusions(comparison))
    lines.extend(["", "## Battery: computed return, drawdown, and exposure", ""])
    battery = comparison.loc[comparison["pool"] == "battery"]
    for position in POSITIONS:
        group = battery.loc[battery["position_config"] == position].set_index("timing_variant")
        lines.append(_metric_line(f"{position} baseline", group.loc["baseline"]))
        lines.append(_metric_line(f"{position} same-day", group.loc["same_day_1455"]))
        lines.append(_metric_line(f"{position} next-session", group.loc["next_session_0935"]))
    lines.extend(_battery_conclusions(comparison))
    lines.extend(["", "## Humanoid robot proxy: computed return versus drawdown", ""])
    robot = comparison.loc[comparison["pool"] == "humanoid_robot_proxy"]
    for position in POSITIONS:
        group = robot.loc[robot["position_config"] == position].set_index("timing_variant")
        baseline = group.loc["baseline"]
        same = group.loc["same_day_1455"]
        next_row = group.loc["next_session_0935"]
        lines.append(
            f"- {position}: baseline return {_percent(baseline['total_net_return'])}; "
            f"same-day/next-session {_percent(same['total_net_return'])} / "
            f"{_percent(next_row['total_net_return'])}. Baseline 5m drawdown "
            f"{_percent(baseline['max_drawdown_5m'])}; timed drawdowns "
            f"{_percent(same['max_drawdown_5m'])} / "
            f"{_percent(next_row['max_drawdown_5m'])}."
        )
    lines.extend(_robot_conclusions(comparison))
    lines.extend(["", "## Innovative drug: zero timed exposure", ""])
    drug_timed = comparison.loc[
        (comparison["pool"] == "innovative_drug")
        & (comparison["timing_variant"] != "baseline")
    ]
    if (
        (drug_timed["closed_trade_count"] == 0).all()
        and (drug_timed["open_trade_count"] == 0).all()
    ):
        lines.append(
            f"All {len(drug_timed)} innovative-drug timed rows have zero closed and open "
            "trades. Their 0% return and 0% drawdown mean no exposure, not an improvement "
            "in selection."
        )
    else:
        lines.append(
            "Innovative-drug timed activity was nonzero; interpret each row using its "
            "explicit closed/open denominator rather than as a no-exposure result."
        )
    low = comparison.loc[
        (comparison["timing_variant"] != "baseline")
        & comparison["low_trade_count_flag"]
    ]
    lines.extend(
        [
            "",
            "## Sample size",
            "",
            (
                f"{len(low)} timed rows have only 2-6 closed trades. Win rates and profit "
                "factors are reported with their closed-trade denominators and are too "
                "thin for stable inference."
            ),
        ]
    )
    for row in low.itertuples(index=False):
        lines.append(
            f"- {row.pool} / {row.position_config} / {row.timing_variant}: "
            f"{int(row.closed_trade_count)} closed, {int(row.open_trade_count)} open."
        )
    equal_modes = timeline.groupby("execution_mode")["state_windows_equal"].all()
    definition_count = int(timeline["timing_definition"].nunique())
    lines.extend(
        [
            "",
            "## Regime audit and limitations",
            "",
            (
                "Both supplied definitions have equal state windows in each mode: "
                + ", ".join(
                    f"{mode}={str(bool(equal_modes.get(mode, False))).lower()}"
                    for mode in TIMINGS
                )
                + f". The audit retains {len(timeline)} event rows across "
                f"{definition_count} definitions."
            ),
            _terminal_event_conclusion(timeline),
            (
                "The regime dates were manually supplied and the exercise is post-hoc. "
                "The 4% rise and -3% fall thresholds were not optimized here; no threshold "
                "optimization or B1 parameter optimization was performed."
            ),
            (
                "Results are exploratory and do not establish causality. Lower drawdown "
                "can arise from lower exposure, so it must not be attributed automatically "
                "to better stock selection."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _write_manifest(
    output_root: Path,
    repo_root: Path,
    full_manifest_path: Path,
    source_hashes: Mapping[str, str],
) -> None:
    generated_hashes = {
        name: _sha256_file(output_root / name)
        for name in (
            "timing_comparison.csv",
            "regime_timeline_comparison.csv",
            "report.md",
        )
    }
    payload = {
        "full_matrix_source_manifest": {
            "path": _repo_relative(full_manifest_path, repo_root),
            "sha256": _sha256_file(full_manifest_path),
        },
        "source_sha256": dict(sorted(source_hashes.items())),
        "generated_sha256": generated_hashes,
        "comparison_row_count": 24,
        "comparison_key_contract": "pool__position_config__timing_variant",
        "source_summary_tolerance": SUMMARY_TOLERANCE,
    }
    (output_root / "run_sources.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def summarize(
    *,
    repo_root: str | Path,
    matrix_root: str | Path,
    output_root: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    repository = Path(repo_root).resolve()
    matrix = Path(matrix_root).resolve()
    output = Path(output_root).resolve()
    _repo_relative(matrix, repository)
    _repo_relative(output, repository)
    full_manifest_path, manifest = _load_manifest(matrix)
    indexed = _validate_matrix_runs(manifest)
    source_hashes = _validate_manifest_sources(manifest, repository)
    timeline, risk_on_counts, session_count, config_hashes = (
        build_regime_timeline_comparison(indexed, repository)
    )
    source_hashes.update(config_hashes)
    comparison, artifact_hashes = build_timing_comparison(
        indexed,
        repository,
        matrix,
        timeline,
        risk_on_counts,
        session_count,
    )
    source_hashes.update(artifact_hashes)

    output.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output / "timing_comparison.csv", index=False, float_format="%.17g")
    timeline.to_csv(output / "regime_timeline_comparison.csv", index=False)
    (output / "report.md").write_text(
        render_report(comparison, timeline), encoding="utf-8"
    )
    _write_manifest(output, repository, full_manifest_path, source_hashes)
    return comparison, timeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize the frozen active-market-cap timing matrix."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--matrix-root",
        type=Path,
        default=Path("outputs/intraday_b1_active_market_cap_20260719"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/intraday_b1_active_market_cap_20260719_summary"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    matrix_root = args.matrix_root
    if not matrix_root.is_absolute():
        matrix_root = repo_root / matrix_root
    output_root = args.output
    if not output_root.is_absolute():
        output_root = repo_root / output_root
    comparison, timeline = summarize(
        repo_root=repo_root,
        matrix_root=matrix_root,
        output_root=output_root,
    )
    print(
        f"wrote {len(comparison)} comparison rows and {len(timeline)} regime audit rows "
        f"to {output_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
