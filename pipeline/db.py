"""SQLite storage: schema, idempotent upserts and the SQL queries the report uses."""
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_actuals (
    city TEXT NOT NULL, date TEXT NOT NULL,
    tmax REAL, tmin REAL, precip REAL, loaded_at TEXT NOT NULL,
    PRIMARY KEY (city, date)
);
CREATE TABLE IF NOT EXISTS forecast_snapshots (
    run_date TEXT NOT NULL, city TEXT NOT NULL, date TEXT NOT NULL, lead_days INTEGER NOT NULL,
    tmax REAL, tmin REAL, precip REAL,
    PRIMARY KEY (run_date, city, date)
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_at TEXT NOT NULL, actual_rows INTEGER, forecast_rows INTEGER, flagged_days INTEGER, status TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def upsert_actuals(con: sqlite3.Connection, df: pd.DataFrame, loaded_at: str) -> int:
    """Insert new days, overwrite revised ones. Rows with missing values are skipped (re-fetched next run)."""
    df = df.dropna(subset=["tmax", "tmin", "precip"])
    rows = [(r.city, r.date, float(r.tmax), float(r.tmin), float(r.precip), loaded_at)
            for r in df.itertuples(index=False)]
    con.executemany(
        """INSERT INTO daily_actuals (city, date, tmax, tmin, precip, loaded_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (city, date) DO UPDATE SET
             tmax = excluded.tmax, tmin = excluded.tmin, precip = excluded.precip, loaded_at = excluded.loaded_at""",
        rows)
    con.commit()
    return len(rows)


def save_forecast(con: sqlite3.Connection, df: pd.DataFrame, run_date: str) -> int:
    run = pd.Timestamp(run_date)
    rows = [(run_date, r.city, r.date, int((pd.Timestamp(r.date) - run).days), r.tmax, r.tmin, r.precip)
            for r in df.itertuples(index=False)]
    con.executemany(
        """INSERT OR REPLACE INTO forecast_snapshots (run_date, city, date, lead_days, tmax, tmin, precip)
           VALUES (?, ?, ?, ?, ?, ?, ?)""", rows)
    con.commit()
    return len(rows)


def last_actual_date(con: sqlite3.Connection, city: str) -> str | None:
    with closing(con.execute("SELECT MAX(date) FROM daily_actuals WHERE city = ?", (city,))) as cur:
        return cur.fetchone()[0]


def read_actuals(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql("SELECT city, date, tmax, tmin, precip FROM daily_actuals ORDER BY city, date", con)


def forecast_accuracy(con: sqlite3.Connection) -> pd.DataFrame:
    """Compares past forecasts with what actually happened, by forecast lead time."""
    sql = """
    SELECT CASE WHEN f.lead_days <= 3 THEN '1-3 days'
                WHEN f.lead_days <= 7 THEN '4-7 days'
                ELSE '8-14 days' END                       AS lead_time,
           COUNT(*)                                        AS n_forecasts,
           ROUND(AVG(ABS(f.tmax - a.tmax)), 2)             AS mae_tmax_c,
           ROUND(AVG(f.tmax - a.tmax), 2)                  AS bias_tmax_c,
           ROUND(AVG(ABS(f.precip - a.precip)), 2)         AS mae_precip_mm
    FROM forecast_snapshots f
    JOIN daily_actuals a ON a.city = f.city AND a.date = f.date
    WHERE f.lead_days BETWEEN 1 AND 14
    GROUP BY lead_time
    ORDER BY MIN(f.lead_days)
    """
    return pd.read_sql(sql, con)


def coverage(con: sqlite3.Connection) -> pd.DataFrame:
    sql = """
    SELECT city, COUNT(*) AS days_stored, MIN(date) AS first_date, MAX(date) AS last_date
    FROM daily_actuals GROUP BY city ORDER BY city
    """
    return pd.read_sql(sql, con)


def log_run(con: sqlite3.Connection, run_at: str, actual_rows: int, forecast_rows: int,
            flagged_days: int, status: str) -> None:
    con.execute("INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?)",
                (run_at, actual_rows, forecast_rows, flagged_days, status))
    con.commit()
