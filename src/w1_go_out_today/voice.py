import base64
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George (standard default)
DEFAULT_MODEL_ID = "eleven_flash_v2_5"  # 0.5 credits/char on free plan
AUDIO_DIR = "audio"
TIMEOUT_SECONDS = 30.0


def get_audio_cache_key(text: str, voice_id: str, model_id: str) -> str:
    """Compute deterministic SHA-256 hash of text, voice_id, and model_id."""
    raw = f"{text.strip()}:{voice_id.strip()}:{model_id.strip()}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def play_audio(audio_path: str) -> None:
    """Open the audio file with os.startfile on Windows, or print path elsewhere."""
    if sys.platform == "win32" and hasattr(os, "startfile"):
        try:
            os.startfile(audio_path)
            return
        except OSError as e:
            sys.stderr.write(f"Note: Could not open audio with os.startfile: {e}\n")
    print(f"Play audio at: {audio_path}")


def generate_voice(
    text: str,
    audio_dir: str = AUDIO_DIR,
    voice_id: str | None = None,
    model_id: str | None = None,
    no_voice: bool = False,
    play: bool = False,
    api_key: str | None = None,
) -> str | None:
    """
    Generate speech from outdoor plan text using ElevenLabs.
    - Operates under free tier with minimal usage.
    - Caches audio by SHA-256 of text + voice_id + model_id.
    - Writes atomically via .part files.
    - Captures word timings via convert_with_timestamps (falling back to plain convert).
    - Prints clean one-line messages on missing key, quota error, rate limit, or network error.
    - Returns audio path string or None.
    """
    if no_voice:
        print("Audio skipped (--no-voice).")
        return None

    stripped_text = text.strip()
    if not stripped_text:
        return None

    if voice_id is None:
        voice_id = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
    if model_id is None:
        model_id = os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID

    cache_dir = Path(audio_dir)
    cache_key = get_audio_cache_key(stripped_text, voice_id, model_id)
    mp3_path = cache_dir / f"brief_{cache_key}.mp3"
    json_path = cache_dir / f"brief_{cache_key}.json"

    # 1. Cache hit check
    if mp3_path.exists() and mp3_path.stat().st_size > 0:
        print(f"[Cached] Audio: {mp3_path.as_posix()}")
        if play:
            play_audio(str(mp3_path))
        return str(mp3_path)

    # 2. Key check
    if api_key is None:
        api_key = os.getenv("ELEVENLABS_API_KEY")

    if not api_key or not api_key.strip():
        print("Audio skipped: ELEVENLABS_API_KEY is not set in .env.")
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    mp3_part = cache_dir / f"brief_{cache_key}.mp3.part"
    json_part = cache_dir / f"brief_{cache_key}.json.part"

    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs.core import ApiError

        client = ElevenLabs(
            api_key=api_key.strip(),
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
        )

        timings_saved = False

        # Attempt 1: convert_with_timestamps
        try:
            resp = client.text_to_speech.convert_with_timestamps(
                voice_id=voice_id,
                text=stripped_text,
                model_id=model_id,
            )
            audio_bytes = base64.b64decode(resp.audio_base_64)
            with open(mp3_part, "wb") as f:
                f.write(audio_bytes)

            if resp.alignment:
                timing_dict = {
                    "characters": resp.alignment.characters,
                    "character_start_times_seconds": resp.alignment.character_start_times_seconds,
                    "character_end_times_seconds": resp.alignment.character_end_times_seconds,
                }
                with open(json_part, "w", encoding="utf-8") as f:
                    json.dump(timing_dict, f, indent=2)
                timings_saved = True

        except ApiError as e:
            # If with-timestamps is rejected specifically because timestamps are unsupported on tier/model
            detail_str = ""
            if isinstance(e.body, dict):
                d = e.body.get("detail")
                if isinstance(d, dict):
                    detail_str = f"{d.get('code', '')} {d.get('status', '')} {d.get('message', '')}".lower()
                elif isinstance(d, str):
                    detail_str = d.lower()
            elif isinstance(e.body, str):
                detail_str = e.body.lower()

            is_auth_or_quota = any(
                k in detail_str
                for k in (
                    "invalid_api_key",
                    "quota",
                    "character",
                    "credit",
                    "rate_limit",
                )
            ) or getattr(e, "status_code", None) in (400, 401, 402, 429)

            if not is_auth_or_quota and (
                "timestamp" in detail_str
                or "not allowed" in detail_str
                or getattr(e, "status_code", None) == 403
            ):
                # Fall back to standard convert
                audio_stream = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=stripped_text,
                    model_id=model_id,
                )
                with open(mp3_part, "wb") as f:
                    for chunk in audio_stream:
                        if chunk:
                            f.write(chunk)
            else:
                raise

        # Atomic commit
        os.replace(mp3_part, mp3_path)
        if timings_saved and json_part.exists():
            os.replace(json_part, json_path)

        print(f"Audio saved to: {mp3_path.as_posix()}")
        if play:
            play_audio(str(mp3_path))
        return str(mp3_path)

    except ApiError as e:
        logger.debug(
            "ElevenLabs ApiError: status_code=%s, headers=%s, body=%s",
            getattr(e, "status_code", None),
            getattr(e, "headers", None),
            getattr(e, "body", None),
        )

        detail_code = ""
        detail_status = ""
        detail_msg = ""
        if isinstance(e.body, dict):
            detail = e.body.get("detail")
            if isinstance(detail, dict):
                detail_code = str(detail.get("code") or "").lower()
                detail_status = str(detail.get("status") or "").lower()
                detail_msg = str(detail.get("message") or "").lower()
            elif isinstance(detail, str):
                detail_msg = detail.lower()
        elif isinstance(e.body, str):
            detail_msg = e.body.lower()

        combined_info = f"{detail_code} {detail_status} {detail_msg}"

        if (
            detail_code == "invalid_api_key"
            or detail_status == "invalid_api_key"
            or "invalid_api_key" in detail_msg
            or (
                getattr(e, "status_code", None) == 401
                and not any(
                    w in combined_info for w in ("quota", "credit", "character")
                )
            )
        ):
            print("Audio skipped: ElevenLabs API key is invalid (check .env).")
        elif (
            detail_code in ("quota_exceeded", "quota_limit_reached")
            or detail_status in ("quota_exceeded", "quota_limit_reached")
            or any(w in combined_info for w in ("quota", "credit", "character"))
            or getattr(e, "status_code", None) == 402
        ):
            print("Audio skipped: ElevenLabs free plan character quota exceeded.")
        elif (
            detail_code in ("rate_limit", "rate_limited", "too_many_requests")
            or detail_status in ("rate_limit", "rate_limited", "too_many_requests")
            or "rate" in detail_code
            or "rate" in detail_status
            or getattr(e, "status_code", None) == 429
        ):
            print("Audio skipped: ElevenLabs API rate limit reached.")
        elif (
            detail_code in ("timeout", "gateway_timeout", "request_timeout")
            or detail_status in ("timeout", "gateway_timeout", "request_timeout")
            or "timeout" in combined_info
            or getattr(e, "status_code", None) in (408, 504)
        ):
            print(
                f"Audio skipped: ElevenLabs API request timed out after {int(TIMEOUT_SECONDS)}s."
            )
        elif (
            detail_code
            in (
                "network_error",
                "connection_error",
                "bad_gateway",
                "service_unavailable",
            )
            or detail_status
            in (
                "network_error",
                "connection_error",
                "bad_gateway",
                "service_unavailable",
            )
            or any(
                w in combined_info
                for w in (
                    "network",
                    "connection",
                    "bad gateway",
                    "service unavailable",
                )
            )
            or getattr(e, "status_code", None) in (502, 503)
        ):
            code_label = (
                f"HTTP {e.status_code}"
                if getattr(e, "status_code", None)
                else (detail_code or detail_status or "NetworkError")
            )
            print(
                f"Audio skipped: Unable to reach ElevenLabs API (network error: {code_label})."
            )
        else:
            status_display = (
                e.status_code
                if getattr(e, "status_code", None) is not None
                else "unknown"
            )
            print(f"Audio skipped: ElevenLabs error ({status_display}).")
        return None

    except (httpx.TimeoutException, TimeoutError):
        logger.debug("ElevenLabs request timed out", exc_info=True)
        print(
            f"Audio skipped: ElevenLabs API request timed out after {int(TIMEOUT_SECONDS)}s."
        )
        return None

    except (httpx.RequestError, ConnectionError, OSError) as e:
        logger.debug("ElevenLabs network error", exc_info=True)
        print(
            f"Audio skipped: Unable to reach ElevenLabs API (network error: {e.__class__.__name__})."
        )
        return None

    except Exception as e:
        logger.debug("Unexpected ElevenLabs TTS error", exc_info=True)
        print(f"Audio skipped: ElevenLabs error ({e.__class__.__name__}).")
        return None

    finally:
        # Clean up any leftover partial files on failure
        if mp3_part.exists():
            try:
                mp3_part.unlink()
            except OSError:
                pass
        if json_part.exists():
            try:
                json_part.unlink()
            except OSError:
                pass
