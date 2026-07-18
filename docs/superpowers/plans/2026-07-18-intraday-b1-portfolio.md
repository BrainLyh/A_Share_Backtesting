# Intraday B1 Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate a five-minute B1 portfolio backtest with rolling D-day scans, 14:55 entry, T+1 exits, three-position capacity, costs, volume limits, and account-level return and drawdown.

**Architecture:** Add focused modules for Tongdaxin LC5 parsing, provisional-day signal scans, deterministic execution/account state, and CLI/report orchestration. Reuse the existing qfq, indicator, and B1 definitions while keeping all existing event-study modes unchanged. Real-data research consumes only the tested public interfaces.

**Tech Stack:** Python 3.11+, pandas, numpy, unittest, Tongdaxin `.lc5`, existing rustdx/qfq CSV snapshots.

## Global Constraints

- Scan only completed bars at 14:40, 14:45, and 14:50; enter at the 14:55 close.
- Candidate Scheme A requires any earlier true scan and B1 still true at 14:50.
- A prior completed B1-false day is required; held codes cannot pyramid.
- Initial cash is CNY 1,000,000; target weight is one third of pre-entry NAV; maximum positions is three.
- Buy and sell slippage are 5 basis points; commission is 0.03% with CNY 5 minimum; sell stamp duty is 0.05%.
- Every fill is capped at 10% of its five-minute raw volume.
- No entry-day sale. Exit priority is stop, +10%, +20%, residual 15% drawdown, D+5 expiry.
- ATR stop is `clamp(1.5 * ATR14 / adjusted_entry_price, 6%, 10%)`.
- Stop wins any same-bar ambiguity. New residual peaks use only completed prior closes.
- Existing CLI modes and their output contracts remain unchanged.
- No parameter tuning on validation dates or sector holdout pools.

---

### Task 1: Tongdaxin LC5 Adapter

**Files:**
- Create: `src/a_share_backtesting/tdx_lc5.py`
- Create: `tests/test_tdx_lc5.py`

**Interfaces:**
- Produces: `read_tdx_lc5_file(path: Path) -> pd.DataFrame`
- Produces: `find_lc5_path(root: Path, code: str) -> Path | None`
- Produces: `audit_lc5_frame(frame: pd.DataFrame) -> list[str]`
- Frame columns: `timestamp,date,time,code,open,high,low,close,volume`

- [ ] **Step 1: Write failing binary-decoding tests**

Create synthetic 32-byte records with `struct.pack("<HHfffffII", encoded_date, minutes, open, high, low, close, amount, volume, reserved)` and assert date `2026-07-17`, time `14:55`, code from filename, OHLC, and volume. Add failures for non-32-byte length, invalid market filename, duplicate timestamps, invalid OHLC, and incomplete required scan bars.

- [ ] **Step 2: Verify red**

Run: `python -m unittest tests.test_tdx_lc5 -v`

Expected: import failure because `a_share_backtesting.tdx_lc5` does not exist.

- [ ] **Step 3: Implement the minimal adapter**

Decode date with `year = raw_date // 2048 + 2004`, `month_day = raw_date % 2048`, and time as minutes after midnight. Ignore amount and reserved. Validate finite positive OHLC, `low <= open/close <= high`, chronological uniqueness, and expected market prefix selected from the six-digit code.

- [ ] **Step 4: Verify green and existing parser tests**

Run: `python -m unittest tests.test_tdx_lc5 tests.test_tdx_day -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/a_share_backtesting/tdx_lc5.py tests/test_tdx_lc5.py
git commit -m "feat: parse Tongdaxin five-minute bars"
```

### Task 2: Intraday B1 Scans

**Files:**
- Create: `src/a_share_backtesting/intraday_signals.py`
- Create: `tests/test_intraday_signals.py`
- Modify: `src/a_share_backtesting/indicators.py`

**Interfaces:**
- Consumes: normalized completed daily qfq bars and one raw LC5 day with `qfq_scale`.
- Produces: `build_provisional_daily_bar(minute_day, scan_time, qfq_scale) -> dict[str, object]`
- Produces: `scan_intraday_b1(daily_history, minute_day, config) -> pd.DataFrame`
- Scan output columns: `date,code,scan_time,b1_signal,eligible,signal_strength,j,prior_j,bbi,dif,volume,volume_ma,atr14`
- Produces: `select_scheme_a_candidates(scans, prior_day_b1, held_codes) -> pd.DataFrame`

- [ ] **Step 1: Write failing provisional-bar tests**

Use four minute bars ending at 14:40 and later bars with extreme values. Assert the 14:40 bar uses only earlier OHLC and cumulative volume. Assert qfq scaling applies only to OHLC and not volume.

- [ ] **Step 2: Verify red**

Run: `python -m unittest tests.test_intraday_signals.IntradaySignalTests.test_provisional_bar_does_not_use_future_bars -v`

