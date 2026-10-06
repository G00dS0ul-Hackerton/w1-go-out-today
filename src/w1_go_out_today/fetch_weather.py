import json
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


def clean_weather_data(data: dict[str, Any]) -> pd.DataFrame:
    """
    Cleans the raw Open-Meteo JSON response into a pandas DataFrame.
    Drops any rows with missing values in the requested columns.
    Never fills precipitation with 0.
    """
    hourly_data = data.get("hourly", {})
    if not hourly_data:
        raise ValueError("No hourly data found in response")

    df = pd.DataFrame(hourly_data)
    
    if "time" in df.columns:
        # Open-Meteo returns strings. We parse them so we have proper datetime types.
        # Open-Meteo provides these in the requested timezone (Africa/Lagos).
        df["time"] = pd.to_datetime(df["time"])
    
    initial_rows = len(df)
    df = df.dropna()
    final_rows = len(df)
    
    dropped_count = initial_rows - final_rows
    print(f"Dropped {dropped_count} rows due to missing values.")
    
    return df


def main() -> None:
    lat = 6.4541
    lon = 3.3947
    start_date = "2023-10-01"
    end_date = "2026-09-30"
    timezone = "Africa/Lagos"
    variables = (
        "temperature_2m,relative_humidity_2m,dew_point_2m,"
        "precipitation,cloud_cover,pressure_msl,wind_speed_10m"
    )

    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&hourly={variables}&timezone={timezone}"
    )

    print("Downloading historical weather data from Open-Meteo ...")
    req = urllib.request.Request(url, headers={"User-Agent": "w1-go-out-today"})
    with urllib.request.urlopen(req) as response:
        if response.status != 200:
            raise RuntimeError(f"Failed to fetch data: HTTP {response.status}")
        raw_data = json.loads(response.read().decode("utf-8"))

    print("Cleaning data...")
    df = clean_weather_data(raw_data)

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    output_path = data_dir / "lagos_weather.csv"
    df.to_csv(output_path, index=False)
    print(f"Saved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
