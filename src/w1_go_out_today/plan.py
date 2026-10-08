import json
import os
import re
import sys
import urllib.error
import urllib.request

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DEFAULT_PROMPT_PATH = "prompts/plan.txt"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"


def load_prompt(prompt_path: str = DEFAULT_PROMPT_PATH) -> str:
    """Load the prompt template from the given file path."""
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def format_hour_12h(time_str: str) -> str:
    """Convert '16:00' to '4 pm', '06:00' to '6 am', '12:00' to '12 pm', '00:00' to '12 am'."""
    try:
        parts = time_str.split(":")
        h = int(parts[0])
        suffix = "am" if h < 12 else "pm"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12} {suffix}"
    except (ValueError, IndexError):
        return time_str


def compute_forecast_facts(fcst_df: pd.DataFrame, activity: str = "a walk") -> dict:
    """
    Compute structured facts from the forecast so the LLM does not need to do reasoning:
    - best window: longest run of contiguous hours with rain chance <= 40% (ties -> lowest average rain).
      If no hours <= 40%, pick single hour with lowest rain chance.
    - window to avoid: contiguous run of hours with rain chance >= 60%.
    - heat hours: hours with temperature >= 32.0°C.
    Formatted voice-friendly in 12-hour format ('4 pm') with at most one weather number per window.
    """
    if fcst_df.empty:
        return {
            "best_window": None,
            "avoid_window": None,
            "heat_hours": [],
            "has_heat_hours": False,
            "facts_block": "No forecast data available.",
        }

    parsed = []
    for _, row in fcst_df.iterrows():
        t = str(row.get("time", "07:00")).strip()
        try:
            temp = float(
                str(row.get("temp_pred", "25"))
                .replace("°C", "")
                .replace("C", "")
                .strip()
            )
        except ValueError:
            temp = 25.0
        try:
            rain = int(str(row.get("rain_prob", "0")).replace("%", "").strip())
        except ValueError:
            rain = 0
        parsed.append({"time": t, "temp": temp, "rain": rain})

    # 1. Best window: longest contiguous run with rain <= 40%
    runs = []
    current_run = []
    for p in parsed:
        if p["rain"] <= 40:
            current_run.append(p)
        else:
            if current_run:
                runs.append(current_run)
                current_run = []
    if current_run:
        runs.append(current_run)

    if runs:
        max_len = max(len(r) for r in runs)
        longest_runs = [r for r in runs if len(r) == max_len]
        best_run = min(longest_runs, key=lambda r: sum(x["rain"] for x in r) / len(r))
    else:
        best_run = [min(parsed, key=lambda x: x["rain"])]

    best_start = best_run[0]["time"]
    best_end = best_run[-1]["time"]
    best_rain_min = min(x["rain"] for x in best_run)
    best_rain_max = max(x["rain"] for x in best_run)
    best_temp_min = min(x["temp"] for x in best_run)
    best_temp_max = max(x["temp"] for x in best_run)

    best_window = {
        "start": best_start,
        "end": best_end,
        "rain_min": best_rain_min,
        "rain_max": best_rain_max,
        "temp_min": best_temp_min,
        "temp_max": best_temp_max,
        "rows": best_run,
    }

    # 2. Window to avoid: contiguous run with rain >= 60%
    avoid_runs = []
    current_avoid = []
    for p in parsed:
        if p["rain"] >= 60:
            current_avoid.append(p)
        else:
            if current_avoid:
                avoid_runs.append(current_avoid)
                current_avoid = []
    if current_avoid:
        avoid_runs.append(current_avoid)

    if avoid_runs:
        max_avoid_len = max(len(r) for r in avoid_runs)
        avoid_longest = [r for r in avoid_runs if len(r) == max_avoid_len]
        avoid_run = max(avoid_longest, key=lambda r: sum(x["rain"] for x in r) / len(r))
        avoid_start = avoid_run[0]["time"]
        avoid_end = avoid_run[-1]["time"]
        avoid_rain_min = min(x["rain"] for x in avoid_run)
        avoid_rain_max = max(x["rain"] for x in avoid_run)
        avoid_window = {
            "start": avoid_start,
            "end": avoid_end,
            "rain_min": avoid_rain_min,
            "rain_max": avoid_rain_max,
            "rows": avoid_run,
        }
    else:
        avoid_window = None

    # 3. Heat hours: temp >= 32°C
    heat_hours = [p["time"] for p in parsed if p["temp"] >= 32.0]
    has_heat_hours = len(heat_hours) > 0

    # Build voice-friendly facts block text (12-hour format, <=1 number per window)
    bw_start_12 = format_hour_12h(best_start)
    bw_end_12 = format_hour_12h(best_end)
    best_desc = f"- Best window for {activity}: {bw_start_12} to {bw_end_12} (chance of rain: at most {best_rain_max}%)"

    if avoid_window:
        aw_start_12 = format_hour_12h(avoid_start)
        aw_end_12 = format_hour_12h(avoid_end)
        avoid_desc = f"- Window to avoid: {aw_start_12} to {aw_end_12} (chance of rain: {avoid_rain_max}%)"
    else:
        avoid_desc = "- Window to avoid: None"

    if has_heat_hours:
        heat_hours_12 = [format_hour_12h(h) for h in heat_hours]
        heat_desc = f"- Heat hours (>=32°C): {', '.join(heat_hours_12)}"
    else:
        heat_desc = "- Heat hours (>=32°C): None"

    # 4. Activity-specific facts for dry clothes
    dry_clothes_info = None
    dry_desc = ""
    if "dry clothes" in activity.lower():
        dry_runs = []
        curr = []
        for p in parsed:
            if p["rain"] <= 20:
                curr.append(p)
            else:
                if curr:
                    dry_runs.append(curr)
                    curr = []
        if curr:
            dry_runs.append(curr)

        if dry_runs:
            longest_dry = max(dry_runs, key=len)
        else:
            longest_dry = best_run

        dry_start = longest_dry[0]["time"]
        dry_end = longest_dry[-1]["time"]
        dry_rain_max = max(x["rain"] for x in longest_dry)

        take_in_time = None
        for p in parsed:
            if p["time"] > dry_start and p["rain"] >= 40:
                take_in_time = p["time"]
                break

        dry_clothes_info = {
            "start": dry_start,
            "end": dry_end,
            "rain_max": dry_rain_max,
            "take_in_time": take_in_time,
        }
        dc_s12 = format_hour_12h(dry_start)
        dc_e12 = format_hour_12h(dry_end)
        dry_desc = f"\n- Recommended clothes drying window: {dc_s12} to {dc_e12} (chance of rain: at most {dry_rain_max}%)"
        if take_in_time:
            ti_12 = format_hour_12h(take_in_time)
            dry_desc += f", take in by {ti_12}"

    facts_block = f"{best_desc}\n{avoid_desc}\n{heat_desc}{dry_desc}".strip()

    return {
        "best_window": best_window,
        "avoid_window": avoid_window,
        "heat_hours": heat_hours,
        "has_heat_hours": has_heat_hours,
        "dry_clothes": dry_clothes_info,
        "facts_block": facts_block,
    }


