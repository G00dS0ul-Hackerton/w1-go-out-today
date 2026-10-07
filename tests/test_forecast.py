from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

# Monkey patch threadpoolctl
import threadpoolctl

threadpoolctl.ThreadpoolController._find_libraries_on_windows = lambda self: None


from w1_go_out_today.forecast import (
    build_climatology,
    forecast,
    get_splits,
    prepare_data,
    train_and_evaluate,
)


class StubTabPFNClassifier:
    def __init__(self, **kwargs):
        self.classes_ = [0, 1]

    def fit(self, X, y):
        return self

    def predict_proba(self, X):
        return np.array([[0.5, 0.5] for _ in range(len(X))])


class StubTabPFNRegressor:
    def __init__(self, **kwargs):
        pass

    def fit(self, X, y):
        return self

    def predict(self, X):
        return np.ones(len(X)) * 25.0


@pytest.fixture
def mock_tabpfn(monkeypatch):
    monkeypatch.setattr(
        "w1_go_out_today.forecast.TabPFNClassifier", StubTabPFNClassifier
    )
    monkeypatch.setattr("w1_go_out_today.forecast.TabPFNRegressor", StubTabPFNRegressor)


def test_prepare_data_no_leakage():
    times = pd.date_range("2023-01-01 00:00", periods=48, freq="h")
    df = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": np.random.rand(48) * 10 + 20,
            "relative_humidity_2m": np.random.rand(48),
            "dew_point_2m": np.random.rand(48),
            "precipitation": np.random.rand(48),
            "cloud_cover": np.random.rand(48),
            "pressure_msl": np.random.rand(48),
            "wind_speed_10m": np.random.rand(48),
        }
    )

    df_pairs = prepare_data(df, n=3)

    row = df_pairs.iloc[0]
    issue_time = row.name
    h = row["hours_ahead"]
    expected_target_time = issue_time + timedelta(hours=h)

    expected_temp = df[df["time"] == expected_target_time]["temperature_2m"].values[0]
    assert np.isclose(row["temp_target"], expected_temp)
    assert "rain_target" in df_pairs.columns


def test_get_splits():
    times = pd.date_range("2023-01-01 00:00", periods=400 * 24, freq="h")
    df = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": np.random.rand(len(times)),
            "relative_humidity_2m": np.random.rand(len(times)),
            "dew_point_2m": np.random.rand(len(times)),
            "precipitation": np.random.rand(len(times)),
            "cloud_cover": np.random.rand(len(times)),
            "pressure_msl": np.random.rand(len(times)),
            "wind_speed_10m": np.random.rand(len(times)),
        }
    )
    df_pairs = prepare_data(df, n=2)
    df_train, df_test, _ = get_splits(df_pairs)

    max_time = df_pairs.index.max()
    test_start = max_time - timedelta(days=30)

    assert df_test.index.min() >= test_start
    assert all(df_test.index.hour == 6)

    assert df_train.index.max() < test_start
    assert len(df_train) <= 3000


def test_climatology():
    times = pd.date_range("2023-01-01 00:00", periods=100, freq="h")
    df = pd.DataFrame(
        {
            "target_month": times.month,
            "target_hour": times.hour,
            "temp_target": np.ones(100) * 20,
            "rain_target": np.zeros(100),
        }
    )
    clim = build_climatology(df)
    assert "clim_temp" in clim.columns
    assert "clim_rain_prob" in clim.columns


def test_train_and_evaluate(mock_tabpfn):
    times = pd.date_range("2023-01-01 00:00", periods=400 * 24, freq="h")
    df = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": np.random.rand(len(times)),
            "relative_humidity_2m": np.random.rand(len(times)),
            "dew_point_2m": np.random.rand(len(times)),
            "precipitation": np.random.rand(len(times)),
            "cloud_cover": np.random.rand(len(times)),
            "pressure_msl": np.random.rand(len(times)),
            "wind_speed_10m": np.random.rand(len(times)),
        }
    )
    df_pairs = prepare_data(df, n=2)
    df_train, df_test, df_pre_test = get_splits(df_pairs)

    clf, reg, feats, *_ = train_and_evaluate(
        df_train, df_test, df_pre_test, n_estimators=2
    )
    assert clf is not None
    assert reg is not None
    assert len(feats) > 0


def test_forecast_latest_issue_time(mock_tabpfn):
    times = pd.date_range("2023-01-01 00:00", periods=100, freq="h")
    df = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": np.random.rand(len(times)),
            "relative_humidity_2m": np.random.rand(len(times)),
            "dew_point_2m": np.random.rand(len(times)),
            "precipitation": np.random.rand(len(times)),
            "cloud_cover": np.random.rand(len(times)),
            "pressure_msl": np.random.rand(len(times)),
            "wind_speed_10m": np.random.rand(len(times)),
        }
    )
    latest_time = df["time"].max()

    # Need to get a stub model
    clf = StubTabPFNClassifier()
    reg = StubTabPFNRegressor()
    feats = ["temperature_2m", "relative_humidity_2m", "hours_ahead"]  # stub features

    # This currently crashes because prepare_data drops NA targets for the latest row
    fcst = forecast(df, latest_time, n=3, clf=clf, reg=reg, features=feats)
    assert len(fcst) == 3


def test_forecast_no_actuals_leakage(mock_tabpfn):
    # Create 100 hours of history
    times = pd.date_range("2023-01-01 00:00", periods=100, freq="h")
    df = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": np.random.rand(100),
            "relative_humidity_2m": np.random.rand(100),
            "dew_point_2m": np.random.rand(100),
            "precipitation": np.random.rand(100),
            "cloud_cover": np.random.rand(100),
            "pressure_msl": np.random.rand(100),
            "wind_speed_10m": np.random.rand(100),
        }
    )

    # Issue time is the absolute last row. No future rows exist in the DataFrame.
    latest_time = df["time"].max()

    clf = StubTabPFNClassifier()
    reg = StubTabPFNRegressor()
    feats = ["temperature_2m", "relative_humidity_2m", "hours_ahead"]

    # If forecast() tries to look up targets at `latest_time + h`, it would fail or leak.
    # Since the rows literally don't exist, success proves no future rows are required.
    fcst = forecast(df, latest_time, n=12, clf=clf, reg=reg, features=feats)

    assert len(fcst) == 12
    # Ensure it only outputs what we expect and no actuals
    expected_cols = {"time", "hours_ahead", "temp_pred", "rain_prob"}
    assert set(fcst.columns) == expected_cols
