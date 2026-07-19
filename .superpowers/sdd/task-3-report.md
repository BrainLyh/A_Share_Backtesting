# Task 3 Report: Optional Portfolio Overlay

## Status

Implemented the optional `MarketRegimeSchedule` overlay in the intraday portfolio runner. The implementation is backward compatible when `market_regime` is omitted or explicitly `None`, and returns an empty `market_regime` result frame in that mode.

## Scope

Production and test changes are limited to:

- `src/a_share_backtesting/intraday_portfolio.py`
- `tests/test_intraday_portfolio.py`

This report is the only additional file. The pre-existing `.gitignore` modification was not changed or staged. Task 1 and Task 2 files were read only where required to use their public schedule and execution contracts.

## Implementation

- Added keyword-only `market_regime: MarketRegimeSchedule | None = None` to `run_intraday_portfolio`.
- Added `market_regime: pd.DataFrame` to `PortfolioResult`; timed runs copy the schedule timeline and untimed runs return an empty frame.
- At an effective down transition, injects one full `market_regime_exit` before ordinary exit processing.
- Same-day transitions use the adjusted 14:55 close as the trigger; next-session transitions use the adjusted 09:35 open.
- Existing regime remainders are preserved on repeated down observations rather than replaced or duplicated.
- Up observations do not mutate positions, pending exits, peaks, entry identity, holding chronology, or expiry.
- Candidate selection and candidate audit still run at every 14:55 cycle. When risk is off, every selected candidate receives `market_regime_off` and cannot fill.
- A surviving regime remainder continues to block entries after a later up event. Entry resumes once all regime remainders reconcile.

## TDD Evidence

All commands used the required interpreter and `PYTHONPATH=$PWD\src`.

### RED 1: Same-day integration

Command:

```text
python -m unittest tests.test_intraday_portfolio.PortfolioChronologyTests -v
```

Result: 9 tests ran; the new same-day test errored as expected because the feature API was absent:

```text
TypeError: run_intraday_portfolio() got an unexpected keyword argument 'market_regime'
FAILED (errors=1)
```

### GREEN 1: Same-day integration

The same command passed after adding the minimal schedule API, pre-exit injection, risk-off gate, and result timeline:

```text
Ran 9 tests in 0.189s
OK
```

### RED 2: Next-session and reconciliation

After adding next-session, repeated-event, state-continuity, and compatibility tests, the chronology command ran 14 tests with two expected failures:

```text
test_next_session_regime_uses_open_after_allowing_signal_day_entry ... FAIL
AssertionError: 10.5947 != 9.3953

test_regime_remainder_survives_repeated_down_and_up_before_entries_resume ... FAIL
AssertionError: 10.5947 != 9.3953

FAILED (failures=2)
```

These failures proved that next-session liquidation incorrectly used the adjusted close and that repeated down replaced the original remainder trigger.

### GREEN 2: Complete chronology behavior

After selecting the trigger column by execution mode, preserving existing regime orders, and gating on surviving remainders:

```text
Ran 14 tests in 0.335s
OK
```

The passing cases include same-day ordering, next-session timing, repeated down, later up, reconciliation, repeated-up state preservation, and omitted/`None` parity.

## Verification

Focused portfolio module:

```text
python -m unittest tests.test_intraday_portfolio -v
Ran 16 tests in 0.361s
OK
```

Full suite:

```text
python -m unittest discover -s tests -v
Ran 112 tests in 1.787s
OK
```

An initial `python -m unittest discover -v` invocation discovered zero tests because this repository requires `-s tests`; it exited with `NO TESTS RAN`. The corrected full-suite command above is the verification result.

`git diff --check` exited successfully. Git emitted only line-ending conversion warnings and no whitespace errors.

## Compatibility Evidence

Two legacy portfolio fixtures (open and expiry-closed states) were run with the argument omitted and with `market_regime=None`. The tests compare all legacy frames (`scans`, `candidates`, `orders`, `fills`, `positions`, `trades`, `nav_5m`, `nav_daily`, `rejections`, and `data_audit`) plus `open_positions`. Both new `market_regime` frames are empty.

## Concerns

No unresolved functional concerns. A held code without the effective 14:55 or 09:35 bar now remains pending and exits from its next executable bar's adjusted open.

## Critical Review Fix: Missing Per-Holding Transition Bar

### Finding and Root Cause

The original overlay discovered a down transition from the union of portfolio timestamps, but attempted to create each held position's `market_regime_exit` only after finding that position's exact timestamp bar. A holding with no 14:55 or 09:35 row skipped the entire exit path, lost liquidation intent, and could coexist with new entries after a later up transition.

The fix creates regime intent for every open position before per-code bar processing. If the held code has the exact effective bar, the pending order retains the adjusted close/open trigger. If it does not, the order retains the transition timestamp with no trigger price; Task 2 therefore prices its eventual fill from the next executable bar's adjusted open. Existing remainders are still not replaced.

### RED

Added heterogeneous-timestamp regressions for both execution modes. In each case another code supplies the global transition timestamp, the held code lacks its effective bar, a later up event occurs, and a candidate attempts entry before the holding can reconcile.

Command:

```text
python -m unittest tests.test_intraday_portfolio.PortfolioChronologyTests -v
```

Initial result:

```text
test_next_session_regime_intent_survives_missing_transition_bar_until_reconciled ... FAIL
test_same_day_regime_intent_survives_missing_transition_bar_until_reconciled ... FAIL

AssertionError: Lists differ: [] != [Timestamp('2026-07-04 15:00:00')]
AssertionError: Lists differ: [] != [Timestamp('2026-07-03 15:00:00')]

Ran 16 tests in 0.409s
FAILED (failures=2)
```

The empty sell lists demonstrate that no regime intent survived the missing effective bars.

### GREEN

The first implementation pass made the same-day regression pass and exposed a `KeyError: 'timestamp'` when a held code had no rows for the entire next-session effective date. Guarding that lookup with the existing `code in minute_days` pattern completed the same root-cause fix.

Final chronology result:

```text
python -m unittest tests.test_intraday_portfolio.PortfolioChronologyTests -v
Ran 16 tests in 0.406s
OK
```

Both regressions verify that no fill or trigger price is synthesized at the missing transition bar, the later candidate receives `market_regime_off`, the real deferred fill uses the next executable bar's adjusted open, and entry resumes only on the following candidate cycle after reconciliation.

### Review-Fix Verification

Focused portfolio module:

```text
python -m unittest tests.test_intraday_portfolio -v
Ran 18 tests in 0.450s
OK
```

Full suite:

```text
python -m unittest discover -s tests -v
Ran 114 tests in 1.868s
OK
```

No execution, schedule, CLI, or `.gitignore` files were changed.
