# HK Stock Dossier Skill — 港股尽职调查研报生成

生成结构化港股尽职调查研报，数据来源为 Pandadata 接口，输出为中文 Markdown 研报。

## Trigger

当用户请求对某只港股生成研报/尽调报告/ dossier 时，加载本 skill。

## Workflow

1. 确认用户提供的港股代码（格式如 `0700.HK`、`0005.HK`、`9988.HK`）
2. 调用 `hk_dossier` 下的数据模块逐一获取数据
3. 按固定模板生成中文研报
4. 输出 Markdown 格式报告

## 研报模板结构

```
# ${股票名称}（${股票代码}）港股尽职调查报告
## 1. 公司概览
## 2. 行情与估值
## 3. 财务分析
## 4. 分红与股本
## 5. 股东结构
## 6. 内部人交易
## 7. 市场机构观点
## 8. 风险提示
## 9. 附录
```

## Usage

```bash
# 命令行生成研报
python -m hk_dossier 0700.HK --output report.md

# 或使用更简洁的入口
python src/hk_dossier/main.py 0700.HK
```

## Data Modules

| 模块 | 功能 | Pandadata 接口 |
|------|------|----------------|
| `data/profile` | 公司基本信息 | `get_hk_detail` |
| `data/market` | 行情与价量指标 | `get_hk_daily`, `get_stock_pv_indicator` |
| `data/financials` | 财务三表与比率 | `get_fina_statement`, `get_stock_mktfin_indicator`, `get_stock_industry_median` |
| `data/dividends` | 分红与市场活动 | `get_stock_dividend_event`, `get_stock_market_event` |
| `data/shareholders` | 股东集中度与持股 | `get_stock_investor_concentration`, `get_stock_top20_concentration`, `get_stock_shareholder_holding` |
| `data/insider` | 内部人交易 | `get_stock_insider_trade` |
| `data/consensus` | 一致预期与评级 | `get_stock_ncycl_consensus`, `get_stock_recommendation_consensus` |
| `data/events` | 公司会议与 IR 活动 | `get_stock_meeting_event`, `get_stock_financial_event`, `get_stock_ir_event` |

## Setup

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 Pandadata 凭证（两种方式）：
# 方式一：环境变量
export DEFAULT_USERNAME="your_username"
export DEFAULT_PASSWORD="your_password"

# 方式二：交互式配置
python scripts/setup_runtime.py

# 生成研报
python -m hk_dossier 0700.HK
```

## Notes

- 港股代码使用 `.HK` 后缀，如 `0700.HK`（腾讯控股）
- 数据时效性取决于 Pandadata 接口更新频率
- 本工具生成内容仅供参考，不构成投资建议
