# Exit Decision 大样本 Replay（Phase 3A～3C）

> 运行日期：2026-09-17  
> 行情：AKShare/东财真实 1m OHLC，2026-09-07 13:53～2026-09-17 15:00（各标的可用区间）  
> 持仓：现有 Factor26 1m 回放生成的入场与持仓区间  
> 对照：`_paper_exit_decision_legacy` ↔ `ExitDecisionEngine`  
> 性质：只读 Shadow Replay；不成交、不写 paper ledger、不启用 Unified

## 结论

第一批真实分钟回放共 **8,077 次 evaluation**：

- Legacy SELL：**25**
- Unified SELL：**25**
- 全量严格一致：**8,077 / 8,077**
- SELL 的 action / price（绝对误差 ≤ 1e-6）/ quantity：**25 / 25**
- Mismatch：**0**

规则覆盖：

- T+1 evaluation：7,360
- Open Protect SELL：20
- Factor26 Path SELL：5
- Factor26 path 触达（含 T+1 只展示）：15
- 半仓 path evaluation：2
- Working Stop SELL：0

这批结果证明：在相同、显式的 `DecisionContext` 下，Legacy 与 Unified 的编排输出一致。它还**不足以单独支持生产切换**：SELL 只有 25 次，真实 working-stop 没有触发，而且持仓来自回放生成，不是历史 paper ledger 快照。

因此当时：

```text
USE_UNIFIED_EXIT_ENGINE = False
SHADOW_UNIFIED_EXIT_ENGINE = False
```

**Historical（2026-09-17）：** 开关保持不变。  
**Superseded by Primary Reversal：** `USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`（Unified = Primary，Legacy = Shadow / fallback）。上方 **8,077 / 8,077** 仍是该次回放事实，未改。

## 比较口径

每次 evaluation 比较：

1. action（HOLD / SELL；show-only 仍按不成交 HOLD）
2. price（SELL 时绝对误差 ≤ 1e-6）
3. quantity ratio
4. factor id
5. reason code

两个路径共享同一份只读输入。Replay 不调用 `paper_exit_decision` 的 feature-flag wrapper，而是直接调用 Legacy 纯决策函数和 Unified Engine，避免测试过程改变生产开关。

## 产物

- 汇总及逐标的覆盖：`backtest/exit_decision_replay/replay_summary.json`
- 全量 mismatch 明细：`backtest/exit_decision_replay/replay_mismatches.json`（本批为空）
- 可复现入口：`backtest/exit_decision_replay/run.py`

## 复现

使用现有缓存（最快）：

```bash
python backtest/exit_decision_replay/run.py --days 10 --source ak
```

重新拉取当前可用真实分钟行情：

```bash
python backtest/exit_decision_replay/run.py --days 10 --source ak --refresh
```

最小冒烟：

```bash
python backtest/exit_decision_replay/run.py --days 10 --source ak --max-symbols 1
python -m unittest backtest.exit_decision_replay.test_run -v
```

## 限制与后续门槛

- AKShare 当前只返回约 1,970 根/标的，不能从本机仓库还原 38,000 次真实历史持仓 evaluation。
- 仓库没有逐轮历史 paper `DecisionContext` 日志；成交汇总不能无损还原 `working_stop`、path、锁仓和当时可卖数量。
- PandaData 运行时当前未安装，未用未配置的数据源伪造长窗。
- 本结果属于真实行情上的研究回放，不是样本外收益结论，也不构成投资建议。

正式接管前建议至少满足：

```text
累计 evaluation >= 30,000
Legacy SELL >= 200
SELL action/price/quantity = 100% match
working_stop / open_protect / Factor26 / T+1 / half 均有真实样本
Mismatch = 0，或逐项分类并批准
```

Phase 3C+ 已把门槛改成 **Exit Path Coverage Gate**（不再用单一 overall parity）。见 [`EXIT_COVERAGE_QUALIFICATION.md`](EXIT_COVERAGE_QUALIFICATION.md)。本文件保留 3A～3C 第一批数字作为基线。

