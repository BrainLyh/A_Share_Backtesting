# Active Market Cap Timing Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the manually supplied Compass 0AMV active-market-cap regime as an optional, auditable timing overlay on the verified five-minute B1 portfolio backtest, then compare untimed, same-day, and next-session execution across four stock pools and two position sizes.

**Architecture:** Introduce a deterministic market-regime module that converts dated up/down observations into effective intraday state transitions. Pass the optional schedule into the existing portfolio loop, where it blocks entries and injects a highest-priority persistent `market_regime_exit`; keep all price, fee, T+1, limit, and participation logic in the execution layer. Extend the CLI conditionally so untimed runs retain their existing output contract while timed runs add a regime audit artifact and source hash.

**Tech Stack:** Python 3.11+, pandas, numpy, unittest, existing Tongdaxin LC5/qfq snapshots and frozen B1 scan CSVs.

## Frozen Research Inputs

- Analysis window: `2026-06-01` through `2026-07-17`; June 1 is an observation start in `risk_off`, not an entry signal.
- Up observations: `single_day_4pct` on June 15; `two_day_total_4pct` on June 15 and the June 18 + June 22 confirmation effective June 22.
- Down observations for both definitions: June 8, July 2, July 7, July 8, July 13, July 16, and July 17.
- Main timing: `same_day_1455`; conservative control: `next_session_0935`.
- Pools: AI/semiconductor, CSI Innovative Drug 30, CSI Battery Theme, and CNI Robot Industry proxy.
- Position targets: canonical one-third and risk-controlled one-quarter; maximum concurrent positions remains three.
- Both signal definitions must generate equal effective state windows on these inputs. Prove equality before reusing a single execution result for both labels.
- This is post-hoc exploratory research. Do not tune the 4%/-3% thresholds or B1 parameters on these outcomes.

---

### Task 1: Deterministic Regime Schedule

**Files:**
- Create: `src/a_share_backtesting/market_regime.py`
- Create: `tests/test_market_regime.py`
- Create: `config/active_market_cap_single_day_4pct_same_day_20260719.json`
- Create: `config/active_market_cap_single_day_4pct_next_session_20260719.json`
- Create: `config/active_market_cap_two_day_4pct_same_day_20260719.json`
- Create: `config/active_market_cap_two_day_4pct_next_session_20260719.json`

**Interfaces:**
- `MarketRegimeSchedule.state_at(timestamp) -> str`
- `MarketRegimeSchedule.event_at(timestamp) -> RegimeTransition | None`
- `MarketRegimeSchedule.timeline -> pd.DataFrame`
- `load_market_regime_config(path) -> dict[str, object]`
- `build_market_regime_schedule(config, trading_dates) -> MarketRegimeSchedule`
- Timeline columns: `signal_date,effective_timestamp,event,label,prior_state,resulting_state,execution_mode`.

- [ ] **Step 1: Write failing schedule tests**

Cover initial `risk_off`, same-day June 15 activation at 14:55, July 2 deactivation at 14:55, repeated up/down idempotence, the June 22 confirmation retaining `risk_on`, and deterministic timeline ordering.

- [ ] **Step 2: Verify red**

Run: `python -m unittest tests.test_market_regime -v`

Expected: import failure because `a_share_backtesting.market_regime` does not exist.

- [ ] **Step 3: Implement same-day state construction and validation**

Validate the initial state, ISO dates, event values, duplicate/conflicting observations, known modes, and that effective timestamps fall on supplied trading dates. Preserve confirmation events in the timeline even when the state does not change.

- [ ] **Step 4: Add failing next-session and equality tests**

Assert D-day observations map to the next available trading date at 09:35, D-day 14:55 still sees the prior state, no future trading session raises an explicit error, and the supplied single-day/two-day definitions have identical state windows despite different event audit rows.

- [ ] **Step 5: Implement next-session mapping and verify green**

Run: `python -m unittest tests.test_market_regime -v`

Expected: all schedule tests pass.

- [ ] **Step 6: Add and parse the four dated configurations**

Keep event labels and execution modes explicit. Load each config in a test, build all four schedules, and assert deterministic effective timestamps and state-window equality by mode.

### Task 2: Highest-Priority Persistent Regime Exit

**Files:**
- Modify: `src/a_share_backtesting/intraday_execution.py`
- Modify: `tests/test_intraday_execution.py`

- [ ] **Step 1: Write failing regime-exit execution tests**

Create a position with ordinary stop/take-profit orders and a `market_regime_exit` order. Assert the regime order is processed first, replaces conflicting ordinary sell intent, records reason `market_regime_exit`, and uses the supplied trigger price at the effective bar.

- [ ] **Step 2: Verify red**

Run: `python -m unittest tests.test_intraday_execution.ExitExecutionTests -v`

Expected: the existing exit processor ignores or rejects the new reason.

