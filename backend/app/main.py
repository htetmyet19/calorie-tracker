import datetime
import hmac
import logging
import re

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import config, cron
from .analysis import AnalysisError, analyze_meal
from .meal_advice import get_advice, meal_facts
from .auth import User, current_user
from .checkin_rules import is_due, next_due_on
from .routine_ai import build_plan
from .routine_rules import Inputs, NotEnoughExercises, build_frame, finalize_plan, week_start
from .schemas import (ActiveRoutineOut, AdviceIn, AdviceOut, AnalyzeResponse, CheckinIn, CheckinList, CheckinOut, DailyTotal, DayLog, MealIn, MealOut, PhotoOut, PhotoRecordIn, PhotoUploadIn, ProfileOut, PushEndpointIn, PushSubscriptionIn, RoleIn,
                      RoutineIn, RoutineOut, SettingsIn, SettingsOut, WeightIn, WeightOut)
from .storage import Storage, StorageError, UploadRejected, new_path
from .store import (EndpointTaken, ProfileExists, RoutineBusy, RoutineLimit, SettingsExist, Store, StoreUnavailable,
                    get_store)

log = logging.getLogger("calorie_tracker")

MEAL_BUCKET = "meal-photos"
PROGRESS_BUCKET = "progress-photos"
MAX_MEAL_PHOTO_BYTES = 300 * 1024
MEAL_PHOTO_TYPES = ("image/jpeg", "image/png", "image/webp")
SIGNED_URL_SECONDS = 300

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_day(value: str, field: str) -> datetime.date:
    """Parse a strict YYYY-MM-DD calendar date or raise 400."""
    try:
        if not DATE_RE.match(value):
            raise ValueError(value)
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{field} must be a real YYYY-MM-DD date")


app = FastAPI(title="Calorie Tracker")


