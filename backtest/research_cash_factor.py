"""A股空仓避险因子挖掘与样本内外回测系统 (2020 - 2026)

样本内 (IS): 2020-01-01 ~ 2024-12-31 (调参与规则挖掘)
样本外 (OOS): 2025-01-01 ~ 2026-11-05 (泛化验证)

候选空仓因子:
1. Factor_DualMA: 指数双均线趋势破位 (MA20/MA60 死叉且低于 MA60)
2. Factor_Breadth: 全市场个股站上 MA20 广度占比 (<20% 恐慌空仓, >30% 恢复)
3. Factor_VolContraction: 缩量阴跌与恐慌放量破位
4. Factor_Composite: 多维复合防御空仓因子 (趋势破位 + 广度溃败)
"""

from __future__ import annotations
import glob
import os
import json
import time
from datetime import datetime
import numpy as np
import pandas as pd
import akshare as ak

# 1. 获取基准指数数据
def get_index_data(symbol='sh000852', name='中证1000'):
    cache_file = f'data_cache/index_{symbol}_daily.parquet'
    if os.path.exists(cache_file):
        df = pd.read_parquet(cache_file)
    else:
        print(f"正在拉取 {name} ({symbol}) 历史日线数据...")
        raw = ak.stock_zh_index_daily(symbol=symbol)
        raw['date'] = pd.to_datetime(raw['date']).dt.strftime('%Y-%m-%d')
        raw = raw.sort_values('date').reset_index(drop=True)
        raw.to_parquet(cache_file)
        df = raw
    return df

# 2. 构建全市场横截面广度指标 (Market Breadth)
def build_market_breadth():
    cache_file = 'data_cache/market_breadth_cross_section.parquet'
    if os.path.exists(cache_file):
        print("从缓存加载全市场广度数据...")
        return pd.read_parquet(cache_file)

    print("正在从 1100+ 只个股日线构建全市场广度数据 (2020-2026)...")
    files = glob.glob('data_cache/*_daily_qfq.parquet')
    stock_records = []
    
    for i, f in enumerate(files):
        try:
            df = pd.read_parquet(f)
            if df.empty or 'close' not in df.columns or len(df) < 60:
                continue
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            df = df.sort_values('date').reset_index(drop=True)
            df['ma20'] = df['close'].rolling(20).mean()
            df['ma60'] = df['close'].rolling(60).mean()
            df['above_ma20'] = (df['close'] > df['ma20']).astype(int)
            df['above_ma60'] = (df['close'] > df['ma60']).astype(int)
            
            # 过去20日新低
            df['low_20'] = df['low'].rolling(20).min()
            df['is_new_low'] = (df['close'] <= df['low_20']).astype(int)
            
            sub = df[['date', 'above_ma20', 'above_ma60', 'is_new_low']].dropna()
            stock_records.append(sub)
        except Exception:
            continue
        if (i + 1) % 200 == 0:
            print(f"  已处理 {i+1}/{len(files)} 只个股...")

    all_stocks = pd.concat(stock_records, ignore_index=True)
    grouped = all_stocks.groupby('date').agg(
        total_stocks=('above_ma20', 'count'),
        stocks_above_ma20=('above_ma20', 'sum'),
        stocks_above_ma60=('above_ma60', 'sum'),
        stocks_new_low=('is_new_low', 'sum')
    ).reset_index()

    grouped['breadth_ma20'] = grouped['stocks_above_ma20'] / grouped['total_stocks']
    grouped['breadth_ma60'] = grouped['stocks_above_ma60'] / grouped['total_stocks']
    grouped['new_low_ratio'] = grouped['stocks_new_low'] / grouped['total_stocks']
    
    # 过滤掉标的太少的前期日期
    grouped = grouped[grouped['total_stocks'] >= 100].sort_values('date').reset_index(drop=True)
    grouped.to_parquet(cache_file)
    print(f"全市场广度指标构建完成，共 {len(grouped)} 个交易日。")
    return grouped


