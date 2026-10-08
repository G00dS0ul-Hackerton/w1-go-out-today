import httpx
import pytest

from w1_go_out_today.live_weather import fetch_live_weather


def test_fetch_returns_correct_columns(monkeypatch):
    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self._json_data = json_data
            self.status_code = status_code

        def raise_for_status(self):
            pass

        def json(self):
            return self._json_data

    def mock_get(*args, **kwargs):
        mock_data = {
            "hourly": {
                "time": ["2023-10-01T00:00", "2023-10-01T01:00", "2023-10-01T02:00"],
                "temperature_2m": [25.0, 24.5, None],
                "relative_humidity_2m": [80.0, 82.0, 85.0],
                "dew_point_2m": [22.0, 21.0, 22.0],
                "precipitation": [0.0, 1.0, 0.0],
                "cloud_cover": [50.0, 60.0, 100.0],
                "pressure_msl": [1012.0, 1011.0, 1010.0],
                "wind_speed_10m": [5.0, 6.0, 4.0],
            }
        }
        return MockResponse(mock_data)

    monkeypatch.setattr(httpx, "get", mock_get)

    df = fetch_live_weather()

    expected_columns = [
        "time",
        "temperature_2m",
        "relative_humidity_2m",
        "dew_point_2m",
        "precipitation",
        "cloud_cover",
        "pressure_msl",
        "wind_speed_10m",
    ]
    assert list(df.columns) == expected_columns
    assert len(df) == 2  # one row had None, should be dropped


def test_fetch_raises_on_network_error(monkeypatch):
    def mock_get_error(*args, **kwargs):
        raise httpx.ConnectError("Connection failed")

    monkeypatch.setattr(httpx, "get", mock_get_error)

    with pytest.raises(RuntimeError, match="Network error fetching weather"):
        fetch_live_weather()
