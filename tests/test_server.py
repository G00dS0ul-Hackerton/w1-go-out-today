import csv
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from w1_go_out_today.server import _state, app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "Go Out Today?" in response.text


def test_status_json(client):
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "forecast_ready" in data
    assert "plan_ready" in data
    assert "audio_ready" in data
    assert "pipeline_running" in data
    assert "current_step" in data


def test_went_outside_appends_csv(client, tmp_path, monkeypatch):
    test_csv = tmp_path / "outside_log.csv"
    monkeypatch.setattr("w1_go_out_today.server.LOG_PATH", test_csv)

    payload = {"activity": "a run", "note": "felt energized"}
    response = client.post("/went-outside", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "logged"}

    assert test_csv.exists()
    with open(test_csv, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 2  # header + 1 row
        assert reader[0] == ["datetime", "activity", "note"]
        assert reader[1][1] == "a run"
        assert reader[1][2] == "felt energized"


def test_brief_starts_pipeline(client, monkeypatch):
    monkeypatch.setitem(_state, "pipeline_running", False)
    mock_run = AsyncMock()
    monkeypatch.setattr("w1_go_out_today.server._run_pipeline", mock_run)

    response = client.post("/brief", json={"activity": "football"})
    assert response.status_code == 200
    assert response.json().get("status") == "started"


def test_activity_brief_switching_and_caching(client, monkeypatch):
    # If pipeline is currently running for 'a walk', a new request for 'dry clothes'
    # must NOT be rejected with 'already_running'; it must cancel or supersede the old
    # task and accept 'dry clothes' with status 'started' or 'cached'.
    monkeypatch.setitem(_state, "pipeline_running", True)
    monkeypatch.setitem(_state, "current_activity", "a walk")
    mock_run = AsyncMock()
    monkeypatch.setattr("w1_go_out_today.server._run_pipeline", mock_run)

    response = client.post(
        "/brief", json={"activity": "dry clothes", "request_id": "req-123"}
    )
    assert response.status_code == 200
    assert response.json().get("status") in ("started", "cached")
    assert response.json().get("status") != "already_running"


def test_events_stream_header(client, monkeypatch):
    monkeypatch.setitem(
        _state,
        "last_brief",
        {
            "plan_text": "Good walk.",
            "audio_file": None,
            "fallback_note": "Voice skipped",
            "timings": {"characters": ["G", "o", "o", "d"]},
        },
    )
    with client.stream("GET", "/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = list(response.iter_lines())
        text = "\n".join(lines)
        assert "event: status" in text
        assert "event: brief_ready" in text
        assert "characters" in text


def test_audio_endpoint(client, tmp_path, monkeypatch):
    test_audio_dir = tmp_path / "audio"
    test_audio_dir.mkdir()
    monkeypatch.setattr("w1_go_out_today.server.AUDIO_DIR", test_audio_dir)

    # 404 for missing
    res404 = client.get("/audio/not_found.mp3")
    assert res404.status_code == 404

    # 200 when exists
    audio_file = test_audio_dir / "test.mp3"
    audio_file.write_bytes(b"fake audio data")

    res200 = client.get("/audio/test.mp3")
    assert res200.status_code == 200
    assert res200.content == b"fake audio data"


def test_warm_endpoint(client):
    response = client.get("/warm")
    assert response.status_code == 200
    assert response.json() == {"status": "warming"}


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "ollama" in data
    assert data["ollama"]["model"] == "qwen2.5-coder:7b"
    assert "forecast_cached" in data
