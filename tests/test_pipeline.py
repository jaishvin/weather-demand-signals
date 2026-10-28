"""Tests run offline: a fake client returns payloads in the same JSON shape as the Open-Meteo API."""
import numpy as np
import pandas as pd
import pytest

from pipeline import api, db, main, signals


def fake_payload(dates, tmax, tmin, precip):
    return {"latitude": 19.07, "longitude": 72.87, "timezone": "Asia/Kolkata",
            "daily_units": {"time": "iso8601", "temperature_2m_max": "°C"},
            "daily": {"time": [d.strftime("%Y-%m-%d") for d in dates],
                      "temperature_2m_max": list(tmax), "temperature_2m_min": list(tmin),
                      "precipitation_sum": list(precip)}}


def seasonal(dates, base, amp, seed):
    rng = np.random.default_rng(seed)
    doy = np.asarray(dates.dayofyear)
    return base + amp * np.sin(2 * np.pi * (doy - 80) / 365) + rng.normal(0, 1, len(dates))


class FakeClient:
    """Normal seasonal weather, plus a heatwave and a downpour in Mumbai's forecast."""
    def __init__(self):
        self.history_calls = []

    def fetch_history(self, city, lat, lon, start, end):
        self.history_calls.append((city, start, end))
        d = pd.date_range(start, end, freq="D")
        p = fake_payload(d, seasonal(d, 32, 4, 1), seasonal(d, 22, 4, 2), np.clip(np.random.default_rng(3).gamma(0.5, 4, len(d)), 0, None))
        return api.parse_daily(p, city)

    def fetch_forecast(self, city, lat, lon, days):
        d = pd.date_range(self.today, periods=days, freq="D")
        tmax, tmin, rain = seasonal(d, 32, 4, 4), seasonal(d, 22, 4, 5), np.full(days, 1.0)
        if city == "Mumbai":
            tmax[3], rain[6] = tmax[3] + 12, 80.0
        return api.parse_daily(fake_payload(d, tmax, tmin, rain), city)


@pytest.fixture
def paths(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n<!-- REPORT:START -->\nold\n<!-- REPORT:END -->\nfooter\n")
    return dict(db_path=tmp_path / "data" / "weather.db", report_dir=tmp_path / "reports",
                export_dir=tmp_path / "data" / "exports", readme_path=readme)


def test_parse_daily_shape():
    d = pd.date_range("2026-01-01", periods=3)
    df = api.parse_daily(fake_payload(d, [30, 31, 32], [20, 21, 22], [0, 5, 10]), "Mumbai")
    assert list(df.columns) == ["city", "date", "tmax", "tmin", "precip"]
    assert len(df) == 3 and df["city"].eq("Mumbai").all()


def test_parse_daily_rejects_bad_payload():
    with pytest.raises(ValueError):
        api.parse_daily({"error": True, "reason": "bad request"}, "Mumbai")


def test_upsert_is_idempotent(tmp_path):
    con = db.connect(tmp_path / "t.db")
    df = pd.DataFrame({"city": ["Mumbai"] * 2, "date": ["2026-01-01", "2026-01-02"],
                       "tmax": [30.0, 31.0], "tmin": [20.0, 21.0], "precip": [0.0, None]})
    assert db.upsert_actuals(con, df, "t1") == 1          # row with a missing value is skipped
    df.loc[0, "tmax"] = 35.0
    db.upsert_actuals(con, df, "t2")
    out = db.read_actuals(con)
    assert len(out) == 1 and out.loc[0, "tmax"] == 35.0  # revised value overwritten, no duplicate


def test_history_window_incremental():
    today = pd.Timestamp("2026-10-29")
    assert main.history_window(None, today)[0] == "2021-10-29"                       # full backfill
    assert main.history_window("2026-10-20", today) == ("2026-10-17", "2026-10-24")  # overlap + archive lag
    assert main.history_window("2026-10-28", today) is None                           # already up to date


def test_circular_season_window():
    hist = pd.DataFrame({"city": "X", "date": ["2025-12-30", "2025-06-30"], "tmax": [10.0, 40.0],
                         "tmin": [5.0, 30.0], "precip": [0.0, 0.0]})
    n = signals.seasonal_normals(hist, pd.DataFrame({"city": ["X"], "date": ["2026-01-03"]}), min_gap_days=0)
    assert n.loc[0, "tmax_normal"] == 10.0   # 30 Dec counts as the same season as 3 Jan; June does not


def test_end_to_end(paths):
    client = FakeClient()
    client.today = pd.Timestamp("2026-10-29")
    result = main.run(client=client, today=client.today, **paths)

    assert result["actual_rows_loaded"] > 6 * 365 * 4      # ~5-year backfill for 6 cities
    assert result["forecast_rows"] == 6 * 14
    flagged = pd.read_csv(paths["export_dir"] / "flagged_days.csv")
    mumbai = flagged[flagged["city"] == "Mumbai"]
    assert {"Heat", "Heavy rain"} <= set(mumbai["signal"])
    assert (paths["report_dir"] / "forecast_vs_normal.png").exists()
    report_md = (paths["report_dir"] / "weekly_report.md").read_text()
    assert "Flagged days" in report_md
    readme = paths["readme_path"].read_text()
    assert "\nold\n" not in readme and "Latest run" in readme and readme.endswith("footer\n")

    # Second run a week later only loads the new days and can now score last week's forecasts
    client.today = pd.Timestamp("2026-11-12")
    result2 = main.run(client=client, today=client.today, **paths)
    assert 0 < result2["actual_rows_loaded"] < 6 * 30
    con = db.connect(paths["db_path"])
    assert len(db.forecast_accuracy(con)) > 0
