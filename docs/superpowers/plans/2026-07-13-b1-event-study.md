# B1 Signal Event Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, reproducible daily-bar event-study runner that compares the original pullback formula, its BBI filter, and B1 right-side confirmation over 2, 5, 10, and 20 full trading-day horizons.

**Architecture:** Preserve the existing continuous-portfolio runner. Add an independent event-study path: normalize local bars, calculate three end-of-day signals, convert first triggers to next-open trades, measure non-overlapping outcomes, and aggregate by signal date. A seeded random control samples the same-date eligible universe.

**Tech Stack:** Python 3.11+, pandas, numpy, unittest, JSON, UTF-8 CSV/Markdown.

## Global Constraints

- Signal date uses only that date's close; entry is next valid open.
- Baseline is technical-only: `require_core_pool=false`; a historical core-pool flag is an optional later filter.
- Variants are frozen as `legacy`, `bbi`, and `b1`; all twelve variant-horizon results are reported.
- Horizon `H`: enter at row `i+1` open after signal row `i`, exit at row `i+1+H` open.
- Per `(code, variant, horizon)`, ignore a new event until the previous event exits.
- Suspensions and price limits create recorded unfilled events, never assumed fills.
- Use `utf-8-sig` for output CSVs and do not fetch remote market data.

---

## Planned File Structure

```text
config/event_study_default.json
DEVELOPMENT_STATUS.md
src/a_share_backtesting/data_contract.py
src/a_share_backtesting/signals.py
src/a_share_backtesting/event_study.py
src/a_share_backtesting/statistics.py
src/a_share_backtesting/event_study_run.py
tests/test_data_contract.py
tests/test_signals.py
tests/test_event_study.py
tests/test_statistics.py
README.md
```

The previous continuous-portfolio runner is removed from this scope. A future continuous-portfolio system requires a separate design after event-study efficacy is established.

Before Task 1, create `DEVELOPMENT_STATUS.md`. Update it after every task with the completed task number, commit SHA, exact verification command/result, changed files, and the next task. This file is the cross-machine handoff record.

### Task 1: Freeze the input contract and experiment configuration

**Files:** Create `src/a_share_backtesting/data_contract.py`, `config/event_study_default.json`, `tests/test_data_contract.py`; modify `README.md`.

**Interfaces:**

```python
def normalize_daily_bars(frame: pd.DataFrame, require_core_pool: bool) -> pd.DataFrame: ...
def validate_event_config(config: dict[str, object]) -> None: ...
```

The required columns are `date`, `code`, `name`, `open`, `high`, `low`, `close`, `volume`, `market_cap`, `is_st`, `is_suspended`. `in_core_pool`, `upper_limit`, and `lower_limit` are optional.

- [ ] **Step 1: Write failing schema tests**

```python
def test_technical_baseline_defaults_missing_core_pool_to_true():
    normalized = normalize_daily_bars(minimum_frame().drop(columns=["in_core_pool"]), False)
    assert normalized["in_core_pool"].eq(True).all()

def test_missing_market_cap_is_rejected():
    with self.assertRaisesRegex(ValueError, "market_cap"):
        normalize_daily_bars(minimum_frame().drop(columns=["market_cap"]), False)
```

- [ ] **Step 2: Run and verify failure**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_data_contract -v
```

Expected: `ModuleNotFoundError` for `a_share_backtesting.data_contract`.

- [ ] **Step 3: Implement normalization and config validation**

```python
REQUIRED_BAR_COLUMNS = {"date", "code", "name", "open", "high", "low", "close", "volume", "market_cap", "is_st", "is_suspended"}

def normalize_daily_bars(frame: pd.DataFrame, require_core_pool: bool) -> pd.DataFrame:
    missing = REQUIRED_BAR_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data["code"] = data["code"].astype(str).str.zfill(6)
    if "in_core_pool" not in data:
        data["in_core_pool"] = not require_core_pool
    if require_core_pool and not data["in_core_pool"].notna().all():
        raise ValueError("in_core_pool is required when require_core_pool is true")
    return data.sort_values(["code", "date"]).reset_index(drop=True)
