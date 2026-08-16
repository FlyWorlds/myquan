# QuantSkills 已安装 Skill 目录

- 来源：https://github.com/quantskills
- 安装位置：`.cursor/skills/`（共 **147** 个可用 Skill）
- 缓存：`_quantskills_cache/`（可删；已加入 `.gitignore`）
- 未装上（上游缺失/空仓）：`skill-commodity-brief`（404）、`skill-stock-memory-analyzer-usa`（仅 README、无 SKILL.md）

完整表见下方；Agent 会按各 `SKILL.md` 的 description 自动匹配调用。


## 数据与接口

- **pandadata-api**：Pandadata and panda\_data Python SDK reference skill for selecting, calling, and troubleshooting quant data APIs.
- **pandadata-warehouse**：Pandadata warehouse skill for caching, refreshing, querying, and validating local DuckDB and Parquet market-data stores.
- **macro-monitor**：Macro monitoring skill for Pandadata macro data, economic calendars, industry prosperity, and high-frequency signals.
- **macro-altdata-nowcast**：Pandadata 宏观特色数据另类高频行业景气 nowcast skill：指标解码、同比环比、趋势、跨行业景气与官方数据领先观察。
- **fin-news**：实时财经资讯聚合 + AI 深度撰稿工具。
- **jq-to-panda-converter**：Batch convert JoinQuant platform strategies to PandaAI-compatible code. Understands strategy intent rather than line-by-line translation, supports single file and batch directory conversion, produces runnable backtest configs with a summary report.

## 市场复盘/监控

- **market-daily-review**：A-share end-of-day review skill covering indexes, valuation, breadth, sentiment, sectors, themes, and capital-flow clues.
- **daily-report**：是一个跨市场每日复盘技能，用于汇总 A 股、港股、美股、日经、韩国市场以及黄金、原油等公开行情数据，并结合板块表现、资金流向和重要新闻，生成结构化的 Markdown 市场复盘报告和次日情景分析。
- **a1-lhb-tracking**：A1 Longhubang event-tracking skill for ranking brokerage-seat activity, net buying and selling, and related market events from public data.
- **b6-limitup-pool**：涨停池动态管理 — panda-data BUILD 技能(B6)。每日维护涨停池，标记首板/连板数/炸板次数/回封时间，含题材分组/特殊形态/情绪面量化(分层晋级率·赚钱效应)，输出多维表格+HTML看板。
- **b7-lhb-monitor**：龙虎榜监控+席位标签库 — panda-data BUILD 技能(B7)。收盘后抓取龙虎榜，席位标签匹配(北向/机构/游资/量化)，生成次日关注清单；个股详情页按上榜原因拆买卖营业部，支持区间统计与交互式HTML看板(搜索/筛选/排序/展开详情)。
- **block-trade-radar**：A-share block-trade discount/premium radar skill
- **northbound-margin-monitor**：A-share northbound capital + margin trading + futures panorama monitor with 25 signal detectors
- **capital-flow-crowding-monitor**：跨市场资金面/拥挤监测：融资融券+北向持股+大宗交易三源聚合，一致性/背离信号 + 拥挤度历史分位
- **event-risk-alert**：A-share event-risk alert skill for watchlists, holdings, unlocks, pledges, reductions, ST changes, forecasts, audit opinions, and traceable reports.
- **earnings-season-tracker**：Whole-market A-share earnings-season scanner covering forecast-type distribution, beat/miss leaders, industry earnings prosperity, and audit-opinion watchlists.
- **regulatory-risk-radar**：A股合规/监管风险雷达：解禁·减持·质押·举牌·冻结·停牌·ST 七类风险聚合分级
- **a-share-market-risk-radar**：A股市场风险雷达：监测技术面、资金流、宏观环境、解禁与行业轮动等市场风险
- **smart-money-profiler**：Identify the capital actors behind A-share trades and profile their cross-period behavior using Pandadata seat, northbound, margin, and block-trade data.
- **post-market-screener**：Daily A-share post-market screener: 8 technical pattern detectors x capital inflow filter with LLM analysis
- **concept-rotation-monitor**：Community Draft: A-share concept and theme momentum, breadth, and rotation monitor.
- **buyback-monitor**：Community Draft: A-share buyback lifecycle, purpose, and intensity research monitor.
- **refinancing-monitor**：Community Draft: A-share refinancing lifecycle, pricing, dilution, and break-issue monitor.
- **holder-structure-scan**：Community Draft: A-share holder structure and ownership-concentration research scan.
- **dividend-yield-scan**：Community Draft: A-share dividend yield, continuity, and payout-quality research scan.
- **institutional-research-tracker**：Community Draft: A-share institutional research activity and attention monitor.
- **etf-arbitrage-monitor**：ETF 一二级套利/折溢价监控：IOPV vs 二级价折溢价、申赎篮子可行性、套利方向与扣费毛收益

