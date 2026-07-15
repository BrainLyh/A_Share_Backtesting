# Staged-Exit B1 Backtest

- Analysis window: 2026-06-01 to 2026-07-15
- Entry: signal-day close.
- Take profit: +5% sells one third, +10% sells one third, +15% sells all remaining.
- Stop loss: -5% sells all remaining.
- Same-day conflict policy: stop-loss before take-profit.
- Expiry: remaining position exits at the horizon-day close.
- Scope: technical-only; historical market-cap, ST and suspension filters are not validated.
- Field limitations: historical_market_cap_unavailable, historical_st_status_unavailable, suspension_status_unavailable

## Summary

| horizon | event_count | mean_net_return | median_net_return | win_rate | mean_intraday_drawdown | worst_intraday_drawdown | mean_position_weighted_drawdown | worst_position_weighted_drawdown | mean_take_profit_fill_count | stop_loss_rate | expiry_exit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 119 | -0.00010709102023549592 | 0.0009232835319792354 | 0.5126050420168067 | -0.041994145391777024 | -0.1480043149946062 | -0.041994145391777024 | -0.1480043149946062 | 0.44537815126050423 | 0.36134453781512604 | 0.6050420168067226 |
| 2 | 117 | -0.002486065844841575 | -0.05 | 0.39316239316239315 | -0.0537309409503397 | -0.19098440182103138 | -0.051689630515605094 | -0.1480043149946062 | 0.7435897435897436 | 0.5555555555555556 | 0.3418803418803419 |
| 3 | 117 | 0.0002917100362005461 | -0.05 | 0.358974358974359 | -0.05769003426538919 | -0.19098440182103138 | -0.05399636550098276 | -0.1480043149946062 | 0.8974358974358975 | 0.6324786324786325 | 0.21367521367521367 |
| 4 | 116 | 0.0007484923909398879 | -0.05 | 0.35344827586206895 | -0.05898975606513329 | -0.19098440182103138 | -0.05424512945557738 | -0.1480043149946062 | 1.0 | 0.6551724137931034 | 0.12931034482758622 |
| 5 | 84 | 0.014568287755066966 | -0.016666666666666673 | 0.4642857142857143 | -0.04881391041762441 | -0.11771192557542698 | -0.044317384510771544 | -0.09841269841269851 | 1.2619047619047619 | 0.5714285714285714 | 0.11904761904761904 |
