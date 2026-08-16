"""A 股巴菲特研究候选构建的稳定常量。"""

from __future__ import annotations

import re


BUILD_ID = "Q44"
BUILD_NAME = "A 股巴菲特长期复利组合"
DATA_VERSION = "9.4.0"
SCHEMA_VERSION = "3.0.0"
DEFAULT_INDEX = "000985.SH"
DEFAULT_UNIVERSE = "all_a"
V8_RULE_FREEZE_DATE = "20260719"
V8_FORWARD_START_DATE = "20260720"
V9_FORWARD_VALIDATION_START = "pending_materialization"
PORTFOLIO_RULE_REVISION = "20260720-quality-first-anti-dilution-5pct-v1"
V9_MAIN_BENCHMARK = "000985.SH"
V9_SECONDARY_BENCHMARK = "510300.SH"
V9_CASH_LEG = "511880.SH"

DEFAULT_THRESHOLDS = {
    "roe_current_min": 10.0,
    "roe_median_min": 12.0,
    "roe_floor_min": None,
    "gross_margin_min_pct": None,
    "gross_margin_std_max_pct": None,
    "capex_to_profit_max": None,
    "strict_buffett_gate": False,
    "cash_conversion_5y_min": 0.60,
    "cash_conversion_3y_min": None,
    "equity_cagr_5y_min": None,
    "owner_earnings_positive_ratio_min": None,
    "quality_exit_min": None,
    "debt_to_profit_max": 4.0,
    "normalized_pe_max": 30.0,
    "cash_earnings_yield_min": 0.03,
    "normalized_eps_years": 3,
    "share_dilution_5y_max": 0.05,
    "quality_score_min": 75.0,
    "bank_quality_score_min": 75.0,
    "bank_normalized_pe_max": 15.0,
    "bank_pb_max": 1.8,
    "bank_roa_current_min": 1.0,
    "bank_roa_median_min": 0.8,
    "bank_roa_floor_min": 0.6,
    "history_years": 10,
    "valid_years_min": 8,
    "missing_score_weight_max": 20.0,
    "quarterly_stale_days": 180,
    "liquidity_observation_days": 60,
    "liquidity_valid_days_min": 40,
    "liquidity_participation_max": 0.05,
    "opportunity_quality_gap": 5.0,
    "opportunity_qualitative_gap": 10.0,
    "opportunity_valuation_gap": 15.0,
    "opportunity_conviction_gap": 10.0,
}


# 经典巴菲特门槛预设：ROE ≥ 15% 且 10 年不跌破 12%、毛利率 ≥ 40% 且波动 < 10 个百分点、
# 资本开支/净利润 < 30%、长期负债 < 净利润 × 4、正常化 PE < 25。银行走独立 ROA 通道，
# 周期股由行业形态判定进入人工复核。启用后 `entry_eligible` 同时要求全部命中。
BUFFETT_STRICT_THRESHOLDS = {
    **DEFAULT_THRESHOLDS,
    "roe_current_min": 15.0,
    "roe_median_min": 15.0,
    "roe_floor_min": 12.0,
    "gross_margin_min_pct": 40.0,
    "gross_margin_std_max_pct": 10.0,
    "capex_to_profit_max": 0.30,
    "debt_to_profit_max": 4.0,
    "normalized_pe_max": 25.0,
    "strict_buffett_gate": True,
}

# Panda's current security-detail endpoint covers Shanghai/Shenzhen A shares;
# Beijing is deliberately rejected instead of being presented as covered.
A_SHARE_PATTERN = re.compile(r"^(?:\d{6})\.(?:SH|SZ)$", re.IGNORECASE)
BANK_PATTERN = re.compile(r"银行|bank", re.I)
FINANCIAL_PATTERN = re.compile(r"银行|证券|保险|多元金融|非银金融|bank|broker|insurance|non[- ]?bank", re.I)
CYCLICAL_PATTERN = re.compile(
    r"煤|钢铁|有色|化工|石油|采掘|航运|造纸|水泥|房地产|建筑材料|建筑装饰|建材|工程建设|基建|"
    r"coal|steel|mining|chemical|oil|shipping|paper|cement|real estate|building materials|construction",
    re.I,
)
# These sectors are not automatically rejected: the scoring layer combines
# the label with observed earnings cyclicality before routing to manual review.
AUTO_PATTERN = re.compile(r"汽车|工程机械|航空|旅游|automotive|heavy equipment|aviation|tourism", re.I)

# These fields have A-share statement semantics. Debt is deliberately limited
# to verified interest-bearing components and never falls back to total NCL.
FINANCIAL_FIELDS = [
    "symbol",
    "quarter",
    "date",
    "if_adjusted",
    "is_n_income_attr_p",
    "bs_total_hldr_eqy_exc_min_int",
    "bs_total_assets",
    "is_gross_profit",
    "is_revenue",
    "cfs_cash_paid_asset",
    "cfs_net_cashflow_operate",
    "cfs_net_cash_operating",
    "cfs_end_cash_equiv",
    "is_operate_profit",
    "is_total_profit",
    "is_income_tax",
    "bs_longterm_loan",
    "bs_bonds_payable",
    "bs_bond_payable",
    "bs_lease_liab",
    "bs_noncurrent_liab_due_1y",
    "bs_non_cur_liab_due_1y",
    "is_basic_eps",
]


class InputValidationError(ValueError):
    pass
