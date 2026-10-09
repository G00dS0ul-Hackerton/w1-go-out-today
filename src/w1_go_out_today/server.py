"""FastAPI server for the Go Out Today? morning brief web UI."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

_demo_speed = False


async def _warm_ollama():
    """Send a short prompt to warm the Ollama model on startup."""
    from w1_go_out_today.plan import (
        DEFAULT_OLLAMA_MODEL,
        OllamaConnectionError,
        OllamaModelError,
        call_ollama,
    )

    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    try:
        await asyncio.to_thread(call_ollama, "hello", None, None, 120, "10m")
        logger.info("Ollama model '%s' warmed successfully", model)
    except (OllamaConnectionError, OllamaModelError) as exc:
        logger.warning("Ollama warm failed: %s", exc)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_warm_ollama())
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    yield


app = FastAPI(title="Go Out Today?", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
AUDIO_DIR = Path("audio")
CACHE_DIR = Path("data") / "cache"
CSV_PATH = Path("data") / "lagos_weather.csv"
LOG_PATH = Path("data") / "outside_log.csv"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {
    "forecast_cache": {},  # {issue_time_str: {"fcst_df_records": [...], "facts": {...}}}
    "trained_models": None,  # {"clf": ..., "reg": ..., "feats": ...}
    "brief_cache": {},  # {f"{issue_time_str}:{activity}": {"plan_text": ..., "audio_file": ..., ...}}
    "last_brief": None,  # {"plan_text": ..., "audio_file": ..., "fallback_note": ...}
    "current_activity": "a walk",
    "current_request_id": None,
    "pipeline_running": False,
    "current_step": "idle",
    "forecast_ready": False,
    "plan_ready": False,
    "audio_ready": False,
}

# Keep strong references to background tasks to prevent GC
_active_tasks: set[asyncio.Task] = set()
_active_pipeline_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# SSE broadcast hub
# ---------------------------------------------------------------------------


class ProgressHub:
    """Pub/Sub broadcaster for pipeline progress events."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def broadcast(self, event_type: str, data: dict) -> None:
        msg = {"event": event_type, "data": data}
        for q in list(self._subscribers):
            await q.put(msg)


_hub = ProgressHub()


# ---------------------------------------------------------------------------
# Forecast cache (disk)
# ---------------------------------------------------------------------------


def _cache_key(issue_time_str: str) -> str:
    return issue_time_str.replace(" ", "_").replace(":", "-")


def _read_disk_cache(issue_time_str: str) -> dict | None:
    path = CACHE_DIR / f"forecast_{_cache_key(issue_time_str)}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _write_disk_cache(issue_time_str: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"forecast_{_cache_key(issue_time_str)}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------


