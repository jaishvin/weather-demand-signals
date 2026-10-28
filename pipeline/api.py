"""Open-Meteo API client: requests session with retries, plus parsing to tidy DataFrames."""
import logging

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

log = logging.getLogger(__name__)


def make_session() -> requests.Session:
    """Session that retries on rate limits and server errors with exponential backoff."""
    retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "weather-demand-signals (github.com/jaishvin)"})
    return session


def parse_daily(payload: dict, city: str) -> pd.DataFrame:
    """Turns the API's `daily` block into one row per city per date."""
    daily = payload.get("daily")
    if not daily or "time" not in daily:
        raise ValueError(f"Unexpected API response for {city}: no 'daily' data")
    df = pd.DataFrame(daily).rename(columns=config.COLUMN_NAMES)
    df["city"] = city
    return df[["city", "date", "tmax", "tmin", "precip"]]


class OpenMeteoClient:
    def __init__(self, session: requests.Session | None = None, timeout: int = 30):
        self.session = session or make_session()
        self.timeout = timeout

    def _get(self, url: str, params: dict) -> dict:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _params(self, lat: float, lon: float) -> dict:
        return {"latitude": lat, "longitude": lon, "daily": ",".join(config.DAILY_VARS),
                "timezone": config.TIMEZONE}

    def fetch_history(self, city: str, lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
        log.info("History %s %s to %s", city, start, end)
        payload = self._get(config.ARCHIVE_URL, {**self._params(lat, lon), "start_date": start, "end_date": end})
        return parse_daily(payload, city)

    def fetch_forecast(self, city: str, lat: float, lon: float, days: int) -> pd.DataFrame:
        log.info("Forecast %s next %s days", city, days)
        payload = self._get(config.FORECAST_URL, {**self._params(lat, lon), "forecast_days": days})
        return parse_daily(payload, city)
