# PandaAI workflow format

Use this reference when normalizing a PandaAI export or API response. The format is intentionally redundant because LiteGraph supports the editor while `nodes` and `links` support execution and persistence.

## Accepted roots

The parser accepts either:

```json
{
  "format_version": "V1.0",
  "name": "example",
  "description": "",
  "litegraph": {},
  "nodes": [],
  "links": []
}
```

or an API wrapper whose `data` object contains those fields.

Top-level `id` and `_id` are both metadata. Do not require either for offline review.

## Field precedence

1. Use normalized `nodes[].static_input_data` for manually entered execution inputs.
2. Use normalized `links` for source node, target node, and field-level data flow.
3. Use `litegraph.nodes` and `litegraph.links` to cross-check the editor representation.
4. Fall back to `litegraph.nodes[].properties` only when normalized code is absent. Real frontend exports label these properties with Chinese keys such as `策略代码` or `代码`, not `code`; check both.
5. Report mismatches rather than silently choosing a convenient value.

## Node shape

Important normalized node fields:

- `uuid`: stable graph identity used by normalized links.
- `name` / `type`: runtime node class, for example `CodeControl`, `StockBacktestControl`, or `FactorAnalysisControl`.
- `litegraph_id`: editor-local integer ID.
- `static_input_data`: user-entered values such as code, dates, costs, stock pool, grouping, and factor direction.
- `output_db_id`: persisted run-output reference when present.
- `custom_code`: API responses may include custom-node implementation code.

Custom published nodes may append an identifier after a colon. Preserve the full name for evidence and use only the prefix for broad family classification.

## Link shape

Important normalized link fields:

- `uuid`
- `litegraph_id`
- `status`
- `previous_node_uuid`
- `next_node_uuid`
- `output_field_name`
- `input_field_name`

A valid link must reference two existing node UUIDs. Never infer a missing edge merely because two nodes appear adjacent on the canvas.

## Node families

Recognize capabilities rather than relying on one frozen list:

- Strategy backtest: names ending in `BacktestControl`.
- Code: `CodeControl` or nodes exposing `code` / `custom_code`.
- Factor production and analysis: names containing `FactorBuild`, `FactorClean`, `FactorAnalysis`, `FactorEvaluate`, `FactorDecay`, or `FactorBlend`.
- Results: names containing `ResultControl` or output references such as `task_id`, `backtest_id`, or `output_db_id`.

Unknown nodes are not defects by themselves. Review their visible schema and connections; report insufficient evidence when their semantics cannot be determined.

## Export limitations

A workflow export describes the current graph. It normally does not include:

- all discarded parameter combinations;
- all historical code versions;
- complete returns or trade records;
- data snapshots and point-in-time provenance;
- the researcher's manual decisions after viewing results.

In real frontend exports, `output_db_id` is `null` and `BackTestResultControl` carries a placeholder `task_id` such as `"error"` even when the workflow was previously run on the platform. Valid run references have so far only been observed in API responses, so expect the `single-run-reference` evidence level to be reachable only for API payloads; frontend exports normally audit as `static-only`.

Therefore, the file supports static review but not a definitive statistical claim about overfitting.

