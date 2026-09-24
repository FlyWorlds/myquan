# 交易系统时间完整性（Temporal Integrity）

> **状态**：2026-09-24 验收 **PASS**（`TEMPORAL INTEGRITY: PASS`）  
> **真源代码**：[`holdingStocks/temporal_integrity.py`](../holdingStocks/temporal_integrity.py)  
> **回归测试**：[`holdingStocks/test_temporal_integrity.py`](../holdingStocks/test_temporal_integrity.py)（纳入 `holdingStocks/run_regression_tests.py`）  
> **性质**：系统级 invariant，非个股补丁；研究/纸面用途，非投资建议。

---

## 四条硬规则（禁止绕过）

### NO LOOK-AHEAD

任何 `decision_at = T` 的决策，**只能**使用 `timestamp <= T` 的数据。

违例代码：`FUTURE_DATA_VIOLATION` — 必须中止抬 HWM / 自动成交，不得静默吞掉。

### HWM CAUSALITY

`peak_high` 必须与 `peak_high_at` **原子一起更新**，且：

```text
peak_high_at <= decision_at
```

语义：`18.88 @ 10:32:15`，不是「当日最终曾到过 18.88」。  
旧仓缺 `peak_high_at`：降级迁移（`buy_time` 或 `LEGACY_UNKNOWN`），**不得发明未来时间**。

### EVENT IMMUTABILITY

成交落库后：

- `triggered_at`
- `filled_at`
- `exit_kind`

**不得**根据事后价格、后续 `dayHigh` / 日K / 新行情反向改写。

**禁止**：用 `fill_px ≈ open_px` 推断「一定是开盘成交」从而把 PATH @ 09:58 改写成 09:30。  
仅真实 `open_bell` / `exit_kind=open_protect` 才可记竞价核 `09:30:00`。

### STALE DATA

旧 `timestamp` 行情不得覆盖较新的策略状态。

违例代码：`STALE_QUOTE_REJECTED`。

---

## 现场还原字段（异常交易审计）

```text
currentPrice / 今日最高(dayHigh) / 持仓最高(peak_high)
peak_high_at / sellTriggerPrice
quote_at / decision_at / triggered_at / filled_at / exit_kind
```

---

## 技术债（独立，不改本轮 trailing）

**Forming 1m 上游行情质量**：未走完的分钟 K 若由供应商提前写入「最终 high」，仍可能造成同分钟内 look-ahead。  
登记于 [`TODO.MD`](../TODO.MD)；**不得**为处理该债再次改动已验收的 trailing stop / HWM 因果逻辑。见 § 独立技术债。

---

## 回归命令

```bash
cd holdingStocks && python run_regression_tests.py
# 或
python -m unittest test_temporal_integrity test_high_watermark_sell_side -v
```
