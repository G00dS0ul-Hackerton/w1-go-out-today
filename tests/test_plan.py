import io
import json
import urllib.error
import urllib.request

import pandas as pd
import pytest

from w1_go_out_today.plan import (
    call_ollama,
    compute_forecast_facts,
    count_sentences,
    extract_fact_numbers,
    generate_fallback_template,
    get_outdoor_plan,
    is_sentence_fragment,
    load_prompt,
    validate_plan_output,
)


@pytest.fixture
def sample_forecast_df():
    # Matches the real Lagos forecast data
    return pd.DataFrame(
        [
            {
                "time": "07:00",
                "hours_ahead": 1,
                "temp_pred": "25.4°C",
                "rain_prob": "31%",
            },
            {
                "time": "08:00",
                "hours_ahead": 2,
                "temp_pred": "26.0°C",
                "rain_prob": "43%",
            },
            {
                "time": "09:00",
                "hours_ahead": 3,
                "temp_pred": "26.4°C",
                "rain_prob": "54%",
            },
            {
                "time": "10:00",
                "hours_ahead": 4,
                "temp_pred": "26.8°C",
                "rain_prob": "72%",
            },
            {
                "time": "11:00",
                "hours_ahead": 5,
                "temp_pred": "27.0°C",
                "rain_prob": "78%",
            },
            {
                "time": "12:00",
                "hours_ahead": 6,
                "temp_pred": "27.1°C",
                "rain_prob": "81%",
            },
            {
                "time": "13:00",
                "hours_ahead": 7,
                "temp_pred": "27.1°C",
                "rain_prob": "80%",
            },
            {
                "time": "14:00",
                "hours_ahead": 8,
                "temp_pred": "27.1°C",
                "rain_prob": "73%",
            },
            {
                "time": "15:00",
                "hours_ahead": 9,
                "temp_pred": "27.1°C",
                "rain_prob": "57%",
            },
            {
                "time": "16:00",
                "hours_ahead": 10,
                "temp_pred": "26.9°C",
                "rain_prob": "37%",
            },
            {
                "time": "17:00",
                "hours_ahead": 11,
                "temp_pred": "26.5°C",
                "rain_prob": "23%",
            },
            {
                "time": "18:00",
                "hours_ahead": 12,
                "temp_pred": "26.2°C",
                "rain_prob": "15%",
            },
        ]
    )


def test_prompt_file_constraints():
    prompt_text = load_prompt("prompts/plan.txt")
    assert "{activity}" in prompt_text
    assert "{facts_block}" in prompt_text
    assert "best time window" in prompt_text
    assert "window to avoid" in prompt_text
    assert "chance of rain" in prompt_text
    assert "will rain" in prompt_text
    assert "2 to 3" in prompt_text
    assert "12-hour" in prompt_text or "4 pm" in prompt_text


def test_compute_forecast_facts(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df, activity="a walk")
    bw = facts["best_window"]
    assert bw is not None
    # Longest run <= 40% rain is 16:00 to 18:00 (length 3, rain 37%, 23%, 15%)
    assert bw["start"] == "16:00"
    assert bw["end"] == "18:00"
    assert bw["rain_min"] == 15
    assert bw["rain_max"] == 37

    aw = facts["avoid_window"]
    assert aw is not None
    # Contiguous run >= 60% is 10:00 to 14:00
    assert aw["start"] == "10:00"
    assert aw["end"] == "14:00"
    assert aw["rain_min"] == 72
    assert aw["rain_max"] == 81

    assert facts["has_heat_hours"] is False
    assert "4 pm to 6 pm" in facts["facts_block"]
    assert "10 am to 2 pm" in facts["facts_block"]