## 个股/组合研究

- **a-share-stock-dossier**：A-share stock dossier skill that uses Pandadata to produce company, financial, dividend, shareholder, and risk analysis.
- **hk-stock-dossier**：生成结构化港股尽职调查研报，输出为中文 Markdown 研报。
- **stock-screener**：Natural-language A-share stock screener skill that maps fundamentals, dividends, valuation, pledges, northbound flows, sectors, holders, and risk filters to Pandadata calls.
- **portfolio-checkup**：Portfolio-level checkup skill that uses Pandadata to aggregate single-stock signals into portfolio structure, concentration, weighted valuation/quality, risk exposure, and benchmark deviation.
- **portfolio-optimize**：Turn an alpha signal into optimal portfolio weights under real constraints. Use when a user has factor scores / expected returns and wants portfolio weights, or asks about mean-variance / risk-parity / minimum-variance...
- **portfolio-attribution**：把主动收益分解为行业配置、个股选择、交互效应（Brinson-Fachler + Carino 多期链接）与因子贡献
- **portfolio-pnl-attribution**：skill 收益归因：证券贡献、行业贡献、费用、基准和主动收益，并做日度 P&L 对账
- **portfolio-liquidity-stress-test**：Stress portfolio liquidation capacity, pro-rata redemption shortfalls, and spread plus square-root impact costs.
- **investment-decision**：Given a company name or ticker, generate a long-term (6-18 month) BUY/NEUTRAL/SELL investment decision report with confidence, charts, and sources in .docx format — self-contained, uses public data.
- **audit-opinion-scanner**：从审计意见、财务报表、行业对标三个维度对 A 股做全面财务健康评估。涵盖审计意见扫描、25项财务科目缓存、15项比率计算、行业分类对标、5维快速评分、8段深度分析、综合风险检测。
- **munger-mental-model**：Munger 5-维模型与一票否决的多角度cross-validation分析工具，面向 A 股。支持单票和行业批筛。
- **buffett-moat-screener**：面向 A 股与美股的巴菲特式研究 Skill：研究建议、持仓复核、年度记录与点时回测。
- **keynes-contrarian-investment**：凯恩斯长期预期与反共识投资研究：识别过度乐观、过度悲观、预期差及价值陷阱
- **klarman-special-situations**：基于克拉曼特殊情况投资框架的 A 股事件驱动研究 Skill，覆盖定增解禁、重组借壳、分拆上市与困境反转；强调证据核验、失败价值与风险边界。
- **news-sentiment-analyst**：A-share financial news sentiment analyst - Claude Code Skill

## 因子研究流水线