```

Validate positive integer horizons, `variants` as a nonempty subset of `{"legacy", "bbi", "b1"}`, and positive `event_notional`, `control_iterations`, and `random_seed`.

- [ ] **Step 4: Add the frozen default config**

```json
{
  "analysis_start": "2020-01-01", "analysis_end": "2026-06-30",
  "variants": ["legacy", "bbi", "b1"], "horizons": [2, 5, 10, 20],
  "require_core_pool": false, "min_market_cap": 10000000000,
  "j_threshold": 15.0, "pit_lookback": 5,
  "volume_ma_window": 5, "volume_multiplier": 1.0,
  "lot_size": 100, "event_notional": 100000,
  "commission_rate": 0.0003, "minimum_commission": 5.0,
  "sell_stamp_duty_rate": 0.0005,
  "control_iterations": 1000, "random_seed": 20260713
}
```

- [ ] **Step 5: Verify and commit**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_data_contract -v
git add src/a_share_backtesting/data_contract.py config/event_study_default.json tests/test_data_contract.py README.md
git commit -m "feat: define event study data contract"
```

Expected: all data-contract tests pass.

### Task 2: Create auditable `legacy`, `bbi`, and `b1` signal variants

**Files:** Modify `src/a_share_backtesting/signals.py`; create `tests/test_signals.py`.

**Interfaces:**

```python
def build_signal_variants(frame: pd.DataFrame, config: dict[str, object]) -> pd.DataFrame: ...
```

Return one row per `(code, date)` with boolean columns `legacy_signal`, `bbi_signal`, `b1_signal`, plus a `<variant>_first_trigger` column for each variant.

- [ ] **Step 1: Write failing variant tests**

```python
def test_bbi_signal_is_a_legacy_signal_with_uptrend_filter(self):
    result = build_signal_variants(bars_with_legacy_signal(), baseline_config())
    self.assertTrue(result.loc[result["bbi_signal"], "legacy_signal"].all())

def test_consecutive_signal_days_become_one_first_trigger(self):
    result = build_signal_variants(two_consecutive_signal_days(), baseline_config())
    self.assertEqual(result["legacy_first_trigger"].sum(), 1)
```

- [ ] **Step 2: Run and verify failure**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_signals -v
```

Expected: `ImportError` for `build_signal_variants`.

- [ ] **Step 3: Implement frozen variant definitions**

```python
data["legacy_signal"] = data["legacy_pullback_signal"]
data["bbi_signal"] = data["legacy_signal"] & trend
data["b1_signal"] = (
    eligibility & trend & (data["dif"] > 0) & prior_pit_seen
    & (data["j"] > prior_j) & (data["close"] > data["open"])
    & (data["volume"] >= data["volume_ma"] * float(config["volume_multiplier"]))
)
for variant in ("legacy", "bbi", "b1"):
    prior = data.groupby("code", sort=False)[f"{variant}_signal"].shift(1).fillna(False)
    data[f"{variant}_first_trigger"] = data[f"{variant}_signal"] & ~prior
```

`prior_pit_seen` is the rolling minimum J through the prior row only, so a confirmation day need not itself satisfy `J < threshold`.

- [ ] **Step 4: Verify preservation and commit**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_core tests.test_signals -v
git add src/a_share_backtesting/signals.py tests/test_signals.py
git commit -m "feat: add event study signal variants"
```

Expected: old indicator tests and new variant tests pass.

### Task 3: Measure executable, non-overlapping event outcomes

**Files:** Create `src/a_share_backtesting/event_study.py`, `tests/test_event_study.py`.

**Interfaces:**

```python
def measure_events(signals: pd.DataFrame, variant: str, horizon: int, config: dict[str, object]) -> pd.DataFrame: ...
```

Each event includes `event_id`, `code`, `variant`, `horizon`, `signal_date`, `entry_date`, `exit_date`, `status`, `gross_return`, `net_return`, `max_adverse_excursion`, and `close_max_drawdown`. Status values are `filled`, `unfilled_entry`, `unfilled_exit`, and `insufficient_history`.

- [ ] **Step 1: Write failing timing and fill tests**

