# 开发进度报告
> 2026-07-16 合并 staged-exit 分批止盈分支（优先阅读本节）

## 本次完成

- 已将远程实验分支 `origin/codex/staged-exit-b1` 快进合并到主开发线 `codex/b1-event-study`；该分支基于 `1ed8fa9`，新增提交为 `47a9948`、`5b97551`、`07a5623`。
- 新增 `--mode staged-exit-b1` 分批退出回测模式：B1 当日收盘买入；触发 5%、10%、15% 浮盈时分别卖出三分之一、三分之一、剩余仓位；触发 -5% 止损时退出剩余仓位；同日止损/止盈冲突按先止损处理；到期未退出部分按 horizon 日收盘价退出。
- 新增设计文档 `docs/superpowers/specs/2026-07-15-staged-exit-b1-design.md` 和计划文档 `docs/superpowers/plans/2026-07-15-staged-exit-b1.md`。
- 已把 staged-exit 与 close-entry 的对比输出提交到 `outputs/` 下，便于跨机器复核；这与上一轮“本地 outputs 未提交”的状态不同。

## 分批止盈结果摘要

### 2026-06-01 至 2026-06-30，AI/半导体股票池

| 持仓天数 | 事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中最大回撤 | 最差盘中最大回撤 | 平均分仓回撤 | 最差分仓回撤 | 平均止盈次数 | 止损率 | 到期退出率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 70 | 0.9377% | 0.9405% | 60.00% | -3.1665% | -9.3778% | -3.1665% | -9.3778% | 0.43 | 22.86% | 74.29% |
| 2 | 70 | 0.8627% | 0.0902% | 51.43% | -4.0218% | -9.3778% | -3.9863% | -9.3778% | 0.83 | 41.43% | 48.57% |
| 3 | 69 | 1.4954% | -1.6667% | 47.83% | -4.4847% | -11.7387% | -4.2480% | -9.3778% | 1.10 | 50.72% | 30.43% |
| 4 | 68 | 1.6073% | -1.6667% | 48.53% | -4.6372% | -11.7387% | -4.2677% | -9.3778% | 1.26 | 52.94% | 17.65% |
| 5 | 67 | 1.8610% | -1.6667% | 49.25% | -4.6637% | -11.7387% | -4.2507% | -9.3778% | 1.33 | 53.73% | 13.43% |

### 2026-06-01 至 2026-07-15，AI/半导体股票池

| 持仓天数 | 事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中最大回撤 | 最差盘中最大回撤 | 平均分仓回撤 | 最差分仓回撤 | 平均止盈次数 | 止损率 | 到期退出率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 119 | -0.0107% | 0.0923% | 51.26% | -4.1994% | -14.8004% | -4.1994% | -14.8004% | 0.45 | 36.13% | 60.50% |
| 2 | 117 | -0.2486% | -5.0000% | 39.32% | -5.3731% | -19.0984% | -5.1690% | -14.8004% | 0.74 | 55.56% | 34.19% |
| 3 | 117 | 0.0292% | -5.0000% | 35.90% | -5.7690% | -19.0984% | -5.3996% | -14.8004% | 0.90 | 63.25% | 21.37% |
| 4 | 116 | 0.0748% | -5.0000% | 35.34% | -5.8990% | -19.0984% | -5.4245% | -14.8004% | 1.00 | 65.52% | 12.93% |
| 5 | 84 | 1.4568% | -1.6667% | 46.43% | -4.8814% | -11.7712% | -4.4317% | -9.8413% | 1.26 | 57.14% | 11.90% |

## 解读边界

- staged-exit 的收益未必高于 close-entry，尤其 2026 年 6 月 close-entry 5 日平均收益为 4.4233%，staged-exit 5 日平均收益为 1.8610%；但 staged-exit 明显降低了 5 日平均盘中最大回撤（-6.9011% 降至 -4.6637%）和最差盘中回撤（-30.9002% 降至 -11.7387%）。
- 这更符合实盘风控逻辑：它牺牲一部分右侧利润，换取更可控的尾部回撤，因此后续比较应同时看收益、止损率、到期退出率和回撤，而不是只看平均收益。
- 当前仍是技术条件版：历史市值、真实 ST、真实停牌状态仍未验证，价格仍基于通达信日线。

