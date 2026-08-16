# Serenity 真实推文研究模型 MVP

运行日期：2026-06-10

## 1. 数据边界

本次使用 `yan-labs/serenity-aleabitoreddit` 公开整理的 `aleabitoreddit_tweets.csv` 作为主数据源。

- 原始帖子：5,857 条
- 原始信号行：16,464 行
- 清洗后信号行：15,929 行
- cashtag 白名单：686 个
- 被移除的疑似假 ticker：535 行
- 需要人工复核：7,898 行
- 引用关系行：6,071 行
- 价格评估覆盖：8,152 行

本报告只复原公开帖子中的研究行为，不验证 Serenity 的真实仓位、收益、买卖点或资金规模。

## 2. 最小颗粒度

一条 Serenity 信号被拆成以下最小单元：

- `ticker`：公开帖子中出现的 `$代码`
- `theme`：AI infrastructure、Photonics/CPO、Memory/HBM、Neocloud、Power Grid、Robotics 等
- `supply_chain_role`：终端需求、系统集成、原材料、组件、设备/测试
- `bottleneck_claim`：是否出现瓶颈、稀缺、约束、卡点等论述
- `evidence_types`：价格成交量、客户 capex、财务拐点、技术约束、专利/科学、政策
- `catalysts`：财报、订单、guidance、shipment、launch 等
- `risk_markers`：risk、sell、short、dilution、bear、wrong、downside、expensive、exit 等
- `conviction_score`：根据长文、重复、高确信措辞、否定语义、免责声明等打分
- `review_flags`：引用上下文、主题贴无 ticker、免责声明、反讽/否定语义

这个颗粒度的目标是把“他看好什么”拆成“为什么看好、在产业链哪个环节、证据是什么、风险有没有被承认、是否只是引用别人观点”。

## 3. 注意力地图

清洗后主题分布：

- AI infrastructure：6,268 行
- Photonics/CPO：2,893 行
- 未分类：2,856 行
- Memory/HBM：1,247 行
- Crypto：1,025 行
- Semiconductor：504 行
- Neocloud：417 行
- Power Grid：391 行
- Robotics/Physical AI：328 行

高频 ticker：

- `NBIS`：692
- `SIVE`：572
- `AXTI`：542
- `NVDA`：519
- `LITE`：509
- `IREN`：444
- `AAOI`：423
- `GOOGL`：348
- `MSFT`：337
- `META`：310
- `AMZN`：289
- `TSM`：286
- `COHR`：280
- `MRVL`：267

## 4. Serenity 的核心研究模型

### 4.1 先找巨大需求波

起点通常不是单家公司，而是一个足够大的资本开支浪潮：

- AI 数据中心
- GPU 集群
- CPO/光互联
- HBM/内存
- neocloud/GPU leasing
- 电力、800V DC、冷却
- robotics/physical AI

他的第一问是：如果这个需求是真的，哪些环节会先不够用？

### 4.2 再沿产业链向上游拆

模型不是只看 `NVDA/MSFT/GOOGL/META/AMZN` 这些显性受益者，而是从终端需求倒推：

终端需求 -> 系统集成 -> 关键组件 -> 原材料/衬底 -> 设备/测试/良率 -> 产能瓶颈

这解释了为什么 `AXTI/SIVE/LITE/AAOI/COHR/MRVL/SOI/IQE/POET` 这类标的频繁出现。

### 4.3 核心是 chokepoint，而不是普通成长

被反复寻找的不是“业务也受益”的公司，而是：

- 供给有限
- 技术门槛高
- 客户认证周期长
- 替代品少
- 小公司收入弹性大
- 机构覆盖不足
- 一旦需求兑现，估值和盈利会非线性重估

这就是 Serenity 模型里最有价值的部分：不是预测大趋势，而是找大趋势里最窄的供给口。

### 4.4 证据体系

从清洗结果看，证据标签最常见的是：

- price-volume：10,617
- customer-capex：6,731
- financial-inflection：6,423
- technical-constraint：4,780
- patent-science：3,026
- policy：1,088

这说明他的公开表达不是纯基本面，也不是纯技术面，而是“产业链论点 + 价格/成交量确认 + 财报/客户/技术文件催化”的混合模型。

### 4.5 时间框架

信号时间框架分布：

- unspecified：6,856
- days-weeks：3,049
- intraday：3,023
- months-quarters：2,354
- multi-year：647

结论：Serenity 的帖子里既有长期产业链判断，也有大量短线/事件驱动表达。不能把每条推文都当成长期持仓 thesis。

## 5. 公开信号表现评估

价格评估覆盖 30 个高频标的、8,152 条信号行。以公开帖子日期后的 Yahoo 日线收盘价计算：

| 周期 | 样本量 | 平均收益 | 中位数 | 胜率 |
|---|---:|---:|---:|---:|
| 1 日 | 8,122 | 0.54% | 0.13% | 51.53% |
| 5 日 | 8,039 | 3.30% | 1.65% | 57.28% |
| 20 日 | 7,475 | 11.92% | 6.15% | 63.04% |
| 60 日 | 4,882 | 29.61% | 9.48% | 61.37% |
| 120 日 | 2,385 | 20.78% | 8.46% | 59.29% |

解读要非常谨慎：

- 这是公开帖子的后验表现，不是 Serenity 的真实交易收益。
- 热门小票可能被账号影响力本身推动。
- 同一 ticker 多次出现会导致样本非独立。
- 有些帖子是引用、回复、反讽或复盘，不一定是新买入信号。

## 6. 人工校正结论

本次已完成第一轮机器+规则校正：

- 假 ticker：用原始 cashtag 白名单过滤，移除 535 行。
- 反讽/否定语义：生成 `review_flags`，特别标记 `not my...`、`joke`、`lol`、`meme`、免责声明等。
- 引用关系：生成 `quote_relationships.csv`，共有 6,071 行需要区分“Serenity 自己的 thesis”还是“引用对象的观点”。
- 高优先级复核：生成 `manual_review_priority_top200.csv`，按互动量和确信度排序，适合先人工看最重要的 200 条。

下一轮人工复核应优先处理：

1. 高互动引用贴：判断论点归属。
2. 高确信但带否定词的帖子：避免把反讽当推荐。
3. 高频标的首次出现贴：确定 thesis 起点。
4. 大涨后的复盘贴：避免误当事前信号。

## 7. 可复用 Skill 生成器雏形

Serenity MVP 已经沉淀出一套可迁移流程：

1. 收集交易员历史公开帖子。
2. 用 cashtag/标的白名单减少假 ticker。
3. 拆成主题、证据、产业链角色、催化、风险、确信度。
4. 单独处理引用、回复、反讽、免责声明。
5. 用公开发帖时间做 forward-return 评估。
6. 从主题和证据频率中抽象个人研究模型。

这套流程可以作为后续 `x-trader-skill-builder` 的样板。
