# 🧩 Global Macro Rates FX Lab

**简体中文** | [English](README.en.md)

> 一句话定位：用**公开 FRED / 央行数据与公开外汇参考价**，加上 Pandadata 国际宏观（`get_macro_gb`），
> 把「海外/全球利率与外汇现在处于什么状态」整理成一份可溯源的事实型宏观格局简报——只描述，不给交易建议。

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)
![data](https://img.shields.io/badge/data-FRED%20%2F%20央行%20%2F%20Pandadata-orange)

## 📖 这是什么

这是一个**面向海外/全球市场（外盘）**的宏观利率与外汇研究 skill。它把一次「帮我看看海外利率 / 收益率曲线 /
美元和主要货币对 / 全球宏观周期」的请求，拆成固定的四步取证 + 事实归纳：

1. **发达市场利率综合体**：政策利率、2y/10y 主权债收益率、2s10s 曲线斜率、实际利率；
2. **美元与主要货币对**：以广义贸易加权美元（`DTWEXBGS`，DXY 代理）为锚，观察 EURUSD / USDJPY / GBPUSD 的方向与一致性；
3. **国际宏观层**：把 Pandadata `get_macro_gb`（宏观行业·国际宏观）委托给 `pandadata-api` skill 取数并对齐日期；
4. **格局归纳**：曲线陡峭/平坦/倒挂、实际利率升降、美元强弱、各证据是否相互印证——全部作为**观察**而非预测。

- **输入**：区域范围（美国必选，可加欧元区/日本/英国）、回看窗口、要利率还是外汇还是两者。
- **产出**：中文 Markdown 格局简报（概览 + 利率表 + 外汇表 + 国际宏观 + 一致性/背离 + 来源时效附录 + 免责声明）。
- **与姊妹仓库的区别**：`macro-monitor` 是 Pandadata 国内宏观（中国为主）、`macro-altdata-nowcast` 是中国另类数据；
  **本 skill 专做外盘/全球利率+外汇、以公开数据为主，Pandadata 只用 `get_macro_gb` 一个接口。**

## 🚀 快速开始

```bash
cp -r skill-global-macro-rates-fx-lab ~/.claude/skills/global-macro-rates-fx-lab
```

触发示例 prompt：

```text
看看当前美债收益率曲线（2s10s）和实际利率处于什么状态
美元和 EURUSD / USDJPY / GBPUSD 最近的方向一致吗？帮我做一份全球宏观格局简报
用公开 FRED 数据加 Pandadata 国际宏观，梳理一下海外利率与外汇的宏观周期
```

生成简报后，可用内置脚本校验结构：

```bash
python scripts/validate_report.py 你的简报.md
```

## 📦 目录结构

```text
skill-global-macro-rates-fx-lab/
├── SKILL.md                       # 运行时入口：规则 / 工作流 / 输出契约 / 边界
├── README.md                      # 中文优先说明（本文件）
├── README.en.md                   # English
├── LICENSE                        # GPLv3
├── agents/
│   └── openai.yaml                # 多运行时适配（cursor-rule.mdc / portable-loader.md 由工作区 sync 生成）
├── references/
│   ├── methodology.md             # 利率综合体与外汇计算、格局归纳、坑与降级
│   ├── data-sources.md            # 精确 series id、提供方、单位、频率、get_macro_gb 契约
│   └── source_boundary.md         # 可读 / 不可读的数据边界
└── scripts/
    └── validate_report.py         # stdlib-only 简报结构校验器（缺段落即非零退出）
```

## 🔌 运行时兼容

以 `SKILL.md` 为统一入口，可在 **Claude Code、Codex、Cursor、Hermes、OpenClaw** 等运行时加载；
`agents/` 下提供各运行时适配文件（`cursor-rule.mdc`、`portable-loader.md` 由工作区同步流程生成）。

## 🧮 数据来源与依赖

- **FRED 公开序列**：`DGS2`、`DGS10`、`T10Y2Y`（2s10s）、`DFII10`（10y 实际利率）、`DTWEXBGS`（广义美元指数代理）。
- **央行政策页（公开）**：美联储、ECB、日本央行、英格兰银行的当前政策利率与立场（只取事实）。
- **公开外汇参考价**：ECB 欧元参考汇率、公开汇率主机，用于 EURUSD / USDJPY / GBPUSD。
- **Pandadata `get_macro_gb`**（宏观行业·国际宏观）：**唯一使用的 Pandadata 接口**，实际取数委托给 `pandadata-api` skill
  （依赖：`skill-pandadata-api`）。本仓库不内置任何密钥。

## 📐 限制与风险边界

| 约束 | 说明 |
| --- | --- |
| 🌐 只用公开或用户提供的资料 | 见 `references/source_boundary.md`；不内置密钥、不抓取付费/私有数据 |
| 🕒 数据会滞后/修订 | FRED 日频序列可能滞后一到数个交易日并被修订，必须标注 as-of / vintage |
| 📏 单位是硬约束 | 收益率/利率用百分比；曲线利差需注明百分点或基点，1pp = 100bp，二者不可混用 |
| 💱 外汇报价方向 | EURUSD/GBPUSD 为美元/单位、USDJPY 为日元/美元；美元走强时前者下、后者上 |
| 📉 倒挂是观察不是预测 | `2s10s < 0` 只报为曲线状态，不翻译成衰退判断或交易 |
| 🚫 只述不荐 | 输出研究结构与事实归纳，不构成任何投资建议 |
| 🧭 领域边界 | 外盘/全球利率+外汇；国内宏观请用 `macro-monitor`、中国另类数据用 `macro-altdata-nowcast` |

**产物默认本地**：本仓库不提交生成的简报，运行结果默认保存在用户本地；`scripts/validate_report.py` 用于自查结构。

## ⚠️ 免责声明

本仓库仅作研究方法层面的整理，非官方、未经认证、不隶属任何被研究对象或央行，不验证任何收益声明。
收益率曲线倒挂、美元强弱、货币对走向等均为对公开数据的事实描述，**不构成任何投资建议**。
投资决策及其风险由用户自行承担。

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