```python
def test_next_open_entry_and_two_full_day_exit(self):
    event = measure_events(signal_on_first_row(), "legacy", 2, baseline_config()).iloc[0]
    self.assertEqual(event["entry_date"], pd.Timestamp("2026-01-05"))
    self.assertEqual(event["exit_date"], pd.Timestamp("2026-01-07"))

def test_upper_limit_entry_has_no_return(self):
    event = measure_events(limit_up_entry_frame(), "legacy", 2, baseline_config()).iloc[0]
    self.assertEqual(event["status"], "unfilled_entry")
    self.assertTrue(pd.isna(event["net_return"]))
```

- [ ] **Step 2: Run and verify failure**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_event_study -v
```

Expected: `ModuleNotFoundError` for `a_share_backtesting.event_study`.

- [ ] **Step 3: Implement horizon, limits, cost, and drawdown rules**

```python
def measure_events(signals, variant, horizon, config):
    rows = []
    trigger = f"{variant}_first_trigger"
    for code, bars in signals.groupby("code", sort=False):
        bars = bars.sort_values("date").reset_index(drop=True)
        next_allowed_index = 0
        for signal_index in bars.index[bars[trigger]]:
            entry_index, exit_index = signal_index + 1, signal_index + 1 + horizon
            if signal_index < next_allowed_index:
                continue
            rows.append(_measure_or_mark_unavailable(bars, signal_index, entry_index, exit_index, variant, horizon, config))
            if exit_index < len(bars):
                next_allowed_index = exit_index + 1
    return pd.DataFrame(rows)
```

`_measure_or_mark_unavailable` must use the next-open prices, lot-rounded `event_notional`, configured fees, daily lows for maximum adverse excursion, daily closes for maximum drawdown, and must not fill a suspended or price-limited order.

- [ ] **Step 4: Add overlap and drawdown tests, verify, commit**

```python
def test_second_event_before_exit_is_excluded(self):
    filled = measure_events(repeated_signal_frame(), "legacy", 5, baseline_config()).query("status == 'filled'")
    self.assertEqual(len(filled), 1)

def test_adverse_excursion_uses_intraday_low(self):
    event = measure_events(low_price_frame(), "legacy", 2, baseline_config()).iloc[0]
    self.assertAlmostEqual(event["max_adverse_excursion"], -0.12)
```

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_event_study -v
git add src/a_share_backtesting/event_study.py tests/test_event_study.py
git commit -m "feat: measure non-overlapping signal events"
```

Expected: all event tests pass.

### Task 4: Aggregate date portfolios and seeded random controls

**Files:** Create `src/a_share_backtesting/statistics.py`, `tests/test_statistics.py`.

**Interfaces:**

```python
def summarize_events(events: pd.DataFrame) -> pd.DataFrame: ...
def summarize_by_signal_date(events: pd.DataFrame) -> pd.DataFrame: ...
def random_control_test(signals: pd.DataFrame, events: pd.DataFrame, variant: str, horizon: int, config: dict[str, object]) -> tuple[pd.DataFrame, dict[str, float]]: ...
```

The primary statistic is the mean of equal-weight portfolios by signal date, preventing one busy signal day from dominating. The control samples non-signal eligible codes on each same signal date and reuses the event measurement rules.

- [ ] **Step 1: Write failing aggregate/control tests**

```python
def test_signal_dates_have_equal_weight(self):
    summary = summarize_by_signal_date(two_dates_with_unequal_event_counts())
    self.assertAlmostEqual(summary["portfolio_net_return"].mean(), 0.03)

def test_seed_makes_control_summary_repeatable(self):
    self.assertEqual(
        random_control_test(signals, events, "legacy", 5, baseline_config())[1],
        random_control_test(signals, events, "legacy", 5, baseline_config())[1],
    )
```

- [ ] **Step 2: Run and verify failure**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_statistics -v
```

Expected: `ModuleNotFoundError` for `a_share_backtesting.statistics`.

- [ ] **Step 3: Implement date aggregation and empirical control test**

```python
def summarize_by_signal_date(events):
    filled = events.loc[events["status"].eq("filled")]
    return filled.groupby(["variant", "horizon", "signal_date"], as_index=False).agg(
        event_count=("event_id", "size"),
        portfolio_net_return=("net_return", "mean"),
        portfolio_excess_return=("excess_return", "mean"),
        portfolio_max_adverse_excursion=("max_adverse_excursion", "mean"),
    )
