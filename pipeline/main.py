"""Runs the full pipeline: incremental API loads -> SQLite -> signals -> report and exports.

Usage:  python -m pipeline.main
"""
import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, db, report, signals
from .api import OpenMeteoClient

log = logging.getLogger("pipeline")


def history_window(last_date: str | None, today: pd.Timestamp) -> tuple[str, str] | None:
    """Incremental load: from the last stored day (minus a small overlap), or a full backfill on first run."""
    end = today - timedelta(days=config.ARCHIVE_LAG_DAYS)
    if last_date is None:
        start = today - pd.DateOffset(years=config.HISTORY_YEARS)
    else:
        start = pd.Timestamp(last_date) - timedelta(days=config.OVERLAP_DAYS)
    if start > end:
        return None
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def run(client=None, today: pd.Timestamp | None = None, db_path=config.DB_PATH,
        report_dir=config.REPORT_DIR, export_dir=config.EXPORT_DIR, readme_path=config.README_PATH) -> dict:
    client = client or OpenMeteoClient()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    today = pd.Timestamp(today or now.date())
    run_label = now.strftime("%d %b %Y, %H:%M IST")
    con = db.connect(db_path)

    # 1. Incremental load of actual weather
    actual_rows = 0
    for city, (lat, lon) in config.CITIES.items():
        window = history_window(db.last_actual_date(con, city), today)
        if window:
            hist = client.fetch_history(city, lat, lon, *window)
            actual_rows += db.upsert_actuals(con, hist, now.isoformat(timespec="seconds"))

    # 2. Forecast for the next 14 days (stored, so forecast accuracy can be tracked later)
    forecast = pd.concat([client.fetch_forecast(city, lat, lon, config.FORECAST_DAYS + 1)
                          for city, (lat, lon) in config.CITIES.items()], ignore_index=True)
    forecast = forecast[pd.to_datetime(forecast["date"]) > today]
    forecast_rows = db.save_forecast(con, forecast, today.strftime("%Y-%m-%d"))

    # 3. Signals vs seasonal normals
    actuals = db.read_actuals(con)
    normals = signals.seasonal_normals(actuals, forecast)
    f = signals.add_anomalies(forecast, normals)
    flagged = signals.detect_signals(f)
    summary = signals.summarize(flagged, config.CITIES)

    # 4. Outputs
    report_dir.mkdir(parents=True, exist_ok=True)
    report.make_chart(f, report_dir / "forecast_vs_normal.png")
    md = report.build_report(run_label, summary, flagged, db.forecast_accuracy(con), db.coverage(con))
    (report_dir / "weekly_report.md").write_text(md, encoding="utf-8")
    report.export_csvs(export_dir, f, flagged, actuals)
    report.update_readme(readme_path, run_label, summary)

    db.log_run(con, now.isoformat(timespec="seconds"), actual_rows, forecast_rows, len(flagged), "success")
    con.close()
    result = {"actual_rows_loaded": actual_rows, "forecast_rows": forecast_rows, "flagged_days": len(flagged)}
    log.info("Done: %s", result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    run()
