"""季节性计算自检：构造已知季节性的合成数据，验证算法能把它识别出来，
并验证"样本量/显著性"这类护栏真的会触发。全部通过退出码 0，否则 1。
"""

import sys
import traceback

import numpy as np
import pandas as pd

from seasonality import (
    MIN_YEARS_WARN,
    build_report,
    current_position,
    monthly_returns,
    seasonality_table,
    load_prices,
)

RNG = np.random.default_rng(20260713)


def _synth_prices(years, month_drift, noise=0.0, start="2010-01-01"):
    """按"指定月份有固定漂移"构造日线，用于验证季节性能被识别。
    month_drift: {月: 该月日均对数漂移}。"""
    dates = pd.bdate_range(start, periods=years * 252)
    logp = np.zeros(len(dates))
    for i, d in enumerate(dates):
        drift = month_drift.get(d.month, 0.0)
        eps = RNG.normal(0, noise) if noise else 0.0
        logp[i] = (logp[i - 1] if i else 0.0) + drift + eps
    return pd.DataFrame({"date": dates, "close": 100 * np.exp(logp)})


def test_detects_strong_up_month():
    """3 月被人为设成强涨月 → 算法必须把它识别为高上涨概率。"""
    px = _synth_prices(12, {3: 0.004}, noise=0.0)
    tbl = seasonality_table(monthly_returns(px))
    mar = tbl[tbl["month"] == 3].iloc[0]
    other = tbl[tbl["month"] != 3]["avg_return"].mean()
    assert mar["win_rate"] == 1.0, f"3月应100%上涨，实际{mar['win_rate']}"
    assert mar["avg_return"] > other + 0.05, "3月平均涨幅应显著高于其他月"


def test_detects_strong_down_month():
    """11 月设成强跌月 → 识别为低上涨概率。"""
    px = _synth_prices(12, {11: -0.004}, noise=0.0)
    tbl = seasonality_table(monthly_returns(px))
    nov = tbl[tbl["month"] == 11].iloc[0]
    assert nov["win_rate"] == 0.0, f"11月应0%上涨，实际{nov['win_rate']}"
    assert nov["avg_return"] < -0.05


def test_no_false_seasonality_on_noise():
    """纯随机游走（无季节性）→ 显著月份数应落在多重检验的期望内。
    12 个月在 α=0.1 下预期约 1.2 个偶然显著，故断言 <=2；
    若实现有 bug（如把大多数月份都标显著）会远超此界被抓出。"""
    px = _synth_prices(15, {}, noise=0.01)
    tbl = seasonality_table(monthly_returns(px))
    pos = current_position(monthly_returns(px), tbl)
    rep = build_report(tbl, pos)
    n_flag = len(rep["seasonal_strong_up_months"]) + len(rep["seasonal_strong_down_months"])
    assert n_flag <= 2, f"纯噪声显著月份 {n_flag} 个，超出多重检验期望（应 <=2），实现可能有误"


def test_all_months_have_returns():
    """回归测试：每个月都要有样本（曾因按年分组丢掉 1 月）。"""
    px = _synth_prices(10, {}, noise=0.005)
    tbl = seasonality_table(monthly_returns(px))
    assert set(tbl["month"]) == set(range(1, 13)), f"缺月份：{set(range(1,13))-set(tbl['month'])}"
    assert (tbl["years"] > 0).all(), "存在样本年数为 0 的月份"


def test_low_sample_warning_triggers():
    """样本年数不足 → 低样本警告必须置位。"""
    px = _synth_prices(MIN_YEARS_WARN - 3, {}, noise=0.005)
    tbl = seasonality_table(monthly_returns(px))
    rep = build_report(tbl, current_position(monthly_returns(px), tbl))
    assert rep["low_sample_warning"] is True, "样本偏少却未触发警告"


def test_short_data_rejected():
    """数据太短必须报错，而不是给出不可靠季节性。"""
    px = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=100),
                       "close": np.linspace(100, 110, 100)})
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.csv")
        px.to_csv(p, index=False)
        try:
            load_prices(p)
        except ValueError:
            return
    raise AssertionError("过短数据未被拒绝")