def extract_fact_numbers(facts: dict) -> set[float]:
    """
    Extract ONLY the numbers present in the facts block.
    Maps 24h hours to both 24h and 12h numbers (e.g. 16:00 -> 16.0 and 4.0).
    Does NOT include 32.0 unless heat hours exist.
    """
    valid_nums: set[float] = {0.0}

    # Best window: start, end (24h and 12h), and rain_max
    bw = facts.get("best_window")
    if bw:
        for t_str in (bw.get("start", ""), bw.get("end", "")):
            if ":" in t_str:
                parts = t_str.split(":")
                try:
                    h24 = int(parts[0])
                    valid_nums.add(float(h24))
                    valid_nums.add(float(h24 % 12 or 12))
                except ValueError:
                    pass
        if "rain_max" in bw:
            valid_nums.add(float(bw["rain_max"]))

    # Avoid window: start, end (24h and 12h), and rain_max
    aw = facts.get("avoid_window")
    if aw:
        for t_str in (aw.get("start", ""), aw.get("end", "")):
            if ":" in t_str:
                parts = t_str.split(":")
                try:
                    h24 = int(parts[0])
                    valid_nums.add(float(h24))
                    valid_nums.add(float(h24 % 12 or 12))
                except ValueError:
                    pass
        if "rain_max" in aw:
            valid_nums.add(float(aw["rain_max"]))

    # Dry clothes window: start, end, take_in_time, and rain_max
    dc = facts.get("dry_clothes")
    if dc:
        for t_str in (
            dc.get("start", ""),
            dc.get("end", ""),
            dc.get("take_in_time") or "",
        ):
            if ":" in t_str:
                parts = t_str.split(":")
                try:
                    h24 = int(parts[0])
                    valid_nums.add(float(h24))
                    valid_nums.add(float(h24 % 12 or 12))
                except ValueError:
                    pass
        if "rain_max" in dc:
            valid_nums.add(float(dc["rain_max"]))

    # Heat hours: 32.0 and hours (24h and 12h)
    if facts.get("has_heat_hours"):
        valid_nums.add(32.0)
        for h in facts.get("heat_hours", []):
            if ":" in h:
                parts = h.split(":")
                try:
                    h24 = int(parts[0])
                    valid_nums.add(float(h24))
                    valid_nums.add(float(h24 % 12 or 12))
                except ValueError:
                    pass

    return valid_nums


