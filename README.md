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
