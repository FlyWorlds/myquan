# 输出契约

顶层 JSON 至少包含：

```text
mode, generated_at, as_of, strict_source, universe,
subjects, limitations, provenance, methodology, disclaimer
```

每个标的至少包含：

```text
symbol, name, expectation, fundamentals, valuation,
market_context, score, vetoes, downgrades, evidence,
counter_evidence, catalysts, invalidation, limitations, provenance
```

指标对象建议包含：

```text
value, unit, status, source_methods, as_of, report_period,
formula, fields, caveat
```

研究门控：`PASS`、`CAUTION`、`FAIL`、`N/A`。分数和覆盖率范围为 0–100 或 N/A。
