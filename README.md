# A 股 B1 信号事件研究

本项目验证 B1 技术信号，并提供事件研究、日线分批退出和五分钟级连续组合回测。所有结果均为历史研究，不是自动交易系统或投资建议。

## 工作目录

当前盘中组合开发 worktree 位于：

`C:\Users\yuhang\Desktop\A_Share_Backtesting\.worktrees\b1-event-study`

请先用 `git worktree list` 核对分支和路径，再在对应 worktree 运行测试、CLI 和 Git 命令。

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

事件研究开发计划见 [B1 Signal Event Study Implementation Plan](docs/superpowers/plans/2026-07-13-b1-event-study.md)。最新盘中组合结果和限制记录在 `DEVELOPMENT_STATUS.md`。

## 通达信日线技术条件版

当只有通达信 `.day` 日线、没有逐日市值和 ST 状态时，先运行技术条件版：

```powershell
& $py -m a_share_backtesting.tdx_import --source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --output data\daily_bars_technical.csv --metadata data\daily_bars_technical.metadata.json
& $py -m a_share_backtesting.event_study_run --data data\daily_bars_technical.csv --config config\event_study_technical_only.json --metadata data\daily_bars_technical.metadata.json --output outputs\event_study_technical_2026h1
```

## 五分钟级连续组合回测

The intraday mode scans completed five-minute bars at 14:40, 14:45, and
14:50, enters at the 14:55 close, and runs one chronological account with
T+1 exits and a maximum of three positions.

```powershell
$py = 'C:\Users\yuhang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m a_share_backtesting.intraday_portfolio_run `
  --minute-root D:\apps\tdx\vipdoc `
  --qfq-source outputs\qfq_20260718\qfq_bars.csv `
  --stock-pool config\ai_semiconductor_stock_pool_20260715.csv `
  --config config\intraday_portfolio_20260718.json `
  --output outputs\intraday_b1_20260601_20260717_ai_semiconductor `
  --analysis-start 2026-06-01 `
  --analysis-end 2026-07-17
```

`config/intraday_portfolio_20260718.json` 是每只股票目标净值 1/3 的原始确认版；`config/intraday_portfolio_risk_controlled_20260718.json` 保持最多三只股票，但把单票目标降为净值 1/4。后者只降低资金风险，不代表信号胜率已经改善。

参数敏感性复跑可通过 `--scan-source <prior-run>/signal_scans.csv` 复用冻结的逐时点信号。该模式仍会根据新账本的实际持仓重新执行首次触发、持仓去重、候选排序和容量约束，不能用 `candidates.csv` 代替。

`max_positions` 必须在 1-3 之间，`participation_rate` 不得超过 10%；两者属于确认策略的硬约束。完整 `.lc5` 交易日必须匹配精确的 48 个五分钟时间戳并包含 15:00，坏文件会写入 `data_audit.csv` 后跳过，不会中止其他代码。

输入日线必须是带 `qfq_scale` 的前复权快照，分析起点前至少保留 180 个交易日。当前结果仍缺少逐日历史 ST、市值和盘口队列，股票池快照还存在成分回看偏差。