Expected: import failure for the new module.

- [ ] **Step 3: Implement provisional bars and ATR14**

Add a reusable grouped true-range/ATR14 helper to `indicators.py`. Build a one-code provisional frame by appending the partial day to completed history and call existing indicators/B1 logic without changing `signals.py` behavior.

- [ ] **Step 4: Write failing Scheme A tests**

Cover true/false/true scans, true at 14:40 but false at 14:50, prior-day B1 true, held code, first trigger ordering, final strength ordering, and code tie-breaks.

- [ ] **Step 5: Verify red, implement candidate selection, and verify green**

Run before implementation: `python -m unittest tests.test_intraday_signals -v`

Expected: Scheme A assertions fail.

Implement explicit scan-time categorical ordering and deterministic sorting. Run the same command and expect all tests to pass.

- [ ] **Step 6: Commit**

```powershell
git add src/a_share_backtesting/indicators.py src/a_share_backtesting/intraday_signals.py tests/test_intraday_signals.py
git commit -m "feat: scan rolling intraday B1 signals"
```

### Task 3: Execution Rules

**Files:**
- Create: `src/a_share_backtesting/intraday_execution.py`
- Create: `tests/test_intraday_execution.py`

**Interfaces:**
- Produces immutable `ExecutionConfig`, `Position`, `PendingExit`, and `Fill` dataclasses.
- Produces: `commission(notional, config) -> float`
- Produces: `entry_fill(candidate, bar, nav, cash, config) -> Fill | Rejection`
- Produces: `process_exit_bar(position, pending, bar, config) -> ExitResult`
- Produces: `is_one_price_limit(bar, preclose, side) -> bool`

- [ ] **Step 1: Write failing entry tests**

Assert one-third NAV sizing, 100-share rounding, adverse 5bp slippage, minimum commission, insufficient cash reduction, 10% volume cap, zero-lot rejection, and one-price upper-limit rejection.

- [ ] **Step 2: Verify red and implement entry functions**

Run: `python -m unittest tests.test_intraday_execution.EntryExecutionTests -v`

Expected: module import failure. Implement only entry behavior and rerun to green.

- [ ] **Step 3: Write failing exit tests**

Cover T+1 block, gap stop at open, threshold stop, same-bar stop/profit conflict, gap above both take-profit levels, ascending profit priority, persistent partial fills, one-price lower-limit blocking, residual prior-close peak, per-fill fees, sell stamp duty, and D+5 overtime status.

- [ ] **Step 4: Verify red and implement exit state transitions**

Run: `python -m unittest tests.test_intraday_execution.ExitExecutionTests -v`

Expected: exit assertions fail. Implement stop cancellation of pending profits, per-bar available volume, exact remaining-unit reconciliation, and legal limit clamps. Rerun to green.

- [ ] **Step 5: Commit**

```powershell
git add src/a_share_backtesting/intraday_execution.py tests/test_intraday_execution.py
git commit -m "feat: model five-minute B1 execution"
```

### Task 4: Chronological Portfolio Engine

**Files:**
- Create: `src/a_share_backtesting/intraday_portfolio.py`
- Create: `tests/test_intraday_portfolio.py`

**Interfaces:**
- Consumes: `dict[str, pd.DataFrame]` daily bars, `dict[str, pd.DataFrame]` minute bars, config, and date range.
- Produces: `PortfolioResult` with `scans,candidates,orders,fills,positions,trades,nav_5m,nav_daily,rejections,data_audit`.
- Produces: `run_intraday_portfolio(...) -> PortfolioResult`
- Produces: `summarize_portfolio(result, initial_cash) -> tuple[pd.DataFrame, pd.DataFrame]`

- [ ] **Step 1: Write failing account chronology tests**

Build two-day, four-code fixtures. Assert no more than three codes, no duplicate code, exit-before-entry at 14:55, same pre-entry NAV target for candidates, same-day sell cash availability before 14:55, and no entry-day sale.

- [ ] **Step 2: Verify red and implement chronological loop**

Run: `python -m unittest tests.test_intraday_portfolio.PortfolioChronologyTests -v`

Expected: module import failure. Implement timestamp-sorted state updates, then rerun to green.

- [ ] **Step 3: Write failing accounting and metric tests**

Assert qfq scale market-value continuity, cash plus positions equals NAV, open trades excluded from win rate, mature cohort labeling, net trade win rate, profit factor, five-minute close drawdown, conservative low drawdown, daily drawdown, turnover, exposure, and cost drag.

- [ ] **Step 4: Verify red and implement reconciliation/metrics**

Run: `python -m unittest tests.test_intraday_portfolio -v`

Expected: metric assertions fail. Implement with explicit finite-value checks and one-cent cash/NAV tolerance. Rerun to green.

- [ ] **Step 5: Commit**

