"""panda_data 通用磁盘缓存层。

规避套餐限额：同一 (接口名, 参数指纹) 只请求一次，之后从磁盘 parquet 读取。
缓存放在 `output/panda_cache/`，可以随时删除以强制重拉。

仅用于长周期回测的"一次拉全、多次消费"场景；实盘请勿依赖。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


CACHE_DIR = Path(__file__).resolve().parents[1] / "output" / "panda_cache"


def _fingerprint(name: str, kwargs: dict[str, Any]) -> str:
    def _norm(v: Any) -> Any:
        if isinstance(v, (list, tuple)):
            return sorted(str(x) for x in v)
        return v

    payload = {k: _norm(v) for k, v in sorted(kwargs.items())}
    encoded = json.dumps({"name": name, "kwargs": payload}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def cached_call(name: str, **kwargs: Any) -> pd.DataFrame:
    """调用 panda_data.<name>(**kwargs)，结果落 parquet 缓存。"""
    fp = _fingerprint(name, kwargs)
    path = CACHE_DIR / f"{name}-{fp}.parquet"
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] read failed {path.name}: {exc}", file=sys.stderr)

    import panda_data

    fn = getattr(panda_data, name, None)
    if fn is None:
        raise RuntimeError(f"panda_data has no {name}")
    df = fn(**kwargs)
    if df is None:
        df = pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[cache] write failed {path.name}: {exc}", file=sys.stderr)
    return df
