import base64
import json
from unittest.mock import MagicMock

import httpx
from elevenlabs.core import ApiError

from w1_go_out_today.voice import (
    DEFAULT_MODEL_ID,
    DEFAULT_VOICE_ID,
    generate_voice,
    get_audio_cache_key,
    play_audio,
)


def test_get_audio_cache_key():
    key1 = get_audio_cache_key("Hello world", DEFAULT_VOICE_ID, DEFAULT_MODEL_ID)
    key2 = get_audio_cache_key("Hello world", DEFAULT_VOICE_ID, DEFAULT_MODEL_ID)
    key3 = get_audio_cache_key("Hello world", "different_voice", DEFAULT_MODEL_ID)
    key4 = get_audio_cache_key("Hello world", DEFAULT_VOICE_ID, "different_model")

    assert key1 == key2
    assert key1 != key3
    assert key1 != key4
    assert len(key1) == 16


def test_generate_voice_no_voice_flag(capsys):
    res = generate_voice("The best time is 4 pm.", no_voice=True)
    assert res is None
    captured = capsys.readouterr()
    assert "Audio skipped (--no-voice)." in captured.out


def test_generate_voice_missing_key(capsys, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    res = generate_voice("The best time is 4 pm.", api_key="")
    assert res is None
    captured = capsys.readouterr()
    assert "Audio skipped: ELEVENLABS_API_KEY is not set in .env." in captured.out


def test_generate_voice_cache_hit(tmp_path, capsys):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    text = "The best time is 4 pm."
    cache_key = get_audio_cache_key(text, DEFAULT_VOICE_ID, DEFAULT_MODEL_ID)
    mp3_file = audio_dir / f"brief_{cache_key}.mp3"
    mp3_file.write_bytes(b"dummy audio")

    # Should hit cache without needing an API key or calling network
    res = generate_voice(text, audio_dir=str(audio_dir), api_key=None)
    assert res == str(mp3_file)
    captured = capsys.readouterr()
    assert "[Cached] Audio:" in captured.out


def test_generate_voice_with_timestamps_success(tmp_path, monkeypatch, capsys):
    audio_dir = tmp_path / "audio"
    text = "The best time is 4 pm."
    fake_audio_bytes = b"fake mp3 audio stream"
    fake_b64 = base64.b64encode(fake_audio_bytes).decode("ascii")

    mock_resp = MagicMock()
    mock_resp.audio_base_64 = fake_b64
    mock_resp.alignment.characters = ["T", "h", "e"]
    mock_resp.alignment.character_start_times_seconds = [0.0, 0.1, 0.2]
    mock_resp.alignment.character_end_times_seconds = [0.1, 0.2, 0.3]

    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.return_value = mock_resp

    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice(text, audio_dir=str(audio_dir), api_key="test_key")
    cache_key = get_audio_cache_key(text, DEFAULT_VOICE_ID, DEFAULT_MODEL_ID)
    expected_mp3 = audio_dir / f"brief_{cache_key}.mp3"
    expected_json = audio_dir / f"brief_{cache_key}.json"

    assert res == str(expected_mp3)
    assert expected_mp3.exists()
    assert expected_mp3.read_bytes() == fake_audio_bytes
    assert expected_json.exists()
    data = json.loads(expected_json.read_text(encoding="utf-8"))
    assert data["characters"] == ["T", "h", "e"]


def test_generate_voice_fallback_to_plain_convert(tmp_path, monkeypatch, capsys):
    audio_dir = tmp_path / "audio"
    text = "The best time is 4 pm."
    fake_audio_chunks = [b"chunk1", b"chunk2"]

    mock_client = MagicMock()
    # convert_with_timestamps fails due to tier/timestamps restriction
    mock_client.text_to_speech.convert_with_timestamps.side_effect = ApiError(
        status_code=403,
        body={"detail": {"message": "Timings not allowed on free tier"}},
    )
    # plain convert succeeds
    mock_client.text_to_speech.convert.return_value = fake_audio_chunks

    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice(text, audio_dir=str(audio_dir), api_key="test_key")
    cache_key = get_audio_cache_key(text, DEFAULT_VOICE_ID, DEFAULT_MODEL_ID)
    expected_mp3 = audio_dir / f"brief_{cache_key}.mp3"

    assert res == str(expected_mp3)
    assert expected_mp3.exists()
    assert expected_mp3.read_bytes() == b"chunk1chunk2"


def test_generate_voice_invalid_key_error(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.side_effect = ApiError(
        status_code=401,
        body={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}},
    )
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="invalid_key")
    assert res is None
    captured = capsys.readouterr()
    assert "Audio skipped: ElevenLabs API key is invalid (check .env)." in captured.out


def test_generate_voice_quota_exceeded_error(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.side_effect = ApiError(
        status_code=401,
        body={"detail": {"message": "Character quota exceeded on your plan"}},
    )
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="exhausted_key")
    assert res is None
    captured = capsys.readouterr()
    assert (
        "Audio skipped: ElevenLabs free plan character quota exceeded." in captured.out
    )


