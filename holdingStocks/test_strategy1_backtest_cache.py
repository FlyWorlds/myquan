from unittest.mock import patch
import pandas as pd
from backtest.strategy1_pool_1m import run as engine


def test_refresh_keeps_older_minutes_and_normalizes_timezones(tmp_path):
    cached = pd.DataFrame({'ts': pd.to_datetime(['2026-10-26 15:00', '2026-10-27 15:00']),
                           'open': [1., 1.], 'high': [1., 1.], 'low': [1., 1.], 'close': [1., 1.]})
    cached.to_parquet(tmp_path / 'sh600330_1m.parquet')
    fresh = pd.DataFrame({'ts': pd.to_datetime(['2026-10-27 15:00', '2026-10-28 15:00']).tz_localize('Asia/Shanghai'),
                          'open': [2., 2.], 'high': [2., 2.], 'low': [2., 2.], 'close': [2., 2.]})
    with patch.object(engine, 'CACHE', tmp_path), patch.object(engine, 'pull_akshare_1m', return_value=fresh):
        result = engine._minutes('sh600330', refresh=True, source='ak')
    assert len(result) == 3
    assert result.close.tolist() == [1., 2., 2.]
    assert result.ts.dt.tz is None
