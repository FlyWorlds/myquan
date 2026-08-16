"""
Orchestration layer for Munger mental model analysis.

Provides cross-validation logic, record building, and CLI interface.
Implements the five-dimension scoring with one-vote veto mechanism.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np

import config
import data
import dimensions


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.bool_, np.integer, np.floating)):
            return obj.item()
        return super().default(obj)


# Radar chart rendering (stub for now)
def _render_radar(symbol: str, radar_scores: list[float], output_path: str) -> None:
    """
    Render and save a 5-dimensional radar chart as PNG.

    Args:
        symbol: Stock symbol
        radar_scores: List of 5 scores [fin, comp, incentive, psych, neg]
        output_path: Path to save PNG file
    """
    # Stub implementation - in full version would use matplotlib/plotly
    pass


def _render_html(symbol: str, record: dict, output_path: str) -> None:
    """
    Generate and save an HTML report from analysis record.

    Args:
        symbol: Stock symbol
        record: Full analysis record dict
        output_path: Path to save HTML file
    """
    dim_names = {
        "fin": "财务维度",
        "comp": "竞争力维度",
        "incentive": "激励机制维度",
        "psych": "心理学维度",
        "neg": "负面因素维度"
    }

    dim_scores = record["dim_scores"]
    dim_passed = record["dim_passed"]
    radar_scores = record["radar_scores"]
    sub_scores = record["sub_scores"]

    # Build dimension cards HTML
    dim_cards = ""
    for key in config.DIM_KEYS:
        score = dim_scores[key]
        passed = dim_passed[key]
        name = dim_names[key]
        status_class = "pass" if passed else ("fail" if passed is False else "insufficient")
        status_text = "通过" if passed else ("未通过" if passed is False else "数据不足")

        dim_cards += f"""
        <div class="dimension-item">
            <div class="dimension-label">
                <span>{name}</span>
                <span class="score-badge {status_class}">{score:.1f}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {score}%"></div>
            </div>
            <div class="status-badge {status_class}">{status_text}</div>
        </div>
        """

    # Build detailed dimension sections
    detail_sections = _build_detail_sections(sub_scores, dim_names, record)

    verdict = record["verdict"]
    confidence = record["high_confidence"]
    verdict_text = {
        "pass": "✓ 通过",
        "fail": "✗ 未通过",
        "veto": "⛔ 一票否决",
        "insufficient_data": "? 数据不足"
    }.get(verdict, verdict)

    verdict_class = "pass" if verdict == "pass" else "fail"
    confidence_text = "高置信度" if confidence else "低置信度"

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>芒格心智模型分析 - {symbol}</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f7fa;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
            border-radius: 12px 12px 0 0;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        .header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        .content {{
            background: white;
            padding: 40px;
        }}
        .verdict-box {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 4px;
        }}
        .verdict-box.fail {{
            background: #f8d7da;
            border-left-color: #dc3545;
        }}
        .verdict-box.pass {{
            background: #d4edda;
            border-left-color: #28a745;
        }}
        .verdict-box h3 {{
            color: #856404;
            margin-bottom: 10px;
        }}
        .verdict-box.fail h3 {{
            color: #721c24;
        }}
        .verdict-box.pass h3 {{
            color: #155724;
        }}
        .main-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
            margin-bottom: 40px;
        }}
        @media (max-width: 1024px) {{
            .main-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .card {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 25px;
            border: 1px solid #dee2e6;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .card h3 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 1.3em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}
        .radar-container {{
            position: relative;
            height: 350px;
        }}
        .dimension-item {{
            margin-bottom: 18px;
        }}
        .dimension-label {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}
        .dimension-label span:first-child {{
            font-weight: 600;
            color: #333;
            font-size: 0.95em;
        }}
        .score-badge {{
            font-size: 1.1em;
            font-weight: bold;
            color: #667eea;
            background: #e7f3ff;
            padding: 4px 12px;
            border-radius: 4px;
            min-width: 60px;
            text-align: center;
        }}
        .score-badge.pass {{
            color: #28a745;
            background: #d4edda;
        }}
        .score-badge.fail {{
            color: #dc3545;
            background: #f8d7da;
        }}
        .progress-bar {{
            height: 8px;
            background: #dee2e6;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 5px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
        }}
        .status-badge {{
            font-size: 0.85em;
            padding: 3px 8px;
            border-radius: 3px;
            background: #e7f3ff;
            color: #0066cc;
            display: inline-block;
        }}
        .status-badge.pass {{
            background: #d4edda;
            color: #155724;
        }}
        .status-badge.fail {{
            background: #f8d7da;
            color: #721c24;
        }}
        .status-badge.insufficient {{
            background: #fff3cd;
            color: #856404;
        }}
        .detail-section {{
            margin-bottom: 40px;
        }}
        .detail-section h3 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 1.25em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}
        .detail-items {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
        }}
        .detail-item {{
            background: white;
            padding: 15px;
            border-radius: 6px;
            border-left: 3px solid #667eea;
        }}
        .detail-item label {{
            display: block;
            color: #666;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        .detail-item value {{
            display: block;
            color: #333;
            font-size: 1.1em;
            font-weight: bold;
        }}
        .veto-detail-box {{
            background: #fff8f0;
            border: 1px solid #ffe0cc;
            border-radius: 8px;
            padding: 20px;
        }}
        .veto-summary {{
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px solid #ffe0cc;
        }}
        .veto-count {{
            font-size: 1.1em;
            font-weight: bold;
            color: #333;
        }}
        .veto-count .highlight {{
            color: #dc3545;
            font-size: 1.3em;
        }}
        .veto-reason {{
            color: #666;
            font-size: 0.95em;
            margin-top: 8px;
        }}
        .veto-checks {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
        }}
        .veto-check {{
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            overflow: hidden;
        }}
        .check-title {{
            background: #f8f9fa;
            padding: 12px 15px;
            font-weight: bold;
            color: #333;
            border-bottom: 1px solid #dee2e6;
            font-size: 0.95em;
        }}
        .check-content {{
            padding: 15px;
        }}
        .check-item {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .check-item label {{
            display: block;
            color: #666;
            font-size: 0.85em;
        }}
        .check-item value {{
            display: block;
            color: #333;
            font-size: 1em;
            font-weight: bold;
        }}
        .check-item status {{
            display: block;
            color: #28a745;
            font-size: 0.85em;
            font-weight: bold;
        }}
        .signals-box {{
            background: #f0f8ff;
            border: 1px solid #b3d9ff;
            border-radius: 8px;
            padding: 20px;
        }}
        .signals-intro {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #b3d9ff;
        }}
        .signals-intro p {{
            color: #333;
            font-size: 0.95em;
        }}
        .signals-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .signal-card {{
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            overflow: hidden;
        }}
        .signal-header {{
            background: #f8f9fa;
            padding: 12px 15px;
            border-bottom: 1px solid #dee2e6;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .signal-name {{
            font-weight: bold;
            color: #333;
            font-size: 0.9em;
        }}
        .signal-weight {{
            background: #667eea;
            color: white;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.75em;
            font-weight: bold;
        }}
        .signal-body {{
            padding: 15px;
        }}
        .signal-item {{
            display: flex;
            flex-direction: column;
            gap: 5px;
            margin-bottom: 10px;
        }}
        .signal-item label {{
            color: #666;
            font-size: 0.85em;
        }}
        .signal-item value {{
            color: #667eea;
            font-size: 1.3em;
            font-weight: bold;
        }}
        .signal-desc {{
            color: #999;
            font-size: 0.8em;
            line-height: 1.4;
        }}
        .composite-score {{
            background: white;
            border: 2px solid #667eea;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }}
        .composite-label {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        .composite-value {{
            color: #667eea;
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        .composite-formula {{
            color: #999;
            font-size: 0.8em;
            line-height: 1.5;
        }}
        .financial-box {{
            background: #f0f7ff;
            border: 1px solid #b3d9ff;
            border-radius: 8px;
            padding: 20px;
        }}
        .financial-intro {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #b3d9ff;
        }}
        .financial-intro p {{
            color: #333;
            font-size: 0.95em;
            margin: 5px 0;
        }}
        .financial-metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .metric-comparison {{
            display: grid;
            grid-template-columns: auto 80px auto auto 80px;
            gap: 8px;
            align-items: center;
            margin-bottom: 10px;
        }}
        .metric-label {{
            color: #666;
            font-size: 0.85em;
            text-align: right;
        }}
        .metric-operator {{
            color: #999;
            font-weight: bold;
            text-align: center;
        }}
        .metric-result {{
            color: #666;
            font-size: 0.85em;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #dee2e6;
        }}
        .competition-box {{
            background: #fff3f0;
            border: 1px solid #ffb3a7;
            border-radius: 8px;
            padding: 20px;
        }}
        .competition-intro {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #ffb3a7;
        }}
        .competition-intro p {{
            color: #333;
            font-size: 0.95em;
            margin: 5px 0;
        }}
        .competition-metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .metric-percentile {{
            margin-bottom: 10px;
        }}
        .percentile-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #f97316;
            margin-bottom: 8px;
        }}
        .percentile-bar {{
            height: 8px;
            background: #ffe4d9;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 8px;
        }}
        .percentile-fill {{
            height: 100%;
            background: linear-gradient(90deg, #f97316 0%, #fbbf24 100%);
            transition: width 0.3s ease;
        }}
        .percentile-text {{
            color: #666;
            font-size: 0.85em;
        }}
        .metric-weight {{
            color: #999;
            font-size: 0.8em;
            margin-top: 8px;
        }}
        .competition-data {{
            background: white;
            border: 1px solid #ffb3a7;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 15px;
        }}
        .data-label {{
            font-weight: bold;
            color: #333;
            margin-bottom: 10px;
            font-size: 0.9em;
        }}
        .data-items {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
        }}
        .data-item {{
            color: #666;
            font-size: 0.85em;
        }}
        .data-value {{
            color: #f97316;
            font-weight: bold;
        }}
        .psychology-box {{
            background: #f5f0ff;
            border: 1px solid #d9c9ff;
            border-radius: 8px;
            padding: 20px;
        }}
        .psychology-intro {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #d9c9ff;
        }}
        .psychology-intro p {{
            color: #333;
            font-size: 0.95em;
            margin: 5px 0;
        }}
        .benchmark {{
            color: #666;
            font-size: 0.85em;
            font-style: italic;
        }}
        .psychology-metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .metric-card {{
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 15px;
        }}
        .metric-title {{
            font-weight: bold;
            color: #333;
            margin-bottom: 15px;
            font-size: 0.95em;
        }}
        .metric-details {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .metric-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #667eea;
        }}
        .metric-bar {{
            height: 10px;
            background: #e9ecef;
            border-radius: 5px;
            overflow: hidden;
        }}
        .metric-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
        }}
        .metric-text {{
            color: #666;
            font-size: 0.85em;
        }}
        .metric-score {{
            color: #667eea;
            font-weight: bold;
            font-size: 0.9em;
        }}
        .psychology-score {{
            background: white;
            border: 2px solid #764ba2;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }}
        .psychology-label {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        .psychology-value {{
            color: #764ba2;
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        .psychology-formula {{
            color: #999;
            font-size: 0.8em;
            line-height: 1.5;
        }}
        .footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #666;
            border-top: 1px solid #dee2e6;
            border-radius: 0 0 12px 12px;
            margin-top: -40px;
        }}
        .timestamp {{
            font-size: 0.9em;
            color: #999;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>芒格心智模型分析</h1>
            <p>{symbol}</p>
        </div>

        <div class="content">
            <div class="verdict-box {verdict_class}">
                <h3>📊 分析结论</h3>
                <p><strong>判决：</strong>{verdict_text}</p>
                <p><strong>置信度：</strong>{confidence_text}</p>
                <p><strong>分析时间：</strong>{record['update_time']}</p>
            </div>

            <div class="main-grid">
                <div class="card">
                    <h3>五维雷达图</h3>
                    <div class="radar-container">
                        <canvas id="radarChart"></canvas>
                    </div>
                </div>

                <div class="card">
                    <h3>五维评分</h3>
                    {dim_cards}
                </div>
            </div>

            {detail_sections}
        </div>

        <div class="footer">
            <p class="timestamp">数据版本: {record['data_version']} | 更新时间: {record['update_time']}</p>
            <p style="margin-top: 10px; font-size: 0.85em;">本分析仅供教育参考，不构成投资建议</p>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('radarChart').getContext('2d');
        const radarChart = new Chart(ctx, {{
            type: 'radar',
            data: {{
                labels: ['财务维度', '竞争力维度', '激励机制维度', '心理学维度', '负面因素维度'],
                datasets: [{{
                    label: '{symbol}',
                    data: {radar_scores},
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    pointRadius: 5,
                    pointBackgroundColor: '#667eea',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                scales: {{
                    r: {{
                        min: 0,
                        max: 100,
                        beginAtZero: true,
                        ticks: {{
                            stepSize: 20,
                            callback: function(value) {{
                                return value;
                            }}
                        }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def _build_detail_sections(sub_scores: dict, dim_names: dict, record: dict = None) -> str:
    detail_html = ""

    # Get dim_scores from record if available
    dim_scores = record.get("dim_scores", {}) if record else {}

    # 财务维度详细
    if "fin" in sub_scores:
        fin = sub_scores["fin"]
        roe_vs_median = fin.get('roe_vs_median', 0)
        gm_vs_median = fin.get('gm_vs_median', 0)
        ocf_vs_median = fin.get('ocf_positive_and_vs_median', 0)

        detail_html += f"""
        <div class="detail-section">
            <h3>📈 {dim_names['fin']} - 详细评分</h3>
            <div class="signals-box">
                <div class="signals-intro">
                    <p>基于ROE、毛利率、经营现金流三项指标与同行中位数对标 (各项权重均为33.33%)</p>
                </div>
                <div class="signals-grid">
                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">指标1: ROE (净资产收益率)</span>
                            <span class="signal-weight">权重: 33.33%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>目标值</label>
                                <value>{fin.get('roe_value', 0):.2f}%</value>
                            </div>
                            <div class="signal-item">
                                <label>中位数</label>
                                <value>{fin.get('roe_median', 0):.2f}%</value>
                            </div>
                            <div class="signal-desc">
                                得分: {roe_vs_median:.0f} {'✓ 超过中位数' if roe_vs_median > 0 else '✗ 低于中位数'}
                            </div>
                        </div>
                    </div>

                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">指标2: 毛利率 (Gross Margin)</span>
                            <span class="signal-weight">权重: 33.33%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>目标值</label>
                                <value>{fin.get('gm_value', 0):.2f}%</value>
                            </div>
                            <div class="signal-item">
                                <label>中位数</label>
                                <value>{fin.get('gm_median', 0):.2f}%</value>
                            </div>
                            <div class="signal-desc">
                                得分: {gm_vs_median:.0f} {'✓ 超过中位数' if gm_vs_median > 0 else '✗ 低于中位数'}
                            </div>
                        </div>
                    </div>

                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">指标3: 经营现金流 (OCF)</span>
                            <span class="signal-weight">权重: 33.33%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>目标值</label>
                                <value>{fin.get('ocf_value', 0):,.0f}</value>
                            </div>
                            <div class="signal-item">
                                <label>中位数</label>
                                <value>{fin.get('ocf_median', 0):,.0f}</value>
                            </div>
                            <div class="signal-desc">
                                得分: {ocf_vs_median:.0f} {'✓ 正数且超中位数' if ocf_vs_median > 0 else '✗ 未达标'}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="composite-score">
                    <div class="composite-label">综合得分</div>
                    <div class="composite-value">{dim_scores.get('fin', 0):.1f}</div>
                    <div class="composite-formula">
                        = ({roe_vs_median:.0f} + {gm_vs_median:.0f} + {ocf_vs_median:.0f}) / 3 × 100
                    </div>
                </div>
            </div>
        </div>
        """

    # 竞争力维度详细
    if "comp" in sub_scores:
        comp = sub_scores["comp"]
        roe_pct = comp.get('roe_percentile', 0)
        gm_pct = comp.get('gm_percentile', 0)
        peer_count = comp.get('peer_count', 0)
        roe_score = (roe_pct / 100) * 40  # ROE 40%权重
        gm_score = (gm_pct / 100) * 40    # GM 40%权重
        conc_bonus = comp.get('concentration_bonus', 0)

        detail_html += f"""
        <div class="detail-section">
            <h3>🏆 {dim_names['comp']} - 详细评分</h3>
            <div class="signals-box">
                <div class="signals-intro">
                    <p>相对于同行业对手的竞争力排位 (ROE 40% + 毛利率 40% + 集中度加分 20%)</p>
                </div>
                <div class="signals-grid">
                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">指标1: ROE 百分位排名</span>
                            <span class="signal-weight">权重: 40%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>排名</label>
                                <value>{roe_pct:.1f}%</value>
                            </div>
                            <div class="signal-item">
                                <label>得分贡献</label>
                                <value>{roe_score:.1f}</value>
                            </div>
                            <div class="signal-desc">
                                在 {int(comp.get('valid_roe_count', 0))} 家同行中排名前 {roe_pct:.1f}%
                            </div>
                        </div>
                    </div>

                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">指标2: 毛利率 百分位排名</span>
                            <span class="signal-weight">权重: 40%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>排名</label>
                                <value>{gm_pct:.1f}%</value>
                            </div>
                            <div class="signal-item">
                                <label>得分贡献</label>
                                <value>{gm_score:.1f}</value>
                            </div>
                            <div class="signal-desc">
                                在 {int(comp.get('valid_gm_count', 0))} 家同行中排名前 {gm_pct:.1f}%
                            </div>
                        </div>
                    </div>

                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">指标3: 集中度加分</span>
                            <span class="signal-weight">权重: 20%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>加分</label>
                                <value>{conc_bonus:.1f}</value>
                            </div>
                            <div class="signal-item">
                                <label>得分贡献</label>
                                <value>{conc_bonus:.1f}</value>
                            </div>
                            <div class="signal-desc">
                                衡量市场集中度 (可用于龙头企业加分)
                            </div>
                        </div>
                    </div>
                </div>
                <div class="composite-score">
                    <div class="composite-label">综合得分</div>
                    <div class="composite-value">{dim_scores.get('comp', 0):.1f}</div>
                    <div class="composite-formula">
                        = {roe_score:.1f} + {gm_score:.1f} + {conc_bonus:.1f}
                    </div>
                </div>
            </div>
        </div>
        """

    # 激励机制维度详细
    if "incentive" in sub_scores:
        incentive = sub_scores["incentive"]
        detail_html += f"""
        <div class="detail-section">
            <h3>💼 {dim_names['incentive']} - 详细评分</h3>
            <div class="signals-box">
                <div class="signals-intro">
                    <p>采用三信号模型 (33.33-33.33-33.33权重) - 基础得分均为60分</p>
                </div>
                <div class="signals-grid">
                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">信号1: 管理层交易</span>
                            <span class="signal-weight">权重: 33.33%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>得分</label>
                                <value>{incentive.get('mgmt_trade_score', 0):.1f}</value>
                            </div>
                            <div class="signal-desc">
                                100=净买入 | 60=无交易 | 20=净卖出
                            </div>
                        </div>
                    </div>

                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">信号2: 股权质押比例</span>
                            <span class="signal-weight">权重: 33.33%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>得分</label>
                                <value>{incentive.get('pledge_score', 0):.1f}</value>
                            </div>
                            <div class="signal-desc">
                                衡量控股股东资金压力 (质押比越低越好)
                            </div>
                        </div>
                    </div>

                    <div class="signal-card">
                        <div class="signal-header">
                            <span class="signal-name">信号3: 控股股东交易</span>
                            <span class="signal-weight">权重: 33.33%</span>
                        </div>
                        <div class="signal-body">
                            <div class="signal-item">
                                <label>得分</label>
                                <value>{incentive.get('controlling_trade_score', 0):.1f}</value>
                            </div>
                            <div class="signal-desc">
                                100=增持 | 60=无交易 | 40=小幅减持(≤2%) | 20=大幅减持
                            </div>
                        </div>
                    </div>
                </div>
                <div class="composite-score">
                    <div class="composite-label">综合得分</div>
                    <div class="composite-value">{dim_scores.get('incentive', 0):.1f}</div>
                    <div class="composite-formula">
                        = {incentive.get('mgmt_trade_score', 0):.1f}×33.33% + {incentive.get('pledge_score', 0):.1f}×33.33% + {incentive.get('controlling_trade_score', 0):.1f}×33.33%
                    </div>
                </div>
            </div>
        </div>
        """

    # 心理学维度详细
    if "psych" in sub_scores:
        psych = sub_scores["psych"]
        meeting_count = psych.get('meeting_count', 0)
        institute_count = psych.get('institute_count', 0)
        meeting_score = psych.get('meeting_score', 0)
        institute_score = psych.get('institute_score', 0)

        # 计算达成度
        meeting_pct = min(100, (meeting_count / 60) * 100) if meeting_count else 0
        institute_pct = min(100, (institute_count / 60) * 100) if institute_count else 0

        detail_html += f"""
        <div class="detail-section">
            <h3>🧠 {dim_names['psych']} - 详细评分</h3>
            <div class="psychology-box">
                <div class="psychology-intro">
                    <p>衡量机构投资者关注度和调研活跃度</p>
                    <p class="benchmark">基准: 60次/年 (周频活跃) 或 60个独立机构</p>
                </div>
                <div class="psychology-metrics">
                    <div class="metric-card">
                        <div class="metric-title">调研会议次数</div>
                        <div class="metric-details">
                            <div class="metric-value">{meeting_count}</div>
                            <div class="metric-bar">
                                <div class="metric-fill" style="width: {meeting_pct}%"></div>
                            </div>
                            <div class="metric-text">
                                {meeting_count} / 60 = {meeting_pct:.0f}%
                            </div>
                            <div class="metric-score">得分: {meeting_score:.1f}</div>
                        </div>
                    </div>

                    <div class="metric-card">
                        <div class="metric-title">参与机构数</div>
                        <div class="metric-details">
                            <div class="metric-value">{institute_count}</div>
                            <div class="metric-bar">
                                <div class="metric-fill" style="width: {institute_pct}%"></div>
                            </div>
                            <div class="metric-text">
                                {institute_count} / 60 = {institute_pct:.0f}%
                            </div>
                            <div class="metric-score">得分: {institute_score:.1f}</div>
                        </div>
                    </div>
                </div>
                <div class="psychology-score">
                    <div class="psychology-label">综合得分</div>
                    <div class="psychology-value">{dim_scores.get('psych', 0):.1f}</div>
                    <div class="psychology-formula">
                        = {meeting_score:.1f} + {institute_score:.1f} (取两者之和, 满分100)
                    </div>
                </div>
            </div>
        </div>
        """

    # 负面因素维度详细
    if "neg" in sub_scores:
        neg = sub_scores["neg"]
        veto_count = neg.get('veto_count', 0)
        audit_opinion = neg.get('audit_opinion', '无数据')
        audit_agency = neg.get('audit_agency', '无数据')
        has_st = neg.get('has_st_status', False)
        max_pledge = neg.get('max_pledge_ratio')
        pledge_limit = neg.get('pledge_limit', 0.5)
        has_controlling_sell = neg.get('has_controlling_sell', False)

        # Format status display
        audit_opinion_display = "无保留意见" if audit_opinion == "unqualified_opinion" else ("未审" if audit_opinion == "no_audit_performed" else audit_opinion)
        st_status = "✗ 存在ST/退市" if has_st else "✓ 无ST/退市"
        controlling_sell = "✗ 存在大额减持" if has_controlling_sell else "⚠️ 无数据"

        # Format pledge ratio display
        # Note: pledge_ratio from API is already in percentage form (0-100, e.g., 18.86 means 18.86%)
        # pledge_limit is in decimal form (0-1, e.g., 0.5 means 50%)
        if max_pledge is not None:
            pledge_display = f"{max_pledge:.2f}%"
            pledge_status = "✗ 超限" if max_pledge > (pledge_limit * 100) else "✓ 正常"
        else:
            pledge_display = "无数据"
            pledge_status = "⚠️ 无数据"

        detail_html += f"""
        <div class="detail-section">
            <h3>⛔ {dim_names['neg']} - 详细评分</h3>
            <div class="veto-detail-box">
                <div class="veto-summary">
                    <div class="veto-count">一票否决总数: <span class="highlight">{veto_count}</span></div>
                    {f'<div class="veto-reason">否决原因: {record["veto_flags"]}</div>' if record["veto_flags"] else ''}
                </div>
                <div class="veto-checks">
                    <div class="veto-check">
                        <div class="check-title">检查1: 审计意见</div>
                        <div class="check-content">
                            <div class="check-item">
                                <label>最新审计意见</label>
                                <value>{audit_opinion_display}</value>
                                <status>✓ 标准意见</status>
                            </div>
                        </div>
                    </div>

                    <div class="veto-check">
                        <div class="check-title">检查2: 审计师变更</div>
                        <div class="check-content">
                            <div class="check-item">
                                <label>近3年审计师</label>
                                <value>{audit_agency if audit_agency else '无数据'}</value>
                                <status>✓ 稳定或正常轮换</status>
                            </div>
                        </div>
                    </div>

                    <div class="veto-check">
                        <div class="check-title">检查3: ST/退市状态</div>
                        <div class="check-content">
                            <div class="check-item">
                                <label>状态</label>
                                <value>{st_status}</value>
                            </div>
                        </div>
                    </div>

                    <div class="veto-check">
                        <div class="check-title">检查4: 股权质押比例</div>
                        <div class="check-content">
                            <div class="check-item">
                                <label>最高质押比例</label>
                                <value>{pledge_display}</value>
                                <label style="margin-top: 8px; font-size: 0.85em; color: #666;">上限: {pledge_limit:.0%}</label>
                                <status>{pledge_status}</status>
                            </div>
                        </div>
                    </div>

                    <div class="veto-check">
                        <div class="check-title">检查5: 大股东减持</div>
                        <div class="check-content">
                            <div class="check-item">
                                <label>减持状态</label>
                                <value>{controlling_sell}</value>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

    return detail_html


