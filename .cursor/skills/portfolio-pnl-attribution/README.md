<div align="center">
  <h1>组合 P&amp;L 归因</h1>
  <p>把已实现组合收益拆成可审计、可复核的证券与行业贡献。</p>
  <p>
    <a href="README.en.md">English</a>
    ·
    <a href="https://github.com/quantskills/skill-portfolio-pnl-attribution/issues">反馈问题</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/QuantSkills-runnable-2f6fdb?style=flat-square" alt="QuantSkills runnable">
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.10 or newer">
    <img src="https://img.shields.io/badge/license-GPL--3.0-2ea44f?style=flat-square" alt="GPL-3.0 license">
  </p>
</div>

> 📌 **定位**：研究核算工具，用于解释组合已经发生的收益；不估计事前因子风险，也不构成投资建议。

## 🧭 能力概览

| 能力 | 结果 |
| --- | --- |
| 证券归因 | 逐日权重、资产收益与贡献 |
| 行业归因 | 按 `sector` 汇总行业贡献 |
| 收益对账 | 毛收益、费用、净收益和基准主动收益 |
| 数据质检 | 拒绝重复键、缺失同日收益和非法数值 |

## ⚡ 快速开始

```bash
pip install -r requirements.txt
python scripts/attribute_portfolio.py --demo --output-dir out
```

处理真实数据前，请阅读 [`references/input_contract.md`](references/input_contract.md)。最小运行示例：

```bash
python scripts/attribute_portfolio.py \
  --positions positions.csv \
  --returns returns.csv \
  --benchmark benchmark.csv \
  --fees fees.csv \
  --output-dir attribution_out
```

## 📥 输入与 📤 输出

| 数据 | 必需字段 | 说明 |
| --- | --- | --- |
| `positions.csv` | `date,symbol,weight` | 可选 `sector` |
| `returns.csv` | `date,symbol,asset_return` | 收益为小数，例如 `0.01` 表示 1% |
| `benchmark.csv` | `date,benchmark_return` | 可选，日期唯一 |
| `fees.csv` | `date,fee` | 可选，按组合价值比例表示 |

脚本会生成：

- `security_attribution.csv`：逐日逐证券的权重、收益和贡献。
- `sector_attribution.csv`：存在 `sector` 时的行业贡献汇总。
- `daily_attribution.csv`：毛收益、费用、净收益、基准收益和主动收益。
- `summary.json`：覆盖范围、累计收益、对账误差和警告。

## 🔬 工作流

```text
输入契约 → 日期与主键检查 → 同日连接 → 证券/行业归因 → 毛净收益对账 → 结果解释
```

当 `reconciliation_error > 1e-10` 时，应视为数据或舍入缺陷；权重和不为 1 时，保留结果但必须披露警告。

## 🧱 边界与来源

- 仅使用允许的公开资料或用户提供的数据，详见 [`references/source_boundary.md`](references/source_boundary.md)。
- 不进行前视填充，不把缺失收益静默补零。
- 不替代风险模型、组合健康检查或资产配置优化。

## 📁 仓库结构

```text
SKILL.md                         # Codex/Agent 工作流
scripts/attribute_portfolio.py   # 确定性计算脚本
references/input_contract.md     # 输入字段与数据约束
references/source_boundary.md    # 资料边界
agents/openai.yaml               # Agent UI 元数据
agents/cursor-rule.mdc           # Cursor 运行时入口
agents/portable-loader.md        # Hermes/便携运行时入口
requirements.txt                 # Python 依赖
```

## ✅ 本地校验

```bash
node scripts/validate-qsh-form.mjs SKILL.md
python scripts/attribute_portfolio.py --demo --output-dir out
```

## 免责声明

本仓库仅作研究方法层面的整理，非官方、不隶属任何被研究对象，不验证任何收益声明，不构成任何投资建议。

## License

GNU General Public License v3.0，见 [LICENSE](LICENSE)。

## PandaAI / QUANTSKILLS 社群

<div align="center">
  <img src="https://raw.githubusercontent.com/quantskills/.github/main/profile/assets/pandaai-community-qr.jpg" alt="PandaAI 社群二维码" width="220">
  <br>
  <sub>扫码加入 PandaAI 社群，交流 QUANTSKILLS 技能、Agent 工作流与量化研究实践。</sub>
</div>
