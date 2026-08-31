# 因子13 说明

> 研究用途，不构成投资建议。

**最后更新**：2026-08-31  
**注册表拆分**：`factor13a`（质量带）· `factor13b`（熊盾，🔒锁定）· `factor13`（别名→13A）

---

## 0. 注册 ID（2026-08 拆分）

| ID | 名称 | 模块 | 用途 |
|----|------|------|------|
| **factor13a** | 质量带契合选股 | `factor13_fit.py` | 夏普/回撤甜区 → `score_quality` TopK |
| **factor13b** | 熊市盾牌 thr\* Top3 | `factor13_bear_shield.py` | WF + 个股 thr*（**当前生产锁定**） |
| **factor13** | 兼容别名 | → `factor13a` | 旧脚本/导入勿断 |
| **factor16** | 龙头评分 | `factor16_leader_score.py` | **13A 过门** + 因子1 OOS **盈亏比/胜率**排序 |

宽宇宙换池（`backtest/s1_f13_refit_2025.py`）：**13A 网格调参 → 因子16 排序 Top10 → 策略1 执行**。

---

## 1. 两条实现线（勿混）

| 线 | 模块 | 用途 | 状态 |
|----|------|------|------|
| **A. 质量带** | `factor13_fit.py` → `factors/factor13.py` | 上年夏普/回撤甜区 → 次年 TopK | 历史 walk-forward，注册表默认文案 |
| **B. 熊市盾牌 thr\* Top3** | `factor13_bear_shield.py` | 熊年超额 + 季熊 + 软牛 + WF + 个股 thr* | **当前推荐 / 已锁定** |

---

## 2. 熊市盾牌（锁定版）

### 2.1 理念

- **熊市**：个股自身下跌期，开盘突破策略要有超额/防守收益。
- **牛市**：不要求超额；软要求年均策略收益、有牛年时牛年策略≥0。
- **反过拟合**：交易年 `T` 的名单与 `thr*` 仅用 **≤T−1**；稳定性过滤；门槛冻结后 VALID 调参、BLIND 只报告。

### 2.2 默认参数（锁定）

| 项 | 值 |
|----|-----|
| TopK | **3** |
| 阈值 | 个股 **thr\***：{2%, 2.5%, 3%} 拟合窗夏普最高；**天通钉 ±3%** |
| 稳定性 | 近 **2** 窗均进 Top **10**，再取 Top3 |
| 年熊门 | 熊年数≥2，熊收益≥−10%，熊超额≥2%，最差熊超额≥−10% |
| 季熊门 | 熊季≥2，季熊超额≥0 |
| 软牛 | 年均策略≥0%；有牛年则牛年策略≥0 |
| 打分 | 熊项百分位为主 + 年均/牛年收益（`w_bull_score=1`） |

### 2.3 2026 锁定名单（fit≤2025）

| # | 股票 | thr* |
|---|------|------|
| 1 | 东材科技 | 2.5% |
| 2 | 西藏珠峰 | 2.5% |
| 3 | 雷赛智能 | 3.0% |

### 2.4 样本外参考（WF，等权 Top3）

| 区间 | 组合收益 | 备注 |
|------|----------|------|
| 盲测 2025 | +42.6% | 未参与选参 |
| 盲测 2026 YTD | +77.2% | 未参与选参 |
| 拼接 2023→今 | +174% | 含 2023 弱年 |

调参报告（VALID=2023–2024，216 trials）：`backtest/factor13_bear_shield_tune_pit/report.html`

### 2.5 脚本与产物

```bash
# 主入口：逐年 WF 回测
python strategy/run_factor13_bear_shield_wf.py

# 防过拟合网格（锁定前已完成）
python strategy/run_factor13_bear_shield_tune_pit.py
```

| 路径 | 说明 |
|------|------|
| `backtest/factor13_bear_shield/LOCKED.json` | 锁定配置与 2026 名单 |
| `backtest/factor13_bear_shield_wf/` | WF 目标、分年、拼接 NAV |
| `backtest/factor13_bear_shield_wf_thr/top3/` | thr* Top3 明细 |
| `strategy/factor13_bear_shield.py` | 选股核心 |

---

## 3. 质量带（A 线，历史）

- 阈值固定 ±2.5%（或面板 thr_mode）。
- 过滤：夏普 ∈ [1.0, 2.2]，回撤 ∈ [18%, 32%]，dd_ratio ≤ 0.55。
- 排序：`score_quality`；Top8–10。
- 规则文件：`backtest/factor13_quality_opt/best_rule.json` 等。

```bash
python strategy/run_factor13_top10_quarterly.py
python strategy/run_factor13_tune_blind.py   # 盲测调参实验
```

---

## 4. 与策略一的关系

因子13 **只负责选股/合格池**；交易仍走 **策略一·因子1**（开盘突破 ±thr*，仅止损）。

组合研究：等权 Top3 回测 ≠ 槽位连续 NAV（现金、换仓、滞后见各 `report.html`）。

---

## 5. 解锁流程

1. 用户明确「解锁因子13」。
2. 改 `LOCKED.json` → `"locked": false`。
3. 重新跑 `tune_pit` 或 WF，更新 `recommended.json` 与本文档数字。
4. 同步 `READ.md`、`strategy/README.md`、`TODO.MD`。