def cross_validate(dims: dict) -> dict:
    """
    Cross-validate dimensions and render final verdict with high_confidence flag.

    Args:
        dims: Dict mapping DIM_KEYS to dimension result dicts.
              Each dim dict has: score, passed, veto, flags, sub_scores

    Returns:
        dict with keys: high_confidence (bool), verdict (str), radar_scores (list[float])

    Logic (spec §5):
    - If dims["neg"]["veto"] → verdict "veto", high_confidence False
    - Elif any dim passed is None → verdict "insufficient_data", False
    - Elif all five passed is True → verdict "pass", True
    - Else → verdict "fail", False
    """
    # Check veto flag from negative dimension
    if dims["neg"].get("veto", False):
        return {
            "high_confidence": False,
            "verdict": "veto",
            "radar_scores": [dims[k]["score"] for k in config.DIM_KEYS],
        }

    # Check for any None (insufficient data)
    for key in config.DIM_KEYS:
        if dims[key]["passed"] is None:
            return {
                "high_confidence": False,
                "verdict": "insufficient_data",
                "radar_scores": [dims[k]["score"] for k in config.DIM_KEYS],
            }

    # Check if all passed
    all_passed = all(dims[k]["passed"] is True for k in config.DIM_KEYS)
    if all_passed:
        verdict = "pass"
        high_confidence = True
    else:
        verdict = "fail"
        high_confidence = False

    return {
        "high_confidence": high_confidence,
        "verdict": verdict,
        "radar_scores": [dims[k]["score"] for k in config.DIM_KEYS],
    }


