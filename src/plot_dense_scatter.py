from __future__ import annotations

import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, LogNorm, Normalize
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.ticker import FuncFormatter, LogLocator
from matplotlib.ticker import MaxNLocator


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "processed" / "expanded" / "visual_novels_master_2020_2025.csv"
OUTPUT_DIR = ROOT / "outputs" / "expanded_vndb_complete_2020_2025" / "charts"

NAVY = "#17324D"
BLUE = "#1E6A8D"
TEAL = "#168A7A"
CORAL = "#F0702C"
MUTED = "#6B7C8F"
GRID = "#D9E1E8"
BACKGROUND = "#F6F8FB"


def configure_style() -> FontProperties:
    font_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if font_path.exists():
        fontManager.addfont(str(font_path))
        font = FontProperties(fname=str(font_path))
        mpl.rcParams["font.family"] = font.get_name()
    else:
        font = FontProperties(family="sans-serif")
    mpl.rcParams.update(
        {
            "axes.unicode_minus": False,
            "figure.facecolor": BACKGROUND,
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": "#A8B5C2",
            "axes.labelcolor": NAVY,
            "xtick.color": "#526577",
            "ytick.color": "#526577",
            "text.color": NAVY,
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "savefig.facecolor": BACKGROUND,
        }
    )
    return font


FONT = configure_style()


def load_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                copies = float(row["copies_sold"])
                months = float(row["months_since_release"])
                reviews = int(row["steam_review_count"])
            except (TypeError, ValueError):
                continue
            if copies <= 0 or months < 0:
                continue
            rows.append(
                {
                    "months": months,
                    "copies": copies,
                    "reviews": reviews,
                    "age": row["all_ages_status"],
                }
            )
    return rows


def arrays(rows: list[dict[str, object]]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([float(row["months"]) for row in rows]),
        np.asarray([float(row["copies"]) for row in rows]),
    )


def sales_formatter(value: float, _position: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if value >= 1_000:
        return f"{value / 1_000:g}k"
    return f"{value:g}"


def density_cmap(accent: str) -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list(
        "density", ["#E8EEF3", "#AFC8D5", accent, NAVY], N=256
    )


def style_axis(ax: mpl.axes.Axes) -> None:
    ax.set_xlim(7, 80)
    ax.set_ylim(1, 10_000_000)
    ax.set_yscale("log")
    ax.set_xlabel("上市后的月数（截至 2026-08-08）", labelpad=8)
    ax.set_ylabel("累计 copiesSold（对数刻度）", labelpad=8)
    ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(6))
    ax.yaxis.set_major_locator(LogLocator(base=10, numticks=8))
    ax.yaxis.set_major_formatter(FuncFormatter(sales_formatter))
    ax.grid(which="major", color=GRID, linewidth=0.7, alpha=0.75)
    ax.grid(which="minor", visible=False)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def median_trend(ax: mpl.axes.Axes, x: np.ndarray, y: np.ndarray, color: str) -> None:
    edges = np.arange(6, 85, 6)
    centers: list[float] = []
    medians: list[float] = []
    for left, right in zip(edges[:-1], edges[1:]):
        values = y[(x >= left) & (x < right)]
        if len(values) >= 8:
            centers.append((left + right) / 2)
            medians.append(float(np.median(values)))
    ax.plot(
        centers,
        medians,
        color="#FFFFFF",
        linewidth=4.0,
        alpha=0.9,
        zorder=4,
    )
    ax.plot(
        centers,
        medians,
        color=color,
        linewidth=2.0,
        marker="o",
        markersize=3.5,
        label="每 6 个月区间的销量中位数",
        zorder=5,
    )


def draw_hexbin(
    ax: mpl.axes.Axes,
    rows: list[dict[str, object]],
    accent: str,
    common_norm: LogNorm | None = None,
) -> mpl.collections.PolyCollection:
    x, y = arrays(rows)
    hb = ax.hexbin(
        x,
        y,
        gridsize=(66, 36),
        xscale="linear",
        yscale="log",
        mincnt=1,
        cmap=density_cmap(accent),
        norm=common_norm,
        linewidths=0.18,
        edgecolors="#FFFFFF",
        alpha=0.96,
    )
    median_trend(ax, x, y, accent)
    style_axis(ax)
    return hb