def count_sentences(text: str) -> int:
    """Count sentences in text, taking care not to split on decimal points."""
    cleaned = text.strip()
    if not cleaned:
        return 0
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    return len(sentences)


def is_sentence_fragment(sentence: str) -> bool:
    """
    Check if a sentence is a grammatical fragment:
    - Must have at least 5 words.
    - Must contain at least one verb or auxiliary verb.
    - Must start with an uppercase letter.
    """
    s = sentence.strip()
    if not s:
        return True
    if not s[0].isupper():
        return True
    words = [w for w in re.split(r"\s+", s) if w]
    if len(words) < 5:
        return True

    # Strip to-infinitives and noun uses of 'walk' (e.g. 'to go for a walk')
    # so they are not mistaken for finite main verbs
    s_clean = re.sub(r"\bto\s+[a-z]+", "", s, flags=re.IGNORECASE)
    s_clean = re.sub(r"\b(a|the|for|your)\s+walk\b", "", s_clean, flags=re.IGNORECASE)

    # Check for presence of finite verbs or auxiliaries
    verb_pattern = (
        r"\b(is|are|was|were|be|been|being|have|has|had|do|does|did|can|could|will|"
        r"would|should|may|might|must|reach|reaches|reached|stay|stays|stayed|start|"
        r"starts|started|fall|falls|fell|rise|rises|rose|make|makes|made|avoid|avoids|"
        r"avoided|expect|expects|expected|provide|provides|provided|offer|offers|offered|"
        r"bring|brings|brought|head|heads|run|runs|ran|walk|walks|walked|hang|hangs|hung|dry|dries|dried)\b"
    )
    return not bool(re.search(verb_pattern, s_clean, re.IGNORECASE))