# 3. 计算各类空仓信号
def generate_cash_signals(index_df, breadth_df):
    df = pd.merge(index_df, breadth_df, on='date', how='inner').sort_values('date').reset_index(drop=True)
    df = df[df['date'] >= '2019-01-01'].copy()

    # 指数技术指标计算
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ma60'] = df['volume'].rolling(60).mean()
    df['vol_ratio'] = df['vol_ma5'] / df['vol_ma60']

    # 真实波幅 ATR
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    df['atr_pct'] = df['atr14'] / df['close']
    df['atr_median'] = df['atr_pct'].rolling(60).median()

    # --- 因子 1: 双均线趋势空仓因子 (DualMA Gate) ---
    # 规则: 跌破 MA60 且 MA20 < MA60 则空仓; 重新站上 MA20 解除空仓
    signal_dual_ma = np.zeros(len(df), dtype=bool)
    in_cash = False
    for i in range(len(df)):
        c = df.loc[i, 'close']
        m20 = df.loc[i, 'ma20']
        m60 = df.loc[i, 'ma60']
        if pd.isna(m60):
            continue
        if not in_cash:
            if c < m60 and m20 < m60:
                in_cash = True
        else:
            if c > m20:
                in_cash = False
        signal_dual_ma[i] = in_cash
    df['cash_dual_ma'] = signal_dual_ma

    # --- 因子 2: 市场广度空仓因子 (Breadth Gate) ---
    # 规则: 全市场站上 MA20 股票比例 < 20% 时恐慌空仓; 回升至 > 32% 时解除
    signal_breadth = np.zeros(len(df), dtype=bool)
    in_cash_b = False
    for i in range(len(df)):
        b = df.loc[i, 'breadth_ma20']
        if pd.isna(b):
            continue
        if not in_cash_b:
            if b < 0.20:
                in_cash_b = True
        else:
            if b > 0.32:
                in_cash_b = False
        signal_breadth[i] = in_cash_b
    df['cash_breadth'] = signal_breadth

    # --- 因子 3: 量价萎缩与暴跌空仓因子 (Volume Contraction Gate) ---
    # 规则: 均线下方 + 缩量阴跌 (c < ma20 且 vol_ratio < 0.70) 或 放量大跌
    signal_vol = np.zeros(len(df), dtype=bool)
    in_cash_v = False
    for i in range(len(df)):
        c = df.loc[i, 'close']
        m20 = df.loc[i, 'ma20']
        vr = df.loc[i, 'vol_ratio']
        if pd.isna(vr) or pd.isna(m20):
            continue
        if not in_cash_v:
            if c < m20 and vr < 0.72:
                in_cash_v = True
        else:
            if c > m20 and vr > 0.85:
                in_cash_v = False
        signal_vol[i] = in_cash_v
    df['cash_volume'] = signal_vol

    # --- 因子 4: 多维复合防御空仓因子 (Composite Defensive Gate) ★ 推荐 ---
    # 核心哲学: 趋势破位 (Trend Broken) + 市场流动性/广度共振溃败 (Breadth Collapse)
    # 触发条件: (指数跌破 MA60) 且 (全市场站上 MA20 比例 < 28% 或 新低比例 > 15%)
    # 解除条件: (指数重新站上 MA20 且 市场广度回升至 35% 以上)
    signal_comp = np.zeros(len(df), dtype=bool)
    in_cash_c = False
    for i in range(len(df)):
        c = df.loc[i, 'close']
        m20 = df.loc[i, 'ma20']
        m60 = df.loc[i, 'ma60']
        b = df.loc[i, 'breadth_ma20']
        nl = df.loc[i, 'new_low_ratio']
        if pd.isna(m60) or pd.isna(b):
            continue
        if not in_cash_c:
            # 趋势与微观广度共振破位
            if (c < m60) and (b < 0.28 or nl > 0.15):
                in_cash_c = True
            # 或者单日发生极端流动性危机 (全市场站上20日线不足 12%)
            elif b < 0.12:
                in_cash_c = True
        else:
            # 企稳右侧入场: 站上20日线且广度恢复至35%以上
            if c > m20 and b > 0.35:
                in_cash_c = False
        signal_comp[i] = in_cash_c
    df['cash_composite'] = signal_comp

    return df


