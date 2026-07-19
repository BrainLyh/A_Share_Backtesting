# Active Market Cap Timing Overlay Design

## Purpose

Add the manually observed Compass 0AMV active-market-cap signals as a market-wide timing overlay on the verified five-minute B1 portfolio backtest. The overlay controls when the portfolio may open or hold risk. It does not alter the B1 formula, candidate ranking, staged exits, costs, or stock-pool definitions.

This is an exploratory timing study. The thresholds and dates were supplied after observing the period, so the result is not an out-of-sample validation and must not be described as proven alpha.

## Confirmed Inputs

The analysis starts on 2026-06-01 with the regime closed. June 1 is only an observation start and does not permit entry.

Down events are identical for both definitions:

- 2026-06-08
- 2026-07-02
- 2026-07-07
- 2026-07-08
- 2026-07-13
- 2026-07-16
- 2026-07-17

Timing definition `single_day_4pct` uses a single-day 0AMV rise of at least 4%:

- up event: 2026-06-15

Timing definition `two_day_total_4pct` uses the supplied two-session cumulative rise events:

- up event: 2026-06-15
- second confirmation: observations on 2026-06-18 and 2026-06-22, effective on 2026-06-22

Both definitions use a single-day 0AMV fall of at least 3% as the down event.

## State Machine

The overlay has two persistent states:

- `risk_off`: reject all new B1 entries and continue trying to liquidate any regime-exit remainder.
- `risk_on`: allow the existing rolling B1 candidate and portfolio rules to operate normally.

An up event changes `risk_off` to `risk_on`. A repeated up event while already `risk_on` is recorded as confirmation but does not reset positions, holding days, peaks, stops, or expiry dates. A down event changes the state to `risk_off`, blocks new entries, and submits a full liquidation order for every open position.

Repeated down events while already `risk_off` do not create duplicate orders. A later up event cancels no existing regime-exit remainder: liquidation must reconcile first, after which new entries may resume.

With the supplied dates, both timing definitions produce the same primary state window: open on 2026-06-15 and close on 2026-07-02. The 2026-06-08 down event occurs while already closed; the 2026-06-22 cumulative confirmation occurs while already open; all later down events occur while already closed. The implementation must verify this equality rather than assume it silently.

## Execution Timing

### Requested Same-Day Mode

The main mode is `same_day_1455`:

- an up event enables the 14:55 B1 entry cycle on that date;
- a down event is applied at 14:55 on that date;
- regime liquidation has priority over stop, take-profit, residual, and expiry processing at that timestamp;
- no new entries are allowed on a down-event date.

Regime liquidation uses the 14:55 completed-bar close as its base price, adverse sell slippage, commission, stamp duty, explicit price limits, 100-share rules, and the fixed 10% bar-volume participation cap. Unfilled quantity remains a `market_regime_exit` order and executes at the next executable bar. Lower-limit locks and zero volume never create synthetic fills.

### Conservative Timing Control

Because a full-day 0AMV change may only be known after the close, also run `next_session_0935`:

- a D-day up event becomes effective at D+1 09:35 and permits entries from D+1 onward;
- a D-day down event becomes effective at D+1 09:35 and liquidates at that bar's open;
- the portfolio still follows the prior state during D, including the D-day 14:55 entry decision.

This control quantifies possible look-ahead advantage in same-day execution. The requested same-day result remains primary, but both results must be reported together.

The sample ends on 2026-07-17, so that date's down observation becomes effective outside the return window on 2026-07-20. The two next-session configurations explicitly carry `calendar_extension_dates` with 2026-07-20 and the official SSE 2026 closure-calendar source. This extension is used only to retain the terminal event in the audit timeline; it does not load future prices, create a fill, or extend the portfolio measurement window.

## Interaction With Existing Rules

- A-share T+1 remains mandatory. The supplied up and down events do not occur on the same date, so the primary schedule does not require an entry-day sell.
- A regime exit overrides ordinary strategy exits because the user-defined market window requires full liquidation.
- Partial fills consume the same per-bar capacity as every other sell.
- A position closed by an ordinary stop or take-profit before the down event is not recreated by the regime layer.
- While `risk_off`, frozen B1 scans remain auditable but candidates are rejected with `market_regime_off`.
- Existing cash, maximum-three-position, no-pyramiding, qfq, and accounting invariants remain unchanged.

## Interfaces And Outputs

Add a dated timing configuration containing:

- timing definition name;
- observation start and initial state;
- up-event dates and optional confirmation labels;
- down-event dates;
- execution timing mode.
- optional calendar-extension dates and their authoritative source when a terminal observation becomes effective after the available price window.

The portfolio runner accepts an optional regime schedule. Existing runs without a schedule remain byte-for-byte behaviorally unchanged.

Each timed run adds:

- `market_regime.csv`: date, event, prior state, resulting state, effective timestamp, and execution mode;
- `market_regime_exit` fill and trade reasons;
- `market_regime_off` entry rejection reasons;
- schedule path and SHA-256 in `run_manifest.json`.

Compact comparisons report baseline versus timed return, five-minute and conservative-low drawdown, closed/open trades, win rate, profit factor, capital utilization, turnover, regime exits, and days in `risk_on` state.

## Experiment Matrix

Use the frozen 2026-06-01 through 2026-07-17 scans and the verified data snapshots.

Run both canonical one-third and risk-controlled one-quarter position targets for:

1. AI/semiconductor;
2. CSI Innovative Drug 30;
3. CSI Battery Theme;
4. CNI Robot Industry proxy.

For each pool and target size, compare:

- no timing overlay baseline;
- `same_day_1455` timing overlay;
- `next_session_0935` timing control.

The two signal-definition labels are compared through their generated regime timelines. Since their effective states are currently identical, duplicate portfolio execution is unnecessary after timeline equality is proven.

## Testing

Unit and integration tests must cover:

- observation start remains `risk_off`;
- up event enables same-day 14:55 entry;
- down event blocks entry and liquidates all positions;
- repeated up/down events are idempotent;
- the 2026-06-22 confirmation does not reset positions;
- regime exit precedes ordinary exits;
- partial regime exit persists through volume and lower-limit constraints;
- next-session mode shifts effective timestamps without changing event dates;
- both supplied timing definitions generate equal state windows;
- existing no-regime tests and outputs remain unchanged;
- manifest hashes and `market_regime.csv` are complete and deterministic.

After focused tests, run the complete suite, real-data artifact reconciliation, `compileall`, and `git diff --check` before reporting results.

## Interpretation Rules

- Do not optimize the 4%/-3% thresholds on the same June-July sample.
- Do not compare event-level mean returns with account returns.
- Show the untimed baseline even if timing improves results.
- Treat a higher win rate without acceptable drawdown and sufficient trade count as inconclusive.
- Explicitly disclose that the 0AMV dates are manually supplied and that same-day execution assumes the signal is observable by 14:55.
