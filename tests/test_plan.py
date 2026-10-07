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


def test_compute_forecast_facts(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df, activity="a walk")
    bw = facts["best_window"]
    assert bw is not None
    # Longest run <= 40% rain is 16:00 to 18:00 (length 3, rain 37%, 23%, 15%)
    assert bw["start"] == "16:00"
    assert bw["end"] == "18:00"
    assert bw["rain_min"] == 15
    assert bw["rain_max"] == 37
    assert bw["temp_min"] == 26.2
    assert bw["temp_max"] == 26.9

    aw = facts["avoid_window"]
    assert aw is not None
    # Contiguous run >= 60% is 10:00 to 14:00
    assert aw["start"] == "10:00"
    assert aw["end"] == "14:00"
    assert aw["rain_min"] == 72
    assert aw["rain_max"] == 81

    assert facts["has_heat_hours"] is False
    assert "16:00 to 18:00" in facts["facts_block"]
    assert "10:00 to 14:00" in facts["facts_block"]


def test_extract_fact_numbers(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    valid_nums = extract_fact_numbers(facts)
    # Best window numbers
    assert 16.0 in valid_nums
    assert 18.0 in valid_nums
    assert 15.0 in valid_nums
    assert 37.0 in valid_nums
    assert 26.2 in valid_nums
    assert 26.9 in valid_nums
    # Avoid window numbers
    assert 10.0 in valid_nums
    assert 14.0 in valid_nums
    assert 72.0 in valid_nums
    assert 81.0 in valid_nums
    # 32°C threshold must NOT be in valid numbers when no heat hours exist
    assert 32.0 not in valid_nums


def test_sentence_fragments():
    # Fragment from coder Run 1 (missing verb in first clause)
    fragment = "Between 07:00 and 08:00, the best time to go for a walk."
    assert is_sentence_fragment(fragment) is True

    # Complete grammatical sentence
    complete = (
        "The best time for a walk is between 16:00 and 18:00 with low rain chances."
    )
    assert is_sentence_fragment(complete) is False


def test_coder_run_6_fails_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    # Coder Run 6 output: "coolest at 26.2°C", completely omitted avoid window
    coder_run_6 = (
        "Between 17:00 and 18:00, the chance of rain is the lowest at 15%. "
        "The temperature is also the coolest at 26.2°C, making it a comfortable time for a walk."
    )
    is_valid, msg = validate_plan_output(coder_run_6, facts)
    assert is_valid is False
    assert "window to avoid" in msg.lower() or "avoid" in msg.lower()


def test_coder_run_3_fails_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    # Coder Run 3 output: mixed hours, omitted avoid window
    coder_run_3 = (
        "Between 17:00 and 18:00, the chance of rain is only 15%, making it a good time for a walk. "
        "The temperature is 26.5°C, which is not too hot."
    )
    is_valid, msg = validate_plan_output(coder_run_3, facts)
    assert is_valid is False
    assert "window to avoid" in msg.lower() or "avoid" in msg.lower()


def test_reject_32_when_no_heat_hours(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    assert facts["has_heat_hours"] is False
    text = (
        "The best time for a walk is between 16:00 and 18:00 with a 15% chance of rain. "
        "Temperatures remain below 32°C so you can avoid midday rain."
    )
    is_valid, msg = validate_plan_output(text, facts)
    assert is_valid is False
    assert "32" in msg


def test_valid_plan_passes_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df)
    valid_text = (
        "The best time for a walk is between 16:00 and 18:00 with a 15% to 37% chance of rain "
        "and temperatures from 26.2°C to 26.9°C. "
        "You should avoid being outside between 10:00 and 14:00 due to a 72% to 81% chance of rain."
    )
    is_valid, msg = validate_plan_output(valid_text, facts)
    assert is_valid is True, msg


def test_fallback_template_passes_guard(sample_forecast_df):
    facts = compute_forecast_facts(sample_forecast_df, activity="a walk")
    fallback = generate_fallback_template(facts, activity="a walk")
    is_valid, msg = validate_plan_output(fallback, facts)
    assert is_valid is True, f"Fallback failed guard: {msg}"
    assert "16:00" in fallback
    assert "18:00" in fallback
    assert "10:00" in fallback
    assert "14:00" in fallback
    assert "chance of rain" in fallback
    assert "will rain" not in fallback.lower()
    assert count_sentences(fallback) == 2


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
