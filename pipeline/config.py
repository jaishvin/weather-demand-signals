"""Settings for the weather demand-signal pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "weather.db"
EXPORT_DIR = ROOT / "data" / "exports"
REPORT_DIR = ROOT / "reports"
README_PATH = ROOT / "README.md"

# Metro markets to monitor (latitude, longitude)
CITIES = {
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Bengaluru": (12.9716, 77.5946),
    "Hyderabad": (17.3850, 78.4867),
    "Chennai": (13.0827, 80.2707),
    "Kolkata": (22.5726, 88.3639),
}

TIMEZONE = "Asia/Kolkata"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"]
COLUMN_NAMES = {"time": "date", "temperature_2m_max": "tmax", "temperature_2m_min": "tmin",
                "precipitation_sum": "precip"}

HISTORY_YEARS = 5         # years of history used to define "normal" weather
FORECAST_DAYS = 14        # forecast horizon analysed in the report
ARCHIVE_LAG_DAYS = 5      # the archive API publishes actuals with a ~5-day delay
OVERLAP_DAYS = 3          # re-load the last few days on each run in case values were revised
SEASON_WINDOW_DAYS = 7    # "normal" = same calendar window (+/- 7 days) in previous years

# Signal thresholds
HEAT_Z, HEAT_ABS_C = 1.5, 40.0      # tmax z-score vs normal, or an absolute ceiling
COLD_Z = -1.5                       # tmin z-score vs normal
RAIN_MIN_MM = 15.0                  # heavy rain: at least 15 mm and above the 90th percentile

# Illustrative category watch-list for demand planners (validate against sales data)
SIGNAL_CATEGORIES = {
    "Heat": "Summer cottons, linen, sunglasses, sunscreen",
    "Heavy rain": "Rainwear, waterproof footwear, umbrellas",
    "Cold snap": "Jackets, sweatshirts, thermals",
}