def test_extract_fact_numbers(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    valid_nums = extract_fact_numbers(facts)
    # Best window numbers: 16:00 maps to 16.0 and 4.0; 18:00 maps to 18.0 and 6.0; rain_max is 37.0
    assert 16.0 in valid_nums
    assert 4.0 in valid_nums
    assert 18.0 in valid_nums
    assert 6.0 in valid_nums
    assert 37.0 in valid_nums
    assert 15.0 not in valid_nums
    # Avoid window numbers: 10:00 maps to 10.0; 14:00 maps to 14.0 and 2.0
    assert 10.0 in valid_nums
    assert 14.0 in valid_nums
    assert 2.0 in valid_nums
    assert 81.0 in valid_nums
    # 32°C threshold must NOT be in valid numbers when no heat hours exist
    assert 32.0 not in valid_nums


def test_sentence_fragments():
    # Fragment from coder Run 1 (missing verb in first clause)
    fragment = "Between 7 am and 8 am, the best time to go for a walk."
    assert is_sentence_fragment(fragment) is True

    # Complete grammatical sentence
    complete = (
        "The best time for a walk is between 4 pm and 6 pm with low rain chances."
    )
    assert is_sentence_fragment(complete) is False


def test_coder_run_6_fails_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    # Avoid window omitted
    coder_run_6 = (
        "Between 5 pm and 6 pm, the chance of rain is the lowest at 15%. "
        "The temperature is also the coolest at 26.2°C, making it a comfortable time for a walk."
    )
    is_valid, msg = validate_plan_output(coder_run_6, facts)
    assert is_valid is False
    assert "window to avoid" in msg.lower() or "avoid" in msg.lower()


def test_coder_run_3_fails_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    # Avoid window omitted
    coder_run_3 = (
        "Between 5 pm and 6 pm, the chance of rain is only 15%, making it a good time for a walk. "
        "The temperature is 26.5°C, which is not too hot."
    )
    is_valid, msg = validate_plan_output(coder_run_3, facts)
    assert is_valid is False
    assert "window to avoid" in msg.lower() or "avoid" in msg.lower()


def test_reject_32_when_no_heat_hours(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    assert facts["has_heat_hours"] is False
    text = (
        "The best time for a walk is between 4 pm and 6 pm with at most a 37% chance of rain. "
        "Temperatures remain below 32°C so you can avoid midday rain."
    )
    is_valid, msg = validate_plan_output(text, facts)
    assert is_valid is False
    assert "32" in msg


def test_valid_plan_passes_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    valid_text = (
        "The best time for a walk is between 4 pm and 6 pm with at most a 37% chance of rain. "
        "You should avoid being outside between 10 am and 2 pm due to an 81% chance of rain."
    )
    is_valid, msg = validate_plan_output(valid_text, facts)
    assert is_valid is True, msg


def test_guard_rejects_24h_time(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    text = (
        "The best time for a walk is between 16:00 and 18:00 with at most a 37% chance of rain. "
        "Avoid being outside from 10:00 to 14:00."
    )
    is_valid, msg = validate_plan_output(text, facts)
    assert is_valid is False
    assert "24-hour time format" in msg


def test_guard_rejects_too_many_words(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    long_text = (
        "The best time for a walk is between 4 pm and 6 pm with at most a 37% chance of rain because the weather is very pleasant outside. "
        "However, please make sure you avoid being outside between 10 am and 2 pm due to an 81% chance of heavy rain, thunder, and lightning across the entire Lagos metropolitan area today so you do not get completely soaked."
    )
    is_valid, msg = validate_plan_output(long_text, facts)
    assert is_valid is False
    assert "Word count" in msg


def test_fallback_template_passes_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df, activity="a walk")
    fallback = generate_fallback_template(facts, activity="a walk")
    is_valid, msg = validate_plan_output(fallback, facts)
    assert is_valid is True, f"Fallback failed guard: {msg}"
    assert "4 pm" in fallback
    assert "6 pm" in fallback
    assert "10 am" in fallback
    assert "2 pm" in fallback
    assert "chance of rain" in fallback
    assert "will rain" not in fallback.lower()
    assert count_sentences(fallback) == 2
    words = len(fallback.split())
    assert words <= 50


class MockHTTPResponse:
    def __init__(self, data: dict):
        self.data_bytes = json.dumps(data).encode("utf-8")

    def read(self):
        return self.data_bytes

    def decode(self, encoding="utf-8"):
        return self.data_bytes.decode(encoding)

    def __enter__(self):
        return io.BytesIO(self.data_bytes)

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_call_ollama_success(monkeypatch):
    mock_resp = MockHTTPResponse({"response": "The morning is clear.", "done": True})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: mock_resp)

    res = call_ollama("Test prompt")
    assert res == "The morning is clear."


def test_call_ollama_not_running(monkeypatch, capsys):
    def mock_urlopen_fail(req, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_fail)

    with pytest.raises(SystemExit) as exc_info:
        call_ollama("Test prompt", model="qwen2.5-coder:7b")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Ollama is not running" in captured.err


def test_call_ollama_model_not_pulled(monkeypatch, capsys):
    def mock_urlopen_404(req, timeout):
        raise urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs={}, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_404)

    with pytest.raises(SystemExit) as exc_info:
        call_ollama("Test prompt", model="unknown-model")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Model 'unknown-model' is not pulled" in captured.err


def test_call_ollama_timeout(monkeypatch, capsys):
    def mock_urlopen_timeout(req, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_timeout)

    with pytest.raises(SystemExit) as exc_info:
        call_ollama("Test prompt", timeout=120)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "timed out after 120s" in captured.err


def test_get_outdoor_plan_retries_and_falls_back(sample_forecast_df, monkeypatch):
    # Mock Ollama always returning invalid text ("will rain")
    mock_resp = MockHTTPResponse({"response": "It will rain all day.", "done": True})
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: mock_resp)

    plan = get_outdoor_plan(sample_forecast_df, activity="a walk")
    facts = compute_forecast_facts(sample_forecast_df)
    is_valid, msg = validate_plan_output(plan, facts)
    assert is_valid is True, f"Should have fallen back to valid template: {msg}"


