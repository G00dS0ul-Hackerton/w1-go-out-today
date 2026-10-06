import json
from pathlib import Path

import pandas as pd

from w1_go_out_today.fetch_weather import clean_weather_data


def test_clean_weather_data_drops_nulls_and_keeps_timezone_correctly():
    fixture_path = Path(__file__).parent / "fixtures" / "weather_fixture.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = clean_weather_data(data)
    
    # Should drop index 1 (null precipitation) and 2 (null temperature), leaving 2 rows.
    assert len(df) == 2
    
    # Time strings "2023-10-01T00:00" will be parsed correctly
    times = df["time"].tolist()
    assert times[0] == pd.Timestamp("2023-10-01T00:00")
    assert times[1] == pd.Timestamp("2023-10-01T03:00")
