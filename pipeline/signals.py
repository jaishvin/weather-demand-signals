"""Seasonal normals and anomaly signals (heat, heavy rain, cold snaps) for the forecast window."""
import numpy as np
import pandas as pd

from . import config


def seasonal_normals(actuals: pd.DataFrame, targets: pd.DataFrame,
                     window: int = config.SEASON_WINDOW_DAYS, min_gap_days: int = 180) -> pd.DataFrame:
    """For each city and target date: the mean/std/90th percentile of the same calendar window
    (+/- `window` days) in previous years. History closer than `min_gap_days` is excluded, so a
    hot spell this month can't inflate its own "normal"."""
    hist = actuals.rename(columns={"date": "hist_date", "tmax": "h_tmax", "tmin": "h_tmin", "precip": "h_precip"})
    hist = hist.assign(hist_date=pd.to_datetime(hist["hist_date"]))
    hist["hist_doy"] = hist["hist_date"].dt.dayofyear

    t = targets[["city", "date"]].drop_duplicates().assign(date=lambda x: pd.to_datetime(x["date"]))
    t["doy"] = t["date"].dt.dayofyear

    m = t.merge(hist, on="city")
    gap = (m["doy"] - m["hist_doy"]).abs()
    m = m[(np.minimum(gap, 365 - gap) <= window)
          & (m["hist_date"] <= m["date"] - pd.Timedelta(days=min_gap_days))]

    normals = (m.groupby(["city", "date"])
                .agg(tmax_normal=("h_tmax", "mean"), tmax_std=("h_tmax", "std"),
                     tmin_normal=("h_tmin", "mean"), tmin_std=("h_tmin", "std"),
                     precip_p90=("h_precip", lambda s: s.quantile(0.9)), n_hist_days=("h_tmax", "size"))
                .reset_index())
    return normals


def add_anomalies(forecast: pd.DataFrame, normals: pd.DataFrame) -> pd.DataFrame:
    f = forecast.assign(date=pd.to_datetime(forecast["date"])).merge(normals, on=["city", "date"], how="left")
    f["tmax_z"] = (f["tmax"] - f["tmax_normal"]) / f["tmax_std"].replace(0, np.nan)
    f["tmin_z"] = (f["tmin"] - f["tmin_normal"]) / f["tmin_std"].replace(0, np.nan)
    return f


def detect_signals(f: pd.DataFrame) -> pd.DataFrame:
    """One row per city, date and signal type."""
    heat = f[(f["tmax_z"] >= config.HEAT_Z) | (f["tmax"] >= config.HEAT_ABS_C)].assign(
        signal="Heat", value=lambda x: x["tmax"], normal=lambda x: x["tmax_normal"], z=lambda x: x["tmax_z"],
        unit="°C max")
    rain = f[(f["precip"] >= config.RAIN_MIN_MM) & (f["precip"] >= f["precip_p90"].fillna(0))].assign(
        signal="Heavy rain", value=lambda x: x["precip"], normal=lambda x: x["precip_p90"], z=np.nan,
        unit="mm (normal = 90th pct)")
    cold = f[f["tmin_z"] <= config.COLD_Z].assign(
        signal="Cold snap", value=lambda x: x["tmin"], normal=lambda x: x["tmin_normal"], z=lambda x: x["tmin_z"],
        unit="°C min")
    cols = ["city", "date", "signal", "value", "normal", "z", "unit"]
    out = pd.concat([heat[cols], rain[cols], cold[cols]], ignore_index=True)
    return out.sort_values(["date", "city", "signal"]).reset_index(drop=True)


def summarize(signals: pd.DataFrame, cities) -> pd.DataFrame:
    """Per city: number of flagged days by signal, the first flagged date and the category watch-list."""
    rows = []
    for city in cities:
        s = signals[signals["city"] == city]
        row = {"City": city}
        for sig in config.SIGNAL_CATEGORIES:
            row[f"{sig} days"] = int((s["signal"] == sig).sum())
        row["First flag"] = s["date"].min().strftime("%d %b") if len(s) else "—"
        active = [sig for sig in config.SIGNAL_CATEGORIES if (s["signal"] == sig).any()]
        row["Watch-list"] = "; ".join(config.SIGNAL_CATEGORIES[a] for a in active) if active else "No unusual weather"
        rows.append(row)
    return pd.DataFrame(rows)
