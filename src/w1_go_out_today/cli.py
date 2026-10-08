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
        help="Outdoor activity to plan for (e.g. 'a walk', 'a run', 'football', 'market', 'dry clothes', 'commute', 'picnic', 'hangout')",
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
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the web UI at http://localhost:8000",
    )
    parser.add_argument(
        "--prebuild",
        action="store_true",
        help="Pre-build the brief for instant playback and exit",
    )

    args = parser.parse_args()

    if args.serve:
        import uvicorn

        from w1_go_out_today.server import app

        uvicorn.run(app, host="127.0.0.1", port=8000)
        return

    if args.prebuild:
        import json
        from pathlib import Path

        from w1_go_out_today.live_weather import fetch_live_weather
        from w1_go_out_today.plan import compute_forecast_facts

        print("Running pre-build pipeline with live weather...")
        live_df = fetch_live_weather()
        live_df["time"] = pd.to_datetime(live_df["time"])
        six_am_rows = live_df[live_df["time"].dt.hour == 6]
        if len(six_am_rows) > 0:
            issue_time = six_am_rows["time"].max()
        else:
            issue_time = live_df["time"].max()

        csv_path = "data/lagos_weather.csv"
        csv_df = pd.read_csv(csv_path)
        csv_df["time"] = pd.to_datetime(csv_df["time"])
        df_pairs = prepare_data(csv_df, n=12, is_training=True)
        df_train, df_test, df_pre_test = get_splits(df_pairs, train_size=3000)
        clf, reg, feats, *_ = train_and_evaluate(
            df_train, df_test, df_pre_test, n_estimators=2, quiet=True
        )

        fcst = forecast(live_df, issue_time, n=12, clf=clf, reg=reg, features=feats)
        facts = compute_forecast_facts(fcst, activity="a walk")

        cache_dir = Path("data/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        slug = str(issue_time).replace(" ", "_").replace(":", "-")
        cache_file = cache_dir / f"forecast_{slug}.json"
        cache_data = {
            "fcst_df_records": fcst.to_dict(orient="records"),
            "facts": facts,
            "issue_time": str(issue_time),
        }
        cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
        print(f"Cached forecast to {cache_file}")

        plan_text = get_outdoor_plan(fcst, activity="a walk")
        print(f"Plan generated: {plan_text}")
        audio_path = generate_voice(plan_text, no_voice=args.no_voice)
        if audio_path:
            print(f"Prebuild audio cached to {audio_path}")
        print("Pre-build complete.")
        return

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
