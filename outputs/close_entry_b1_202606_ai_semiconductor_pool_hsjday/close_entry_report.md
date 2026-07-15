# Close-Entry B1 Backtest

- Analysis window: 2026-06-01 to 2026-06-30
- Entry: signal-day close.
- Exit: future close by holding horizon.
- Drawdown: lowest intraday low during the holding window, capped at 0 when price never falls below entry.
- Scope: technical-only; historical market-cap, ST and suspension filters are not validated.
- Field limitations: historical_market_cap_unavailable, historical_st_status_unavailable, suspension_status_unavailable

## Summary

| horizon | event_count | mean_net_return | median_net_return | win_rate | mean_intraday_drawdown | median_intraday_drawdown | worst_intraday_drawdown | mean_close_drawdown | worst_close_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 70 | 0.011320637269165981 | 0.00940517765925497 | 0.6142857142857143 | -0.03166516127336665 | -0.024855644253069353 | -0.09377817853922465 | -0.01462595987237648 | -0.07484220018034271 |
| 2 | 70 | 0.014203367637165372 | 0.014915933847031715 | 0.5285714285714286 | -0.046136022071504024 | -0.03314917504557274 | -0.15741195741195746 | -0.028084222712468174 | -0.1372207716855237 |
| 3 | 69 | 0.028319958036079278 | 0.04608425219112244 | 0.5797101449275363 | -0.058691873084935536 | -0.05022831050228305 | -0.15741195741195746 | -0.03931365362281087 | -0.15651070003627132 |
| 4 | 68 | 0.04579469973769557 | 0.027145232311326484 | 0.5441176470588235 | -0.06237919001085876 | -0.05287355524699627 | -0.1767935121646912 | -0.041297108905331024 | -0.15651070003627132 |
| 5 | 67 | 0.04423270002022943 | 0.027692307692307683 | 0.6417910447761194 | -0.06901075093774939 | -0.0544605809128631 | -0.3090022675736961 | -0.04937536435450506 | -0.2857142857142857 |