```powershell
git add src/a_share_backtesting/intraday_portfolio.py tests/test_intraday_portfolio.py
git commit -m "feat: add chronological B1 portfolio ledger"
```

### Task 5: CLI, Outputs, and Manifest

**Files:**
- Create: `src/a_share_backtesting/intraday_portfolio_run.py`
- Create: `tests/test_intraday_portfolio_run.py`
- Modify: `README.md`

**Interfaces:**
- CLI inputs: `--minute-root`, `--qfq-source`, `--stock-pool`, `--config`, `--output`, `--analysis-start`, `--analysis-end`.
- Writes the 14 artifacts specified by the design.

- [ ] **Step 1: Write a failing end-to-end CLI test**

Create two synthetic LC5 files, qfq CSV, pool CSV, and config in a temporary directory. Call `main([...])`; assert exit code zero, every required output exists, manifest hashes are populated, and summary cash/NAV reconcile.

- [ ] **Step 2: Verify red**

Run: `python -m unittest tests.test_intraday_portfolio_run -v`

Expected: import failure for the CLI module.

- [ ] **Step 3: Implement loading, output, and reporting**

Load only pool codes, retain 180 actual daily observations before the analysis start, join per-day qfq scale and explicit price limits, validate the exact five-minute grid and minute/day close alignment, write CSVs with UTF-8 BOM, write stable JSON with source hashes, repository-relative Git revision, and dirty state, and generate a concise Markdown report with limitations.

- [ ] **Step 4: Verify focused and full suites**

Run: `python -m unittest tests.test_intraday_portfolio_run -v`

Then run: `python -m unittest discover -s tests -v`

Expected: all tests pass with no warnings or tracebacks.

- [ ] **Step 5: Commit**

```powershell
git add src/a_share_backtesting/intraday_portfolio_run.py tests/test_intraday_portfolio_run.py README.md
git commit -m "feat: expose intraday portfolio backtest CLI"
```

### Task 6: Real Data Runs and Research Report

**Files:**
- Modify: `DEVELOPMENT_STATUS.md`
- Create: `config/intraday_portfolio_20260718.json`
- Create when sourced: `config/innovative_drug_stock_pool_20260718.csv`
- Create when sourced: `config/lithium_battery_stock_pool_20260718.csv`
- Create when sourced: `config/humanoid_robot_stock_pool_20260718.csv`
- Track only compact comparison summaries under `outputs/`; leave large ledgers ignored.

**Interfaces:**
- Consumes the tested CLI only.
- Produces same-window, latest-window, mature-cohort, parameter sensitivity, and cross-sector comparisons.

- [ ] **Step 1: Audit and rebuild qfq inputs through 2026-07-17**

Use the current Tongdaxin daily files and `D:/apps/tdx/T0002/hq_cache/gbbq`. Confirm raw/qfq rows, last date, code coverage, adjustment jumps, and 15:00 daily-close matches. Do not overwrite the previous qfq snapshot; create a dated output directory.

- [ ] **Step 2: Run AI/semiconductor canonical windows**

Run the CLI for 2026-06-01 through 2026-07-15 and through 2026-07-17. Preserve manifests and compact summaries. Compare daily baseline, unlimited rolling events, and canonical portfolio without conflating event mean return with account return.

- [ ] **Step 3: Run frozen sensitivity checks**

Keep signal and exit parameters fixed. Run only execution sensitivities that preserve hard strategy limits: slippage 0/5/10bp and max positions 1/2/3. Audit every fill against the fixed 10% participation cap. Report these as capacity/execution checks, not strategy optimization.

- [ ] **Step 4: Apply walk-forward discipline if strategy quality is weak**

Use the earlier portion as training and the latest complete lifecycle dates as validation. Candidate changes may include signal persistence count, market trend gating, and relative-strength ranking, but select at most one rule using training data. Freeze it before validation and sector testing. Keep the original canonical result visible even when an improvement is tested.

- [ ] **Step 5: Build cited sector pools and run holdouts**

Use public index constituent or recognized sector-universe sources to create innovation-drug, lithium-battery, and humanoid-robot pools with source URLs and as-of date in companion metadata. Intersect with available LC5/qfq codes, run unchanged parameters, and report coverage/missing codes.

- [ ] **Step 6: Update progress and verify repository state**

Record commands, data hashes, result tables, limitations, optimization separation, and cross-sector conclusions in `DEVELOPMENT_STATUS.md`. Run the full test suite, `git diff --check`, inspect tracked outputs, commit, push `codex/b1-event-study`, and confirm the worktree is clean.

---

## Self-review checklist

- Every confirmed design requirement maps to Tasks 1-6.
- Existing historical modes are untouched except shared indicator extraction with regression coverage.
- All production functions are introduced after a failing test.
- Real-data and sector research use the tested CLI rather than one-off return calculators.
- Strategy optimization is separated from execution sensitivity and held-out validation.
