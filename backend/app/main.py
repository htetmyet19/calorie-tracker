import datetime
import hmac
import logging
import re

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import config, cron
from .analysis import AnalysisError, analyze_meal
from .auth import User, current_user
from .checkin_rules import is_due, next_due_on
from .schemas import (AnalyzeResponse, CheckinIn, CheckinList, CheckinOut, DailyTotal, DayLog, MealIn, MealOut, PhotoOut, PhotoRecordIn, PhotoUploadIn, ProfileOut, PushEndpointIn, PushSubscriptionIn, RoleIn,
                      SettingsIn, SettingsOut, WeightIn, WeightOut)
from .storage import Storage, StorageError, UploadRejected, new_path
from .store import EndpointTaken, ProfileExists, SettingsExist, Store, StoreUnavailable, get_store

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


@app.post("/api/checkins", response_model=CheckinOut, status_code=201)
def create_checkin(body: CheckinIn, store: Store = Depends(require_profile)):
    day = parse_day(body.checked_on, "checked_on")
    row = store.create_checkin(day, body.weight_kg)
    store.reset_reminders()
    return CheckinOut(id=row["id"], checked_on=row["checked_on"], weight_kg=row["weight_kg"])


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
    checkins = []
    for r in rows:
        photos = []
        for p in r["photos"]:
            try:
                url = storage.signed_url(PROGRESS_BUCKET, p["photo_path"], SIGNED_URL_SECONDS)
            except StorageError:  # row points at a missing object: leave it out
                continue
            photos.append(PhotoOut(id=p["id"], pose=p["pose"], url=url))
        checkins.append(CheckinOut(id=r["id"], checked_on=r["checked_on"],
                                   weight_kg=r["weight_kg"], photos=photos))
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


# Serves static/index.html and its assets at "/". API routes above are matched first.
app.frontend("/", directory=config.STATIC_DIR)


@app.get("/api/push/public-key")
def push_public_key():
    if not config.VAPID_PUBLIC_KEY:
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
