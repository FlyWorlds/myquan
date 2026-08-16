# 🧩 Global Commodity Term Structure

**简体中文** | [English](README.en.md)

> 用**公开网络数据**研究海外/国际商品期货的**期限结构**：contango/backwardation 判别、
> 曲线斜率、展期收益（roll yield）、跨期与跨品种价差，并补充库存背景。期限结构描述的是
> **持有成本（carry），不是价格方向信号**。

![type](https://img.shields.io/badge/type-skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

## 📖 这是什么

这是一个 QuantSkills 社区 **skill**（能力包），供 Agent 加载后为**海外商品期货**构建并解读
期限结构。输入是一个品种（或做价差的一对品种）+ 场所 + 参考日期；处理是抓取多个真实挂牌合约月
的价格、判别 contango/backwardation、计算斜率、估算展期收益、计算跨期与跨品种价差、补充库存
背景；产出是一份带来源与日期标注的事实性研究简报。

**为什么单独做这一个：** Pandadata **不覆盖海外期货**（其覆盖文档建议海外合约改用 Yahoo /
stooq / 交易所公开数据），因此本 skill **刻意不调用 Pandadata**，只用公开网页数据。它也与国内
期货 skill（`futures-deepview-analyst`、`futures-industrial-profit`、
`futures-cross-variety-corr`，读境内交易所/DeepView 数据）明确区分——**本 skill 专做海外商品、
公开数据**。

数据通过仓库自带的联网工具（Agent 的浏览器 / 抓取 / 搜索能力）读取公开网页，**不含任何 API Key
或付费数据源**。

## 🚀 快速开始

```bash
cp -r skill-global-commodity-term-structure ~/.claude/skills/global-commodity-term-structure
```

触发示例 prompt：

```text
帮我看看 WTI 原油（CL=F）当前的期限结构，是 contango 还是 backwardation，斜率多少
研究一下黄金 GC=F 的近月曲线并估算展期收益
Brent–WTI 价差和金银比现在是什么水平（用公开数据）
```

产出示例：一份 `outputs/term-structure-<symbol>-<date>.md` 简报（默认保存在本地、不入库）。
交付前可运行：

```bash
python scripts/validate_report.py outputs/term-structure-CL=F-2026-07-14.md
```

## 📦 目录结构

```text
skill-global-commodity-term-structure/
├── SKILL.md                       # 运行时入口：编号工作流 + 产出契约 + 边界
├── README.md                      # 中文优先说明（本文件）
├── README.en.md                   # English
├── LICENSE                        # GPLv3
├── agents/
│   └── openai.yaml                # OpenAI / Codex 适配（cursor-rule.mdc、portable-loader.md 由同步生成）
├── references/
│   ├── methodology.md             # 曲线构建、斜率/展期/价差公式、判别规则、坑与降级
│   ├── data-sources.md            # 场所清单、品种→符号映射、单位/货币、结算 vs 最新成交
│   └── source_boundary.md         # 可读 / 不可读数据边界
└── scripts/
    └── validate_report.py         # 报告结构校验器（stdlib，坏报告非零退出）
```

## 🔌 运行时兼容

以 `SKILL.md` 为统一入口，可在 **Claude Code、Codex、Cursor、Hermes、OpenClaw** 等运行时加载；
`agents/` 下提供各运行时适配文件（`cursor-rule.mdc`、`portable-loader.md` 由工作区同步脚本生成）。

## 📐 核心工作流（简）

1. 明确品种/场所/参考日期，先读边界与数据源文档。
2. 品种映射到公开符号（`CL=F`/`BZ=F`/`GC=F`/`HG=F`/`NG=F` 等），记录场所、货币、单位。
3. 抓取**≥2 个真实挂牌合约月**的价格（结算优先，标注结算 vs 最新成交与日期）。
4. 判别 contango/backwardation，计算年化斜率。
5. 估算展期收益（注明 roll 约定，仅为 carry 近似）。
6. 计算跨期价差与跨品种价差（Brent–WTI、金银比、简化 crack 代理等，注明公式与单位）。
7. 补充公开库存背景（EIA 石油、LME 库存），仅作定性色彩。
8. 产出事实性简报，每个数字带来源与日期标注。

详见 `references/methodology.md`。

## 📊 数据来源与依赖

- **交易所结算/产品页**：CME / COMEX / NYMEX / ICE / LME 公开页面。
- **Yahoo Finance**：连续/近月符号（`CL=F`、`BZ=F`、`GC=F`、`SI=F`、`HG=F`、`NG=F` …）及挂牌月。
- **stooq**：公开期货报价，做交叉校验/兜底。
- **公开库存**：EIA（石油）、LME 仓库库存。
- 依赖：仓库自带联网工具（浏览器/抓取/搜索）+ Python 标准库；`requires: []`（无姊妹 skill 依赖）。

## ⚠️ 限制与风险边界

- 仅覆盖**海外商品、公开网页数据**；不调用 Pandadata、无付费源、无 API Key。
- **一条曲线至少需要 2 个真实挂牌合约月**；绝不虚构或插值合约月——只有一个价格就如实说明并停止。
- **连续合约拼接会扭曲价位**（换月跳空）：使用连续序列时注明 roll 约定，拼接历史视为近似。
- 区分**结算价 vs 最新成交价**；尊重**各交易所货币与单位差异**，不静默混用单位。
- 库存背景为定性背景，非预测输入。
- 期限结构描述 carry，**不是价格信号**；仅供研究与教育，非官方、未认证、未验证。
- 外部写操作（保存/发布）需用户显式触发。

## 📄 免责声明

本仓库仅作研究方法层面的整理，为社区项目，非官方、不隶属任何被研究对象或交易所，不验证任何收益
声明，**不构成任何投资建议**。数据来自第三方公开来源，可能存在延迟、缺失或错误，使用者需自行核实
并承担全部决策与风险。

## 🧑‍🔧 维护者

Created or maintained by `abgyjaguo`.

## 📜 License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).

## 🐼 PandaAI / QUANTSKILLS 社群

<div align="center">
  <img src="https://raw.githubusercontent.com/quantskills/.github/main/profile/assets/pandaai-community-qr.jpg" alt="PandaAI 社群二维码" width="220">
  <br>
  <sub>扫码加入 PandaAI 社群，交流 QUANTSKILLS 技能、Agent 工作流与量化研究实践。</sub>
</div>