- [ ] **Step 3: Implement minimal regime-order support**

Teach `process_exit_bar` to recognize a pending regime exit before ordinary exits. Retain the existing T+1 guard, lower-limit lock, adverse sell slippage, commission, stamp duty, 100-share handling, and 10% bar-volume cap. A partially filled regime order persists as the only pending sell intent and continues at the next executable bar.

- [ ] **Step 4: Test lower-limit, zero-volume, and T+1 behavior**

Assert no synthetic fill under a lower-limit one-price lock or zero volume, partial quantities reconcile exactly across bars, and an entry-day regime exit remains pending rather than violating T+1.

- [ ] **Step 5: Verify focused regression**

Run: `python -m unittest tests.test_intraday_execution -v`

Expected: all old and new execution tests pass.

### Task 3: Optional Portfolio Overlay

**Files:**
- Modify: `src/a_share_backtesting/intraday_portfolio.py`
- Modify: `tests/test_intraday_portfolio.py`

**Interface change:**
- Add keyword-only `market_regime: MarketRegimeSchedule | None = None` to `run_intraday_portfolio`.
- Add `market_regime: pd.DataFrame` to `PortfolioResult`, empty for untimed runs.

- [ ] **Step 1: Write failing same-day portfolio tests**

Using synthetic bars and a fixed candidate provider, assert: June 15 at 14:55 allows entry; July 2 at 14:55 injects full liquidation before ordinary exits; July 2 entries are rejected; every selected risk-off candidate is retained in the candidate audit and gets a `market_regime_off` rejection.

- [ ] **Step 2: Verify red and add schedule integration**

Run: `python -m unittest tests.test_intraday_portfolio.PortfolioChronologyTests -v`

Inject regime orders before the open-position exit loop at an effective transition timestamp. At the 14:55 entry cycle, evaluate candidates normally for audit, then gate fills from the resulting state. Do not duplicate regime orders for repeated down observations.

- [ ] **Step 3: Write next-session and reconciliation tests**

Assert a D-day down event leaves D-day 14:55 entries governed by the prior state, forces liquidation at D+1 09:35 using that bar's open as trigger, and blocks subsequent entries. Assert repeated up confirmation does not reset position IDs, peaks, holding days, pending orders, or expiry.

- [ ] **Step 4: Prove untimed behavior is unchanged**

Run each existing fixture both with the omitted argument and with `None`; compare every legacy result frame and open-position state. The new regime frame must be empty and no new rejection/exit reasons may appear.

- [ ] **Step 5: Verify portfolio tests**

Run: `python -m unittest tests.test_intraday_portfolio -v`

Expected: all chronology, accounting, metric, and regime tests pass.

### Task 4: Conditional CLI Artifact and Manifest Provenance

**Files:**
- Modify: `src/a_share_backtesting/intraday_portfolio_run.py`
- Modify: `tests/test_intraday_portfolio_run.py`
- Modify: `README.md`
- Modify: `config/active_market_cap_single_day_4pct_next_session_20260719.json`
- Modify: `config/active_market_cap_two_day_4pct_next_session_20260719.json`

- [ ] **Step 1: Write failing timed CLI test**

Pass `--market-regime <config>` to the existing synthetic end-to-end fixture. Assert `market_regime.csv` exists with the exact schema, event rows, and execution mode; the manifest contains the resolved schedule path and SHA-256; fills/trades/rejections expose the new reasons.

- [ ] **Step 2: Verify red and implement the optional argument**

Run: `python -m unittest tests.test_intraday_portfolio_run -v`

Build the schedule from actual in-window minute trading dates. Add `market_regime.csv` only when the argument is supplied, append it to the timed run's manifest outputs, and include the schedule in the runner call.

For next-session configurations, merge validated `calendar_extension_dates` into the scheduling calendar. The supplied configs must add 2026-07-20 with the official SSE 2026 closure-calendar source so the terminal 2026-07-17 observation remains auditable outside the return window. Calendar extensions affect only schedule construction and must never add NAV timestamps, bars, fills, or analysis days.

- [ ] **Step 3: Guard the untimed output contract**

Retain the existing `REQUIRED_OUTPUTS` set and existing manifest fields for runs without `--market-regime`. Extend the current untimed test to assert that it does not write `market_regime.csv` or schedule provenance.

- [ ] **Step 4: Add limitations disclosure**

Timed reports must state that dates were manually supplied, the thresholds are post-hoc, and `same_day_1455` assumes the full signal is observable by 14:55. The untimed report remains unchanged.

- [ ] **Step 5: Verify CLI and full regression suite**

Run: `python -m unittest tests.test_intraday_portfolio_run -v`

Then run: `python -m unittest discover -s tests -v`

Expected: all tests pass with no traceback or warning.

### Task 5: Execute Frozen Real-Data Matrix

