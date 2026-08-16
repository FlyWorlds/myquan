"""
Matplotlib radar-chart PNG renderer.

Renders 5-axis radar charts for the Munger Mental Model analysis.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # Set backend BEFORE importing pyplot
import matplotlib.pyplot as plt
import numpy as np


def render(record: dict, out_path: str) -> str:
    """
    Render a 5-axis radar chart and save to PNG.

    Args:
        record: Dict with 'radar_scores' (list of 5 floats 0-100) and 'symbol' (str).
        out_path: Path where PNG should be saved.

    Returns:
        out_path (string).
    """
    radar_scores = record["radar_scores"]
    symbol = record["symbol"]

    # 5 axes labels (Chinese: Financial, Competition, Incentive, Psychological, Negative)
    labels = ["财务", "竞争", "激励", "心理", "反面清单"]

    # Close any existing figure to avoid memory leaks
    plt.close("all")

    # Create figure and polar subplot
    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw=dict(projection="polar"))

    # Calculate angles for 5 axes
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    # Close the polygon by appending first angle at end
    angles += angles[:1]

    # Close the radar scores by appending first value at end
    scores = radar_scores + radar_scores[:1]

    # Plot radar polygon
    ax.plot(angles, scores, "o-", linewidth=2)
    ax.fill(angles, scores, alpha=0.25)

    # Set axis labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels)

    # Set radial limits (0 to 100)
    ax.set_ylim(0, 100)

    # Add title with symbol
    ax.set_title(f"Radar Chart: {symbol}", pad=20)

    # Adjust subplot margins to prevent label overflow
    fig.subplots_adjust(bottom=0.15)

    # Save to PNG at 120 dpi with extra padding
    fig.savefig(out_path, dpi=120, bbox_inches="tight", pad_inches=0.2)

    # Close figure to avoid memory leaks
    plt.close(fig)

    return out_path