def test_winrate_significance_monotone():
    """上涨概率越极端，p 值应越小（护栏内部一致性）。"""
    from seasonality import _binom_two_sided_p
    p_extreme = _binom_two_sided_p(11, 11)   # 11年全涨
    p_mild = _binom_two_sided_p(7, 11)       # 11年7涨
    assert p_extreme < p_mild, "全涨的显著性应强于7/11"
    assert _binom_two_sided_p(6, 11) > 0.5, "接近5:5应不显著"


def test_ttest_uses_student_t_not_normal():
    """回归测试：t 检验必须用真实 t 分布，不能退回正态近似。
    小样本（如 11 年 = 10 自由度）下正态近似会系统性低估 p、高估显著性——
    与本 skill '不把噪声当规律' 的立身之本相悖。
    这里对已知 t 统计量核对 p 值：正态会给约 0.011，t(10) 应约 0.029。"""
    from math import erf, sqrt
    from seasonality import _t_test_p, _student_t_sf_two_sided

    # 构造一组 11 个数，其 t 统计量 ≈ 2.54（10 自由度）
    x = np.array([0.02] * 11, float)
    x[0] += 0.05; x[1] -= 0.05; x[2] += 0.03; x[3] -= 0.03
    t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))

    p_got = _t_test_p(x)
    p_normal = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))   # 旧的错误实现

    # 真实 t 分布 p 应显著大于正态近似（正态低估 p）
    assert p_got > p_normal * 1.5, (
        f"t 检验疑似退回正态近似：得到 p={p_got:.4f}，正态={p_normal:.4f}")
    # 对照独立的 t 分布尾概率实现（自校验）
    p_ref = _student_t_sf_two_sided(t, len(x) - 1)
    assert abs(p_got - p_ref) < 1e-9, f"p 值与 t 分布参考不符：{p_got} vs {p_ref}"

    # 与 α=0.1 阈值边界一致性：t≈1.72（10 自由度）真实 p>0.1，不得判显著
    p_boundary = _student_t_sf_two_sided(1.72, 10)
    assert p_boundary > 0.1, f"t=1.72,df=10 真实 p 应>0.1，实际 {p_boundary:.4f}"


def test_html_output_selfcontained():
    """HTML 报告必须自包含（无外部网络依赖）、含全部 12 个月数据、保留严谨性说明。
    关键：显著性逻辑与 --faded 透明度须在，以保证不显著月份在图上视觉退隐，
    避免"漂亮的图掩盖不显著"。"""
    from seasonality import render_html, _html_escape
    px = _synth_prices(11, {11: -0.004}, noise=0.008)
    m = monthly_returns(px)
    tbl = seasonality_table(m)
    rep = build_report(tbl, current_position(m, tbl), "TEST 测试品种")
    html = render_html(rep)

    assert "<svg" in html and "TEST 测试品种" in html, "HTML 缺图或品种名"
    # 12 个月数据全部嵌入（JS DATA 数组）
    for mm in range(1, 13):
        assert f'"m": {mm}' in html, f"HTML 缺第 {mm} 月数据"
    # 自包含：不得引用任何外部网络资源（SVG 命名空间的 http 字面量不算加载）
    for bad in ('src="http', 'href="http', '<link', '<script src',
                'cdn.', 'googleapis', '@import', 'url(http'):
        assert bad not in html, f"HTML 引用了外部资源: {bad}"
    # 严谨性保留：显著性判定逻辑、退隐透明度、全部免责说明都在
    assert "d.pw < 0.1" in html and "--faded" in html, "显著性视觉编码缺失"
    for c in rep["caveats"]:
        assert _html_escape(c) in html, "免责说明在 HTML 中丢失"


TESTS = [
    test_detects_strong_up_month,
    test_detects_strong_down_month,
    test_no_false_seasonality_on_noise,
    test_all_months_have_returns,
    test_low_sample_warning_triggers,
    test_short_data_rejected,
    test_winrate_significance_monotone,
    test_ttest_uses_student_t_not_normal,
    test_html_output_selfcontained,
]


def main():
    passed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(TESTS)} 通过")
    return 0 if passed == len(TESTS) else 1


if __name__ == "__main__":
    sys.exit(main())