**Files:**
- Create: `tools/run_active_market_cap_comparison.py`
- Create: `tests/test_active_market_cap_comparison.py`
- Generate ignored full ledgers under: `outputs/intraday_b1_active_market_cap_20260719/`

**Run matrix:** four pools x two target fractions x two execution modes = 16 timed portfolio runs. Reuse the corresponding verified untimed baseline artifacts. Do not rerun duplicate signal-definition labels after proving timeline equality.

- [ ] **Step 1: Write failing orchestration tests**

Test deterministic run naming, all 16 unique matrix keys, mapping of each pool to qfq/pool/scan inputs, one-third/one-quarter configs, and refusal to run when the two supplied definitions do not have equal state windows.

- [ ] **Step 2: Implement the matrix driver**

Invoke the tested portfolio CLI interfaces, fail fast on a nonzero return, and write a run-source manifest. Never discover or mutate inputs dynamically: use the frozen explicit paths listed in the design and repository configuration.

- [ ] **Step 3: Verify the driver on synthetic fixtures**

Run: `python -m unittest tests.test_active_market_cap_comparison -v`

Expected: all matrix and safety tests pass.

- [ ] **Step 4: Run the 16 real-data timed backtests**

Run: `python tools/run_active_market_cap_comparison.py --minute-root D:\apps\tdx\vipdoc --output outputs\intraday_b1_active_market_cap_20260719`

Expected: 16 complete run directories, each with all standard artifacts plus `market_regime.csv`, zero nonzero exits, and source hashes matching the frozen inputs.

- [ ] **Step 5: Reconcile every run**

Check ending cash plus marked positions equals NAV, sold shares never exceed bought shares, no position overlaps itself, no portfolio exceeds three holdings, all risk-off entries are absent, regime partials reconcile, and all output CSVs parse without schema drift.

### Task 6: Compact Comparison and Research Interpretation

**Files:**
- Create: `outputs/intraday_b1_active_market_cap_20260719_summary/timing_comparison.csv`
- Create: `outputs/intraday_b1_active_market_cap_20260719_summary/regime_timeline_comparison.csv`
- Create: `outputs/intraday_b1_active_market_cap_20260719_summary/run_sources.json`
- Create: `outputs/intraday_b1_active_market_cap_20260719_summary/report.md`

- [ ] **Step 1: Build the compact comparison from verified artifacts**

For each pool and position target, report untimed baseline, same-day, and next-session total net return, five-minute drawdown, conservative-low drawdown, daily drawdown, closed/open trades, win rate, profit factor, capital utilization, turnover, regime-exit count, and risk-on trading days.

- [ ] **Step 2: Add explicit deltas and sample-size checks**

Compute same-day-minus-baseline, next-session-minus-baseline, and same-day-minus-next-session return/drawdown deltas. Flag zero/low closed-trade counts and do not present win-rate changes without the denominator.

- [ ] **Step 3: Interpret without threshold optimization**

Separate the effect of reduced market exposure from stock-selection quality. State whether improvements are consistent across pools and position sizes, whether drawdown reduction compensates for missed upside, and how much result advantage disappears under next-session timing.

- [ ] **Step 4: Verify compact outputs**

Recompute key metrics directly from `nav_5m.csv`, `nav_daily.csv`, and `trades.csv`; assert the compact summary matches source artifacts within floating-point tolerance and contains no duplicate matrix rows.

### Task 7: Documentation, Final Verification, Commit, and Push

**Files:**
- Modify: `DEVELOPMENT_STATUS.md`
- Modify: `README.md` if command examples or limitations need final correction.
- Track the four regime configs, implementation/tests, plan/spec, matrix driver, and compact summary only. Keep full per-run ledgers ignored.

- [ ] **Step 1: Update project progress**

Record the exact state window, execution assumptions, run matrix, output locations, test count, primary metrics, same-day look-ahead caveat, and the fact that both supplied signal definitions currently yield the same state window.

- [ ] **Step 2: Run complete verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tools
git diff --check
git status --short --branch
```

Also rerun the artifact reconciliation and compact-summary consistency checks after all documentation edits.

- [ ] **Step 3: Review the final diff**

Confirm no raw Tongdaxin/qfq data, large full ledgers, stale outputs, unrelated changes, credentials, or user-local absolute paths are staged. Confirm untimed CLI behavior and artifacts remain unchanged.

- [ ] **Step 4: Commit implementation and research artifacts**

```powershell
git add src tests tools config docs README.md DEVELOPMENT_STATUS.md
git add -f outputs/intraday_b1_active_market_cap_20260719_summary
git commit -m "feat: add active market cap timing overlay"
```

- [ ] **Step 5: Push the approved branch**

```powershell
git push origin codex/b1-event-study
```

Report the pushed revision, test evidence, worktree cleanliness, and the comparison's key return/drawdown/win-rate conclusions.
