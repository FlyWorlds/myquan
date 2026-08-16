"""共用的构建契约、常量与 Panda 边界导入。"""

from __future__ import annotations


import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

try:
    from .panda_adapter import (
        PandaDataError,
        build_production_frame,
        clear_process_credentials,
        clear_checkpointing,
        configure_checkpointing,
        configure_from_environment,
        fetch,
        inspect_production,
        sdk_version,
        write_production,
    )
except ImportError:  # 支持直接执行：python scripts/build.py
    from panda_adapter import (
        PandaDataError,
        build_production_frame,
        clear_process_credentials,
        clear_checkpointing,
        configure_checkpointing,
        configure_from_environment,
        fetch,
        inspect_production,
        sdk_version,
        write_production,
    )


BUILD_ID = "Q51"
BUILD_NAME = "塞思·克拉曼特殊情况研究"
DATA_VERSION = "7.4.0"

REORGANIZATION_PATTERN = re.compile(
    r"重大资产重组|资产重组|借壳|吸收合并|发行股份购买资产|要约收购|私有化",
    re.I,
)
SPINOFF_PATTERN = re.compile(r"分拆上市|分拆.*子公司|spin.?off", re.I)
DISTRESS_PATTERN = re.compile(r"\*ST|ST|退市风险|特别处理|破产|重整", re.I)
PLACEMENT_UNLOCK_PATTERN = re.compile(r"定向增发|非公开发行|机构配售", re.I)
AUDIT_WARNING_PATTERN = re.compile(
    r"(?<!un)qualified(?:_opinion)?|adverse|disclaimer|unable|going.concern|material.uncertainty|"
    r"保留意见|否定意见|无法表示意见|持续经营|重大不确定",
    re.I,
)
NO_AUDIT_PATTERN = re.compile(r"no.audit|未审计|未经审计", re.I)
TRADE_DIRECTIVE_PATTERN = re.compile(
    r"建议(?:买入|卖出|开仓|平仓|加仓|减仓)|推荐(?:买入|卖出)|"
    r"应当(?:买入|卖出|开仓|平仓)|\b(?:buy|sell|go long|go short|position size)\b",
    re.I,
)

NET_PROFIT_FIELDS = [
    "is_n_income_attr_p",
    "is_n_income",
    "net_profit_parent",
    "np_parent_owners",
    "net_profit",
    "is_net_profit_parent",
]
OPERATING_CASH_FIELDS = [
    "cfs_net_cash_operating",
    "net_cash_flow_operating",
    "cfs_net_cashflow_operating",
    "cfs_cash_net_operating",
]


class InputValidationError(ValueError):
    pass
