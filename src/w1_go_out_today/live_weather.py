from __future__ import annotations

import logging

import httpx
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_live_weather(past_days: int = 2) -> pd.DataFrame:
    """Fetch recent hourly weather data from Open-Meteo."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 6.4541,
        "longitude": 3.3947,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,cloud_cover,pressure_msl,wind_speed_10m",
        "past_days": past_days,
        "forecast_days": 1,
        "timezone": "Africa/Lagos",
    }
    logger.info("Fetching live weather data from Open-Meteo")
    try:
        response = httpx.get(url, params=params, timeout=15.0)
        response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise RuntimeError(f"Network error fetching weather: {e}") from e

    data = response.json()
    hourly_data = data.get("hourly", {})
    if not hourly_data:
        return pd.DataFrame()

    df = pd.DataFrame(hourly_data)
    df["time"] = pd.to_datetime(df["time"])
    df = df.dropna()
    df = df.sort_values("time").reset_index(drop=True)
    return df