# 4. 收益回测模拟函数 (含资金曲线、最大回撤、交易成本)
def run_backtest(df, cash_col=None, cost_rate=0.0015):
    """
    cash_col: None 表示基准买入持有 (Buy & Hold)
              'cash_dual_ma' 等表示应用对应的空仓因子
    cost_rate: 每次切换仓位 (买入或卖出) 扣除的摩擦成本 (含佣金+印花税+滑点，单边 0.15%)
    """
    df = df.copy().reset_index(drop=True)
    df['ret'] = df['close'].pct_change().fillna(0)
    
    # 现金无风险年化收益率 1.8% (每日约 1.8% / 244)
    cash_daily_ret = 0.018 / 244

    # 信号次日生效 (避免未来函数 T+1 交易)
    if cash_col is None:
        pos = np.ones(len(df))
    else:
        # 当日盘后计算出空仓信号，次日执行
        pos = np.where(df[cash_col].shift(1).fillna(False), 0.0, 1.0)

    # 换手交易成本
    pos_change = np.abs(np.diff(pos, prepend=pos[0]))
    trade_costs = pos_change * cost_rate

    # 组合日收益率
    strategy_ret = pos * df['ret'] + (1.0 - pos) * cash_daily_ret - trade_costs
    df['strategy_ret'] = strategy_ret
    
    # 净值曲线
    df['nav'] = (1.0 + strategy_ret).cumprod()
    df['peak'] = df['nav'].cummax()
    df['drawdown'] = (df['nav'] - df['peak']) / df['peak']
    
    return df


# 5. 绩效统计函数
def compute_metrics(df):
    total_ret = df['nav'].iloc[-1] / df['nav'].iloc[0] - 1.0
    n_days = len(df)
    ann_ret = (1.0 + total_ret) ** (244.0 / n_days) - 1.0 if n_days > 0 else 0
    vol = df['strategy_ret'].std() * np.sqrt(244)
    max_dd = df['drawdown'].min()
    sharpe = (ann_ret - 0.018) / vol if vol > 0 else 0
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 0 else 0
    return {
        'total_ret': total_ret,
        'ann_ret': ann_ret,
        'vol': vol,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'calmar': calmar,
        'days': n_days
    }