@app.middleware("http")
async def revalidate_app_files(request: Request, call_next):
    """Pages and their JS/CSS: the browser must check for a newer copy (a cheap 304 if
    unchanged). Without this it may reuse old JS after a deploy, next to new HTML."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.exception_handler(StoreUnavailable)
async def store_unavailable_handler(request: Request, exc: StoreUnavailable):
    return JSONResponse(
        {"detail": "The database is unreachable. Try again in a minute."}, status_code=503
    )


def get_storage(user: User = Depends(current_user)) -> Storage:
    return Storage(user)


def require_profile(store: Store = Depends(get_store)) -> Store:
    if store.get_profile() is None:
        raise HTTPException(409, "choose_role")
    return store


@app.get("/api/public-config")
async def public_config():
    return {
        "supabase_url": config.SUPABASE_URL,
        "supabase_publishable_key": config.SUPABASE_PUBLISHABLE_KEY,
    }


@app.get("/api/me", response_model=ProfileOut)
def me(store: Store = Depends(get_store)):
    profile = store.get_profile()
    if profile is None:
        raise HTTPException(404, "no_profile")
    return profile


@app.post("/api/me/role", response_model=ProfileOut, status_code=201)
def choose_role(body: RoleIn, store: Store = Depends(get_store)):
    try:
        return store.create_profile(body.role, body.display_name)
    except ProfileExists:
        raise HTTPException(409, "Role already chosen")


@app.get("/api/health")
async def health():
    if config.LLM_PROVIDER == "gemini":
        return {"ok": True, "provider": "gemini", "model": config.GEMINI_MODEL, "api_key_set": bool(config.GEMINI_API_KEY)}
    from .ollama_client import status

    problem = await status()
    # api_key_set stays in the response because the Android app checks it; a local model needs no key.
    return {"ok": problem is None, "provider": "ollama", "model": config.OLLAMA_MODEL, "api_key_set": True, "detail": problem}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(photo: UploadFile = File(...), user: User = Depends(current_user)):
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(400, "Please upload an image file.")
    raw = await photo.read()
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image is larger than 10 MB.")
    try:
        return await analyze_meal(raw)
    except AnalysisError as e:
        raise HTTPException(e.status_code, e.message)


@app.post("/api/meals/advice", response_model=AdviceOut)
async def meal_advice(body: AdviceIn, store: Store = Depends(require_profile)):
    """How a just-estimated meal fits the day. Nothing about it is stored."""
    day = parse_day(body.date, "date")
    # The browser sends its local date, at most one day ahead of UTC.
    if day > utc_today() + datetime.timedelta(days=1):
        raise HTTPException(400, "date is in the future")
    meals = await run_in_threadpool(store.meals_on, day)
    settings = await run_in_threadpool(store.get_settings) or {}
    facts = meal_facts([i.model_dump() for i in body.items],
                       sum(m.total_calories for m in meals),
                       settings.get("goal_kcal"), settings.get("weight_goal"))
    allowed = await run_in_threadpool(store.record_advice)
    text, source, _reason = await get_advice(facts, allow_ai=allowed)
    return AdviceOut(text=text, verdict=facts.verdict, source=source)


@app.post("/api/meals", response_model=MealOut, status_code=201)
def create_meal(meal: MealIn, store: Store = Depends(require_profile)):
    return store.add_meal(meal)


MAX_TOTALS_DAYS = 31


@app.get("/api/meals/daily-totals", response_model=list[DailyTotal])
def daily_totals(from_: str = Query(..., alias="from", description="YYYY-MM-DD"),
                 to: str = Query(..., description="YYYY-MM-DD"),
                 store: Store = Depends(require_profile)):
    """Calories per day from..to inclusive, zero-filled; at most 31 days."""
    start, end = parse_day(from_, "from"), parse_day(to, "to")
    if start > end:
        raise HTTPException(400, "from must not be after to")
    if (end - start).days + 1 > MAX_TOTALS_DAYS:
        raise HTTPException(400, f"range must be at most {MAX_TOTALS_DAYS} days")
    return store.daily_totals(start, end)


@app.get("/api/meals", response_model=DayLog)
def list_meals(date: str = Query(..., description="YYYY-MM-DD"), store: Store = Depends(require_profile)):
    day = parse_day(date, "date")
    meals = store.meals_on(day)
    items = [i for m in meals for i in m.items]
    return DayLog(
        date=date,
        meals=meals,
        total_calories=round(sum(m.total_calories for m in meals)),
        protein_g=round(sum(i.protein_g for i in items), 1),
        carbs_g=round(sum(i.carbs_g for i in items), 1),
        fat_g=round(sum(i.fat_g for i in items), 1),
    )


@app.delete("/api/meals/{meal_id}", status_code=204)
def remove_meal(meal_id: int, store: Store = Depends(require_profile),
                storage: Storage = Depends(get_storage)):
    row = store.delete_meal_returning(meal_id)
    if row is None:
        raise HTTPException(404, "Meal not found")
    if row.get("photo_path"):
        # The row is already gone; an orphaned file is removed by the daily job's orphan sweep (Task 7).
        try:
            storage.remove(MEAL_BUCKET, [row["photo_path"]])
        except Exception as e:
            log.warning("meal_photo_delete_failed meal_id=%s error=%s", meal_id, type(e).__name__)
    return Response(status_code=204)


@app.put("/api/meals/{meal_id}/photo", status_code=204)
async def put_meal_photo(meal_id: int, photo: UploadFile = File(...),
                         store: Store = Depends(require_profile),
                         storage: Storage = Depends(get_storage)):
    old = await run_in_threadpool(store.meal_photo_path, meal_id)
    if old is False:
        raise HTTPException(404, "Meal not found")
    content_type = (photo.content_type or "").lower()
    if content_type not in MEAL_PHOTO_TYPES:
        raise HTTPException(400, "Photo must be a JPEG, PNG or WebP image.")
    raw = await photo.read(MAX_MEAL_PHOTO_BYTES + 1)
    if len(raw) > MAX_MEAL_PHOTO_BYTES:
        raise HTTPException(413, "Photo is larger than 300 KB.")
    path = new_path(store.user.id)
    try:
        await run_in_threadpool(storage.upload, MEAL_BUCKET, path, raw, content_type)
    except UploadRejected:
        raise HTTPException(400, "Photo was rejected.")
    if not await run_in_threadpool(store.set_meal_photo, meal_id, path):
        # Meal vanished between the lookup and the update: do not leave an orphan.
        await run_in_threadpool(storage.remove, MEAL_BUCKET, [path])
        raise HTTPException(404, "Meal not found")
    if old:
        try:
            await run_in_threadpool(storage.remove, MEAL_BUCKET, [old])
        except Exception as e:
            log.warning("meal_photo_delete_failed meal_id=%s error=%s", meal_id, type(e).__name__)
    return Response(status_code=204)


@app.get("/api/meals/{meal_id}/photo")
def get_meal_photo(meal_id: int, store: Store = Depends(require_profile),
                   storage: Storage = Depends(get_storage)):
    path = store.meal_photo_path(meal_id)
    if not path:  # False: not found / not owner; None: no photo
        raise HTTPException(404, "Photo not found")
    try:
        url = storage.signed_url(MEAL_BUCKET, path, SIGNED_URL_SECONDS)
    except StorageError:  # row points at a missing object; StoreUnavailable still gives 503
        raise HTTPException(404, "Photo not found")
    return RedirectResponse(url, status_code=307)


@app.get("/api/settings", response_model=SettingsOut)
def get_settings(store: Store = Depends(require_profile)):
    return store.get_settings() or SettingsOut()


@app.put("/api/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, only_if_empty: bool = Query(False),
                 store: Store = Depends(require_profile)):
    try:
        return store.put_settings(body, only_if_empty=only_if_empty)
    except SettingsExist:
        raise HTTPException(409, "settings_exist")


MAX_WEIGHT_SPAN_DAYS = 400


@app.get("/api/weights", response_model=list[WeightOut])
def list_weights(from_: str = Query(..., alias="from", description="YYYY-MM-DD"),
                 to: str = Query(..., description="YYYY-MM-DD"),
                 store: Store = Depends(require_profile)):
    start, end = parse_day(from_, "from"), parse_day(to, "to")
    if start > end:
        raise HTTPException(400, "from must not be after to")
    if (end - start).days > MAX_WEIGHT_SPAN_DAYS:
        raise HTTPException(400, f"range must be at most {MAX_WEIGHT_SPAN_DAYS} days")
    return store.weights_between(start, end)


@app.put("/api/weights/{day}", response_model=WeightOut)
def put_weight(day: str, body: WeightIn, store: Store = Depends(require_profile)):
    return store.upsert_weight(parse_day(day, "date"), body.weight_kg)


@app.delete("/api/weights/{day}", status_code=204)
def remove_weight(day: str, store: Store = Depends(require_profile)):
    if not store.delete_weight(parse_day(day, "date")):
        raise HTTPException(404, "Weight not found")


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _signed_photos(storage: Storage, photos: list[dict]) -> list[PhotoOut]:
    out = []
    for p in photos:
        try:
            url = storage.signed_url(PROGRESS_BUCKET, p["photo_path"], SIGNED_URL_SECONDS)
        except StorageError:  # row points at a missing object: leave it out
            continue
        out.append(PhotoOut(id=p["id"], pose=p["pose"], url=url))
    return out


@app.post("/api/checkins", response_model=CheckinOut, status_code=201)
def create_checkin(body: CheckinIn, response: Response, store: Store = Depends(require_profile),
                   storage: Storage = Depends(get_storage)):
    """Create the day's check-in (201), or return the one that exists for that day (200).

    A retry after a timeout must not create a second check-in. A weight sent again
    is upserted into that day's weight log.
    """
    day = parse_day(body.checked_on, "checked_on")
    # The browser sends its local date, at most one day ahead of UTC.
    if day > utc_today() + datetime.timedelta(days=1):
        raise HTTPException(400, "checked_on is in the future")
    existing = store.checkin_on(day)
    if existing is None:
        row = store.create_checkin(day, body.weight_kg)
        store.reset_reminders()
        return CheckinOut(id=row["id"], checked_on=row["checked_on"], weight_kg=row["weight_kg"])
    if body.weight_kg is not None:
        store.upsert_weight(day, body.weight_kg)
        existing = store.checkin_on(day) or existing
    store.reset_reminders()
    response.status_code = 200
    return CheckinOut(id=existing["id"], checked_on=existing["checked_on"],
                      weight_kg=existing["weight_kg"],
                      photos=_signed_photos(storage, existing["photos"]))


def _own_checkin(store: Store, checkin_id: int) -> dict:
    row = store.get_checkin(checkin_id)
    if row is None:
        raise HTTPException(404, "Check-in not found")
    return row


@app.post("/api/checkins/{checkin_id}/photos/upload-url")
def checkin_photo_upload_url(checkin_id: int, body: PhotoUploadIn,
                             store: Store = Depends(require_profile),
                             storage: Storage = Depends(get_storage)):
    _own_checkin(store, checkin_id)
    path = new_path(store.user.id)
    try:
        url = storage.signed_upload_url(PROGRESS_BUCKET, path)
    except StorageError:
        raise HTTPException(502, "Could not prepare the upload.")
    return {"upload_url": url, "path": path}


@app.post("/api/checkins/{checkin_id}/photos", response_model=PhotoOut, status_code=201)
def record_checkin_photo(checkin_id: int, body: PhotoRecordIn,
                         store: Store = Depends(require_profile),
                         storage: Storage = Depends(get_storage)):
    _own_checkin(store, checkin_id)
    if not body.path.startswith(f"{store.user.id}/") or ".." in body.path:
        raise HTTPException(400, "Invalid photo path.")
    if not storage.exists(PROGRESS_BUCKET, body.path):
        raise HTTPException(400, "photo_not_uploaded")
    old = store.photo_for_pose(checkin_id, body.pose)
    row = store.upsert_photo(checkin_id, body.pose, body.path)
    if old and old["photo_path"] != body.path:
        # The row already points at the new file; a leftover is removed by the daily orphan sweep.
        try:
            storage.remove(PROGRESS_BUCKET, [old["photo_path"]])
        except Exception as e:
            log.warning("progress_photo_delete_failed photo_id=%s error=%s", row["id"], type(e).__name__)
    try:
        url = storage.signed_url(PROGRESS_BUCKET, body.path, SIGNED_URL_SECONDS)
    except StorageError:
        raise HTTPException(502, "Could not create a link for the photo.")
    return PhotoOut(id=row["id"], pose=row["pose"], url=url)


@app.get("/api/checkins", response_model=CheckinList)
def list_checkins(today: str = Query(..., description="YYYY-MM-DD, the browser's local date"),
                  limit: int = Query(26, ge=1, le=100),
                  store: Store = Depends(require_profile),
                  storage: Storage = Depends(get_storage)):
    today_d = parse_day(today, "today")
    rows = store.list_checkins(limit)
    checkins = [CheckinOut(id=r["id"], checked_on=r["checked_on"], weight_kg=r["weight_kg"],
                           photos=_signed_photos(storage, r["photos"])) for r in rows]
    last = datetime.date.fromisoformat(rows[0]["checked_on"]) if rows else None
    return CheckinList(checkins=checkins, next_due_on=next_due_on(last, today_d).isoformat(),
                       due=is_due(last, today_d))


@app.delete("/api/progress-photos/{photo_id}", status_code=204)
def remove_progress_photo(photo_id: int, store: Store = Depends(require_profile),
                          storage: Storage = Depends(get_storage)):
    row = store.delete_photo_returning(photo_id)
    if row is None:
        raise HTTPException(404, "Photo not found")
    try:
        storage.remove(PROGRESS_BUCKET, [row["photo_path"]])
    except Exception as e:
        log.warning("progress_photo_delete_failed photo_id=%s error=%s", photo_id, type(e).__name__)
    return Response(status_code=204)


# ---- workout routines ----

NOT_ENOUGH_EXERCISES = "Not enough exercises for these choices yet. Try other equipment."
ROUTINE_LIMIT = "You've made 5 routines today. Try again tomorrow."
ROUTINE_BUSY = "Another routine was just built. Reload to see it."


def _routine_out(row: dict, videos: dict[int, dict]) -> RoutineOut:
    days = []
    for d in row["plan"]["days"]:
        items = []
        for it in d["items"]:
            v = videos.get(it["video_id"])
            items.append({
                **{k: it[k] for k in ("video_id", "sets", "reps", "seconds", "rest_sec")},
                "warm_up": bool(it.get("warm_up")),
                "youtube_id": v["youtube_id"] if v else "",
                "title": v["title"] if v else "Exercise",
                "channel": v["channel"] if v else "",
                "category": v["category"] if v else "",
                "available": bool(v and v.get("active", True)),
            })
        days.append({**{k: d[k] for k in ("index", "type", "title", "why", "est_min")}, "items": items})
    return RoutineOut(
        id=row["id"], created_at=str(row["created_at"]), days_per_week=row["days_per_week"],
        level=row["level"], equipment=row["equipment"], session_min=row["session_min"],
        goal=row["goal"], source=row["source"], note=row["plan"].get("note"), days=days)


@app.post("/api/routines", response_model=RoutineOut, status_code=201)
async def create_routine(body: RoutineIn, store: Store = Depends(require_profile)):
    settings = await run_in_threadpool(store.get_settings)
    goal = (settings or {}).get("weight_goal") or "maintain"
    videos = await run_in_threadpool(store.active_videos)
    inputs = Inputs(body.days_per_week, body.level, body.equipment, body.session_min)
    try:
        frame = build_frame(inputs, goal, videos)
    except NotEnoughExercises:
        raise HTTPException(409, NOT_ENOUGH_EXERCISES)
    # Counted before the AI call, so a build whose save later fails still counts.
    try:
        await run_in_threadpool(store.record_build)
    except RoutineLimit:
        raise HTTPException(429, ROUTINE_LIMIT)
    try:
        plan, source, reason = await build_plan(frame)
    except NotEnoughExercises:
        raise HTTPException(409, NOT_ENOUGH_EXERCISES)
    try:
        row = await run_in_threadpool(store.create_routine, {
            "days_per_week": inputs.days_per_week, "level": inputs.level,
            "equipment": inputs.equipment, "session_min": inputs.session_min, "goal": goal,
            "source": source, "fallback_reason": reason, "plan": finalize_plan(plan, frame)})
    except RoutineBusy:
        raise HTTPException(409, ROUTINE_BUSY)
    return _routine_out(row, {v["id"]: v for v in videos})


@app.get("/api/routines/active", response_model=ActiveRoutineOut)
def active_routine(today: str = Query(..., description="YYYY-MM-DD, the browser's local date"),
                   store: Store = Depends(require_profile)):
    day = parse_day(today, "today")
    row = store.active_routine()
    if row is None:
        return ActiveRoutineOut(routine=None, done=[], week_start=None)
    ids = [it["video_id"] for d in row["plan"]["days"] for it in d["items"]]
    start = week_start(day)
    done = store.sessions_between(row["id"], start, start + datetime.timedelta(days=6))
    return ActiveRoutineOut(routine=_routine_out(row, store.videos_by_ids(ids)),
                            done=done, week_start=start.isoformat())


def _tick_target(store: Store, routine_id: int, day_index: int, day: str) -> datetime.date:
    row = store.get_routine(routine_id)
    if row is None or not row["active"] or not 0 <= day_index < len(row["plan"]["days"]):
        raise HTTPException(404, "Routine day not found")
    d = parse_day(day, "day")
    # The browser sends its local date, at most one day ahead of UTC.
    if d > utc_today() + datetime.timedelta(days=1):
        raise HTTPException(400, "day is in the future")
    return d


@app.put("/api/routines/{routine_id}/days/{day_index}/done/{day}", status_code=204)
def mark_day_done(routine_id: int, day_index: int, day: str, store: Store = Depends(require_profile)):
    store.mark_done(routine_id, day_index, _tick_target(store, routine_id, day_index, day))
    return Response(status_code=204)


@app.delete("/api/routines/{routine_id}/days/{day_index}/done/{day}", status_code=204)
def unmark_day_done(routine_id: int, day_index: int, day: str, store: Store = Depends(require_profile)):
    store.unmark_done(routine_id, day_index, _tick_target(store, routine_id, day_index, day))
    return Response(status_code=204)


@app.get("/api/push/public-key")
def push_public_key():
    if not config.push_configured():
        raise HTTPException(503, "Push is not configured")
    return {"key": config.VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe", status_code=201)
def push_subscribe(body: PushSubscriptionIn, store: Store = Depends(require_profile)):
    try:
        store.add_push_subscription(str(body.endpoint), body.keys.p256dh, body.keys.auth)
    except EndpointTaken:
        raise HTTPException(409, "endpoint_taken")
    return Response(status_code=201)


@app.delete("/api/push/subscribe", status_code=204)
def push_unsubscribe(body: PushEndpointIn, store: Store = Depends(require_profile)):
    store.remove_push_subscription(str(body.endpoint))
    return Response(status_code=204)


@app.get("/api/cron/daily")
def cron_daily(request: Request):
    expected = config.CRON_SECRET
    given = request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(given.encode(), f"Bearer {expected}".encode()):
        raise HTTPException(401, "Unauthorized")
    return cron.run_daily(datetime.datetime.now(datetime.timezone.utc))


# Serves static/index.html and its assets at "/". Registered last so that every
# /api route above is matched before the static catch-all.
app.frontend("/", directory=config.STATIC_DIR)