async def _run_pipeline(activity: str, request_id: str | None = None) -> None:
    """Run the full brief pipeline in the background, broadcasting SSE events."""
    import pandas as pd

    from w1_go_out_today.plan import (
        OllamaConnectionError,
        OllamaModelError,
        compute_forecast_facts,
    )

    _state["pipeline_running"] = True
    _state["current_activity"] = activity
    _state["current_request_id"] = request_id
    _state["plan_ready"] = False
    _state["audio_ready"] = False

    async def emit(event_type: str, data: dict) -> None:
        data["activity"] = activity
        if request_id:
            data["request_id"] = request_id
        await _hub.broadcast(event_type, data)

    try:
        # --- Step 1-3: Forecast (check cache first) -----------------------
        cached = None
        issue_time_str = None

        # Check in-memory cache
        for key, val in _state["forecast_cache"].items():
            cached = val
            issue_time_str = key
            break

        # Check disk cache if not in memory
        if cached is None:
            now = datetime.now(UTC)
            today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now.hour >= 6:
                candidate_issue = today_6am
            else:
                candidate_issue = today_6am.replace(day=today_6am.day - 1)
            candidate_str = str(candidate_issue)
            disk = _read_disk_cache(candidate_str)
            if disk is not None:
                cached = disk
                issue_time_str = candidate_str
                _state["forecast_cache"][issue_time_str] = cached

        if cached is not None:
            logger.info("Forecast cache hit for %s", issue_time_str)
            _state["forecast_ready"] = True
            fcst_records = cached["fcst_df_records"]
            fcst_df = pd.DataFrame(fcst_records)
            facts = compute_forecast_facts(fcst_df, activity=activity)

            await emit("progress", {"step": "reading_sky", "status": "done"})
            await emit("progress", {"step": "tabpfn", "status": "done"})
            await emit(
                "forecast_ready",
                {
                    "forecast": fcst_records,
                    "facts": facts,
                    "data_up_to": cached.get("data_up_to", ""),
                    "issue_time": issue_time_str,
                    "forecast_cached": True,
                },
            )
        else:
            # Step 1: Fetch live weather
            await emit("progress", {"step": "reading_sky", "status": "running"})
            if _demo_speed:
                await asyncio.sleep(1.5)
            _state["current_step"] = "reading_sky"

            from w1_go_out_today.live_weather import fetch_live_weather

            live_df = await asyncio.to_thread(fetch_live_weather)
            logger.info("Fetched %d live weather rows", len(live_df))
            await emit("progress", {"step": "reading_sky", "status": "done"})

            # Step 2: TabPFN forecast
            await emit("progress", {"step": "tabpfn", "status": "running"})
            if _demo_speed:
                await asyncio.sleep(1.5)
            _state["current_step"] = "tabpfn"

            # Train on CSV
            from w1_go_out_today.forecast import (
                fit_models,
                forecast,
                get_splits,
                prepare_data,
            )

            csv_df = await asyncio.to_thread(
                lambda: pd.read_csv(str(CSV_PATH), parse_dates=["time"])
            )

            if _state["trained_models"] is None:
                df_pairs = await asyncio.to_thread(prepare_data, csv_df, 12, True)
                df_train, *_ = await asyncio.to_thread(get_splits, df_pairs, 3000)
                clf, reg, feats = await asyncio.to_thread(fit_models, df_train, 2)
                _state["trained_models"] = {
                    "clf": clf,
                    "reg": reg,
                    "feats": feats,
                }
            else:
                clf = _state["trained_models"]["clf"]
                reg = _state["trained_models"]["reg"]
                feats = _state["trained_models"]["feats"]

            # Determine issue time from live data
            live_df["time"] = pd.to_datetime(live_df["time"])
            six_am_rows = live_df[live_df["time"].dt.hour == 6]
            if len(six_am_rows) > 0:
                issue_time = six_am_rows["time"].max()
            else:
                issue_time = live_df["time"].max()
            issue_time_str = str(issue_time)
            data_up_to = str(live_df["time"].max().strftime("%H:%M"))

            # Run forecast
            fcst_df = await asyncio.to_thread(
                forecast, live_df, issue_time, 12, clf, reg, feats
            )

            facts = compute_forecast_facts(fcst_df, activity=activity)
            fcst_records = fcst_df.to_dict(orient="records")

            cache_entry = {
                "fcst_df_records": fcst_records,
                "facts": facts,
                "issue_time": issue_time_str,
                "data_up_to": data_up_to,
            }
            _state["forecast_cache"][issue_time_str] = cache_entry
            _write_disk_cache(issue_time_str, cache_entry)

            _state["forecast_ready"] = True
            await emit("progress", {"step": "tabpfn", "status": "done"})
            await emit(
                "forecast_ready",
                {
                    "forecast": fcst_records,
                    "facts": facts,
                    "data_up_to": data_up_to,
                    "issue_time": issue_time_str,
                    "forecast_cached": False,
                },
            )

        # Check brief cache for this activity
        brief_cache_key = f"{issue_time_str}:{activity}"
        if brief_cache_key in _state["brief_cache"]:
            logger.info("Brief cache hit for %s", brief_cache_key)
            cached_brief = dict(_state["brief_cache"][brief_cache_key])
            cached_brief["activity"] = activity
            if request_id:
                cached_brief["request_id"] = request_id
            _state["plan_ready"] = True
            _state["audio_ready"] = cached_brief.get("audio_file") is not None
            _state["last_brief"] = cached_brief
            _state["current_step"] = "done"
            await emit("progress", {"step": "plan", "status": "done"})
            await emit("progress", {"step": "voice", "status": "done"})
            await emit("brief_ready", cached_brief)
            return

        # --- Step 3: Plan text ---------------------------------------------
        await emit("progress", {"step": "plan", "status": "running"})
        if _demo_speed:
            await asyncio.sleep(1.5)
        _state["current_step"] = "plan"

        fallback_note = None
        try:
            from w1_go_out_today.plan import get_outdoor_plan

            plan_text = await asyncio.to_thread(
                get_outdoor_plan,
                fcst_df,
                activity,
                None,
                None,
                "prompts/plan.txt",
                120,
                "10m",
            )
        except (OllamaConnectionError, OllamaModelError) as exc:
            logger.warning("Ollama fallback: %s", exc)
            from w1_go_out_today.plan import generate_fallback_template

            facts_for_fallback = compute_forecast_facts(fcst_df, activity=activity)
            plan_text = generate_fallback_template(
                facts_for_fallback, activity=activity
            )
            if isinstance(exc, OllamaModelError):
                fallback_note = "Local model offline \u2014 model not pulled"
            elif "timed out" in str(exc).lower():
                fallback_note = "Local model offline \u2014 first load timed out"
            else:
                fallback_note = "Local model offline \u2014 Ollama is not running"

        _state["plan_ready"] = True
        await emit("progress", {"step": "plan", "status": "done"})

        # --- Step 4: Voice -------------------------------------------------
        await emit("progress", {"step": "voice", "status": "running"})
        if _demo_speed:
            await asyncio.sleep(1.5)
        _state["current_step"] = "voice"

        audio_file = None
        timings = None
        try:
            from w1_go_out_today.voice import generate_voice

            audio_path = await asyncio.to_thread(generate_voice, plan_text)
            if audio_path:
                audio_file = Path(audio_path).name
                stem = Path(audio_file).stem
                json_path = AUDIO_DIR / f"{stem}.json"
                if json_path.exists():
                    try:
                        timings = json.loads(json_path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        timings = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Voice generation failed: %s", exc)
            if fallback_note is None:
                fallback_note = "Voice skipped"

        _state["audio_ready"] = audio_file is not None
        await emit("progress", {"step": "voice", "status": "done"})

        # --- Done -----------------------------------------------------------
        if audio_file is None and fallback_note is None:
            fallback_note = "Voice skipped"

        brief = {
            "plan_text": plan_text,
            "audio_file": audio_file,
            "fallback_note": fallback_note,
            "timings": timings,
            "activity": activity,
            "request_id": request_id,
        }
        _state["brief_cache"][brief_cache_key] = brief
        _state["last_brief"] = brief
        _state["current_step"] = "done"
        await emit("brief_ready", brief)

    except asyncio.CancelledError:
        logger.info("Pipeline cancelled for activity %s", activity)
        raise
    except Exception as exc:
        logger.exception("Pipeline error")
        _state["current_step"] = "error"
        await emit("error", {"message": str(exc)})
    finally:
        if _state.get("current_activity") == activity:
            _state["pipeline_running"] = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/status")
async def get_status():
    return {
        "forecast_ready": _state["forecast_ready"],
        "plan_ready": _state["plan_ready"],
        "audio_ready": _state["audio_ready"],
        "pipeline_running": _state["pipeline_running"],
        "current_step": _state["current_step"],
        "current_activity": _state["current_activity"],
    }


@app.get("/warm")
async def warm_model():
    task = asyncio.create_task(_warm_ollama())
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return {"status": "warming"}


def _ping_ollama_sync(endpoint: str, payload: bytes) -> bool:
    req = urllib.request.Request(
        endpoint, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5):
        return True


@app.get("/health")
async def health_check():
    from w1_go_out_today.plan import DEFAULT_OLLAMA_MODEL, DEFAULT_OLLAMA_URL

    ollama_ok = False
    ollama_error = None
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)
    try:
        endpoint = f"{base_url.rstrip('/')}/api/generate"
        payload = json.dumps(
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "options": {"num_predict": 0},
            }
        ).encode()
        await asyncio.to_thread(_ping_ollama_sync, endpoint, payload)
        ollama_ok = True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        ollama_error = str(exc)
    return {
        "status": "ok" if ollama_ok else "degraded",
        "ollama": {
            "status": "ok" if ollama_ok else "error",
            "model": model,
            "error": ollama_error,
        },
        "forecast_cached": bool(_state["forecast_cache"]),
    }