def test_generate_voice_rate_limit_error(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.side_effect = ApiError(
        status_code=429,
        body={"detail": {"message": "Rate limit reached"}},
    )
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="limited_key")
    assert res is None
    captured = capsys.readouterr()
    assert "Audio skipped: ElevenLabs API rate limit reached." in captured.out


def test_generate_voice_timeout_error(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.side_effect = (
        httpx.TimeoutException("Timed out")
    )
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="valid_key")
    assert res is None
    captured = capsys.readouterr()
    assert "timed out after 30s" in captured.out


def test_generate_voice_network_error(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    req = httpx.Request("POST", "https://api.elevenlabs.io")
    mock_client.text_to_speech.convert_with_timestamps.side_effect = httpx.NetworkError(
        "Unreachable", request=req
    )
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="valid_key")
    assert res is None
    captured = capsys.readouterr()
    assert "Unable to reach ElevenLabs API (network error" in captured.out


def test_generate_voice_atomic_part_cleanup_on_failure(tmp_path, monkeypatch):
    mock_client = MagicMock()

    cache_key = get_audio_cache_key("Hello", DEFAULT_VOICE_ID, DEFAULT_MODEL_ID)

    def raise_during_write(*args, **kwargs):
        # Create a partial file matching the cache key
        part = tmp_path / "audio" / f"brief_{cache_key}.mp3.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"corrupted partial")
        raise RuntimeError("Failure during streaming")

    mock_client.text_to_speech.convert_with_timestamps.side_effect = raise_during_write
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice(
        "Hello", audio_dir=str(tmp_path / "audio"), api_key="valid_key"
    )
    assert res is None
    # Verify no .part file was left behind
    assert not list((tmp_path / "audio").glob("*.part"))


def test_play_audio(monkeypatch, capsys):
    mock_startfile = MagicMock()
    monkeypatch.setattr("os.startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    play_audio("audio/brief_test.mp3")
    assert mock_startfile.called or "Play audio at:" in capsys.readouterr().out


def test_generate_voice_400_invalid_api_key(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    err = ApiError(
        status_code=400,
        headers={"content-type": "application/json", "x-request-id": "req_123"},
        body={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}},
    )
    mock_client.text_to_speech.convert_with_timestamps.side_effect = err
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="bad_key")
    assert res is None
    captured = capsys.readouterr()
    assert "Audio skipped: ElevenLabs API key is invalid (check .env)." in captured.out
    assert "headers" not in captured.out.lower()
    assert "req_123" not in captured.out


def test_generate_voice_unknown_api_error_no_leaks(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    err = ApiError(
        status_code=500,
        headers={"content-type": "application/json", "x-secret-trace": "trace_999"},
        body={"detail": {"status": "internal_crash", "message": "Sensitive DB Trace"}},
    )
    mock_client.text_to_speech.convert_with_timestamps.side_effect = err
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="valid_key")
    assert res is None
    captured = capsys.readouterr()
    assert "Audio skipped: ElevenLabs error (500)." in captured.out
    assert "headers" not in captured.out.lower()
    assert "trace_999" not in captured.out
    assert "Sensitive DB Trace" not in captured.out


def test_generate_voice_quota_detail_code(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    err = ApiError(
        status_code=400,
        headers={"content-type": "application/json"},
        body={"detail": {"code": "quota_exceeded", "message": "Out of credits"}},
    )
    mock_client.text_to_speech.convert_with_timestamps.side_effect = err
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="valid_key")
    assert res is None
    captured = capsys.readouterr()
    assert (
        "Audio skipped: ElevenLabs free plan character quota exceeded." in captured.out
    )


def test_generate_voice_apierror_timeout(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    err = ApiError(
        status_code=504,
        headers={"content-type": "application/json"},
        body={"detail": {"code": "gateway_timeout", "message": "Gateway Timeout"}},
    )
    mock_client.text_to_speech.convert_with_timestamps.side_effect = err
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="valid_key")
    assert res is None
    captured = capsys.readouterr()
    assert "timed out after 30s" in captured.out


def test_generate_voice_apierror_bad_gateway(tmp_path, monkeypatch, capsys):
    mock_client = MagicMock()
    err = ApiError(
        status_code=502,
        headers={"content-type": "application/json"},
        body={"detail": {"status": "bad_gateway", "message": "Bad Gateway"}},
    )
    mock_client.text_to_speech.convert_with_timestamps.side_effect = err
    monkeypatch.setattr("elevenlabs.client.ElevenLabs", lambda **kwargs: mock_client)

    res = generate_voice("Hello", audio_dir=str(tmp_path), api_key="valid_key")
    assert res is None
    captured = capsys.readouterr()
    assert "Unable to reach ElevenLabs API (network error: HTTP 502)" in captured.out
