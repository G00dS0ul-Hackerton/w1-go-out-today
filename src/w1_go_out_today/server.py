"""FastAPI server for the Go Out Today? morning brief web UI."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="Go Out Today?")

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
    "last_brief": None,  # {"plan_text": ..., "audio_file": ..., "fallback_note": ...}
    "pipeline_running": False,
    "current_step": "idle",
    "forecast_ready": False,
    "plan_ready": False,
    "audio_ready": False,
}

# Keep strong references to background tasks to prevent GC
_active_tasks: set[asyncio.Task] = set()


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


async def _run_pipeline(activity: str) -> None:
    """Run the full brief pipeline in the background, broadcasting SSE events."""
    import pandas as pd

    _state["pipeline_running"] = True
    _state["plan_ready"] = False
    _state["audio_ready"] = False
    _state["last_brief"] = None

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
            await _hub.broadcast("progress", {"step": "reading_sky", "status": "done"})
            await _hub.broadcast("progress", {"step": "tabpfn", "status": "done"})
            await _hub.broadcast(
                "forecast_ready",
                {
                    "forecast": cached["fcst_df_records"],
                    "facts": cached["facts"],
                    "data_up_to": cached.get("data_up_to", ""),
                    "issue_time": issue_time_str,
                },
            )
        else:
            # Step 1: Fetch live weather
            await _hub.broadcast(
                "progress", {"step": "reading_sky", "status": "running"}
            )
            _state["current_step"] = "reading_sky"

            from w1_go_out_today.live_weather import fetch_live_weather

            live_df = await asyncio.to_thread(fetch_live_weather)
            logger.info("Fetched %d live weather rows", len(live_df))
            await _hub.broadcast("progress", {"step": "reading_sky", "status": "done"})

            # Step 2: TabPFN forecast
            await _hub.broadcast("progress", {"step": "tabpfn", "status": "running"})
            _state["current_step"] = "tabpfn"

            # Train on CSV
            from w1_go_out_today.forecast import (
                forecast,
                get_splits,
                prepare_data,
                train_and_evaluate,
            )

            csv_df = await asyncio.to_thread(
                lambda: pd.read_csv(str(CSV_PATH), parse_dates=["time"])
            )

            if _state["trained_models"] is None:
                df_pairs = await asyncio.to_thread(prepare_data, csv_df, 12, True)
                df_train, df_test, df_pre_test = await asyncio.to_thread(
                    get_splits, df_pairs, 3000
                )
                clf, reg, feats, *_ = await asyncio.to_thread(
                    train_and_evaluate, df_train, df_test, df_pre_test, 2, True
                )
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

            # Compute facts for timeline
            from w1_go_out_today.plan import compute_forecast_facts

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
            await _hub.broadcast("progress", {"step": "tabpfn", "status": "done"})
            await _hub.broadcast(
                "forecast_ready",
                {
                    "forecast": fcst_records,
                    "facts": facts,
                    "data_up_to": data_up_to,
                    "issue_time": issue_time_str,
                },
            )

        # --- Step 3: Plan text ---------------------------------------------
        await _hub.broadcast("progress", {"step": "plan", "status": "running"})
        _state["current_step"] = "plan"

        fcst_records = cached["fcst_df_records"] if cached else fcst_records
        facts = cached["facts"] if cached else facts

        import pandas as pd

        fcst_df = pd.DataFrame(fcst_records)

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
        except SystemExit:
            from w1_go_out_today.plan import (
                compute_forecast_facts,
                generate_fallback_template,
            )

            facts_for_fallback = compute_forecast_facts(fcst_df, activity=activity)
            plan_text = generate_fallback_template(
                facts_for_fallback, activity=activity
            )
            fallback_note = "Local model offline"

        _state["plan_ready"] = True
        await _hub.broadcast("progress", {"step": "plan", "status": "done"})

        # --- Step 4: Voice -------------------------------------------------
        await _hub.broadcast("progress", {"step": "voice", "status": "running"})
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
        await _hub.broadcast("progress", {"step": "voice", "status": "done"})

        # --- Done -----------------------------------------------------------
        if audio_file is None and fallback_note is None:
            fallback_note = "Voice skipped"

        brief = {
            "plan_text": plan_text,
            "audio_file": audio_file,
            "fallback_note": fallback_note,
            "timings": timings,
        }
        _state["last_brief"] = brief
        _state["current_step"] = "done"
        await _hub.broadcast("brief_ready", brief)

    except Exception as exc:
        logger.exception("Pipeline error")
        _state["current_step"] = "error"
        await _hub.broadcast("error", {"message": str(exc)})
    finally:
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
    }


@app.get("/events")
async def sse_events(request: Request):
    q = _hub.subscribe()

    async def event_generator():
        try:
            # Send current state immediately
            yield _sse_format(
                "status",
                {
                    "forecast_ready": _state["forecast_ready"],
                    "pipeline_running": _state["pipeline_running"],
                    "current_step": _state["current_step"],
                },
            )

            # If brief is already done, send it immediately
            if _state["last_brief"] is not None:
                yield _sse_format("brief_ready", _state["last_brief"])
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield _sse_format(msg["event"], msg["data"])
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
    body = await request.json()
    activity = body.get("activity", "a walk")

    if _state["pipeline_running"]:
        return {"status": "already_running"}

    task = asyncio.create_task(_run_pipeline(activity))
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return {"status": "started"}


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
