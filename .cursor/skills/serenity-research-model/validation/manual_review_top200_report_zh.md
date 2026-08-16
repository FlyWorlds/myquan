# Top200 人工复核报告

复核日期：2026-06-10

复核对象：

- `manual_review_priority_top200.csv`

输出文件：

- `manual_review_priority_top200_human_reviewed.csv`：人工语义复核版
- `manual_review_priority_top200_auto_reviewed.csv`：脚本规则自动复核版
- `manual_review_priority_top200_forward_signals.csv`：剔除无效/复盘/quote-only 后的前瞻信号子集
- `manual_review_priority_top200_review_summary.md`：自动复核统计

## 1. 复核方法

Top200 不是 200 条完全不同的推文，而是 200 个 ticker-level 信号行。

聚合后发现，Top200 实际来自 10 条唯一推文。很多行来自同一条长清单或长 thesis，例如一条“30 个股票清单”会被拆成 30 多个 ticker 行。

所以本次复核按两层完成：

1. 先按 `url/text` 聚合，判断唯一推文的语义类型。
2. 再按 ticker 回填到每一行，判断这个 ticker 是 Serenity 正文观点，还是只出现在引用文本里。

## 2. 五个复核问题

每一行都按以下问题判断：

1. 这条推文到底是不是 Serenity 自己的观点？
2. 是事前研究，还是上涨后的复盘？
3. 是强 thesis，还是调侃、引用、免责声明？
4. ticker 是否是标的本身，还是只是对比对象/引用对象？
5. 这条信号应该保留、降权，还是删除？

## 3. 人工复核结果

Top200 人工语义复核后：

| 决策 | 行数 | 含义 |
|---|---:|---|
| `delete_from_this_signal` | 53 | ticker 只出现在引用文本里，不能算本条 Serenity 信号 |
| `remove_from_forward_signal_keep_as_track_record_context` | 44 | 事后收益/历史命中复盘，不进入前瞻信号 |
| `deweight` | 41 | 候选池、众包名单、未完成 DD，保留但低权重 |
| `keep_deweighted` | 33 | Serenity 正文观点，但属于广谱清单，单票 thesis 较粗 |
| `keep` | 26 | 高质量主动 thesis 或明确事件链条 |
| `keep_as_explainer_deweight` | 2 | 事件解释，不是明确做多/做空 |
| `delete` | 1 | 纯链接，无可解析观点 |

最终可进入前瞻信号子集的行数：

- 保留或降权后：102 行
- 剔除或仅作背景：98 行

## 4. 10 条唯一推文的判断

### 4.1 2026-01-03 委内瑞拉事件链条

URL：`https://x.com/aleabitoreddit/status/2007387427820978510`

判断：

- 正文里出现的 `CF/CVE/VLO/LDOS/AVAV/HII/LHX/BA/RTX/HON` 等，是 Serenity 围绕委内瑞拉事件写的受益链条。
- 这些可以保留为事件驱动观点，但不是 AI 供应链核心模型。
- 只出现在引用的 Jan 1 ratings 里的 ticker，应从本条信号删除，不能把它们当成委内瑞拉事件 thesis。

结论：

- 正文 ticker：`keep`
- quote-only ticker：`delete_from_this_signal`

### 4.2 2026-05-12 humanoid 众包名单

URL：`https://x.com/aleabitoreddit/status/2054335940026573222`

判断：

- 这条明确写了 `crowdsourced list` 和 `Will start doing DD`。
- 它不是完成的 thesis，而是候选池。
- 可以用来观察 Serenity 的注意力迁移，但不能当强信号。

结论：

- 正文候选 ticker：`deweight`
- 只在引用问题中的 `RKLB/TSLA` 等：`delete_from_this_signal`

### 4.3 2026-04-09 30 个股票清单

URL：`https://x.com/aleabitoreddit/status/2042187668931616964`

判断：

- 正文是 Serenity 自己写的 `random stocks I like today and why`。
- 这是有效偏好清单，但覆盖 30 个股票，单票研究深度不一致。
- 适合作为注意力和主题偏好，不适合作为每个 ticker 的强 thesis。

