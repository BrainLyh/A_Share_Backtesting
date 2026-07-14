# 开发进度报告

> 2026-07-14 续开发记录（优先阅读本节）

## 今日完成

- 已核验通达信原始数据：目标沪深主板 3,439 个 `.day` 文件，约 13,976,804 条记录、447,257,728 字节；数据截至 2026-07-13。
- 已确认仅有日线，缺少逐日市值与 ST 状态；研究口径冻结为“技术条件版”：`min_market_cap=0`、未复权价格、不宣称验证市值/ST 过滤。
- 已新增并推送 TDX 二进制解析、主板筛选、技术条件版配置保护、报告限制披露和导入器：`4f3d6cf`、`902630f`、`da1c216`。
- 原全量 CSV 导入因一次性拼接全市场数据未成功产出可用 CSV，已转为流式方案；流式设计与计划已推送：`c6b2a0c`、`c370ffa`。
- 流式任务1完成并推送：逐股读取、预热、信号和事件测量，不保留全市场日线：`2645b15`、`940ac13`。
- 流式任务2核心完成并推送：第二遍逐股生成同日非信号候选事件、固定随机种子抽样：`32fb50e`。
- 已验证：在提交 `32fb50e` 时，完整单元测试为 30/30 通过。
- 本轮续作已补充测试：空窗口股票帧跳过、流式 CLI 产物写出、BOM JSON 配置读取、进度日志与阶段耗时元数据；完整单元测试为 33/33 通过。
- 流式 CLI 初稿已补齐七类研究产物：`signal_audit.csv`、`events.csv`、`date_portfolios.csv`、`summary.csv`、`control_distribution.csv`、`control_summary.json`、`report.md`，并额外写出 `streaming_metadata.json` 和 `control_candidates.csv`。
- 已用 6 个真实通达信 `.day` 样本文件试跑：原始 1000 次控制迭代配置 15.667 秒完成，输出 12 个 `variant + horizon` 组合各 1000 行控制分布；样本元数据为 3 个有效窗口代码、4,713 行信号审计、737 个候选对照事件。
- 已诊断此前“长时间无输出”的主要可复现原因之一：随机对照抽样在迭代内反复筛选 DataFrame；现已改为预先按 `variant + horizon + signal_date` 建候选池索引。
- 已新增流式 CLI 进度汇报：参数 `--progress-interval-seconds` 默认 60 秒，控制台输出 `progress {...}`，同时写入 `progress.jsonl`；`streaming_metadata.json` 记录 `total_elapsed_seconds` 与 `stage_durations_seconds`。

## 当前未提交状态与阻塞点

- 今日源码、测试与开发记录准备提交为一个进度提交；提交后本地不应保留未提交代码变更。
- `data/daily_bars_technical.metadata.json` 是本地研究数据；保持忽略，不提交。
- 本轮发现并停止了一个残留全量流式 CLI 进程和一个样本长跑进程；当前不应再依赖此前 `outputs/event_study_technical_2026h1` 的任何半成品。
- 真实全量 3,439 个目标主板文件尚未重新跑完；不能将真实回测视为已完成，也不能提交或推送为最终结果。

## 下一步执行顺序

1. 运行 `git status --short`，确认仅保留上述未提交源码、测试、文档和本地研究数据，不覆盖任何改动。
2. 再次确认没有残留 `streaming_event_study_run` 进程。
3. 运行全量真实数据 CLI：`--source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --config config\event_study_technical_only.json --output outputs\event_study_technical_2026h1 --progress-interval-seconds 60`。
4. 记录退出码、耗时、产物存在性、事件数、12 个组合的控制分布行数、`streaming_metadata.json` 和进程/内存证据。
5. 全量产物完整且审计通过后，再更新本文件、提交源码和文档、推送 `codex/b1-event-study`。

最后更新：2026-07-14（Asia/Shanghai）

## 当前目标

实现 B 层 A 股 B1 信号事件研究：对 `legacy`、`bbi`、`b1` 三组日线收盘信号，分别计算下一交易日开盘入场后持有 2、5、10、20 个完整交易日的结果，并与同日随机对照组比较。

## 工作状态

- 开发分支：`codex/b1-event-study`
- 当前工作树：随机器而变；以分支 `codex/b1-event-study` 和本文件的提交号为准。
- 基线提交：`06c3899`（`chore: establish B1 event study baseline`）
- 实施计划：[docs/superpowers/plans/2026-07-13-b1-event-study.md](docs/superpowers/plans/2026-07-13-b1-event-study.md)
- 已完成：清理此前连续组合回测路径；保留指标、信号基础和最小测试。
- 已验证：`python -m unittest discover -s tests -v`，2 项通过。
- 已完成：Task 1（数据契约与冻结实验配置），提交 `29f9e8d`。
- 验证：`python -m unittest discover -s tests -v`，7 项通过。
- 已完成：Task 2（`legacy`、`bbi`、`b1` 信号变体与首次触发标记），提交 `2f3332f`。
- 验证：`python -m unittest discover -s tests -v`，10 项通过。
- 已完成：Task 3（事件入场、持有期、未成交状态、收益与回撤测量），提交 `ab3fcb3`。
- 验证：`python -m unittest discover -s tests -v`，14 项通过。
- 已完成：Task 4（按信号日汇总与确定性随机对照组），提交 `50457f9`、`23d76c9`。
- 验证：`python -m unittest discover -s tests -v`，17 项通过。
- 已完成：Task 5（事件研究命令行入口、产物写入和研究报告），提交 `4a571ec`。
- 验证：`python -m unittest discover -s tests -v`，18 项通过。
- 下一任务：Task 6（使用真实历史数据运行冻结实验并审计研究产物）。

## 已确定的研究口径

- 技术基线不要求 `in_core_pool`；有历史主线池后再作为可选过滤器比较增量价值。
- 信号在 `D` 收盘后生成；下一交易日开盘入场。
- 持有期 `H` 使用完整交易日：信号行 `i`，入场行 `i+1` 开盘，退出行 `i+1+H` 开盘。
- 同一股票在同一 `variant + horizon` 的前一事件退出前，不重复计入新事件。
- 停牌、涨跌停无法成交时记录未成交状态，不虚构收益。

## 下一步

1. 准备带 120 个交易日预热期的本地历史日线数据和冻结配置。
2. 运行 CLI，检查输出文件、信号/入场/退出时序及未成交事件计数。
3. 记录数据来源、覆盖日期、基准和复权口径；不在结果出现后修改参数。

## 跨机器续作

1. 切换到 `codex/b1-event-study` 分支，并同步该分支的最新提交。
2. 先阅读本文件和实施计划；不要从 `main` 直接继续开发。
3. 设置运行环境后执行：

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest discover -s tests -v
```

4. 从“下一步”的第一条继续；完成一个任务后，更新本文件的已完成项、验证结果、提交号和下一步。