```

Use `np.random.default_rng(config["random_seed"])`, `control_iterations` resamples, and report `observed_mean`, `control_mean`, `control_percentile`, and `empirical_p_value = mean(control_mean >= observed_mean)`. If a date has no eligible non-signal control, omit that date and report the omission count.

- [ ] **Step 4: Add empty-control test, verify, commit**

```python
def test_empty_control_pool_is_not_zero_return(self):
    distribution, summary = random_control_test(no_control_signals(), events, "legacy", 5, baseline_config())
    self.assertTrue(distribution.empty)
    self.assertTrue(np.isnan(summary["empirical_p_value"]))
```

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_statistics -v
git add src/a_share_backtesting/statistics.py tests/test_statistics.py
git commit -m "feat: compare signal events with random controls"
```

Expected: all statistics tests pass.

### Task 5: Add CLI, artifacts, documentation, and frozen-run audit

**Files:** Create `src/a_share_backtesting/event_study_run.py`; modify `README.md`; modify `tests/test_event_study.py`.

**Interfaces:**

```text
python -m a_share_backtesting.event_study_run --data <bars.csv> --config <config.json> --benchmark <benchmark.csv> --output <dir>
```

Benchmark is optional and has `date`, `open`, `close`. Artifacts are `signal_audit.csv`, `events.csv`, `date_portfolios.csv`, `summary.csv`, `control_distribution.csv`, `control_summary.json`, and `report.md`.

- [ ] **Step 1: Write failing CLI smoke test**

```python
def test_cli_writes_research_artifacts(self):
    code = main(["--data", str(self.bars_csv), "--config", str(self.config_json), "--output", str(self.output_dir)])
    self.assertEqual(code, 0)
    self.assertTrue((self.output_dir / "events.csv").exists())
    self.assertTrue((self.output_dir / "summary.csv").exists())
    self.assertTrue((self.output_dir / "report.md").exists())
```

- [ ] **Step 2: Run and verify failure**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_event_study.EventStudyCliTests.test_cli_writes_research_artifacts -v
```

Expected: `ImportError` for `event_study_run.main`.

- [ ] **Step 3: Implement orchestration and artifact writing**

```python
def main(argv=None):
    args = build_parser().parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    validate_event_config(config)
    bars = normalize_daily_bars(pd.read_csv(args.data, dtype={"code": str}), config["require_core_pool"])
    signals = build_signal_variants(bars, config)
    events = pd.concat([measure_events(signals, v, h, config) for v in config["variants"] for h in config["horizons"]], ignore_index=True)
    write_artifacts(Path(args.output), signals, events, config)
    return 0
```

Write CSV with `utf-8-sig`, JSON with `ensure_ascii=False`, and a report containing date coverage, all twelve result rows, filled/unfilled counts, cost assumptions, random seed, and the next-open convention.

- [ ] **Step 4: Verify the full suite and document execution**

```powershell
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest discover -s tests -v
& $py -m a_share_backtesting.event_study_run --data data\daily_bars.csv --benchmark data\benchmark_000300.csv --config config\event_study_default.json --output outputs\event_study_2026h1
```

Expected: all tests pass; the second command writes every artifact when real input files are present.

- [ ] **Step 5: Audit the frozen run and commit source/docs only**

Verify in `events.csv` that every filled event satisfies `signal_date < entry_date < exit_date`, no unfilled-entry event has a return, and every variant-horizon pair is present in `summary.csv`. Add the exact command, 120-day indicator warm-up requirement, point-in-time core-pool limitation, data source, date coverage, benchmark, and price-adjustment convention to README.

```powershell
git add src/a_share_backtesting/event_study_run.py README.md tests/test_event_study.py
git commit -m "feat: add reproducible B1 event study runner"
```

## Self-Review

- Coverage: Tasks 1–2 define inputs and three frozen experiments; Task 3 enforces time ordering, costs, limits, non-overlap, and risk measures; Task 4 produces date-clustered summaries and controls; Task 5 makes the research repeatable and auditable.
- Consistency: `build_signal_variants` feeds `measure_events`; event outputs feed both summary functions and the CLI. Configuration is validated before any calculation.
- Scope: This plan deliberately excludes daily portfolio rebalancing, discretionary core-pool construction, multi-stage scaling, and intraday stop simulation; those need separate designs after signal efficacy is established.