## 验证

- 合并后已运行完整单元测试：`python -m unittest discover -s tests -v`，47/47 通过。
- 本节对应的合并和进度记录推送后，远程 `origin/codex/b1-event-study` 应包含 staged-exit 模式与结果产物。

> 2026-07-15 AI/半导体股票池回测（优先阅读本节）

## 本次完成

- 已解析用户整理的股票池文件 `C:\Users\playd\Desktop\AI-Semiconductor-Stock-Universe-20260715.md`，提取并去重得到 171 个 6 位 A 股代码，保存为 `config/ai_semiconductor_stock_pool_20260715.csv`。
- 流式 CLI 新增 `--stock-pool` 参数；传入股票池后，TDX 文件遍历按股票池代码精确过滤，不再只限原先沪深主板前缀。
- 信号层新增股票池 universe：默认仍按原主板范围过滤；传入 `stock_pool_codes` 时，`688/300/301/835438` 等非主板代码可作为候选参与 B1 计算。
- 修复通达信目录中同一 6 位代码可能同时存在 `sh/lday` 与 `sz/lday` 的错前缀重复文件问题；股票池模式现在按代码段校验交易所前缀，避免双计数。
- 已补充回归测试：股票池包含非主板代码、股票池 CLI 输出、股票池 universe eligibility、错市场前缀重复路径过滤。

## 2026 年 6 月股票池 close-entry B1 回测

- 命令模式：`--mode close-entry-b1 --analysis-start 2026-06-01 --analysis-end 2026-06-30 --horizons 1 2 3 4 5 --stock-pool config/ai_semiconductor_stock_pool_20260715.csv`。
- 输出目录：`outputs/b1_close_entry_202606_ai_semiconductor_pool`。
- 元数据：`stock_pool_count=171`，`processed_code_count=171`，`selected_signal_count=70`，`event_count=350`；买入价仍为 B1 当日收盘价，退出价为未来第 N 个交易日收盘价，回撤使用持仓期盘中最低价。
- 汇总结果：持仓 1/2/3/4/5 日平均收益分别为 1.1321%、1.4203%、2.8320%、4.5795%、4.4233%；胜率分别为 61.43%、52.86%、57.97%、54.41%、64.18%。
- 平均盘中最大回撤：持仓 1/2/3/4/5 日分别为 -3.1665%、-4.6136%、-5.8692%、-6.2379%、-6.9011%；最差盘中最大回撤分别为 -9.3778%、-15.7412%、-15.7412%、-17.6794%、-30.9002%。

### 最新收益与回撤明细

| 持仓天数 | 成交事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中最大回撤 | 最差盘中最大回撤 | 平均收盘回撤 | 最差收盘回撤 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 70 | 1.1321% | 0.9405% | 61.43% | -3.1665% | -9.3778% | -1.4626% | -7.4842% |
| 2 | 70 | 1.4203% | 1.4916% | 52.86% | -4.6136% | -15.7412% | -2.8084% | -13.7221% |
| 3 | 69 | 2.8320% | 4.6084% | 57.97% | -5.8692% | -15.7412% | -3.9314% | -15.6511% |
| 4 | 68 | 4.5795% | 2.7145% | 54.41% | -6.2379% | -17.6794% | -4.1297% | -15.6511% |
| 5 | 67 | 4.4233% | 2.7692% | 64.18% | -6.9011% | -30.9002% | -4.9375% | -28.5714% |

## 同步与披露状态