def analyze_all():
    # 数据加载
    index_df = get_index_data('sh000852', '中证1000')
    breadth_df = build_market_breadth()
    data = generate_cash_signals(index_df, breadth_df)

    # 回测区间拆分
    is_mask = (data['date'] >= '2020-01-01') & (data['date'] <= '2024-12-31')
    oos_mask = (data['date'] >= '2025-01-01') & (data['date'] <= '2026-11-05')
    all_mask = (data['date'] >= '2020-01-01') & (data['date'] <= '2026-11-05')

    factors = {
        '基准 (买入持有)': None,
        '双均线趋势空仓 (DualMA)': 'cash_dual_ma',
        '市场广度空仓 (Breadth)': 'cash_breadth',
        '量能萎缩空仓 (Volume)': 'cash_volume',
        '多维复合防御空仓 (Composite ★)': 'cash_composite'
    }

    results = []
    
    for period_name, mask in [('样本内 (2020-2024)', is_mask), 
                              ('样本外 (2025-2026)', oos_mask), 
                              ('全周期 (2020-2026)', all_mask)]:
        sub_df = data[mask].copy().reset_index(drop=True)
        for fname, fcol in factors.items():
            bt = run_backtest(sub_df, cash_col=fcol)
            m = compute_metrics(bt)
            # 计算空仓天数比例
            if fcol is not None:
                cash_days = int(sub_df[fcol].sum())
                cash_ratio = cash_days / len(sub_df)
            else:
                cash_days = 0
                cash_ratio = 0.0

            results.append({
                'period': period_name,
                'factor': fname,
                'total_ret': m['total_ret'],
                'ann_ret': m['ann_ret'],
                'max_dd': m['max_dd'],
                'sharpe': m['sharpe'],
                'calmar': m['calmar'],
                'cash_ratio': cash_ratio
            })

    res_df = pd.DataFrame(results)
    print("\n" + "="*80)
    print("【空仓因子挖掘全量绩效对比表】")
    print("="*80)
    for p in ['样本内 (2020-2024)', '样本外 (2025-2026)', '全周期 (2020-2026)']:
        print(f"\n>>> 区间: {p}")
        sub = res_df[res_df['period'] == p]
        for _, row in sub.iterrows():
            print(f"  · {row['factor']:<28} | 收益: {row['total_ret']*100:+7.2f}% | 年化: {row['ann_ret']*100:+6.2f}% | 最大回撤: {row['max_dd']*100:6.2f}% | 夏普: {row['sharpe']:5.2f} | 卡玛: {row['calmar']:5.2f} | 空仓率: {row['cash_ratio']*100:4.1f}%")

    # 导出年度收益明细 (逐年对比)
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    yearly_records = []
    for y in years:
        y_mask = (data['date'] >= f'{y}-01-01') & (data['date'] <= f'{y}-12-31')
        sub = data[y_mask].copy().reset_index(drop=True)
        if len(sub) < 5:
            continue
        y_row = {'year': str(y)}
        for fname, fcol in factors.items():
            bt = run_backtest(sub, cash_col=fcol)
            m = compute_metrics(bt)
            y_row[f"{fname}_ret"] = m['total_ret']
            y_row[f"{fname}_dd"] = m['max_dd']
        yearly_records.append(y_row)

    yearly_df = pd.DataFrame(yearly_records)
    print("\n" + "="*80)
    print("【逐年收益对比: 基准 vs 复合空仓因子】")
    print("="*80)
    for _, r in yearly_df.iterrows():
        y = r['year']
        b_ret = r['基准 (买入持有)_ret'] * 100
        b_dd = r['基准 (买入持有)_dd'] * 100
        c_ret = r['多维复合防御空仓 (Composite ★)_ret'] * 100
        c_dd = r['多维复合防御空仓 (Composite ★)_dd'] * 100
        alpha = c_ret - b_ret
        print(f"  {y}年: 基准收益 {b_ret:+6.2f}% (回撤 {b_dd:6.2f}%) | 复合空仓收益 {c_ret:+6.2f}% (回撤 {c_dd:6.2f}%) | 超额: {alpha:+6.2f}%")

    # 典型历史避险案例分析
    print("\n" + "="*80)
    print("【重大历史下杀期避险实测分析 (复合空仓因子)】")
    print("="*80)
    crises = [
        ('2020年3月 全球流动性冲击', '2020-03-01', '2020-04-15'),
        ('2022年春 俄乌与封控单边主跌浪', '2022-01-01', '2022-04-28'),
        ('2022年秋 破位二次探底', '2022-07-01', '2022-10-31'),
        ('2023年下半年 持续单边阴跌', '2023-08-01', '2023-12-31'),
        ('2024年初 微盘股与流动性踩踏危机', '2024-01-02', '2024-02-08'),
        ('2025年 样本外震荡期', '2025-01-01', '2025-12-31'),
        ('2026年 样本外最新阶段', '2026-01-01', '2026-11-05'),
    ]
    for cname, sdate, edate in crises:
        c_mask = (data['date'] >= sdate) & (data['date'] <= edate)
        sub = data[c_mask].copy().reset_index(drop=True)
        if len(sub) == 0:
            continue
        base_bt = run_backtest(sub, cash_col=None)
        comp_bt = run_backtest(sub, cash_col='cash_composite')
        base_m = compute_metrics(base_bt)
        comp_m = compute_metrics(comp_bt)
        avoided_dd = base_m['max_dd'] - comp_m['max_dd']
        alpha = comp_m['total_ret'] - base_m['total_ret']
        print(f"  · {cname:<26} | 指数涨跌: {base_m['total_ret']*100:+6.2f}% (回撤 {base_m['max_dd']*100:6.2f}%) | 复合因子涨跌: {comp_m['total_ret']*100:+6.2f}% (回撤 {comp_m['max_dd']*100:6.2f}%) | 避险超额: {alpha:+6.2f}%")

    # 保存分析明细为 json
    os.makedirs('reports/cash_factor_research', exist_ok=True)
    report_data = {
        'metrics': res_df.to_dict(orient='records'),
        'yearly': yearly_df.to_dict(orient='records'),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with open('reports/cash_factor_research/result.json', 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print("\n研究数据已成功导出至 reports/cash_factor_research/result.json")

if __name__ == '__main__':
    analyze_all()
