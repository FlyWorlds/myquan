---
name: alpha-a06-hotmoney-reversal
description: Use this skill to calculate, validate, backtest, and publish the A06 hot-money seat cooling-reversal and collaborative-breakout Alpha factor for A-share Dragon-Tiger List data.
tags: [quant, skill, alpha, stock, lhb]
license: GPL-3.0-only
maintainer: quantskills
runtime_adapters: [codex, claude-code, cursor, hermes, openclaw]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-alpha-a06-hotmoney-reversal
  repository_url: https://github.com/quantskills/skill-alpha-a06-hotmoney-reversal
  project_type: skill
  collection: alpha
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "补充数据范围、回测区间、产物路径或具体问题（可选）",
    "required": false
  },
  "fields": [
    {
      "key": "mode",
      "label": "处理模式",
      "type": "select",
      "default": "inspect",
      "options": [
        { "value": "inspect", "label": "查询与解读" },
        { "value": "calculate", "label": "计算因子" },
        { "value": "validate", "label": "验证因子" },
        { "value": "backtest", "label": "执行回测" },
        { "value": "release", "label": "构建发布产物" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}按 {{mode}} 模式处理 A06 游资席位降温反转与协同突破因子，严格遵守信号于 t 日收盘后形成、t+1 开盘买入、t+2 收盘卖出的可执行口径，说明数据来源、泄漏与过拟合风险以及结果边界，输出中文报告。"
}
```

# A06 Hot-Money Reversal Alpha Skill

## Purpose

This repository packages the QuantSkills A06 Alpha factor as a reusable skill. A06 models hot-money seat behavior on A-share Dragon-Tiger List data, combining short-term crowding reversal and collaborative breakout continuation signals.

Use it when a user needs to:

- compute or inspect the A06 factor;
- validate the factor for leakage, overfitting, and out-of-sample stability;
- run executable backtests using the documented `t+1` open entry and `t+2` close exit convention;
- build production Parquet outputs and acceptance reports;
- query existing A06 production results.

## Repository Layout

- `开发产物/SKILL.md`: full development skill manual.
- `开发产物/skill.json`: machine-readable metadata.
- `开发产物/scripts/`: factor calculation, validation, backtest, release build, and production update scripts.
- `开发产物/references/`: data guide.
- `生产产物/SKILL.md`: production-result reader contract.
- `生产产物/数据库.parquet`: production-format output.
- `生产产物/发布验收报告.*`: release acceptance reports.
- `README.md` and `README.en.md`: Chinese and English project introductions.

## Factor Logic

The core hypothesis is that crowded hot-money coordination on the Dragon-Tiger List often reverses over the short term, while a smaller set of non-overheated repeated-seat coordinated net buys may continue as breakouts.

The documented formula is:

```text
factor_value = (-z(net_buy_to_amount) - z(ret_5d) - z(ret_10d)) / 3 + 0.25 * watch + 3.0 * buy
```

Higher `factor_value` means a stronger signal. The supported mode is `hotmoney_executable_open`.

## Usage

Run commands from `开发产物/`.

```bash
python scripts/factor.py --demo
python scripts/validate.py
python scripts/backtest.py
python scripts/update_production.py --full-refresh --bootstrap-start-date 20230601
```

Build a release from fixed PandaData snapshots:

```bash
python scripts/build_release.py \
  --details panda_lhb_detail.parquet \
  --calendar panda_trade_calendar.parquet \
  --quotes panda_market_data.parquet \
  --start-date 20230601 \
  --end-date 20260605 \
  --output ../生产产物/数据库.parquet \
  --report ../生产产物/发布验收报告.json
```

## Runtime Adapter Notes

- Codex and Claude Code can use this root `SKILL.md` directly, then open `开发产物/SKILL.md`.
- Cursor should load `agents/cursor-rule.mdc`.
- Hermes and other portable agents should load `agents/portable-loader.md`.
- OpenClaw should load `agents/openai.yaml` or `agents/portable-loader.md`.

## Limitations And Risk Boundaries

- Official calculation uses PandaData or fixed PandaData raw snapshots; do not substitute an old factor panel as the official input.
- The factor is a research artifact, not investment advice. Do not present signals as return promises or trading recommendations.
- Production readers should read existing Parquet outputs and must not pull raw data or recalculate the factor during ordinary queries.
- The documented executable convention is signal after `t` close, buy at `t+1` open if tradable, and sell at `t+2` close.
- Skip halted stocks and open-limit-up cases according to the project rules.

## Compliance Metadata

- Repository type: QuantSkills skill repository.
- Upstream organization: QuantSkills, https://github.com/quantskills.
- Repository: https://github.com/quantskills/skill-alpha-a06-hotmoney-reversal.
- License: GPL-3.0-only.
- Maintainer: QuantSkills.
- Sensitive data: do not commit credentials, tokens, proprietary data, user directories, or local absolute paths.