def validate_plan_output(text: str, facts: dict) -> tuple[bool, str]:
    """
    Validate the model response against stronger guard constraints:
    (a) Every number in the text must come from the facts block.
    (b) Never says 'will rain' (case-insensitive).
    (c) Exactly 2 to 3 sentences.
    (d) Reject sentence fragments.
    (e) Reject 32°C threshold unless there are heat hours.
    (f) Must mention the window to avoid if an avoid window exists in facts.
    """
    stripped = text.strip()
    if not stripped:
        return False, "Response is empty."

    # Voice-friendly requirement: No 24-hour colon time formats (like 16:00)
    if re.search(r"\b\d{1,2}:\d{2}\b", stripped):
        return (
            False,
            "Found 24-hour time format with colon (use voice-friendly format like '4 pm' instead of '16:00').",
        )

    # Constraint (b): Never says "will rain"
    if "will rain" in stripped.lower():
        return False, "Forbidden phrase 'will rain' detected."

    # Constraint (c): 2 to 3 sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", stripped) if s.strip()]
    if len(sentences) not in (2, 3):
        return False, f"Sentence count is {len(sentences)}, expected 2 to 3 sentences."

    # Word count: about 40 words max
    words = re.findall(r"\b[A-Za-z0-9]+(?:'[a-z]+)?\b", stripped)
    if len(words) > 55:
        return False, f"Word count is {len(words)}, expected about 40 words max."

    # Constraint (d): Reject sentence fragments
    for s in sentences:
        if is_sentence_fragment(s):
            return False, f"Sentence fragment detected: '{s}'"

    # Constraint (e): Reject 32°C threshold unless heat hours exist
    found_nums = re.findall(r"\b\d+(?:\.\d+)?\b", stripped)
    has_heat = facts.get("has_heat_hours", False)
    for num_str in found_nums:
        try:
            val = float(num_str)
            if val == 32.0 and not has_heat:
                return False, "Mentioned 32°C threshold when no heat hours exist."
        except ValueError:
            pass

    # Constraint (f): Must address the avoid window if one exists
    aw = facts.get("avoid_window")
    if aw:
        avoid_start_hr = aw["start"].split(":")[0]
        try:
            avoid_start_12h = str(int(avoid_start_hr) % 12 or 12)
        except ValueError:
            avoid_start_12h = avoid_start_hr
        lower_text = stripped.lower()
        has_avoid_term = (
            "avoid" in lower_text
            or avoid_start_hr in found_nums
            or avoid_start_12h in found_nums
        )
        if not has_avoid_term:
            return False, "Failed to address the window to avoid."

    # Constraint (a): Every number in text must come from facts block
    valid_nums = extract_fact_numbers(facts)
    for num_str in found_nums:
        try:
            num_val = float(num_str)
            if num_val not in valid_nums:
                return False, f"Number '{num_str}' does not appear in the facts block."
        except ValueError:
            pass

    return True, "Valid"


def generate_fallback_template(facts: dict, activity: str = "a walk") -> str:
    """
    Generate a deterministic, 2-sentence voice-friendly plan directly from facts.
    Guaranteed to pass all guard rules.
    """
    bw = facts.get("best_window")
    aw = facts.get("avoid_window")

    if not bw:
        return (
            f"A good time for {activity} cannot be determined due to missing forecast data. "
            "Please check conditions before heading out."
        )

    bw_start = format_hour_12h(bw["start"])
    bw_end = format_hour_12h(bw["end"])
    bw_rain_max = bw["rain_max"]

    if "dry clothes" in activity.lower() and facts.get("dry_clothes"):
        dc = facts["dry_clothes"]
        dc_start = format_hour_12h(dc["start"])
        dc_end = format_hour_12h(dc["end"])
        dc_rain = dc["rain_max"]
        sentence1 = f"Hang your clothes out between {dc_start} and {dc_end} with at most {dc_rain}% chance of rain."
        if aw:
            aw_start = format_hour_12h(aw["start"])
            aw_end = format_hour_12h(aw["end"])
            aw_rain = aw["rain_max"]
            sentence2 = f"Avoid leaving clothes outside between {aw_start} and {aw_end} due to a {aw_rain}% chance of rain."
        elif dc.get("take_in_time"):
            ti_12 = format_hour_12h(dc["take_in_time"])
            sentence2 = f"Bring them inside by {ti_12} before rain chances rise."
        else:
            sentence2 = f"Rain chances stay low under {dc_rain}% throughout the rest of the day."
        return f"{sentence1} {sentence2}"

    sentence1 = f"The best time for {activity} is between {bw_start} and {bw_end} with at most {bw_rain_max}% chance of rain."

    if aw:
        aw_start = format_hour_12h(aw["start"])
        aw_end = format_hour_12h(aw["end"])
        aw_rain = aw["rain_max"]
        sentence2 = f"Avoid being outside between {aw_start} and {aw_end} due to a {aw_rain}% chance of rain."
    elif facts.get("has_heat_hours"):
        heat_strs = [format_hour_12h(h) for h in facts["heat_hours"]]
        sentence2 = (
            f"Avoid being outside during peak heat around {', '.join(heat_strs)}."
        )
    else:
        sentence2 = f"Rain chances stay low under {bw_rain_max}% throughout the rest of the day."

    return f"{sentence1} {sentence2}"


