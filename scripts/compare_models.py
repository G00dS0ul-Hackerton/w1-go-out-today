import json
import os
import re
import sys
import time
import urllib.request

import pandas as pd
from dotenv import load_dotenv

from w1_go_out_today.forecast import (
    forecast,
    get_splits,
    prepare_data,
    train_and_evaluate,
)
from w1_go_out_today.plan import (
    compute_forecast_facts,
    load_prompt,
    validate_plan_output,
)

load_dotenv()


def check_time_window(text: str) -> bool:
    """Check if the text names a specific time window or specific time."""
    pattern = (
        r"(?:between|from|around)?\s*\b\d{1,2}(?::\d{2})?\s*(?:to|-|and)\s*\b\d{1,2}(?::\d{2})?|"
        r"\baround\s+\d{1,2}:\d{2}\b|\bat\s+\d{1,2}:\d{2}\b"
    )
    return bool(re.search(pattern, text, re.IGNORECASE))


def check_reason(text: str) -> bool:
    """Check if text gives a reason related to rain or heat/temperature."""
    lower = text.lower()
    has_rain_reason = "rain" in lower or "chance" in lower
    has_temp_reason = (
        "temp" in lower or "heat" in lower or "cool" in lower or "°c" in lower
    )
    return has_rain_reason or has_temp_reason


def run_ollama_call(
    prompt: str,
    model: str,
    base_url: str = "http://localhost:11434",
    seed: int = 42,
) -> tuple[str, float]:
    endpoint = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "1m",
        "options": {
            "temperature": 0.3,
            "seed": seed,
        },
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
    )

    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=240) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    duration = time.perf_counter() - t0
    return result.get("response", "").strip(), duration


def main():
    csv_path = "data/lagos_weather.csv"
    cache_path = "data/forecast_cache.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["time"])
    latest_06 = df[df["time"].dt.hour == 6]["time"].max()

    if os.path.exists(cache_path):
        print(f"Loading cached 12-hour forecast from {cache_path}...")
        fcst = pd.read_csv(cache_path)
    else:
        print("Loading weather data and fitting TabPFN...")
        df_pairs = prepare_data(df, n=12, is_training=True)
        df_train, df_test, df_pre_test = get_splits(df_pairs, train_size=3000)
        clf, reg, feats, *_ = train_and_evaluate(
            df_train, df_test, df_pre_test, n_estimators=2, quiet=True
        )
        print(f"Generating 12-hour forecast for issue time {latest_06}...")
        fcst = forecast(df, latest_06, n=12, clf=clf, reg=reg, features=feats)
        fcst.to_csv(cache_path, index=False)

    print("Forecast table:")
    print(fcst[["time", "temp_pred", "rain_prob"]].to_string(index=False))

    # Compute facts from the forecast
    facts = compute_forecast_facts(fcst, activity="a walk")
    print("\nComputed Forecast Facts:")
    print(facts["facts_block"])

    prompt_template = load_prompt("prompts/plan.txt")
    prompt = prompt_template.format(
        activity="a walk",
        facts_block=facts["facts_block"],
    )

    model = "qwen2.5-coder:7b"
    print(
        f"\nRunning 3 evaluations for {model} with facts-based prompting & stronger guard..."
    )
    runs = []
    for i in range(1, 4):
        seed = 42 + (i - 1) * 7
        print(f"  Run {i}/3 (seed={seed})...", end="", flush=True)
        text, duration = run_ollama_call(prompt, model, seed=seed)
        print(f" done in {duration:.2f}s")

        window_ok = check_time_window(text)
        reason_ok = check_reason(text)
        guard_ok, guard_msg = validate_plan_output(text, facts)

        runs.append(
            {
                "run": i,
                "seed": seed,
                "duration": duration,
                "text": text,
                "window": window_ok,
                "reason": reason_ok,
                "guard": guard_ok,
                "guard_msg": guard_msg,
            }
        )

    # Read existing report
    output_path = os.path.join(
        "..", "docs", "challenge", "w1", "m4-model-comparison.md"
    )
    abs_output_path = os.path.abspath(output_path)

    existing_content = ""
    if os.path.exists(abs_output_path):
        with open(abs_output_path, "r", encoding="utf-8") as f:
            existing_content = f.read()

    # Append new section
    new_section_lines = [
        "",
        "---",
        "",
        "## Refined Architecture: Facts-Based Prompting & Stronger Guard (`qwen2.5-coder:7b`)",
        "",
        f"- **Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- **Architecture Change:** In-code computation of meteorological facts (best window: longest run <=40% rain, avoid window: run >=60% rain, heat hours >=32°C). Only facts are provided to LLM.",
        "- **Stronger Guard:** Numbers restricted strictly to facts block; 32°C rejected unless heat hours exist; sentence fragments rejected; avoid window required.",
        "",
        "### Precomputed Facts Block Given to LLM",
        "",
        "```text",
        facts["facts_block"],
        "```",
        "",
        "### Results Summary (Facts-Based)",
        "",
        "| Model | Run | Latency | Time Window | Reason | Guard Passed | Notes |",
        "| --- | --- | --- | :---: | :---: | :---: | --- |",
    ]

    for r in runs:
        w_mark = "✓" if r["window"] else "✗"
        rs_mark = "✓" if r["reason"] else "✗"
        g_mark = "✓" if r["guard"] else "✗"
        note = "All checks passed" if r["guard"] else r["guard_msg"]
        new_section_lines.append(
            f"| `{model}` | Run {r['run']} | {r['duration']:.2f}s | {w_mark} | {rs_mark} | {g_mark} | {note} |"
        )

    new_section_lines.append("\n### Detailed Run Outputs\n")
    durations = [r["duration"] for r in runs]
    avg_dur = sum(durations) / len(durations)
    new_section_lines.append(
        f"**Average Latency:** {avg_dur:.2f}s (Min: {min(durations):.2f}s, Max: {max(durations):.2f}s)\n"
    )

    for r in runs:
        w_mark = "✓" if r["window"] else "✗"
        rs_mark = "✓" if r["reason"] else "✗"
        g_mark = "✓" if r["guard"] else "✗"
        new_section_lines.append(f"#### Run {r['run']} ({r['duration']:.2f}s)")
        new_section_lines.append(
            f"- Checks: Time Window {w_mark} | Reason {rs_mark} | Guard {g_mark}"
        )
        if not r["guard"]:
            new_section_lines.append(f"- Guard rejection: {r['guard_msg']}")
        new_section_lines.append("```text")
        new_section_lines.append(r["text"])
        new_section_lines.append("```\n")

    full_updated_content = (
        existing_content.rstrip() + "\n" + "\n".join(new_section_lines) + "\n"
    )

    with open(abs_output_path, "w", encoding="utf-8") as f:
        f.write(full_updated_content)

    print(
        "\nComparison report updated with facts-based runs at: docs/challenge/w1/m4-model-comparison.md"
    )


if __name__ == "__main__":
    main()