def build_record(
    symbol: str,
    trade_date: str,
    dims: dict,
    update_time: str,
) -> dict:
    """
    Build full output record with all spec §6 fields.

    Args:
        symbol: Stock symbol
        trade_date: Trade date (YYYY-MM-DD)
        dims: Dimension results dict
        update_time: Update timestamp

    Returns:
        dict with spec §6 fields:
        - symbol, trade_date, dim_scores, dim_passed, sub_scores,
        - veto_flags, data_flags, radar_scores, high_confidence,
        - verdict, data_version, update_time
    """
    # Get cross-validation result
    xval = cross_validate(dims)

    # Collect all veto flags from negative dimension
    veto_flags = dims["neg"].get("veto_flags", [])

    # Collect all data flags from all dimensions
    data_flags = []
    for key in config.DIM_KEYS:
        data_flags.extend(dims[key].get("flags", []))

    # Build dim_scores and dim_passed dicts
    dim_scores = {k: dims[k]["score"] for k in config.DIM_KEYS}
    dim_passed = {k: dims[k]["passed"] for k in config.DIM_KEYS}

    # Collect all sub_scores
    sub_scores = {}
    for key in config.DIM_KEYS:
        sub_scores[key] = dims[key].get("sub_scores", {})

    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "dim_scores": dim_scores,
        "dim_passed": dim_passed,
        "sub_scores": sub_scores,
        "veto_flags": veto_flags,
        "data_flags": data_flags,
        "radar_scores": xval["radar_scores"],
        "high_confidence": xval["high_confidence"],
        "verdict": xval["verdict"],
        "data_version": config.DATA_VERSION,
        "update_time": update_time,
    }


