# Task 4 Report: Conditional CLI Artifact and Manifest Provenance

## Status

Implemented the optional `--market-regime` CLI integration without changing the untimed artifact, report, or manifest contracts.

## Implementation Commit

- `61a32ea feat: add conditional market regime CLI artifacts`

## Files Changed

- `src/a_share_backtesting/intraday_portfolio_run.py`
- `tests/test_intraday_portfolio_run.py`
- `README.md`
- `config/active_market_cap_single_day_4pct_next_session_20260719.json`
- `config/active_market_cap_two_day_4pct_next_session_20260719.json`
- `.superpowers/sdd/task-4-report.md` (this report only)

The pre-existing `.gitignore` and timing design/plan edits were not changed, staged, or committed.

## RED/GREEN Evidence

All Python commands used the bundled interpreter with `PYTHONPATH=$PWD\src`.

1. Baseline: `python -m unittest tests.test_intraday_portfolio_run -v` passed 7 tests before Task 4 edits.
2. RED 1: after adding the timed end-to-end test, the focused module ran 8 tests and errored only on the new case because `--market-regime` was unrecognized (`SystemExit: 2`).
3. GREEN 1: after the conditional CLI path was implemented, the focused module passed all 8 tests.
4. RED 2: the extension-validation test produced seven expected assertion failures and one incidental `AttributeError`, demonstrating that malformed list/date/source/mode/boundary inputs were not explicitly rejected.
5. GREEN 2: after explicit validation was added, the focused module passed all 9 tests.
6. Final focused verification: 9 tests passed in 0.677 seconds.
7. Full regression verification: 116 tests passed in 2.084 seconds with no traceback or warning.

## Behavior Delivered

- Timed runs load and hash the resolved regime config, build the schedule from actual loaded minute dates, pass it to `run_intraday_portfolio`, and add `market_regime.csv` plus timed-only manifest output/provenance fields.
- Next-session `calendar_extension_dates` require a non-empty unique ISO-date list, a non-empty source, `next_session_0935`, and dates after the loaded in-window sessions.
- Extensions affect schedule construction only. The timed test proves a July 20 transition can appear in `market_regime.csv` while NAV and fill timestamps remain on or before July 17.
- Fills/trades expose `market_regime_exit`; rejections expose `market_regime_off`.
- Timed reports disclose manually supplied dates, post-hoc thresholds, and the 14:55 observability assumption. Untimed reports remain unchanged.
- Both next-session configs add `2026-07-20` with the exact supplied SSE closure-calendar source.

## Self-Review

- `REQUIRED_OUTPUTS` is unchanged, and the untimed test asserts the exact legacy file set, absence of schedule provenance, absence of `market_regime.csv`, and absence of timed report text.
- The extension calendar is never passed to data loaders or used to change `analysis_end`; it is scoped to schedule construction.
- The timed timeline schema and both event rows are asserted exactly, including the terminal transition after the return window.
- Manifest schedule provenance uses the resolved path and SHA-256 of the source config.
- Both edited JSON files parse successfully, and `git diff --check` passed with only expected line-ending conversion notices.

## Concerns

- The CLI validates extension metadata structurally and preserves it in the hashed config, but it does not fetch or independently authenticate the referenced exchange calendar.
