# 🇭🇰 HK Stock Dossier — 港股尽职调查研报生成工具

基于 [Pandadata](https://pandadata.pandaaiquant.com/) 数据接口的港股尽职调查研报自动生成工具。

## 功能

覆盖 **九大维度** 的港股分析：

| 模块 | 内容 | 数据源 |
|------|------|--------|
| 公司概览 | 基本信息、行业分类、上市信息 | `get_hk_detail` |
| 行情与估值 | 最新行情、价量指标、阶段涨跌幅、Beta | `get_hk_daily`, `get_stock_pv_indicator` |
| 财务分析 | 估值指标、盈利能力、成长能力、财务健康、行业中位数对比 | `get_fina_statement`, `get_stock_mktfin_indicator`, `get_stock_industry_median` |
| 分红与股本 | 分红历史、配售/增发/锁定期事件 | `get_stock_dividend_event`, `get_stock_market_event` |
| 股东结构 | 投资者集中度、前20大股东、持股变动 | `get_stock_investor_concentration`, `get_stock_top20_concentration`, `get_stock_shareholder_holding` |
| 内部人交易 | 董监高增减持记录 | `get_stock_insider_trade` |
| 市场机构观点 | 目标价一致预期、买卖建议分布 | `get_stock_ncycl_consensus`, `get_stock_recommendation_consensus` |
| 公司事件日历 | 会议、财务披露、IR 活动 | `get_stock_meeting_event`, `get_stock_financial_event`, `get_stock_ir_event` |
| 风险提示 | 自动识别的 Beta、估值、杠杆、流动性、集中度风险 | — |

## 快速开始

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置 Pandadata 凭证

```bash
export DEFAULT_USERNAME="your_username"
export DEFAULT_PASSWORD="your_password"
export JAVA_SERVICE_BASE_URL="http://pandadata.pandaaiquant.com"
```

或使用提供的配置脚本：

```bash
python scripts/setup_runtime.py
```

### 3. 生成研报

```bash
# 生成腾讯控股研报，输出到终端
python -m hk_dossier 0700.HK

# 保存到文件
python -m hk_dossier 0700.HK --output tencent_report.md

# 简写代码（自动补齐 .HK 后缀）
python -m hk_dossier 0700

# 详细日志输出
python -m hk_dossier 0700.HK --verbose
```

## 输出示例

生成的研报为中文 Markdown 格式，包含完整的九大分析模块，以及与行业中位数的对比。

## 项目结构

```
hk-stock-dossier/
├── CLAUDE.md                     # 技能定义（供 Claude Code 使用）
├── pyproject.toml                # 项目配置
├── requirements.txt              # Python 依赖
├── README.md                     # 本文件
├── .gitignore
└── src/
    └── hk_dossier/
        ├── __init__.py
        ├── __main__.py           # CLI 入口
        ├── client.py             # Pandadata 客户端封装
        ├── core.py               # 协调器
        ├── renderer.py           # Markdown 渲染
        ├── utils.py              # 工具函数
        └── data/
            ├── __init__.py
            ├── profile.py        # 公司概况
            ├── market.py         # 行情数据
            ├── financials.py     # 财务数据
            ├── dividends.py      # 分红数据
            ├── shareholders.py   # 股东数据
            ├── insider.py        # 内部人交易
            ├── consensus.py      # 一致预期
            └── events.py         # 公司事件
```

## 作为 Claude Code Skill 使用

本项目的 `CLAUDE.md` 定义了技能行为。在项目目录中启动 Claude Code 即可使用：

```
# Claude Code 会自动加载 CLAUDE.md 中的技能定义
# 你可以直接要求：
"生成一份腾讯控股的港股研报"
```

## 数据来源

所有数据均通过 [Pandadata](http://pandadata.pandaaiquant.com/) 接口获取。

## License

MIT