- **factor-mine**：Disciplined factor-mining workflow for hypothesis design, implementation, validation, iteration notes, acceptance, and rollback decisions.
- **factor-evaluate**：Single-factor evaluation skill covering rank IC, Pearson IC, Sharpe, drawdown, monotonicity, turnover, and composite scoring.
- **factor-debug**：Factor debugging playbook for NaNs, signal validation failures, look-ahead bias, horizon mismatch, checksum drift, and correlation violations.
- **factor-review**：Factor-library review skill for experiment logs, acceptance rates, score dynamics, factor-family structure, correlations, and research recommendations.
- **factor-blend**：Multi-factor blending skill for deduplicating evaluated signals, combining weights, and re-evaluating one composite signal with diagnostics.
- **factor-decay**：Factor-decay analysis skill for comparing IC, turnover, and group-return decay across holding horizons to judge signal shelf life.
- **factor-orthogonalize**：Factor-orthogonalization skill for stripping industry, size, style, and legacy-factor exposures from daily cross-sectional signals.
- **factor-optimize**：Factor-optimization skill for sweeping parameters, running component ablations, and refining existing stock or futures factors with a keep-or-replace conclusion.
- **factor-idea-generation**：Generate initial stock alpha ideas with economic rationale and concrete factor shapes, defaulting to daily OHLCV when no fields are specified.
- **factor-ranking-sage**：Rank and select quantitative model factors from local factor and label CSV files with one of two self-contained methods: deterministic regression mRMR using F-statistic relevance and Pearson redundancy, or fixed-model...
- **factor-pool-evolution**：One-round CogAlpha-style factor-pool recommendation workflow that prepares mutation and crossover prompt packs for the current model, then evaluates generated candidate factors by RankIC and RankICIR to recommend next-round seeds.
- **factor-grouped-wrapper**：通过分组贪心wrapper，迭代删除或加入因子，并以模型训练和回测表现筛选最优因子池。
- **factor-alpha191-alpha101**：Factor-library skill for computing Alpha101 and Alpha191 values from long-form OHLCV CSV data, with wide CSV outputs and skipped-factor summaries for downstream research.
- **factor-backtest**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **ic-analysis**：Multidimensional IC diagnostics for rank versus Pearson IC, IC decay, subsample IC, top-basket stability, and cumulative IC timelines.
- **fundamental-factor-analysis**：Compute, validate, and analyze A-share fundamental factors. Covers value (EP/BP/SP/CP/FCFP/GP/A), quality (ROE/ROA/gross margin/accruals/leverage), growth (earnings growth/revenue growth/analyst revision) and composite factors. Uses Pandadata financial APIs with IC analysis, grouped returns, and Fama-MacBeth regression for validation.
- **residual-guided-factor-selection**：基于样本外残差IC和LightGBM增量重训练，筛选具有互补信息的候选因子
- **factormad-debate-factor-mining**：FactorMAD multi-agent debate skill for exploring stock alpha factors through public hypotheses, code generation, and validation loops.
- **quant-factor-skill-factory**：Factory skill for turning OHLCV alpha ideas into QuantSkills factor skills with real-market validation and packaging.
- **quant-factor-directional-alpha**：Directional OHLCV alpha factor library with 296 trend, breakout, reversal, and channel-position factor Skills validated on real market data.
- **quant-factor-risk-pattern-alpha**：Risk-state and chart-pattern OHLCV alpha factor library with 288 factor Skills for volatility, K-line shape, shock, drawdown, and pressure analysis.
- **quant-factor-volume-stat-alpha**：Volume, volume-price, ranking, and statistical OHLCV alpha factor library with 216 factor Skills validated on real market data.
- **doc-to-alphas**：Generate OHLCV alpha expressions from document text, with a formula contract and toy-data validation.
- **ml-factor-ensemble**：ML 因子集成：LightGBM/ElasticNet/Ridge + Purged & Embargoed 滚动 walk-forward 防泄漏，OOS 元信号
- **model-hpo-evidence-driven**：面向量化多因子模型的 evidence-driven 超参数优化 Skill，通过固定训练验证流程、记录 trial 级别实验证据，并引入 LLM 对搜索空间进行自适应调整，用于提升 LGBM、MLP 等模型超参数搜索的系统性、可解释性和可复现性。

## 回测与风控

