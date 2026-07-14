# A 股 B1 信号事件研究

本项目当前只验证技术信号的历史统计有效性，不做连续持仓或自动交易。

## 工作目录

本项目的真实开发 worktree 位于：

`C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`

请在该目录运行测试、CLI 和 Git 命令。`C:\Users\playd\Desktop\A_Share_Backtesting` 根目录保留 `main` checkout、`.worktrees/`、`data/` 和 `outputs/`，不作为本分支的直接开发目录。

第一阶段比较三组日线收盘信号：

- `legacy`：原通达信缩量回撤公式；
- `bbi`：原公式加 BBI 多头向上过滤；
- `b1`：J 值低位后右侧转强确认。

每个信号均按下一交易日开盘入场，分别测量 2、5、10、20 个完整交易日后的收益、最大不利波动、收盘最大回撤，并与同日随机对照组比较。

## 运行事件研究

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m a_share_backtesting.event_study_run `
  --data data\daily_bars.csv `
  --config config\event_study_default.json `
  --output outputs\event_study_2026h1
```

输入应在首个分析日前保留至少 120 个交易日的预热数据，并覆盖最后一个信号日之后最长持有期及退出日。当前基线不要求历史主线池；只有提供逐日、无未来信息的 `in_core_pool` 后，才可声称验证了完整六步法。

开发计划见 [B1 Signal Event Study Implementation Plan](docs/superpowers/plans/2026-07-13-b1-event-study.md)。尚未接入真实历史数据，也尚未生成策略表现结论。

## 通达信日线技术条件版

当只有通达信 `.day` 日线、没有逐日市值和 ST 状态时，先运行技术条件版：

```powershell
& $py -m a_share_backtesting.tdx_import --source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --output data\daily_bars_technical.csv --metadata data\daily_bars_technical.metadata.json
& $py -m a_share_backtesting.event_study_run --data data\daily_bars_technical.csv --config config\event_study_technical_only.json --metadata data\daily_bars_technical.metadata.json --output outputs\event_study_technical_2026h1
```

该版本仅保留沪深主板代码及技术信号，价格使用未复权日线；需在分析起点前保留至少 120 个交易日预热数据。它不验证历史市值大于 100 亿或非 ST 过滤，亦不推断停牌状态。