def test_best_window_uses_highest_rain_chance(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df, activity="a walk")
    # Best window rain ranges 15% to 37%. Must use highest: at most 37%
    assert "at most 37%" in facts["facts_block"]
    fallback = generate_fallback_template(facts, activity="a walk")
    assert "at most 37%" in fallback
    assert "15%" not in fallback
    is_valid, msg = validate_plan_output(fallback, facts)
    assert is_valid is True, f"Fallback failed guard: {msg}"


def test_guard_rejects_best_window_understated_rain(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    understated_text = (
        "The best time for a walk is between 4 pm and 6 pm with only a 15% chance of rain. "
        "You should avoid being outside between 10 am and 2 pm due to an 81% chance of rain."
    )
    is_valid, msg = validate_plan_output(understated_text, facts)
    assert is_valid is False
    assert "15" in msg


def test_dry_clothes_facts_and_template(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df, activity="dry clothes")
    assert facts["dry_clothes"] is not None
    assert "start" in facts["dry_clothes"]
    assert "end" in facts["dry_clothes"]
    template = generate_fallback_template(facts, activity="dry clothes")
    assert "Hang your clothes" in template
    assert "Conditions remain mild" not in template
    is_valid, msg = validate_plan_output(template, facts)
    assert is_valid is True, f"Dry clothes template failed guard: {msg}"


def test_picnic_and_hangout_activities(sample_forecast_df):
    for act in ("picnic", "hangout"):
        facts = compute_forecast_facts(sample_forecast_df, activity=act)
        template = generate_fallback_template(facts, activity=act)
        assert act in template
        is_valid, msg = validate_plan_output(template, facts)
        assert is_valid is True, f"Template for {act} failed guard: {msg}"


def test_fallback_no_filler_sentences(sample_forecast_df):
    # Even when avoid window is removed from facts
    facts = compute_forecast_facts(sample_forecast_df, activity="a walk")
    facts["avoid_window"] = None
    template = generate_fallback_template(facts, activity="a walk")
    assert "Conditions remain mild" not in template
    assert "Rain chances stay low" in template