def call_ollama(
    prompt: str,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 120,
    keep_alive: str = "1m",
) -> str:
    """
    Call Ollama /api/generate endpoint.
    Exits with a clean one-line message and non-zero exit code if:
    - Ollama is not running (URLError)
    - Model is not pulled (HTTPError 404 or missing model)
    - Request times out (TimeoutError)
    """
    if base_url is None:
        base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)
    if model is None:
        model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    endpoint = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0.3,
            "seed": 42,
        },
    }

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("response", "").strip()

    except (TimeoutError, urllib.error.URLError) as e:
        if isinstance(e, urllib.error.HTTPError):
            if e.code == 404:
                sys.stderr.write(
                    f"Error: Model '{model}' is not pulled. Run: ollama pull {model}\n"
                )
                sys.exit(1)
            sys.stderr.write(
                f"Error: Ollama returned HTTP error {e.code}: {e.reason}\n"
            )
            sys.exit(1)
        elif isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            sys.stderr.write(f"Error: Ollama request timed out after {timeout}s.\n")
            sys.exit(1)
        else:
            sys.stderr.write(
                f"Error: Ollama is not running. Start Ollama and run: ollama pull {model}\n"
            )
            sys.exit(1)
    except OSError as e:
        if "timed out" in str(e).lower():
            sys.stderr.write(f"Error: Ollama request timed out after {timeout}s.\n")
            sys.exit(1)
        sys.stderr.write(f"Error communicating with Ollama: {e}\n")
        sys.exit(1)


def get_outdoor_plan(
    fcst_df: pd.DataFrame,
    activity: str = "a walk",
    base_url: str | None = None,
    model: str | None = None,
    prompt_path: str = DEFAULT_PROMPT_PATH,
    timeout: int = 120,
    keep_alive: str = "1m",
) -> str:
    """
    Generate outdoor plan text:
    1. Computes structured facts from forecast.
    2. Populates prompt with facts_block and activity.
    3. Calls Ollama with temperature=0.3, seed=42, keep_alive='1m'.
    4. Validates output with stronger guard.
    5. If invalid, retries once.
    6. If retry also fails, falls back to deterministic template plan.
    """
    facts = compute_forecast_facts(fcst_df, activity=activity)
    prompt_template = load_prompt(prompt_path)
    prompt = prompt_template.format(
        activity=activity,
        facts_block=facts["facts_block"],
    )

    # Attempt 1
    raw_response = call_ollama(
        prompt, base_url=base_url, model=model, timeout=timeout, keep_alive=keep_alive
    )
    is_valid, _ = validate_plan_output(raw_response, facts)
    if is_valid:
        return raw_response

    # Attempt 2 (Retry once)
    raw_response_retry = call_ollama(
        prompt, base_url=base_url, model=model, timeout=timeout, keep_alive=keep_alive
    )
    is_valid_retry, _ = validate_plan_output(raw_response_retry, facts)
    if is_valid_retry:
        return raw_response_retry

    # Fallback to deterministic template
    return generate_fallback_template(facts, activity=activity)