- 代码、测试和股票池配置对应功能提交为 `12b372b feat: support stock-pool b1 backtests`，并已推送到 `origin/codex/b1-event-study`；本次收益/回撤明细属于后续文档补充提交。
- `outputs/b1_close_entry_202606_ai_semiconductor_pool` 是本地复测产物目录，未作为 Git 跟踪文件提交；人工复核时优先查看本地 `close_entry_summary.csv` 和 `close_entry_selected_signals.csv`。
- 本轮暂未发现其他未同步到进度文档的信息：工作目录、股票池来源、CLI 参数、去重/市场前缀修复、测试结果、回测元数据、收益/回撤和下一步复核事项均已记录在本节。

## 验证

- 已运行完整单元测试：`python -m unittest discover -s tests -v`，42/42 通过。
- 已重新运行股票池回测并确认 `processed_code_count` 与 `stock_pool_count` 均为 171，未再出现重复市场前缀导致的额外处理代码窗口。

## 下一步

1. 人工抽查 `outputs/b1_close_entry_202606_ai_semiconductor_pool/close_entry_selected_signals.csv` 中的 70 个 B1 信号，优先检查 6 月 3 日、6 月 4 日、6 月 15 日信号密集日期。
2. 基于股票池结果新增行业/主题池对比：AI 半导体池 vs 全市场 6 月结果，确认收益改善来自行业趋势过滤，而不是样本期偶然。
3. 下一轮策略改进建议增加“行业/主题池参数”作为显式输入，而不是把行业判断混入 KDJ/BBI 技术信号本身。


> 2026-07-15 B1 规则与收盘买入回测（优先阅读本节）

## B1 信号口径修正

- 人工核验 2026-06-30 样本后，已将 B1 的 KDJ 条件修正为：T-1 日 J < 15 且 T 日 J > T-1 日 J，避免把已经远离低位后的阶段高点误判为 B1。
- B1 不再要求 BBI 本身已较前一日上升；B1 只要求价格站上 BBI，`bbi` 对照变体仍保留 BBI 上升过滤。
- 已补充针对 immediate prior low-J 与 BBI 斜率差异的回归测试。

## B1 收盘买入月度回测 CLI

- 已为流式 CLI 增加 `--mode close-entry-b1`，支持用 `--analysis-start`、`--analysis-end` 和 `--horizons` 覆盖配置文件，在指定日期段内筛选 B1，按信号日收盘价买入、未来第 N 个交易日收盘价退出。
- 输出文件包括 `close_entry_events.csv`、`close_entry_summary.csv`、`close_entry_selected_signals.csv`、`close_entry_metadata.json`、`close_entry_report.md`。
- 已运行 2026-06-01 至 2026-06-30 月度回测，输出目录为 `outputs/b1_close_entry_202606`；处理有效代码窗口 3,165 个，B1 信号 237 个，事件记录 1,185 条。
- 月度结果：1日平均收益 0.4441%、2日 0.3052%、3日 0.4412%、4日 0.4209%、5日 -0.2486%；对应平均盘中最大回撤分别为 -3.2252%、-4.5651%、-5.6858%、-6.3968%、-7.4936%。
> 2026-07-15 全量运行审计（优先阅读本节）

## 全量 CLI 结果

- 全量流式 CLI 已在真实开发 worktree `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study` 跑完，输出目录为 `outputs/event_study_technical_2026h1`。
- 产物齐全：`signal_audit.csv`、`events.csv`、`date_portfolios.csv`、`summary.csv`、`control_distribution.csv`、`control_summary.json`、`report.md`、`streaming_metadata.json`、`progress.jsonl`、`control_candidates.csv`。
- `progress.jsonl` 最后一条为 `overall_percent=100.0`；`streaming_metadata.json` 记录总耗时 `6899.734` 秒（约 1 小时 55 分）。
- 数据处理计数：目标文件 3,439 个，有效窗口代码 3,339 个，信号审计行 4,842,212，事件 730,844，已成交事件 728,754，候选对照事件 7,411,192。
- `summary.csv` 有 12 行，覆盖 `legacy`、`bbi`、`b1` 与 2、5、10、20 日全部组合；`control_distribution.csv` 有 12,000 行，每个组合 1,000 次随机对照，且没有 NaN。
- 事件状态审计正常：`insufficient_history` 与 `unfilled_entry` 的收益为空，未虚构收益。

