import datetime
import logging
import re

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import config
from .analysis import AnalysisError, analyze_meal
from .auth import User, current_user
from .schemas import AnalyzeResponse, DayLog, MealIn, MealOut, ProfileOut, RoleIn, SettingsIn, SettingsOut, WeightIn, WeightOut
from .storage import Storage, UploadRejected, new_path
from .store import ProfileExists, SettingsExist, Store, StoreUnavailable, get_store

log = logging.getLogger("calorie_tracker")

MEAL_BUCKET = "meal-photos"
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
        # The row is already gone; a leftover file is retried by the retention job.
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
    url = storage.signed_url(MEAL_BUCKET, path, SIGNED_URL_SECONDS)
    return RedirectResponse(url, status_code=307)


@app.get("/api/settings", response_model=SettingsOut)
def get_settings(store: Store = Depends(require_profile)):
    return store.get_settings() or SettingsOut()


@app.put("/api/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, only_if_empty: str = Query("0"),
                 store: Store = Depends(require_profile)):
    try:
        return store.put_settings(body, only_if_empty=only_if_empty.lower() in ("1", "true"))
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


# Serves static/index.html and its assets at "/". API routes above are matched first.
app.frontend("/", directory=config.STATIC_DIR)
