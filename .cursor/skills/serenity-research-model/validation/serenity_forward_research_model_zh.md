# Serenity 前瞻研究模型：去污染版

运行日期：2026-06-10

本报告基于全量语义复核后的 `signals_auto_reviewed.csv`，剔除了引用污染、事后收益复盘、纯链接、无效文本等内容，重新计算 Serenity 的真实前瞻研究模型。

## 1. 为什么要重算

原始 `signals.csv` 有一个问题：它把很多不同语义的内容都当成了信号。

污染来源包括：

- ticker 只出现在被引用推文里，不是 Serenity 自己说的。
- YTD、10x、历史命中列表，是事后复盘，不是新观点。
- 众包名单只是候选池，还没完成 DD。
- 广谱股票清单有真实偏好，但单票 thesis 很粗。
- 事件解释不是明确做多/做空信号。

所以这一步的目标是得到更接近真实的前瞻研究模型。

## 2. 全量语义复核结果

全量清洗后信号行：15,929 行。

语义复核后：

| 决策 | 行数 | 含义 |
|---|---:|---|
| `keep_deweighted` | 8,515 | Serenity 正文提及，但是广谱清单或普通提及，需要降权 |
| `delete_from_this_signal` | 2,948 | ticker 只在引用文本中出现，应从本条信号删除 |
| `keep` | 2,652 | 高质量主动 thesis |
| `deweight` | 1,322 | 候选池、众包名单、未完成 DD |
| `remove_from_forward_signal_keep_as_track_record_context` | 463 | 事后收益复盘，只保留为 track record 背景 |
| `keep_as_explainer_deweight` | 24 | 事件解释，保留为背景但不进核心前瞻信号 |
| `delete` | 5 | 纯链接或无法解析 |

## 3. 前瞻干净口径

定义：

只保留：

- `keep`
- `keep_deweighted`
- `deweight`

剔除：

- quote-only
- 事后收益复盘
- 纯链接
- 事件解释背景

结果：

- 前瞻信号行：12,489
- 覆盖 ticker：673

主题分布：

| 主题 | 行数 |
|---|---:|
| AI infrastructure | 4,782 |
| 未分类 | 2,752 |
| Photonics/CPO | 2,113 |
| Memory/HBM | 819 |
| Crypto | 722 |
| Neocloud | 365 |
| Semiconductor | 338 |
| Power Grid | 301 |
| Robotics/Physical AI | 297 |

高频 ticker：

- `NBIS`：634
- `SIVE`：550
- `AXTI`：470
- `LITE`：435
- `IREN`：386
- `NVDA`：382
- `AAOI`：374
- `MSFT`：249
- `GOOGL`：241
- `META`：213
- `MRVL`：212
- `COHR`：211

这个口径说明：Serenity 的广义注意力仍然围绕 AI 基建展开，但已经剔除了大量引用和复盘污染。

## 4. 高质量 thesis 口径

定义：

只保留 `keep`。

这是最接近“Serenity 真正主动研究模型”的口径。

结果：

- 高质量 thesis 行：2,652
- 覆盖 ticker：272

主题分布：

| 主题 | 行数 |
|---|---:|
| Photonics/CPO | 1,420 |
| AI infrastructure | 683 |
| Memory/HBM | 335 |
| Semiconductor | 56 |
| 未分类 | 50 |
| Crypto | 32 |
| Neocloud | 29 |
| Power Grid | 27 |
| Robotics/Physical AI | 20 |

高频 ticker：

- `SIVE`：221
- `LITE`：218
- `AXTI`：178
- `AAOI`：133
- `COHR`：117
- `NVDA`：109
- `MRVL`：93
- `SOI`：80
- `IQE`：64
- `AVGO`：60
- `GOOGL`：58
- `MSFT`：58
- `POET`：53
- `AMZN`：52
- `JBL`：50

这一步非常关键：去掉引用、复盘、清单污染后，Serenity 的核心不再只是笼统的 AI，而是非常明确的 Photonics/CPO 供应链。

## 5. 重新计算后的公开信号表现

### 5.1 前瞻干净口径

| 周期 | 样本量 | 平均收益 | 中位数 | 胜率 |
|---|---:|---:|---:|---:|
| 1 日 | 6,658 | 0.56% | 0.16% | 51.82% |
| 5 日 | 6,573 | 3.53% | 1.95% | 58.09% |
| 20 日 | 6,162 | 12.38% | 6.22% | 62.74% |
| 60 日 | 4,072 | 31.16% | 10.38% | 61.71% |
| 120 日 | 1,963 | 22.65% | 12.48% | 61.03% |

### 5.2 高质量 thesis 口径

| 周期 | 样本量 | 平均收益 | 中位数 | 胜率 |
|---|---:|---:|---:|---:|
| 1 日 | 1,626 | 0.79% | 0.31% | 53.08% |
| 5 日 | 1,598 | 4.77% | 2.47% | 59.76% |
| 20 日 | 1,466 | 20.52% | 14.81% | 76.06% |
| 60 日 | 657 | 72.93% | 40.64% | 84.02% |
| 120 日 | 21 | 43.03% | 10.63% | 66.67% |

高质量 thesis 的 20 日和 60 日表现明显强于全量口径。

但要注意：

- 同一 ticker 多次出现，样本不是完全独立。
- Serenity 对小票可能有影响力，发帖本身可能成为催化。
- 120 日高质量样本太少，不适合下强结论。
- 这不是 Serenity 的真实交易收益。

## 6. 去污染后的 Serenity 模型

真正有效的 Serenity 模型可以概括为：

1. 从 AI 基建大趋势出发。
2. 不停留在 `NVDA/MSFT/GOOGL/META/AMZN` 这些显性受益者。
3. 沿供应链往上游找最窄的物理瓶颈。
4. 重点寻找 Photonics/CPO、光模块、InP、激光器、衬底、封装、测试、良率、产能约束。
5. 高质量 thesis 通常包含：
   - TAM 扩张
   - 技术路径变化
   - 供应链位置
   - 客户或 capex 连接
   - 产能/认证约束
   - 风险回报比
   - 持有周期或代际迁移
6. 众包名单和广谱清单只是注意力地图，不能等同强信号。
7. YTD/10x/历史命中贴只作为 track record 背景，不能进入前瞻回测。

一句话：

去污染后的 Serenity 不是“什么 AI 票都提”，而是围绕 AI 基建寻找光电供应链中最窄、最容易被重估的 chokepoint。

## 7. 后续建议

下一步可以做两件事：

1. 用 `signals_high_quality_thesis.csv` 反推 Serenity 的高质量 thesis 写作模板。
2. 把这套语义复核规则抽象成 `x-trader-skill-builder` 的通用模块。

高质量 thesis 模板应重点提取：

- 起点大趋势
- 供应链位置
- 为什么是 chokepoint
- 为什么市场没定价
- 证据来源
- 催化
- 风险
- 跟踪指标
