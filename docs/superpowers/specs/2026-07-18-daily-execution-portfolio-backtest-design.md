# Daily execution and portfolio backtest design

## Purpose

Upgrade the current B1 trend-runner from an independent-event study into an auditable daily portfolio backtest. The new mode must answer a different question from the existing reports: what account-level return and drawdown could have been achieved after realistic entry timing, A-share T+1 restrictions, transaction costs, gap fills, position limits, and overlapping signals?

The existing `close-entry-b1`, `staged-exit-b1`, and `trend-runner-b1` modes remain unchanged as research baselines. The new mode becomes the preferred source for investability claims.

## Confirmed decisions

- Intraday data is not a prerequisite for the first implementation.
- A B1 signal is confirmed after the D-day close and enters at the D+1 open.
- A position bought on D+1 cannot be sold until D+2.
- Signals, qfq prices, and the current `+10%/+20% + ATR + residual drawdown` exit parameters are frozen while execution realism is added.
- The first portfolio mode requires qfq CSV input and an explicit stock pool. It does not attempt an all-market portfolio run.
- Same-day high/low ambiguity keeps the approved conservative rule: stop loss before take profit before residual exit.
- Five-minute data will be a separate follow-up adapter used to test a 14:50 entry variant and intraday ordering sensitivity.

## Alternatives considered

### A. Daily-first portfolio engine (selected)

Use qfq daily OHLC for signals and valuation, raw OHLC/preclose for tradeability checks, and deterministic conservative fill rules. This immediately fixes the largest biases without waiting for a new data download.

### B. Wait for five-minute history

Build the portfolio engine only after downloading and parsing five-minute bars. This gives better tail-ordering and entry timing, but it delays transaction-cost, capital, overlap, and account-drawdown corrections that do not require intraday data.

### C. Keep event studies and add cost haircuts

Subtract a fixed cost from each event and continue averaging events. This is quick but cannot model cash, simultaneous positions, repeated signals, T+1, or an account equity curve, so it is not sufficient.

## Scope

In scope:

- Add a conservative daily execution model shared by entries and exits.
- Enter on D+1 open and enforce T+1 sell eligibility.
- Apply lot rounding, commission, minimum commission, sell stamp duty, and configurable slippage to every fill.
- Handle gap-through stop and take-profit prices.
- Detect conservative one-price limit locks using raw prices and raw preclose where the required fields are available.
- Run all stock-pool signals through one chronological cash and position ledger.
- Prevent stacking a second position in a code that is already held.
- Support maximum-position scenarios of 5, 10, and 20 without retuning B1 or exit thresholds.
- Produce daily NAV, account drawdown, holdings, orders, fills, rejected orders, and summary metrics.
- Compare only common eligible signal cohorts when contrasting exit variants or horizons.
- Write a reproducibility manifest for every run.

Out of scope:

- Five-minute or one-minute parsing.
- A 14:50 same-day entry claim.
- Dynamic historical AI/semiconductor membership.
- Historical ST status repair.
- Full-market portfolio runs.
- Changes to B1 signal conditions or optimization of exit parameters.
- GUI work or live trading integration.

## Architecture

### Market data view

Load the explicit stock pool from qfq CSV into one date-sorted table with a 180-business-day indicator warmup. Strategy calculations and total-return thresholds use `qfq_open`, `qfq_high`, `qfq_low`, and `qfq_close`. Entry lot sizing and tradeability checks use raw OHLC, raw preclose, volume, code, and date.

The ledger must not treat qfq prices as executable raw share prices. At entry, it calculates an integer raw-share quantity from the raw open and converts that position into adjusted economic units using the entry-day qfq scale. Subsequent qfq valuation of those units preserves total-return continuity across adjustment jumps. Every position crossing an `adjustment_jump` is marked for corporate-action audit, and the report discloses the count and return contribution of those trades. This is total-return accounting, not a claim that cash dividends and bonus shares were posted as separate ledger events.

The first implementation must fail clearly when qfq strategy prices are missing. Missing raw tradeability fields do not invent certainty: affected fills carry a `tradeability_quality` value and the run metadata reports the count.

### Signal layer