def add_density_colorbar(fig: mpl.figure.Figure, hb, axes) -> None:
    colorbar = fig.colorbar(hb, ax=axes, pad=0.018, fraction=0.026)
    colorbar.set_label("每个六边形内的游戏数量", color=NAVY, labelpad=8)
    colorbar.locator = MaxNLocator(integer=True)
    colorbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    colorbar.update_ticks()
    colorbar.outline.set_edgecolor("#B6C2CC")


def save_overall(rows: list[dict[str, object]]) -> None:
    fig, ax = plt.subplots(figsize=(13.5, 7.4), constrained_layout=False)
    fig.subplots_adjust(left=0.08, right=0.91, bottom=0.16, top=0.84)
    hb = draw_hexbin(ax, rows, BLUE)
    add_density_colorbar(fig, hb, ax)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.suptitle(
        "上市时长—累计销量｜六边形聚合密度图",
        x=0.08,
        y=0.94,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.08,
        0.08,
        f"相近游戏合并到同一六边形；颜色越深表示该区域游戏越多。共绘制 {len(rows):,} 款 copiesSold>0 的游戏。",
        fontsize=9.5,
        color=MUTED,
    )
    fig.savefig(OUTPUT_DIR / "03_overall_duration_sales_scatter.png", dpi=200)
    plt.close(fig)