结论：

- 正文 ticker：`keep_deweighted`
- 只出现在提问引用中的已有仓位/排除项：`delete_from_this_signal`

### 4.4 2026-05-23 YTD 3840.39% 复盘

URL：`https://x.com/aleabitoreddit/status/2058230354063102028`

判断：

- 这是收益和历史命中复盘。
- 里面列出的 ticker 是事后 track record，不是新信号。
- 收益数字没有经过审计，不能作为真实盈利证据。

结论：

- `remove_from_forward_signal_keep_as_track_record_context`

### 4.5 2026-05-15 YTD 3152.77% 复盘

URL：`https://x.com/aleabitoreddit/status/2055401446397690311`

判断：

- 同样是历史多头命中回顾。
- 可以保留作“自我归因/宣传/track record”材料，但不能进入 forward signal。

结论：

- `remove_from_forward_signal_keep_as_track_record_context`

### 4.6 2026-05-17 photonics 深度反驳

URL：`https://x.com/aleabitoreddit/status/2055822766600016238`

判断：

- 这是高质量主动 thesis。
- 正文包含 photonics TAM、SIVE、LPK、LITE、JBL、POET、MRVL、AMD、COHR、ASML、INTC 等产业链拆解。
- 有 TAM、技术路径、风险、估值和持有周期，是最符合 Serenity 方法论的样本。

结论：

- 正文 ticker：`keep`
- 只出现在引用组合里的 ticker：`delete_from_this_signal`

### 4.7 2026-01-31 SLV 操纵历史解释

URL：`https://x.com/aleabitoreddit/status/2017669714353537024`

判断：

- 是白银市场结构/操纵历史解释。
- 不是明确做多或做空 SLV。

结论：

- `keep_as_explainer_deweight`

### 4.8 2026-05-19 纯链接

URL：`https://x.com/aleabitoreddit/status/2056691097594925522`

判断：

- 只有链接，没有可解析文本和 ticker。

结论：

- `delete`

### 4.9 2026-01-30 SLV 闪崩解释

URL：`https://x.com/aleabitoreddit/status/2017353453790761259`

判断：

- 是事后解释 SLV 闪崩机制。
- 不是明确投资 thesis。

结论：

- `keep_as_explainer_deweight`

### 4.10 2026-04-25 photonics supercycle 更新

URL：`https://x.com/aleabitoreddit/status/2048129936813428922`

判断：

- 是主动研究框架更新。
- 回答 photonics 是否太晚，并拆解 LITE、COHR、AXTI、AAOI、JBL、SIVE、POET、ALMU 等代际机会。

结论：

- `keep`

## 5. 写回脚本的规则

已把本次复核规则写回 `serenity_mvp.py`，新增命令：

```powershell
python .\serenity-research-model\scripts\serenity_mvp.py auto-review `
  --signals .\real_runs\serenity_mvp_20260610\outputs\cleaned\manual_review_priority_top200.csv `
  --out .\real_runs\serenity_mvp_20260610\outputs\cleaned
```

自动复核规则包括：

- ticker 只出现在引用文本：删除本条信号
- YTD、10x、历史命中、return %：转为 track-record 背景，不进前瞻信号
- crowdsourced list、will start doing DD：降权为候选池
- random stocks I like today and why：保留但降权为广谱清单
- photonics、chokepoint、TAM、risk/reward、I'll walk through：保留为主动 thesis
- crash、ended the day down、market manipulation：降权为事件解释
- 纯链接：删除

## 6. 下一步

下一步应该把这套 review 规则应用到完整 `manual_review_queue.csv`，生成全量语义复核版。

然后再重新计算：

- 剔除 quote-only 和复盘贴后的公开信号表现
- 只保留 `keep/keep_deweighted/deweight` 后的主题分布
- 高质量 thesis 的 forward return
- Serenity 真正的“前瞻研究模型”，而不是被引用、复盘和清单污染后的模型
