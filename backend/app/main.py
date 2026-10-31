import datetime
import re

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from . import config
from .analysis import AnalysisError, analyze_meal
from .auth import User, current_user
from .schemas import AnalyzeResponse, DayLog, MealIn, MealOut, ProfileOut, RoleIn
from .store import ProfileExists, Store, StoreUnavailable, get_store

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


app = FastAPI(title="Calorie Tracker")


@app.exception_handler(StoreUnavailable)
async def store_unavailable_handler(request: Request, exc: StoreUnavailable):
    return JSONResponse(
        {"detail": "The database is unreachable. Try again in a minute."}, status_code=503
    )


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
    try:
        if not DATE_RE.match(date):
            raise ValueError(date)
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "date must be a real YYYY-MM-DD date")
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
def remove_meal(meal_id: int, store: Store = Depends(require_profile)):
    if not store.delete_meal(meal_id):
        raise HTTPException(404, "Meal not found")


# Serves static/index.html and its assets at "/". API routes above are matched first.
app.frontend("/", directory=config.STATIC_DIR)
