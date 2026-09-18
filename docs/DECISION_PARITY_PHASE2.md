# Decision Parity Phase 2

> 日期：2026-09-17  
> Harness：`strategy/test_exit_fixture_parity.py`  
> Fixtures：`strategy/fixtures/exit_parity_cases.json`（22 案）  
> 对照：`paper_exit_decision`（legacy）↔ `ExitDecisionEngine`

---

## 1. 汇总

| 指标 | 值 |
|------|----|
| Total | **22** |
| Exact Match | **22**（100%） |
| Mismatch | **0** |
| Open protect | 4/4 |
| Working stop (last) | 2/2 |
| Factor26 path | 5/5 |
| T+1 | 2/2 |
| Half position | 2/2 |

比较维度：`hit` / `hit_show` / `kind` / `fill_px` / `quantity_ratio`（半仓）+ `reason_code`。

---

## 2. Mismatch 分类

| Class | 含义 | 本批数量 |
|-------|------|----------|
| A BUG | 疑似实现错误 | 0 |
| B 已知设计差异 | 产品口径不同 | 0 |
| C Context 缺失 | 缺字段 | 0 |
| D Rule Order | 优先级错 | 0 |
| E Price semantics | 成交价语义 | 0 |
| F Legacy 特殊 | 仅展示差异 | 0 |
| G Unknown | 未归类 | 0 |

> Phase 1 报告中「Engine 缺开盘保护 / 无 path 的 last」差异，在 **ExitDecisionEngine** 路径上已消除（编排对齐 paper）。  
> 旧 `Strategy16Decision` / `Factor26Decision` **未**替换；AKQUANT 日线仍独立（见 `AKQUANT_DECISION_GAPS.md`）。

---

## 3. 覆盖标签

fixture tags：`hold` / `open_protect` / `working_stop` / `factor26` / `path` / `half` / `t1` / `gap` / `no_path` / `rule_order`

含：开盘优先于 path、path 优先于 working_stop、半仓 quantity_ratio=0.5、T+1 只展示、锁仓/跌停/竞价拦截。

---

## 4. 生产开关状态（Phase 2 当时默认）

| Flag | 当时默认 | 含义 |
|------|------|------|
| `USE_UNIFIED_EXIT_ENGINE` | **False** | True 时 paper 返回引擎结果 |
| `SHADOW_UNIFIED_EXIT_ENGINE` | **False** | True 时双跑只记 Shadow，不成交 |

Legacy 仍可回滚；未删除 `_paper_exit_decision_legacy`。

**Superseded by Primary Reversal：** 当前 `USE_UNIFIED_EXIT_ENGINE=True`，`SHADOW_UNIFIED_EXIT_ENGINE=True`。

---

## 5. 复现

```bash
python -m unittest strategy.test_exit_fixture_parity -v
python -c "from strategy.test_exit_fixture_parity import run_fixture_parity; import json; print(json.dumps(run_fixture_parity()['tallies'], indent=2))"
```

---

*Phase 2E：fixture parity 建立；未为刷数字改交易规则。*
