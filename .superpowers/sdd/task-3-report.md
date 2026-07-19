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

No unresolved functional concerns. Overlay transitions require the corresponding effective 5-minute bar (14:55 or 09:35) to be present for a position to execute at the specified trigger, which matches the supplied portfolio-bar contract.
