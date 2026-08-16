---
name: skill-hk-stock-dossier
description: >
  生成结构化港股尽职调查研报（Due Diligence Dossier），覆盖公司概览、业务分析、
  行情估值、财务分析、分红股本、股东结构、内部人交易、机构观点、券商研报、
  公司事件、风险提示及尽调结论十二大维度。数据来源为 Pandadata 接口。
metadata:
  organization: quantskills
  repository: skill-hk-stock-dossier
  project_type: skill
  category: analytics
  tags:
    - hk-stock
    - dossier
    - due-diligence
    - pandadata
    - hong-kong
    - chinese
  platforms:
    - claude-code
  status: beta
  maintainer: xixihaha-dzh
  contributors:
    - xixihaha-dzh
  upstream: https://github.com/quantskills/skill-hk-stock-dossier
---

# HK Stock Dossier — 港股尽职调查研报生成

生成结构化港股尽职调查研报，数据来源为 Pandadata 接口，输出为中文 Markdown 研报。

## 功能特性

- **12 维度深度覆盖**：公司概览 → 业务分析 → 行情估值 → 财务分析 → 分红股本 → 股东结构 → 内部人交易 → 机构观点 → 券商研报 → 公司事件 → 风险提示 → 尽调结论
- **并行数据抓取**：8 个数据模块并行调用 Pandadata API，生成效率提升 3-5 倍
- **智能估值计算**：自动从财务报表计算 PE/PB/毛利率/净利率/ROE 等关键指标
- **图表可视化**：可选生成股价走势图和成交量图
- **券商研报集成**：内置精选券商研报数据库，覆盖中金、中信、星展、高盛等主流机构观点
- **专业尽调结论**：基于信号评分体系自动生成偏积极/中性/偏谨慎的综合评估
- **PDF 输出**：支持 Markdown → PDF 一键转换

## 使用方式

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 Pandadata 凭证（.env 文件）
echo "DEFAULT_USERNAME=your_username" > .env
echo "DEFAULT_PASSWORD=your_password" >> .env

# 生成研报（带图表）
python -m hk_dossier 0700.HK --output report.md --charts

# 简写代码（自动补齐 .HK）
python -m hk_dossier 0700 --output report.md --charts

# 生成 PDF
python -m hk_dossier 0700 --output report.md --charts --pdf
```

## 研报模板（12 章）

```
# ${股票名称}（${股票代码}）港股尽职调查报告
## 一、公司概览
## 二、业务分析
## 三、行情与估值
## 四、财务分析
## 五、分红与股本动作
## 六、股东结构
## 七、内部人交易
## 八、市场机构观点
## 九、券商研报观点
## 十、公司事件日历
## 十一、风险提示
## 十二、尽调结论
```

## 数据模块映射

| 模块 | 功能 | Pandadata 接口 |
|------|------|----------------|
| `data/profile` | 公司基本信息 | `get_hk_detail` |
| `data/research` | 业务分析 + 券商研报 | 精选数据库（年报/公告/公开资讯） |
| `data/market` | 行情与价量 | `get_hk_daily`, `get_stock_pv_indicator` |
| `data/financials` | 财务三表 + 估值计算 | `get_fina_statement`, `get_stock_mktfin_indicator`, `get_stock_industry_median` |
| `data/dividends` | 分红与市场活动 | `get_stock_dividend_event`, `get_stock_market_event` |
| `data/shareholders` | 股东集中度与持股 | `get_stock_investor_concentration`, `get_stock_top20_concentration`, `get_stock_shareholder_holding` |
| `data/insider` | 内部人交易 | `get_stock_insider_trade` |
| `data/consensus` | 一致预期与建议 | `get_stock_ncycl_consensus`, `get_stock_recommendation_consensus` |
| `data/events` | 公司会议与 IR | `get_stock_meeting_event`, `get_stock_financial_event`, `get_stock_ir_event` |
| `charts.py` | 图表生成 | matplotlib（需安装） |

## 技术栈

- Python >= 3.10
- Pandadata SDK（数据源）
- matplotlib（图表）
- python-dotenv（配置管理）

## 重要限制

- 数据时效性取决于 Pandadata 接口更新频率
- 港股 `get_fina_statement` 接口偶发 504 超时（自动重试短日期范围）
- 部分港股 PE/PB 数据需从财务报表自行计算（Pandadata mktfin 接口对港股支持有限）
- 业务分析数据为精选数据库，非实时自动抓取
- 本工具生成内容仅供参考，**不构成投资建议**

## 维护者

- Organization: [QUANTSKILLS](https://github.com/quantskills)
- Maintainer: [xixihaha-dzh](https://github.com/xixihaha-dzh)
- 项目地址: [skill-hk-stock-dossier](https://github.com/quantskills/skill-hk-stock-dossier)