@app.get("/events")
async def sse_events(request: Request):
    q = _hub.subscribe()
    activity = request.query_params.get("activity")

    async def event_generator():
        try:
            # Send current state immediately
            yield _sse_format(
                "status",
                {
                    "forecast_ready": _state["forecast_ready"],
                    "pipeline_running": _state["pipeline_running"],
                    "current_step": _state["current_step"],
                    "current_activity": _state.get("current_activity"),
                },
            )

            # If matching brief is already done, send it immediately
            issue_time_str = next(iter(_state["forecast_cache"].keys()), None)
            target_brief = None
            if activity and issue_time_str:
                target_brief = _state["brief_cache"].get(f"{issue_time_str}:{activity}")
            if target_brief is None and _state.get("last_brief"):
                lb = _state["last_brief"]
                if not activity or lb.get("activity") == activity:
                    target_brief = lb

            if target_brief is not None:
                yield _sse_format("brief_ready", target_brief)
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    data = msg["data"]
                    if (
                        activity
                        and isinstance(data, dict)
                        and data.get("activity")
                        and data["activity"] != activity
                    ):
                        continue
                    yield _sse_format(msg["event"], data)
                    if msg["event"] in ("brief_ready", "error"):
                        break
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            _hub.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_format(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/forecast")
async def get_forecast():
    for val in _state["forecast_cache"].values():
        return JSONResponse(val["fcst_df_records"])
    return JSONResponse([], status_code=404)


@app.post("/brief")
async def start_brief(request: Request):
    global _active_pipeline_task
    body = await request.json()
    activity = body.get("activity", "a walk")
    request_id = body.get("request_id")

    issue_time_str = next(iter(_state["forecast_cache"].keys()), None)
    brief_cache_key = f"{issue_time_str}:{activity}" if issue_time_str else None

    if brief_cache_key and brief_cache_key in _state["brief_cache"]:
        cached_brief = dict(_state["brief_cache"][brief_cache_key])
        cached_brief["activity"] = activity
        if request_id:
            cached_brief["request_id"] = request_id
        _state["current_activity"] = activity
        _state["current_request_id"] = request_id
        _state["last_brief"] = cached_brief
        _state["pipeline_running"] = False
        _state["current_step"] = "done"

        await _hub.broadcast(
            "progress", {"step": "reading_sky", "status": "done", "activity": activity}
        )
        await _hub.broadcast(
            "progress", {"step": "tabpfn", "status": "done", "activity": activity}
        )
        await _hub.broadcast(
            "progress", {"step": "plan", "status": "done", "activity": activity}
        )
        await _hub.broadcast(
            "progress", {"step": "voice", "status": "done", "activity": activity}
        )
        await _hub.broadcast("brief_ready", cached_brief)
        return {"status": "cached", "activity": activity}

    if _active_pipeline_task and not _active_pipeline_task.done():
        _active_pipeline_task.cancel()

    _state["pipeline_running"] = True
    _state["current_activity"] = activity
    _state["current_request_id"] = request_id

    task = asyncio.create_task(_run_pipeline(activity, request_id))
    _active_pipeline_task = task
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return {"status": "started", "activity": activity}


def _append_outside_log(activity: str, note: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["datetime", "activity", "note"])
        writer.writerow([datetime.now(UTC).isoformat(), activity, note])


@app.post("/went-outside")
async def went_outside(request: Request):
    body = await request.json()
    activity = body.get("activity", "")
    note = body.get("note", "")

    await asyncio.to_thread(_append_outside_log, activity, note)
    return {"status": "logged"}


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    path = AUDIO_DIR / filename
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg")