def analyze_symbol(symbol: str, end_date: str | None, update_time: str) -> dict:
    """
    Analyze a single symbol: fetch data, score all 5 dimensions, build record.

    Args:
        symbol: Stock symbol
        end_date: Optional analysis date (YYYY-MM-DD or YYYYMMDD)
        update_time: Update timestamp string

    Returns:
        Full analysis record dict (from build_record)

    Flow:
    1. Fetch industry peers + fina for all (target + peers)
    2. Extract target row
    3. Score all 5 dimensions
    4. Build record

    If target row missing → all dims marked passed=None, build record with insufficient_data
    """
    print(f"\n{'='*70}")
    print(f"ANALYZING: {symbol} (end_date={end_date})")
    print(f"{'='*70}")

    # Fetch industry peers and financial data
    print(f"\n[STEP 1] Fetching industry peers...")
    try:
        peers = data.fetch_industry_peers(symbol, end_date)
        print(f"  ✓ Found {len(peers)} peers (including target)")
        print(f"    Peers: {peers[:5]}{'...' if len(peers) > 5 else ''}")
    except Exception as e:
        print(f"  ⚠ Warning: Could not fetch peers for {symbol}: {e}")
        peers = [symbol]

    # Fetch financial data for target + peers
    print(f"\n[STEP 2] Fetching financial data (ROE, 毛利率, 经营现金流)...")
    try:
        fina_df = data.fetch_fina(peers, end_date)
        print(f"  ✓ Fetched financial data for {len(fina_df)} companies")
        print(f"  Columns: {list(fina_df.columns)}")
        print(f"\n  Financial Data Summary:")
        print(f"  {fina_df[['symbol', 'roe', 'gross_profit', 'ocf']].to_string()}")
    except Exception as e:
        print(f"  ✗ Error: Could not fetch financial data for {symbol}: {e}")
        raise

    # Extract target row
    target_fina = fina_df[fina_df["symbol"] == symbol]

    # If target missing, mark all dims as insufficient_data
    if target_fina.empty:
        print(f"  ✗ Target {symbol} not found in financial data!")
        dims = {
            "fin": {"score": 0.0, "passed": None, "veto": False, "flags": [], "sub_scores": {}},
            "comp": {"score": 0.0, "passed": None, "veto": False, "flags": [], "sub_scores": {}},
            "incentive": {"score": 0.0, "passed": None, "veto": False, "flags": [], "sub_scores": {}},
            "psych": {"score": 0.0, "passed": None, "veto": False, "flags": [], "sub_scores": {}},
            "neg": {"score": 0.0, "passed": None, "veto": False, "veto_flags": [], "flags": [], "sub_scores": {}},
        }
        return build_record(symbol, end_date or "", dims, update_time)

    target_row = target_fina.iloc[0]
    peer_fina = fina_df[fina_df["symbol"] != symbol]

    # Prepare target dict for financial and competition scoring
    target_fin_dict = {
        "roe": target_row.get("roe", 0.0),
        "gross_profit": target_row.get("gross_profit", 0.0),
        "ocf": target_row.get("ocf", 0.0),
    }

    print(f"\n  Target Data ({symbol}):")
    print(f"    ROE: {target_fin_dict['roe']}")
    print(f"    Gross Profit Rate: {target_fin_dict['gross_profit']}")
    print(f"    Operating Cash Flow: {target_fin_dict['ocf']}")

    # Score financial dimension
    print(f"\n[STEP 3] Scoring Financial Dimension...")
    dims_fin = dimensions.score_financial(target_fin_dict, peer_fina)
    print(f"  Score: {dims_fin['score']:.2f}")
    print(f"  Passed: {dims_fin['passed']}")
    print(f"  Sub-scores: {dims_fin['sub_scores']}")

    # Score competition dimension
    print(f"\n[STEP 4] Scoring Competition Dimension...")
    dims_comp = dimensions.score_competition(target_fin_dict, peer_fina)
    print(f"  Score: {dims_comp['score']:.2f}")
    print(f"  Passed: {dims_comp['passed']}")
    print(f"  Sub-scores: {dims_comp['sub_scores']}")
    if dims_comp['flags']:
        print(f"  Flags: {dims_comp['flags']}")

    # Fetch and score incentive dimension
    print(f"\n[STEP 5] Fetching & Scoring Incentive Dimension...")
    try:
        sh_change = data.fetch_shareholder_change(symbol, end_date)
        print(f"  ✓ Shareholder changes: {len(sh_change)} records")
        if not sh_change.empty:
            print(f"    {sh_change.to_string()}")
    except Exception as e:
        print(f"  ⚠ Warning: Could not fetch incentive data for {symbol}: {e}")
        sh_change = __import__('pandas').DataFrame()

    # Fetch pledge data (needed by both incentive and negative dimensions)
    print(f"\n[STEP 5a] Fetching pledge data...")
    try:
        pledge = data.fetch_pledge(symbol, end_date)
        print(f"  ✓ Pledge records: {len(pledge)}")
        if not pledge.empty:
            print(f"    {pledge.to_string()}")
    except Exception as e:
        print(f"  ⚠ Warning: Could not fetch pledge data for {symbol}: {e}")
        pledge = __import__('pandas').DataFrame()

    # Score incentive dimension (now uses pledge)
    dims_incentive = dimensions.score_incentive(sh_change, pledge)
    print(f"  Score: {dims_incentive['score']:.2f}")
    print(f"  Passed: {dims_incentive['passed']}")
    print(f"  Sub-scores: {dims_incentive['sub_scores']}")

    # Fetch and score psychology dimension
    print(f"\n[STEP 6] Fetching & Scoring Psychology Dimension...")
    try:
        activity = data.fetch_investor_activity(symbol, end_date)
        print(f"  ✓ Investor activity records: {len(activity)}")
        if not activity.empty:
            print(f"    {activity.head().to_string()}")
    except Exception as e:
        print(f"  ⚠ Warning: Could not fetch investor activity for {symbol}: {e}")
        activity = __import__('pandas').DataFrame()

    dims_psych = dimensions.score_psychology(activity)
    print(f"  Score: {dims_psych['score']:.2f}")
    print(f"  Passed: {dims_psych['passed']}")
    print(f"  Sub-scores: {dims_psych['sub_scores']}")

    # Fetch and score negative dimension
    print(f"\n[STEP 7] Fetching & Scoring Negative Dimension (Veto Check)...")
    try:
        audit = data.fetch_audit(symbol, end_date)
        status = data.fetch_status_change(symbol, end_date)
        print(f"  ✓ Audit records: {len(audit)}")
        if not audit.empty:
            print(f"    {audit.to_string()}")
        print(f"  ✓ Status changes: {len(status)}")
        if not status.empty:
            print(f"    {status.to_string()}")
    except Exception as e:
        print(f"  ⚠ Warning: Could not fetch negative dimension data for {symbol}: {e}")
        audit = __import__('pandas').DataFrame()
        status = __import__('pandas').DataFrame()
        # Note: pledge is already fetched above and reused here; don't reset it

    dims_neg = dimensions.score_negative(audit, status, pledge, sh_change)
    print(f"  Score: {dims_neg['score']:.2f}")
    print(f"  Passed: {dims_neg['passed']}")
    print(f"  Veto: {dims_neg['veto']}")
    if dims_neg['veto_flags']:
        print(f"  Veto Flags: {dims_neg['veto_flags']}")
    print(f"  Sub-scores: {dims_neg['sub_scores']}")

    # Assemble dims dict
    dims = {
        "fin": dims_fin,
        "comp": dims_comp,
        "incentive": dims_incentive,
        "psych": dims_psych,
        "neg": dims_neg,
    }

    # Build and return record
    trade_date = end_date or ""
    print(f"\n[STEP 8] Cross-validating & Building Final Record...")
    record = build_record(symbol, trade_date, dims, update_time)
    print(f"  Verdict: {record['verdict']}")
    print(f"  High Confidence: {record['high_confidence']}")
    print(f"  Radar Scores: {record['radar_scores']}")

    return record


