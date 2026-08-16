# A股超跌反弹

简体中文 | [English](README.en.md)

> QuantSkills 社区项目，由 GitHub 用户 `cikeqi` 维护。项目尚未经过独立审核，不代表 QuantSkills 官方认证，也不承诺收益或生产环境适用性。

独立交付版 A 股超跌反弹 Skill：严格只使用 PandaData，先做全市场 1–10 日反弹择时，再从沪深300、中证500或中证1000成分股中筛选候选。默认股票池为沪深300。

## 文件

- `SKILL.md`：Skill 触发说明和硬规则
- `scripts/oversold_rebound.py`：主程序
- `scripts/pandadata_source.py`：PandaData 认证、调用和溯源
- `scripts/indicators.py`：RSI/MACD/布林/ATR/量价指标
- `scripts/scoring.py`：五维市场评分、阶段判断和候选评分
- `references/`：方法和数据契约
- `tests/`：无未来数据、N/A 权重、国家队证据、否决条件测试

## 凭证

设置环境变量：

```bash
export PANDA_USERNAME='你的账号'
export PANDA_PASSWORD='你的密码'
```

或写入 `~/.pandadata/pandadata.env`：

```text
PANDA_USERNAME=你的账号
PANDA_PASSWORD=你的密码
```

文件夹内不包含任何账号、密码或 token。

## 快速运行

接口探测：

```bash
python3.11 scripts/oversold_rebound.py --probe-only
```

全市场择时 + 沪深300成分股选股（默认）：

```bash
python3.11 scripts/oversold_rebound.py --universe csi300 --top-n 20
```

切换股票池：

```bash
python3.11 scripts/oversold_rebound.py --universe csi500 --top-n 20
python3.11 scripts/oversold_rebound.py --universe csi1000 --top-n 20
```

脚本通过 PandaData `get_index_weights` 拉取分析日及之前的最新成分股快照，股票池约为 300/500/1000 只，并非只分析示例中的三只股票。

手工指定少量股票（会覆盖 `--universe`）：

```bash
python3.11 scripts/oversold_rebound.py \
  --symbols 000001.SZ 600519.SH 300750.SZ \
  --top-n 10
```

历史截止日：

```bash
python3.11 scripts/oversold_rebound.py \
  --as-of 20250115 \
  --universe csi500
```

## 示例问句

- 判断现在是不是情绪冰点，并从沪深300找 20 只超跌反弹候选。
- 用中证500股票池，筛选跌透但开始止跌的股票。
- 看看中证1000现在有没有反弹机会，列出评分最高的 30 只。
- 大跌之后能不能抄底？先判断市场阶段，再从沪深300选股。
- 截至 2025-01-15，用当时的中证1000成分股做一次扫描。
- 只分析 000001.SZ、600519.SH 和 300750.SZ 的短线反弹条件。

默认输出：

- `/tmp/oversold_rebound.json`
- `/tmp/oversold_rebound.md`

## 测试

```bash
python3.11 -m unittest discover -s tests -v
```

## 数据来源、假设与限制

- 数据来源：仅使用 PandaData；具体接口、字段与计算边界见 `references/`。
- 关键假设：收盘后生成的技术与市场信号最早在下一交易日观察；指数成分股采用分析日及之前的最新快照。
- 已知限制：技术超卖不等于反弹；ETF、指数或成交额异动只能作为代理证据；缺失指标保持为 N/A 并按可用权重归一化。
- 风险边界：输出仅供研究与教育，不构成投资建议、收益承诺、个股推荐或自动交易指令。

## 维护与许可

- 维护者：GitHub 用户 `cikeqi`
- 仓库：`quantskills/skill-oversold-rebound`
- 许可：[GNU GPL v3.0 only](LICENSE)（SPDX：`GPL-3.0-only`）
