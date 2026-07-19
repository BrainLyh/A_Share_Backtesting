# Active Market Cap Timing Comparison

## Scope and metric contract

This compact comparison recomputes return, 5-minute/low/daily drawdown, closed/open trade counts, win rate, profit factor, capital utilization, turnover, and regime exits directly from NAV, fills, and trades. Source summary values were accepted only within 1e-10 tolerance.
Baseline risk-on session counts mean all analysis sessions were entry-eligible; timed counts use the supplied regime state at each 14:55 entry cycle.

## AI semiconductor: same-day versus next-session

- canonical: same-day 8.66% versus next-session 2.33%, a same-day advantage of 6.32 percentage points; closed-trade denominators 6 and 5.
- risk025: same-day 6.55% versus next-session 1.95%, a same-day advantage of 4.61 percentage points; closed-trade denominators 6 and 5.
The same-day 14:55 result has potential look-ahead because it assumes the full daily signal is observable and actionable before the close. The next-session control is the more conservative timing interpretation.

## Cross-matrix consistency

Among 12 exposed timed rows, 8 improve return versus their position-matched baseline; 2 of 3 exposed pools improve in every timed row.
4 zero-trade rows are reported separately and are not counted as return improvements.
Return direction across position sizes is consistent in 6 of 6 exposed pool/timing pairs: 4 positive, 2 negative, and 0 flat; 0 pairs are mixed.
Drawdown improvement among 12 exposed timed rows: 12 improve 5-minute drawdown, 12 improve conservative-low drawdown, and 12 improve daily drawdown.

## Battery: computed return, drawdown, and exposure

- canonical baseline: return -12.94%; 5m/low/daily drawdown -16.01% / -16.17% / -15.76%; closed/open 12/0; win rate 33.33% (denominator 12); capital utilization 32.48%; turnover 7.18x.
- canonical same-day: return -0.44%; 5m/low/daily drawdown -5.24% / -5.50% / -1.89%; closed/open 3/0; win rate 66.67% (denominator 3); capital utilization 6.86%; turnover 1.98x.
- canonical next-session: return -0.02%; 5m/low/daily drawdown -5.24% / -5.50% / -1.80%; closed/open 3/0; win rate 66.67% (denominator 3); capital utilization 6.88%; turnover 1.98x.
- risk025 baseline: return -9.90%; 5m/low/daily drawdown -12.17% / -12.29% / -11.97%; closed/open 12/0; win rate 33.33% (denominator 12); capital utilization 24.84%; turnover 5.50x.
- risk025 same-day: return -0.37%; 5m/low/daily drawdown -3.99% / -4.19% / -1.46%; closed/open 3/0; win rate 66.67% (denominator 3); capital utilization 5.16%; turnover 1.49x.
- risk025 next-session: return -0.05%; 5m/low/daily drawdown -3.99% / -4.19% / -1.39%; closed/open 3/0; win rate 66.67% (denominator 3); capital utilization 5.18%; turnover 1.50x.
All 4 battery timed rows improve return versus baseline.
4 of 4 battery timed rows improve all three drawdown measures versus baseline.
All 4 battery timed rows have lower capital utilization and fewer total trades than their position-matched baselines; reduced exposure is therefore material in this sample.

## Humanoid robot proxy: computed return versus drawdown

- canonical: baseline return 9.37%; same-day/next-session 2.74% / 0.16%. Baseline 5m drawdown -12.25%; timed drawdowns -4.60% / -4.59%.
- risk025: baseline return 7.81%; same-day/next-session 2.03% / 0.12%. Baseline 5m drawdown -9.48%; timed drawdowns -3.37% / -3.42%.
All 4 robot timed rows return less than their position-matched baselines.
In this sample, all 4 robot timed rows pair missed upside with improved five-minute drawdown. Whether drawdown control compensates for missed upside is a sample-specific trade-off, not a universal conclusion.

## Innovative drug: zero timed exposure

All 4 innovative-drug timed rows have zero closed and open trades. Their 0% return and 0% drawdown mean no exposure, not an improvement in selection.

## Sample size

12 timed rows have only 1-6 closed trades. Win rates and profit factors are reported with their closed-trade denominators and are too thin for stable inference.
- ai_semiconductor / canonical / same_day_1455: 6 closed, 0 open.
- ai_semiconductor / canonical / next_session_0935: 5 closed, 0 open.
- ai_semiconductor / risk025 / same_day_1455: 6 closed, 0 open.
- ai_semiconductor / risk025 / next_session_0935: 5 closed, 0 open.
- battery / canonical / same_day_1455: 3 closed, 0 open.
- battery / canonical / next_session_0935: 3 closed, 0 open.
- battery / risk025 / same_day_1455: 3 closed, 0 open.
- battery / risk025 / next_session_0935: 3 closed, 0 open.
- humanoid_robot_proxy / canonical / same_day_1455: 3 closed, 0 open.
- humanoid_robot_proxy / canonical / next_session_0935: 2 closed, 0 open.
- humanoid_robot_proxy / risk025 / same_day_1455: 3 closed, 0 open.
- humanoid_robot_proxy / risk025 / next_session_0935: 2 closed, 0 open.

## Regime audit and limitations

Both supplied definitions have equal state windows in each mode: same_day_1455=true, next_session_0935=true. The audit retains 34 event rows across 2 definitions.
The audit contains both expected July 20 terminal next-session effective rows (2 of 2), one for each supplied definition.
The regime dates were manually supplied and the exercise is post-hoc. The 4% rise and -3% fall thresholds were not optimized here; no threshold optimization or B1 parameter optimization was performed.
Results are exploratory and do not establish causality. Lower drawdown can arise from lower exposure, so it must not be attributed automatically to better stock selection.
