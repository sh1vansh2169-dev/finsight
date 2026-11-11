"""Static PNG charts for reports (Matplotlib, light theme).

Colours are the validated reference palette (blue = money in, orange =
money out; checked with the palette validator: CVD and normal-vision
separation and contrast all pass on the light surface). Text uses ink
colours, never series colours. Periods with no statement coverage are drawn
as a labelled grey band, never as zero.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.dates

matplotlib.use("Agg")  # no display needed; must precede pyplot

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
MONEY_IN = "#2a78d6"
MONEY_OUT = "#eb6834"
NO_DATA = "#f0efec"


def _style(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=13, color=INK, pad=22, fontweight="bold")
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK_SECONDARY)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _money_axis(ax: plt.Axes, axis: str = "y") -> None:
    formatter = FuncFormatter(lambda v, _: f"{v:,.0f}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)


def _save(fig: plt.Figure, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


def monthly_in_out(monthly: pd.DataFrame, currency: str, path: Path) -> Path:
    """Grouped bars: income vs spending per month (minor units in, major out)."""
    fig, ax = plt.subplots(figsize=(8, 4))
    labels = [p.strftime("%b %Y") for p in monthly.index]
    x = np.arange(len(labels))
    width = 0.32
    income = monthly["income"] / 100
    expenses = monthly["spending"] / 100
    ax.bar(x - width / 2 - 0.02, income, width, color=MONEY_IN, label="Income")
    ax.bar(x + width / 2 + 0.02, expenses, width, color=MONEY_OUT, label="Spending")
    # Say how complete each month is under its label: a partly covered month
    # would otherwise look as authoritative as a fully covered one.
    for i, cover in enumerate(monthly["coverage"]):
        if cover == 0:
            ax.axvspan(i - 0.45, i + 0.45, color=NO_DATA, zorder=0)
            labels[i] += "\nno statement"
        elif cover < 0.995:
            labels[i] += f"\n{cover:.0%} covered"
    ax.set_xticks(x, labels)
    _money_axis(ax)
    _style(ax, "Income and spending by month", f"Recorded transactions only, in {currency}. Not a bank balance.")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY, loc="upper left", ncols=2,
              bbox_to_anchor=(0, 1.0))
    return _save(fig, path)


def spending_by_category(by_category: pd.DataFrame, currency: str, path: Path, top: int = 8) -> Path:
    """Horizontal bars, largest first, one hue (magnitude, not identity)."""
    data = by_category["net"].head(top)[::-1] / 100
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(data) + 1.4))
    ax.barh(data.index, data.to_numpy(), height=0.55, color=MONEY_IN)
    total = by_category["net"].sum() / 100
    for y, value in enumerate(data.to_numpy()):
        ax.text(value, y, f"  {value:,.0f}  ({value / total:.0%})", va="center", fontsize=8, color=INK_SECONDARY)
    ax.set_xlim(min(0, data.min() * 1.3), data.max() * 1.3)
    _money_axis(ax, "x")
    _style(ax, "Spending by category", f"Recorded spending after refunds, in {currency}; share in brackets.")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.tick_params(axis="y", colors=INK_SECONDARY)
    return _save(fig, path)


def daily_spending(daily: pd.DataFrame, currency: str, path: Path) -> Path:
    """One thin column per day (daily amounts are discrete, so no connecting
    line). Days without any statement get a grey band and no column."""
    fig, ax = plt.subplots(figsize=(8, 3.4))
    days = daily.index.to_timestamp()
    ax.bar(days, (daily["spending"] / 100).fillna(0), width=0.7, color=MONEY_OUT)
    unknown = (daily["coverage"] == 0).to_numpy()
    if unknown.any():
        ax.fill_between(days, 0, 1, where=unknown, transform=ax.get_xaxis_transform(), color=NO_DATA, step="mid",
                        zorder=0, label="No statement for these days")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_SECONDARY, loc="upper right")
    if (daily["spending"].fillna(0) >= 0).all():
        ax.set_ylim(bottom=0)
    else:
        ax.axhline(0, color=BASELINE, linewidth=0.8)  # a refund day goes below the line
    ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator(minticks=4, maxticks=8))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d %b"))
    _money_axis(ax)
    _style(ax, "Daily spending", f"Recorded spending after refunds, in {currency}. Grey days are unknown, not zero.")
    return _save(fig, path)