Continue using the existing `b1_first_trigger` definition. At the D close, create an entry intent for D+1. A signal for an already-held code is rejected with reason `position_already_open` and is retained in the audit output.

When entry demand exceeds available slots, rank candidates by the existing frozen `signal_strength`, descending, then by code ascending for deterministic ties. The report must disclose that ranking is a capacity rule, not independently validated alpha. Results are run for 5, 10, and 20 maximum positions to expose capacity sensitivity.

### Execution layer

Implement pure execution functions that accept an order intent, the current bar, the position state, and execution configuration, then return either a fill or a rejection with an explicit reason.

Entry rules:

1. A D-close signal may enter only at the D+1 open.
2. The order is rejected when the security has no D+1 bar, is known suspended, or is conservatively identified as locked at its upper limit.
3. The executable buy price is the D+1 raw open plus configured buy slippage. The corresponding qfq price and qfq scale are stored for total-return valuation.
4. Raw shares are rounded down to a board lot of 100 and must remain within available cash after fees. The ledger converts them into adjusted economic units after the fill.

Exit rules:

1. No exit is allowed on the entry date. Exit evaluation begins on the next trading day for that code.
2. Stop loss is evaluated first in qfq total-return space. If the open gaps through the stop, use the open; otherwise use the stop threshold. Convert the selected qfq fill to raw-price space with that day's qfq scale before applying sell slippage and transaction costs.
3. If stop loss does not trigger, evaluate take-profit levels in ascending order in qfq space. If the open gaps above a take-profit threshold, use the open; otherwise use the threshold. Convert the selected fill to raw-price space before costs.
4. A day that spans both stop and take-profit exits uses the conservative stop-first order.
5. Residual drawdown uses the highest completed close from prior days. The current day's close cannot define a peak before the current day's low is evaluated.
6. A gap through the residual stop fills at the open; an intraday cross fills at the threshold.
7. A known one-price lower-limit lock rejects the sell and leaves the position open for the next trading day.
8. A scheduled horizon exit uses the horizon-day close less sell slippage. The report labels this as a scheduled-close approximation.

The entry date is holding day 1. For a five-day horizon, a D-close signal enters on D+1 open and has a scheduled exit on the fifth trading bar after the signal. Because the entry-day position is not sellable, the new mode rejects horizons shorter than two trading days.

Partial exits are based on original shares, rounded down to board lots. The final exit always sells the exact remaining shares so fills cannot leave rounding dust.

### Portfolio layer

Maintain one chronological account ledger with:

- cash,
- open positions,
- sellable shares,
- pending D+1 entries,
- realized P&L,
- cumulative fees and taxes,
- end-of-day market value,
- NAV and drawdown.

Each scenario starts with configurable initial cash. New positions target `1 / max_positions` of start-of-day NAV. Existing positions are not rebalanced. Entry orders are sized from start-of-day cash and processed by deterministic rank. Proceeds from intraday exits become available for subsequent days, avoiding same-open cash reuse that daily bars cannot justify.

The canonical initial cash is CNY 1,000,000. All sell proceeds, including gap exits observed at the open, are conservatively unavailable to new entries until the next trading day.

The initial portfolio scenarios are:

- `max_positions=5`
- `max_positions=10`
- `max_positions=20`

No per-code pyramiding is allowed. The engine records every capacity, cash, tradeability, and duplicate-position rejection.

## Transaction costs

Use the existing configuration keys as the default source:

- `commission_rate`
- `minimum_commission`
- `sell_stamp_duty_rate`
- `lot_size`

Add explicit buy and sell slippage configuration in basis points. The canonical run uses 10 basis points in the adverse direction on each side and includes 0 and 20 basis-point sensitivity runs. Commission minimums apply per fill, including each staged partial sale. Net trade P&L and account NAV are calculated after all fees, taxes, and slippage. Transaction costs use raw executable notional. Qfq values are retained separately for signal thresholds and total-return reconciliation.

## Tradeability model

Price-limit checks use raw prices rather than qfq prices. For the 2026 first-phase run, infer the normal board limit by code family and compare raw open/high/low/close with raw preclose using tick-size tolerance. A sell or buy is blocked only for a conservative one-price locked board, not merely because the price touched a limit.