def panel_density(
    groups: list[tuple[str, list[dict[str, object]], str]],
    title: str,
    note: str,
    filename: str,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14.2, 7.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.07, right=0.91, bottom=0.16, top=0.82, wspace=0.12)
    hexbins = []
    for ax, (label, group_rows, accent) in zip(axes, groups):
        hb = draw_hexbin(ax, group_rows, accent)
        hexbins.append(hb)
        ax.set_title(f"{label}｜{len(group_rows):,} 款", color=accent, pad=12)
        ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    axes[1].set_ylabel("")

    global_max = max(float(np.max(hb.get_array())) for hb in hexbins)
    common_norm = Normalize(vmin=1, vmax=max(2, global_max))
    for hb in hexbins:
        hb.set_norm(common_norm)
        hb.set_cmap(density_cmap(BLUE))
    add_density_colorbar(fig, hexbins[-1], axes)

    fig.suptitle(
        title,
        x=0.07,
        y=0.94,
        ha="left",
        fontsize=20,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(0.07, 0.08, note, fontsize=9.5, color=MUTED)
    fig.savefig(OUTPUT_DIR / filename, dpi=200)
    plt.close(fig)


def binned_median(rows: list[dict[str, object]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # 78–84 months only contains a small fraction of 2020-01, so exclude that incomplete bin.
    edges = np.arange(6, 79, 6)
    centers: list[float] = []
    medians: list[float] = []
    counts: list[int] = []
    for left, right in zip(edges[:-1], edges[1:]):
        values = [float(row["copies"]) for row in rows if left <= float(row["months"]) < right]
        centers.append((left + right) / 2)
        medians.append(float(np.median(values)) if values else np.nan)
        counts.append(len(values))
    return np.asarray(centers), np.asarray(medians), np.asarray(counts)


def save_combined_median_trends(rows: list[dict[str, object]]) -> None:
    groups = [
        ("整体", rows, NAVY, "o", "-", 3.4),
        ("高热度（评论 >198）", [row for row in rows if int(row["reviews"]) > 198], CORAL, "^", "--", 2.2),
        ("低热度（评论 ≤198）", [row for row in rows if int(row["reviews"]) <= 198], "#4A90B8", "s", ":", 2.2),
        ("全年龄（has_ero=false）", [row for row in rows if row["age"] == "全年龄"], TEAL, "D", "-.", 2.2),
        ("非全年龄（has_ero=true）", [row for row in rows if row["age"] == "非全年龄"], "#A65A9E", "X", "-", 2.2),
    ]
    series = {}
    for label, group_rows, color, marker, linestyle, linewidth in groups:
        x, medians, counts = binned_median(group_rows)
        series[label] = {"x": x, "median": medians, "count": counts}

    fig = plt.figure(figsize=(14.5, 9.4))
    grid = fig.add_gridspec(2, 1, height_ratios=[2.25, 1], hspace=0.12)
    ax = fig.add_subplot(grid[0])
    ratio_ax = fig.add_subplot(grid[1], sharex=ax)
    fig.subplots_adjust(left=0.075, right=0.975, bottom=0.105, top=0.84)

    for label, _group_rows, color, marker, linestyle, linewidth in groups:
        values = series[label]
        ax.plot(
            values["x"], values["median"],
            color=color, marker=marker, linestyle=linestyle,
            linewidth=linewidth, markersize=5.5,
            markeredgecolor="#FFFFFF", markeredgewidth=0.7,
            label=label, zorder=5 if label == "整体" else 3,
        )

    ax.set_yscale("log")
    ax.set_ylim(250, 100_000)
    ax.set_ylabel("六个月区间的 copiesSold 中位数（对数刻度）")
    ax.yaxis.set_major_locator(LogLocator(base=10, numticks=6))
    ax.yaxis.set_major_formatter(FuncFormatter(sales_formatter))
    ax.grid(which="major", color=GRID, linewidth=0.75, alpha=0.8)
    ax.grid(which="minor", visible=False)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", labelbottom=False)
    ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, 1.13), ncol=3,
        frameon=False, fontsize=9.5, columnspacing=1.5, handlelength=2.8,
    )

    overall = series["整体"]["median"]
    ratio_ax.axhspan(0.8, 1.25, color="#DDE6EC", alpha=0.55, zorder=0)
    ratio_ax.axhline(1, color=NAVY, linewidth=2.2, zorder=2)
    ratio_ax.text(7.6, 1.32, "整体基准＝1", ha="left", va="bottom", color=NAVY, fontsize=9)
    for label, _group_rows, color, marker, linestyle, linewidth in groups[1:]:
        values = series[label]
        ratio_ax.plot(
            values["x"], values["median"] / overall,
            color=color, marker=marker, linestyle=linestyle,
            linewidth=linewidth, markersize=5,
            markeredgecolor="#FFFFFF", markeredgewidth=0.7,
        )
    ratio_ax.set_yscale("log")
    ratio_ax.set_ylim(0.25, 35)
    ratio_ax.set_yticks([0.25, 0.5, 1, 2, 5, 10, 20])
    ratio_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}×"))
    ratio_ax.set_ylabel("相对整体中位数")
    ratio_ax.set_xlabel("上市后的月数（每个点代表一个六个月区间）")
    ratio_ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(6))
    ratio_ax.grid(which="major", color=GRID, linewidth=0.75, alpha=0.8)
    ratio_ax.grid(which="minor", visible=False)
    ratio_ax.set_axisbelow(True)
    ratio_ax.spines["top"].set_visible(False)
    ratio_ax.spines["right"].set_visible(False)

    fig.suptitle(
        "上市时长—累计销量中位数｜五组趋势同图比较",
        x=0.075, y=0.955, ha="left",
        fontsize=20, fontweight="bold", color=NAVY,
    )
    fig.text(
        0.075, 0.035,
        "整体线是全部 4,259 款已知 copiesSold 游戏的分箱中位数，并非各分组的算术平均；已排除样本不完整的 78–84 个月区间。",
        fontsize=9.2, color=MUTED,
    )
    fig.savefig(OUTPUT_DIR / "11_combined_median_trends.png", dpi=200)
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    high = [row for row in rows if int(row["reviews"]) > 198]
    low = [row for row in rows if int(row["reviews"]) <= 198]
    all_ages = [row for row in rows if row["age"] == "全年龄"]
    not_all_ages = [row for row in rows if row["age"] == "非全年龄"]

    save_overall(rows)
    panel_density(
        [("高热度（评论 >198）", high, CORAL), ("低热度（评论 ≤198）", low, BLUE)],
        "上市时长—累计销量｜按 Steam 评论热度分面",
        "每个面板均使用六边形聚合，密度色阶保持一致；折线为每 6 个月区间的销量中位数。",
        "06_review_heat_duration_sales_scatter.png",
    )
    panel_density(
        [("全年龄（has_ero=false）", all_ages, TEAL), ("非全年龄（has_ero=true）", not_all_ages, CORAL)],
        "上市时长—累计销量｜按 has_ero 分类分面",
        "相近点已合并；分类只依据 VNDB Release.has_ero，minage 不参与判断。两个面板使用相同密度色阶。",
        "09_all_ages_duration_sales_scatter.png",
    )
    save_combined_median_trends(rows)
    print(
        {
            "overall": len(rows),
            "high_heat": len(high),
            "low_heat": len(low),
            "all_ages": len(all_ages),
            "not_all_ages": len(not_all_ages),
            "output_dir": str(OUTPUT_DIR),
        }
    )


if __name__ == "__main__":
    main()