## 结果初读

- 技术条件版结果显示：`b1` 四个持有期平均净收益均为负，且相对同日随机对照偏弱；当前不能把 B1 作为有效增强信号。
- `bbi` 的 10、20 日平均净收益略正，但优势不稳定；`legacy` 的 20 日相对随机对照较强，值得后续按年份和市场阶段拆分复核。
- 本轮结论仍限于“技术条件版”：未验证历史市值、ST 与真实停牌状态过滤，价格为未复权通达信日线。

## 本轮代码/报告披露修正

- 已补充流式 CLI 报告与 `streaming_metadata.json` 的字段限制披露：`historical_market_cap_unavailable`、`historical_st_status_unavailable`、`suspension_status_unavailable`。
- 已补充回归测试，要求流式 CLI 的 metadata 和 report 同时披露 `suspension_status_unavailable`。
- 已验证：`python -m unittest discover -s tests -v`，33/33 通过。

## 下一步

1. 提交并推送本轮披露修正与进度记录。
2. 做正式结果解读文档，优先按年份、市场阶段、信号触发条件拆分解释 `legacy`、`bbi`、`b1` 的差异。
3. 如需进一步提高结论可信度，补充可获取的逐日 ST、停牌、市值或历史指数成分数据后，再跑非技术条件版复核。

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
- 已新增流式 CLI 进度汇报：参数 `--progress-interval-seconds` 默认 60 秒，控制台输出 `progress {...}`，同时写入 `progress.jsonl`；`streaming_metadata.json` 记录 `total_elapsed_seconds` 与 `stage_durations_seconds`。`df4decc` 已同步到真实开发 worktree `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`。

## 当前未提交状态与阻塞点

- 当前代码变更已提交为 `df4decc`，并同步到真实开发 worktree；本次仅补充目录说明与进度记录后提交、推送。
- `data/daily_bars_technical.metadata.json` 是本地研究数据；保持忽略，不提交。
- 本轮发现并停止了一个残留全量流式 CLI 进程和一个样本长跑进程；当前不应再依赖此前 `outputs/event_study_technical_2026h1` 的任何半成品。
- 真实全量 3,439 个目标主板文件尚未重新跑完；不能将真实回测视为已完成，也不能提交或推送为最终结果。

## 下一步执行顺序

1. 在真实开发 worktree `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study` 运行 `git status --short`，确认工作区 clean。
2. 再次确认没有残留 `streaming_event_study_run` 进程。
3. 在真实开发 worktree 运行全量真实数据 CLI：`--source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --config config\event_study_technical_only.json --output outputs\event_study_technical_2026h1 --progress-interval-seconds 60`。
4. 记录退出码、耗时、产物存在性、事件数、12 个组合的控制分布行数、`streaming_metadata.json` 和进程/内存证据。
5. 全量产物完整且审计通过后，再更新本文件、提交源码和文档、推送 `codex/b1-event-study`。

最后更新：2026-07-15（Asia/Shanghai）

## 当前目标

实现 B 层 A 股 B1 信号事件研究：对 `legacy`、`bbi`、`b1` 三组日线收盘信号，分别计算下一交易日开盘入场后持有 2、5、10、20 个完整交易日的结果，并与同日随机对照组比较。

## 工作状态

- 开发分支：`codex/b1-event-study`
- 当前工作树：`C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`；不要在 `C:\Users\playd\Desktop\A_Share_Backtesting` 根目录或 `C:\Users\playd\Documents\A_share_backtesting` 继续本分支开发。
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

1. 进入 `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`，确认当前分支为 `codex/b1-event-study` 并同步该分支的最新提交。
2. 先阅读本文件和实施计划；不要从 `main` 直接继续开发。
3. 设置运行环境后执行：

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest discover -s tests -v
```

4. 从“下一步”的第一条继续；完成一个任务后，更新本文件的已完成项、验证结果、提交号和下一步。
