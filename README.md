# w1-go-out-today

A local, voice-first morning brief that tells people in Lagos the best time today to be outside.
(work in progress)

## Setup

This repository is managed with `uv` (Python 3.12), and includes `pytest` and `ruff`.

## Data Processing

To download historical hourly weather data for Lagos from scratch, run:
```bash
uv run python -m w1_go_out_today.fetch_weather
```

### Data Source
Weather data is provided by the [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license.

### Missing Data Handling
During the data fetch step, any hourly rows containing missing values (`null`) for any of the requested variables are dropped entirely.

## Changes after submission

## Forecast Evaluation

To evaluate the TabPFN model (predicting rain probability and temperature per hour) and compare it against climatology and persistence baselines, run:
```bash
uv run w1-go-out-today
```

To run the slower `n_estimators=10` execution for comparison against the default `n_estimators=2` output:
```bash
uv run w1-go-out-today --compare
```

### Metrics (Holdout: 2026-09-01 to 2026-09-30)

| Model | Temp MAE | Rain ROC AUC | Rain Brier Score |
| --- | --- | --- | --- |
| **TabPFN (n=2)** | **0.712** | **0.733** | **0.205** |
| Climatology | 0.750 | 0.606 | 0.231 |
| Persistence | 1.608 | 0.663 | 0.322 |

*(Note: Per-lead hourly numbers output by the CLI come from exactly 30 rows each (one 06:00 issue time per day for 30 days) so they can be quite noisy).*

**Note on TabPFN:**
The forecast uses TabPFN running locally on the CPU. The source code is licensed under the Apache License 2.0. The weights are TabPFN 3.5, which use a non-commercial licence (see the [TabPFN License File](https://github.com/PriorLabs/TabPFN/blob/main/LICENSE)). 
On Windows, set `TABPFN_TOKEN` in `.env`. The browser login prompt fails.
