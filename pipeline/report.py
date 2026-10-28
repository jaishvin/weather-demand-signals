"""Builds the weekly Markdown report, chart, CSV exports and the README summary block."""
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import config  # noqa: E402

README_START, README_END = "<!-- REPORT:START -->", "<!-- REPORT:END -->"


def md_table(df: pd.DataFrame, floatfmt: str = "{:.1f}") -> str:
    """Markdown table without extra dependencies."""
    def fmt(v):
        if isinstance(v, float):
            return "—" if pd.isna(v) else floatfmt.format(v)
        if isinstance(v, pd.Timestamp):
            return v.strftime("%a %d %b")
        return str(v)
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def make_chart(f: pd.DataFrame, path) -> None:
    """Small multiples: forecast max temperature vs the seasonal normal band, rain as bars."""
    cities = list(config.CITIES)
    fig, axes = plt.subplots(2, 3, figsize=(15, 7), sharex=True)
    for ax, city in zip(axes.flat, cities):
        c = f[f["city"] == city].sort_values("date")
        ax.fill_between(c["date"], c["tmax_normal"] - c["tmax_std"], c["tmax_normal"] + c["tmax_std"],
                        color="#c9d6e8", label="normal range (±1 sd)")
        ax.plot(c["date"], c["tmax_normal"], color="#7d8fa6", lw=1, ls="--", label="normal max")
        ax.plot(c["date"], c["tmax"], color="#d1495b", lw=2, marker="o", ms=3, label="forecast max")
        ax.set_title(city, fontsize=11, loc="left")
        ax.set_ylabel("°C")
        ax2 = ax.twinx()
        ax2.bar(c["date"], c["precip"], color="#2a6fdb", alpha=0.35, width=0.8, label="rain (mm)")
        ax2.set_ylim(0, max(40, c["precip"].max() * 1.3 if len(c) else 40))
        ax2.set_ylabel("mm", color="#2a6fdb")
        ax.set_zorder(ax2.get_zorder() + 1)   # keep the temperature line above the rain bars
        ax.patch.set_visible(False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.grid(alpha=0.3)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles + [plt.Rectangle((0, 0), 1, 1, color="#2a6fdb", alpha=0.35)], labels + ["rain (mm)"],
               loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.04))
    fig.suptitle("Next 14 days: forecast vs seasonal normal", fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def build_report(run_label: str, summary: pd.DataFrame, signals: pd.DataFrame,
                 accuracy: pd.DataFrame, coverage: pd.DataFrame) -> str:
    flagged = signals.assign(
        Date=signals["date"], City=signals["city"], Signal=signals["signal"],
        Forecast=signals["value"], Normal=signals["normal"], **{"z-score": signals["z"]}, Unit=signals["unit"],
    )[["Date", "City", "Signal", "Forecast", "Normal", "z-score", "Unit"]]

    parts = [
        "# Weekly weather demand signals",
        f"_Generated automatically on {run_label} by GitHub Actions. Data: [Open-Meteo](https://open-meteo.com/)._",
        "",
        "## Summary: next 14 days",
        md_table(summary),
        "",
        "Watch-list categories are an illustrative mapping for demand planners. Validate against sales data before acting.",
        "",
        "![Forecast vs normal](forecast_vs_normal.png)",
        "",
        "## Flagged days",
        md_table(flagged) if len(flagged) else "No unusual weather in the next 14 days.",
        "",
        "## Forecast accuracy check",
        "Past forecasts stored by this pipeline, compared with the actual weather (MAE = mean absolute error).",
        "",
        md_table(accuracy, "{:.2f}") if len(accuracy) else
        "_Builds up automatically: needs a few weekly runs before past forecasts can be compared with actuals._",
        "",
        "## Data coverage",
        md_table(coverage),
        "",
    ]
    return "\n".join(parts)


def update_readme(readme_path, run_label: str, summary: pd.DataFrame) -> None:
    """Replaces the block between the README markers with this week's summary."""
    if not readme_path.exists():
        return
    text = readme_path.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return
    block = "\n".join([
        README_START,
        f"**Latest run: {run_label}**. [Full report](reports/weekly_report.md)",
        "",
        md_table(summary),
        "",
        "![Forecast vs normal](reports/forecast_vs_normal.png)",
        README_END,
    ])
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    readme_path.write_text(pattern.sub(lambda _: block, text), encoding="utf-8")


def export_csvs(export_dir, f: pd.DataFrame, signals: pd.DataFrame, actuals: pd.DataFrame) -> None:
    """Flat files for BI tools (Power BI, Tableau, Excel)."""
    export_dir.mkdir(parents=True, exist_ok=True)
    cols = ["city", "date", "tmax", "tmin", "precip", "tmax_normal", "tmax_std", "tmin_normal",
            "precip_p90", "tmax_z", "tmin_z"]
    as_text = {"date": lambda x: pd.to_datetime(x["date"]).dt.strftime("%Y-%m-%d")}
    f[cols].assign(**as_text).round(2).to_csv(export_dir / "forecast_with_normals.csv", index=False)
    signals.assign(**as_text).round(2).to_csv(export_dir / "flagged_days.csv", index=False)
    actuals.to_csv(export_dir / "daily_actuals.csv", index=False)