- **backtest**：Standard cross-sectional long-only backtest protocol with T+1 execution, fees, limit filters, NAV curves, IC, drawdown, and diagnostic charts.
- **backtest-overfit**：Detect backtest overfitting and selection bias from multiple testing. Use when a user has a backtest / factor result and asks whether the Sharpe is real, whether a strategy is overfit, or wants to validate results...
- **backtesting-bias-avoidance**：回测引擎构建与偏差规避Build a correct, look-ahead-free backtest and audit a strategy for the biases that make backtests lie — look-ahead bias, survivorship bias, overfitting and data-snooping — while modeling realistic transaction costs and validating with out-of-sample and walk-forward testing and a full set of performance metrics.
- **numerical-leak-check**：当 agent 需要检查时间序列计算、量化因子、特征工程、标签生成、回测信号或研究管线是否存在未来信息泄露时使用。Use this skill for numerical causality checks, lookahead/future-leakage detection, prefix replay, future mutation, batch checking many factors or cases, and...
- **risk-model**：Build a Barra-style structural multi-factor risk model and attribute portfolio risk. Use when a user wants a covariance matrix for optimisation, asks how risky a portfolio is, where its risk comes from (which factors /...
- **walk-forward-validator**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **signal-stability-audit**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **transaction-cost-analysis**：交易成本分析(TCA)：implementation shortfall 五项分解 + VWAP/TWAP/arrival 对标
- **transaction-cost-calibration**：skill基于成交、历史盘口或 OHLCV 校准手续费、点差、滑点和参与率冲击成本，区别于已有的组合流动性压力测试
- **strategy-tearsheet-report**：策略绩效 tearsheet：全套风险调整指标 + 自包含 HTML 看板
- **brinson-performance-attribution**：Brinson-Fachler / BHB 归因 + Carino 多期链接
- **survivorship-universe-auditor**：Audit point-in-time universe membership, security lifecycles, stable identities, and missing delisting returns before backtesting.
- **corporate-action-adjustment-auditor**：Audit split and cash-dividend consistency across raw and adjusted equity prices before research or backtesting.
- **futures-roll-auditor**：Audit continuous futures contract selection, roll events, same-day price gaps, and adjustment ledgers before research or backtesting.
- **intraday-data-quality-auditor**：Audit normalized intraday OHLCV data for timestamp, gap, price, volume, and trading-date defects before research or backtesting.
- **a-share-pit-fundamental-vintage-builder**：A 股 PIT 财务数据审计：\*\*还原历史可见财报，而非使用今天的最新版。
- **forecast-calibration-audit**：skill评估概率预测的可靠性、Brier Score、Log Loss、ECE/MCE、校准斜率和时间漂移，区别于已有的因子 IC 评估和盈利预告扫描

## 期货/期权/宏观

- **futures-deepview-analyst**：Futures DeepView analyst skill for position seats, basis, inventory, term structure, and calendar-spread signals from Pandadata.
- **options-vol-analyst**：Options volatility analyst skill for option chains, implied volatility, realized volatility, IV percentiles, term structure, skew, and volatility-premium reports.
- **option-strategy-builder**：期权策略构建器：7 种结构（垂直价差/跨式/宽跨式/领口/日历/备兑/自定义）选腿+损益图+盈亏平衡+净希腊字母+保证金，BS 用 math.erf 纯标准库补算
- **ag-futures-seasonality**：农产品期货月度季节性分析工具:算清各月历史涨跌规律与显著性,叠加作物日历,出可视化报告。
- **commodity-carry-cta**：商品期货横截面 CTA 因子库：carry/时序动量/横截面动量/基差动量/库存，主连接续 + 多空品种轮动回测
- **oil-brief**：生成原油简报，数据来源为 Pandadata 期货接口、美国能源信息署（EIA）开放 API、OPEC 月度报告、雅虎财经等，输出为中文 Markdown 简报。
- **global-commodity-term-structure**：Research overseas commodity futures term structure, roll yield, and cross-commodity spreads from public data.
- **global-macro-rates-fx-lab**：Study global rates, FX, and macro regime from public FRED/central-bank data and Pandadata international macro.
- **global-macro-trend-strategy**：Turn an overseas commodity/macro/FX signal into a framework-neutral, backtestable research strategy.
- **market-regime-analysis**：结合指数数据、宏观指标、期货期限结构和波动率聚集特征，对 A 股市场进行状态划分与状态感知的策略构建。
- **dalio-all-weather**：Build and audit reproducible, research-only A-share All Weather allocations with PandaData, growth-inflation regimes, inverse-volatility risk budgets, quarterly backtests, and risk-contribution diagnostics.
- **alpha-f1-position-change**：当需要开发、计算、验证期货前20席位持仓突变因子时，使用此 skill。支持多空持仓优势分析、主力调仓方向判断。
- **alpha-f5-member-position-concentration**：Use when researching or validating the F5 commodity futures member-position concentration factor in a local Panda data environment.
- **alpha-f6-family-position-reverse**：Use when researching or validating the F6 commodity futures family-position reverse factor in a local Panda data environment.
- **alpha-f8-family-main-divergence**：Use when researching or validating the F8 commodity futures broker-position divergence factor in a local Panda data environment.
- **cb-analyzer**：A-share convertible bond daily analyzer: double-low strategy + Black-Scholes Greeks + IC backtest

## 交易执行/仓位

- **b11-auto-stop-loss-take-profit**：当需要对 A 股和期货持仓做自动止盈止损与仓位管理时，使用此 skill。支持次日高开止盈、次日低开止损、持仓满2交易日强平、单票名义仓位上限控制。交易日历唯一来源 = panda\_data.get\_trade\_cal（硬依赖）。
- **b12-intraday-position-manager**：当需要对日内多品种持仓做动态仓位管理时，使用此 skill。支持 A股/A股ETF/股指期货/商品期货/港股+ETF；区分 T+1/T+0、昨仓/今仓、保证金/现金，输出标准 8 字段调仓指令。
- **ssquant-ai-trader**：SSQuant AI Trader skill for converting natural-language trading descriptions into automated or semi-automated strategy workflows.
- **ssquant-trader-generator**：Trader-generator skill that turns natural-language trading ideas into deployable AI Trader rules, code, and operating plans.
- **quant-execution-microstructure**：QuantSkills community project; maintainers should add an accurate one-line summary.

## 海外/另类

- **hk-us-insider-radar**：HK/US insider trading signal radar skill
- **hk-us-consensus-radar**：Community Draft: HK/US sell-side consensus ratings, targets, and revision research.
- **hk-us-consensus-revision-radar**：Hong Kong & US Consensus Revision Radar: Uses PandaData to analyze target prices, ratings, price divergence, analyst coverage, and revision trajectories, generating auditable offline HTML research reports.
- **hk-us-dividend-events**：Community Draft: HK/US dividend event calendar, yield, and DRIP research workflow.
- **hk-us-quote-scan**：Community Draft: HK/US quote, liquidity, return, and valuation research snapshots.
- **us-sector-rotation**：Community Draft: US equity sector return, valuation, and rotation research monitor.
- **us-sec-edgar-harvester**：Harvest and structure US SEC EDGAR public filings into a deduplicated, sourced, time-lined dataset.
- **overseas-equity-factor-miner**：Discover and validate cross-sectional alpha factors for HK/US equities by IC, decay, and turnover.
- **cross-listing-parity**：Community Draft: A/H and China ADR cross-listing parity research monitor.
- **gaetano-crux-capital-research-model**：Research-model skill for public-material analysis of photonics, optical networking, Physical AI, and AI infrastructure themes.
- **serenity-research-model**：Research-model skill for reconstructing Serenity-style AI, semiconductor, and supply-chain theses from public posts and datasets.
- **x-trader-builder**：Skill-builder workflow for turning public X/Twitter data and user materials into trader-specific research-model skills.
- **gao-shanwen-research-model**：Codex skill for Gao Shanwen bibliography and public article research workflow

## 平台/工程

- **pandaai-workflow-generator**：根据自然语言量化想法生成可一键导入 PandaAI 的工作流 JSON：LiteGraph 节点连线、内嵌 Python 策略/因子代码、成本与回测参数注入
- **pandaai-workflow-audit**：像代码评审一样审计 PandaAI 工作流文件：图结构、策略与因子代码、数据时序、参数自由度、回测假设与验证证据，逐条给出缺陷与优化方案
- **pandaai-factor-online**：PandaAI 因子大赛上手与在线挖掘技能：环境体检、登录、字段算子速查、可续跑批量回测与成本折算复盘 · Onboarding and online factor mining for PandaAI
- **paper-replication**：Framework-neutral quantitative paper replication skill for research scripts, backtests, charts, and auditable outputs.
- **report-replication**：Quant report replication skill that turns papers or reports into Chinese translations, factor formulas, validation reports, and strategy assets.
- **quant-research-replication**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **quant-research-experiment-registry**：Quantitative research experiment registry and reproducibility audit skill.
- **template**：Template repository for initializing QuantSkills skill projects with SKILL.md, README files, licensing, and baseline adapters.
- **time-series-analysis**：Time-series analysis skill focused on feature inspection, statistical diagnostics, and research workflow organization.
- **xingtai-catcher**：Pattern-search skill for finding similar A-share stock and futures K-line setups from text, screenshots, or hand drawings, with scored candidates and result links.
- **qbti**：QBTI（平凡人策略）：五组问答把投资性格翻译成因子方向与策略参数，交给 QuantSkills 因子库与回测流水线
- **dl-gnn-stock-graph**：当需要对 A 股市场进行 GNN 量化选股时，使用此 skill。支持多层异构图（申万 L1/L2/L3 行业 + 概念板块 + 机构持仓 + DTW 形态相似 + Pearson 相关性）构建、GATs\_ts 与 MF-IAMGCN 双模型架构、五维特征工程（量价/基本面/情绪/宏观/关系）、TopK 选股策略、完整 A 股回测引擎（含 T+1/涨跌停/佣金+印花税+滑点模拟）。
- **etf-fund-evaluator**：境内股票指数ETF评价与同类比较：分析跟踪质量、风险收益、流动性、规模和资金流

## 其他

- **alpha-a06-hotmoney-reversal**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **alpha-ncav-graham**：Graham NCAV 净流动资产折价因子技能。A股深度价值筛选，排除金融股，计算 NCAV 折价并生成 buy/sell/hold 信号。
- **build-b10-factor-evaluation**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **calendar-anomaly-scanner**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **factor-mining-pandaai**：Community skill for extracting paper-derived quant factors and analyzing them with PandaAI
- **index-rebalance-event-study**：Run reproducible index addition, deletion, and weight-change event studies around announcement or effective-date anchors.
- **index-valuation-rotation**：Index valuation and A-share industry rotation skill for PE/PB percentiles, valuation temperature, broad-index references, momentum ranks, and rotation summaries.
- **ma-crossover-signal**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **oversold-rebound**：A股超跌反弹择时与选股：判断短期反弹环境并筛选候选股票
- **pair-correlation**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **quant-portfolio-risk**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **quant-research**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **risk-return-metrics**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **rolling-beta-exposure**：QuantSkills community project; maintainers should add an accurate one-line summary.
- **simons-pairs-trading**：Screen and audit reproducible, research-only A-share pairs with adjusted PandaData prices, same-industry Engle-Granger tests, Benjamini-Hochberg FDR, formation-only clustering, rolling backtests, conservative gates, and...
- **statistical-arbitrage-time-series**：统计套利与时间序列建模 Generate a sourced, reproducible statistical-arbitrage research dossier from a candidate pair, basket, or asset universe, covering data preparation, pair selection, cointegration and stationarity testing (train-window ADF + KPSS), spread modeling with hedge-ratio stability, mean-reversion estimation, z-score signal construction
