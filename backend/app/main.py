import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from . import config, db
from .analysis import AnalysisError, analyze_meal
from .schemas import AnalyzeResponse, DayLog, MealIn, MealOut

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Calorie Tracker", lifespan=lifespan)


@app.get("/api/health")
async def health():
    if config.LLM_PROVIDER == "gemini":
        return {"ok": True, "provider": "gemini", "model": config.GEMINI_MODEL, "api_key_set": bool(config.GEMINI_API_KEY)}
    from .ollama_client import status

    problem = await status()
    # api_key_set stays in the response because the Android app checks it; a local model needs no key.
    return {"ok": problem is None, "provider": "ollama", "model": config.OLLAMA_MODEL, "api_key_set": True, "detail": problem}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(photo: UploadFile = File(...)):
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
def create_meal(meal: MealIn):
    return db.add_meal(meal)


@app.get("/api/meals", response_model=DayLog)
def list_meals(date: str = Query(..., description="YYYY-MM-DD")):
    if not DATE_RE.match(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    meals = db.meals_on(date)
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
def remove_meal(meal_id: int):
    if not db.delete_meal(meal_id):
        raise HTTPException(404, "Meal not found")


# Serves static/index.html and its assets at "/". API routes above are matched first.
app.frontend("/", directory=config.STATIC_DIR)
