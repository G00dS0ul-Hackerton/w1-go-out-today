import argparse
import os
import sys
from datetime import timedelta

import pandas as pd
from dotenv import load_dotenv

from w1_go_out_today.forecast import (
    forecast,
    get_splits,
    prepare_data,
    run_forecast_evaluation,
    train_and_evaluate,
)
from w1_go_out_today.plan import get_outdoor_plan
from w1_go_out_today.voice import generate_voice

load_dotenv()


def display_forecast_table(
    df: pd.DataFrame, fcst: pd.DataFrame, issue_time: pd.Timestamp
) -> None:
    """Format and print forecast table and actuals comparison if in history."""
    has_actuals = False
    actual_temps = []
    actual_rains = []
    df_indexed = df.set_index("time")

    for h in fcst["hours_ahead"]:
        target_time = issue_time + timedelta(hours=int(h))
        if target_time in df_indexed.index:
            row = df_indexed.loc[target_time]
            if not pd.isna(row["temperature_2m"]) and not pd.isna(row["precipitation"]):
                actual_temps.append(row["temperature_2m"])
                actual_rains.append("Yes" if row["precipitation"] >= 0.1 else "No")
                has_actuals = True
                continue
        actual_temps.append(None)
        actual_rains.append(None)

    display_df = fcst.copy()
    display_df["actual temp"] = [
        f"{t:.1f}°C" if t is not None else "-" for t in actual_temps
    ]
    display_df["actually rained?"] = [r if r is not None else "-" for r in actual_rains]
    display_df = display_df.rename(
        columns={"temp_pred": "forecast temp", "rain_prob": "rain chance"}
    )

    cols_to_print = [
        "time",
        "forecast temp",
        "actual temp",
        "rain chance",
        "actually rained?",
    ]
    if not has_actuals:
        cols_to_print = ["time", "forecast temp", "rain chance"]

    print(f"\n--- Forecast for issue time ({issue_time}) ---")
    print(display_df[cols_to_print].to_string(index=False))

    if has_actuals:
        valid_idx = [i for i, t in enumerate(actual_temps) if t is not None]
        raw_temp_preds = [
            float(str(t).replace("°C", "")) for t in display_df["forecast temp"]
        ]
        raw_rain_probs = [
            int(str(p).replace("%", "")) for p in display_df["rain chance"]
        ]
        errs = [abs(raw_temp_preds[i] - actual_temps[i]) for i in valid_idx]
        avg_err = sum(errs) / len(errs) if errs else 0
        rainy_hits = sum(
            1 for i in valid_idx if actual_rains[i] == "Yes" and raw_rain_probs[i] > 50
        )
        rainy_total = sum(1 for i in valid_idx if actual_rains[i] == "Yes")
        print(
            f"\nSummary for {issue_time.date()}: Avg temp error {avg_err:.1f}°C. "
            f"Rainy hours predicted (>50% chance): {rainy_hits}/{rainy_total}."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Go Out Today? - Morning Brief & Forecast for Lagos"
    )
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Run holdout evaluation against climatology and persistence baselines",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare n_estimators=2 vs 10 during evaluation",
    )
    parser.add_argument(
        "--sample-size-check",
        action="store_true",
        help="Run sample-size check on 1,000, 3,000, and 5,000 rows",
    )
    parser.add_argument(
        "--issue-time",
        type=str,
        default=None,
        help="Forecast issue time (default: latest 06:00 in data/lagos_weather.csv)",
    )
    parser.add_argument(
        "--activity",
        type=str,
        default="a walk",
        help="Outdoor activity to plan for (default: 'a walk')",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Skip voice generation with ElevenLabs",
    )
    parser.add_argument(
        "--play",
        action="store_true",
        help="Open/play the audio file after generating",
    )

    args = parser.parse_args()

    # Route evaluation requests directly to forecast evaluation logic
    if args.eval or args.sample_size_check:
        run_forecast_evaluation()
        return

    csv_path = "data/lagos_weather.csv"
    if not os.path.exists(csv_path):
        sys.stderr.write(
            f"Error: Weather data not found at {csv_path}. Run fetch_weather first.\n"
        )
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["time"])

    # Determine issue time
    if args.issue_time:
        try:
            issue_time = pd.to_datetime(args.issue_time)
        except (ValueError, TypeError) as e:
            sys.stderr.write(f"Error: Invalid --issue-time '{args.issue_time}': {e}\n")
            sys.exit(1)
    else:
        issue_time = df[df["time"].dt.hour == 6]["time"].max()

    # Train TabPFN on 3,000 training pairs
    df_pairs = prepare_data(df, n=12, is_training=True)
    df_train, df_test, df_pre_test = get_splits(df_pairs, train_size=3000)
    clf, reg, feats, _, _, _, _ = train_and_evaluate(
        df_train, df_test, df_pre_test, n_estimators=2, quiet=True
    )

    # Generate 12-hour forecast
    fcst = forecast(df, issue_time, n=12, clf=clf, reg=reg, features=feats)

    # Print forecast table
    display_forecast_table(df, fcst, issue_time)

    # Generate and print outdoor plan
    print(f"\n--- Outdoor Plan ({args.activity}) ---")
    plan_text = get_outdoor_plan(fcst, activity=args.activity)
    print(plan_text)

    # Generate voice with ElevenLabs (M5)
    print()
    generate_voice(plan_text, no_voice=args.no_voice, play=args.play)


if __name__ == "__main__":
    main()