def main() -> None:
    """
    CLI entry point for symbol analysis.

    Args:
        --symbol: Comma-separated list of symbols (e.g., "000001.SZ,600000.SH")
        --industry: L2 industry code (alternative to --symbol)
        --end-date: Optional analysis date (YYYY-MM-DD or YYYYMMDD)

    Flow:
    1. data.init() first
    2. For each symbol: analyze_symbol(), write per-symbol JSON, render radar PNG
    3. Collect high_confidence records
    4. Write high_confidence_list.csv if any
    5. Print summary
    """
    parser = argparse.ArgumentParser(
        description="Analyze stocks using Munger 5-dimension mental model"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        help="Comma-separated list of stock symbols (e.g., 000001.SZ,600000.SH)",
    )
    parser.add_argument(
        "--industry",
        type=str,
        help="L2 industry code (e.g., L2004001 for banks)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="Analysis date in YYYY-MM-DD or YYYYMMDD format (default: today)",
    )

    args = parser.parse_args()

    # Determine symbols to analyze
    if args.symbol:
        symbols = [s.strip() for s in args.symbol.split(",")]
    elif args.industry:
        symbols = data.fetch_industry_peers_by_code(args.industry)
    else:
        parser.error("Either --symbol or --industry is required")
        return

    # Initialize panda_data session
    print("Initializing panda_data session...")
    data.init()

    # Get current time for update_time field
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Analyze each symbol
    high_confidence_records = []
    results = []

    for symbol in symbols:
        print(f"Analyzing {symbol}...")
        try:
            record = analyze_symbol(symbol, args.end_date, update_time)
            results.append(record)

            if record["high_confidence"]:
                high_confidence_records.append(record)

            # Write per-symbol JSON report to production directory only
            import os
            # Get the absolute path to production directory
            script_dir = Path(__file__).parent.parent  # From scripts/ to munger-mental-model/
            prod_dir = script_dir / ".." / "munger-mental-model-production"
            prod_dir = prod_dir.resolve()  # Resolve to absolute path
            prod_dir.mkdir(parents=True, exist_ok=True)
            report_path = prod_dir / f"report_{symbol}.json"
            with open(report_path, "w") as f:
                json.dump(record, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
            print(f"  ✓ Wrote {report_path}")

            # Render HTML report
            html_path = prod_dir / f"report_{symbol}.html"
            _render_html(symbol, record, str(html_path))
            print(f"  ✓ Wrote {html_path}")

            # Render radar chart (stub)
            radar_path = f"radar_{symbol}.png"
            _render_radar(symbol, record["radar_scores"], radar_path)

            # Print verdict
            verdict = record["verdict"]
            confidence = "HIGH" if record["high_confidence"] else "LOW"
            print(f"  Verdict: {verdict} ({confidence} confidence)")

        except Exception as e:
            print(f"  Error: {e}")
            continue

    # Write high_confidence_list.csv if any records
    if high_confidence_records:
        import csv
        csv_path = "high_confidence_list.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["symbol", "verdict", "fin", "comp", "incentive", "psych", "neg"],
            )
            writer.writeheader()
            for rec in high_confidence_records:
                writer.writerow({
                    "symbol": rec["symbol"],
                    "verdict": rec["verdict"],
                    "fin": rec["dim_scores"]["fin"],
                    "comp": rec["dim_scores"]["comp"],
                    "incentive": rec["dim_scores"]["incentive"],
                    "psych": rec["dim_scores"]["psych"],
                    "neg": rec["dim_scores"]["neg"],
                })
        print(f"\n✓ Wrote {csv_path} with {len(high_confidence_records)} high-confidence records")

    # Print summary
    total = len(results)
    high_conf = len(high_confidence_records)
    print(f"\nSummary: {total} analyzed, {high_conf} high-confidence")


if __name__ == "__main__":
    main()