Historical ST status is unavailable, so the engine must not silently assume that all 5% ST limits are known. It records `historical_st_status_unavailable` and reports any tradeability decision made with incomplete status. A later point-in-time data project will replace this limitation.

## Benchmarks and research comparisons

The first report contains three views:

1. Strategy portfolio: B1 plus frozen trend-runner exits under realistic execution.
2. Fixed-pool benchmark: equal-weight available pool members at the analysis-start open, hold through the analysis-end close, and apply the same entry/exit costs. It is clearly labeled as a retrospective fixed-universe cohort.
3. Common-cohort event comparison: old close-entry, old trend-runner, and realistic execution measured only on signals that have sufficient data for every compared horizon.

Random same-date matched controls and an external semiconductor index are deferred until the portfolio engine is stable. The report must not call fixed-pool excess return `alpha`.

## Metrics

Portfolio summary:

- total net return,
- annualized return when the sample is at least 90 calendar days,
- maximum account drawdown,
- annualized volatility,
- Sharpe and Sortino ratios when enough daily observations exist,
- Calmar ratio when annualized return is reported,
- average and maximum gross exposure,
- turnover,
- total commission, tax, and slippage cost,
- positions crossing a qfq adjustment jump and their return contribution,
- maximum simultaneous positions,
- rejected-entry and rejected-exit counts.

Trade summary:

- trade count and win rate,
- mean and median net trade return,
- profit factor,
- average holding days,
- stop-loss, take-profit, residual-drawdown, and expiry rates,
- worst trade return and maximum adverse excursion.

Event-level adverse excursion remains available but is not labeled as portfolio drawdown.

## Outputs

The new mode writes a separate directory containing:

- `portfolio_daily.csv`
- `portfolio_positions.csv`
- `portfolio_orders.csv`
- `portfolio_fills.csv`
- `portfolio_trades.csv`
- `portfolio_rejections.csv`
- `portfolio_summary.csv`
- `common_cohort_comparison.csv`
- `fixed_pool_benchmark.csv`
- `run_manifest.json`
- `portfolio_report.md`

The run manifest records source path, source file hash, stock-pool hash, configuration hash, last source date, qfq adjustment label, gbbq path/hash when supplied by upstream metadata, Git commit, Python version, and all known field limitations.

## Invariants and error handling

Every run must enforce:

- cash never falls below a one-cent tolerance,
- entry raw shares are non-negative board-lot integers, while adjusted economic units are positive finite values,
- sold shares never exceed sellable shares,
- one code has at most one open position,
- fill dates never precede order dates,
- no sell fill occurs on the entry date,
- position market value plus cash reconciles to NAV,
- all partial fills sum to the original adjusted economic units at final close,
- every rejected order has a machine-readable reason.

The CLI fails before writing final summary files when reconciliation or chronology invariants fail. Partial diagnostic files may be retained in a run-specific temporary directory and must be labeled incomplete.

## Testing

Add focused tests for:

- D-close signal entering at D+1 open rather than D close.
- T+1 preventing an entry-day stop or take-profit sale.
- buy and sell lot rounding with minimum commission.
- stamp duty applying only to sells.
- slippage applying in the adverse direction.
- an open gap below stop filling at the open rather than the stop threshold.
- an open gap above take profit filling at the open.
- same-day stop/take-profit conflict using stop first.
- residual drawdown using only prior completed-close peaks.
- a one-price upper-limit entry rejection and lower-limit exit rejection.
- partial exits reconciling to original shares.
- duplicate signals not stacking positions.
- cash and maximum-position capacity rejections.
- deterministic signal ranking.
- daily NAV and maximum account drawdown calculation.
- common-cohort comparison using identical signals across horizons.
- manifest hashes and field limitations.
- CLI output completeness for all three maximum-position scenarios.

Run the full existing suite after the focused tests.

## Follow-up projects

After this daily engine is verified:

1. Add a Tongdaxin `.lc5` adapter and aggregate five-minute bars into ten-minute bars with session-aware boundaries.
2. Compare D+1 open entry with a D-day 14:50 signal/entry model using only information available by 14:50.
3. Add point-in-time ST, suspension, market-cap, and dynamic stock-pool data.
4. Run walk-forward and market-regime validation without changing frozen parameters on the test windows.
