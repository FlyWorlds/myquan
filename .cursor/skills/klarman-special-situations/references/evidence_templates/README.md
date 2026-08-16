# Evidence 包填写指南

`run(config={"evidence_dir": ".../evidence"})` 会加载这个目录下每个 JSON。
每份 JSON 是一个事件族，用 `event_family_id + revision_id` 追加修订。

## 4 类特殊情况模板

- [private_placement_unlock.json](private_placement_unlock.json) —— 定增折价+解禁
- [reorganization_backdoor.json](reorganization_backdoor.json) —— 重组/借壳
- [spin_off.json](spin_off.json) —— 分拆上市
- [distress_turnaround.json](distress_turnaround.json) —— 困境反转

## 每个 atom 的必需字段

```json
{
  "atom_id": "唯一 ID",
  "field_name": "承保公式使用的键名",
  "value": "具体值",
  "unit": "单位（万元/股/日等）",
  "currency": "CNY / 无",
  "basis": "证据基础",
  "source_type": "exchange_disclosure / csrc_filing / court_docket / audit_report",
  "source_ref": "公告标题或 URL",
  "source_record_id": "公告编号",
  "available_date": "YYYYMMDD 首次公开日",
  "content_hash": "SHA-256 hex",
  "extraction_method": "provider",
  "evidence_kind": "structured_fact",
  "core": true
}
```

## 承保门与 atom 对应

| Klarman 门 | 至少需要 atom |
|---|---|
| `security_access` | 证券代码、交易状态、可流通性 |
| `deal_terms` | 对价、条件、审批、截止日、终止条款 |
| `conservative_value` | 保守估值输入（净资产、可回收资产、SOTP 组件） |
| `failure_value` | 失败情景估值（回收瀑布、资产清算价值） |
| `capital_structure` | 优先债、担保、或有负债、完全稀释股数 |
| `liquidity` | 日均成交额、停牌史、退市风险状态 |
| `legal_accounting` | 审计意见、诉讼、监管处罚 |
| `catalyst` | 事件催化剂（批文号、法院裁定、公告 ID） |

## 禁止

- 不得填 `verified: true` 但缺 `source_record_id` 或 `content_hash`
- 不得用人工推断值填 `core: true` 的 atom
- 不得回写：新证据用新 `revision_id`，不覆盖旧 `available_date`
- 不得包含"建议买入"等交易指令语言（会被 `TRADE_DIRECTIVE_PATTERN` 拒绝）
