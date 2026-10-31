"""Meal photo analysis: shared image prep, prompt and sanity checks, dispatched to the configured LLM provider."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config
from .schemas import AnalyzeResponse, MealAnalysis

PROMPT = """You are a nutrition assistant. Identify every distinct food and drink in this photo
and estimate its portion and nutrition.

Rules:
- List each item separately (e.g. rice, dal, and roti as three items), not one combined dish,
  unless it is a single mixed dish like biryani or pizza.
- Use visual cues (plate size, utensils, hands) to estimate grams. Assume a standard ~26 cm dinner plate
  if there is no other reference.
- Include likely hidden calories (cooking oil, ghee, butter, sugar, dressings) in the item's estimate
  and mention them in notes.
- Use typical values from standard food composition tables. Be realistic, not optimistic.
- Set confidence to "low" when the food is ambiguous or the portion is hard to judge.
- If the image does not show food, set is_food to false and return an empty items list.
"""


class AnalysisError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def prepare_image(raw: bytes) -> bytes:
    """Fix phone rotation, downscale, and re-encode as JPEG (which also strips EXIF/GPS metadata)."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise AnalysisError("Could not read the image. Use JPEG, PNG or WebP.", 400) from e
    img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def sanity_warnings(analysis: MealAnalysis) -> list[str]:
    """LLM numbers can be internally inconsistent, so check them against basic nutrition rules."""
    warnings = []
    for item in analysis.items:
        # Atwater factors: protein 4, carbs 4, fat 9 kcal/g.
        macro_kcal = 4 * item.protein_g + 4 * item.carbs_g + 9 * item.fat_g
        if item.calories > 0 and abs(macro_kcal - item.calories) / item.calories > 0.25:
            warnings.append(
                f"{item.name}: macros add up to ~{macro_kcal:.0f} kcal but calories say {item.calories:.0f}."
            )
        if item.grams > 0 and item.calories / item.grams > 9.5:
            warnings.append(f"{item.name}: {item.calories / item.grams:.1f} kcal/g is above pure fat, likely wrong.")
    return warnings


async def analyze_meal(raw_image: bytes) -> AnalyzeResponse:
    image = prepare_image(raw_image)
    if config.LLM_PROVIDER == "gemini":
        from .gemini_client import generate
    else:
        from .ollama_client import generate
    analysis = await generate(image, PROMPT)

    # Compute the total ourselves rather than trusting the model's arithmetic.
    total = round(sum(i.calories for i in analysis.items))
    return AnalyzeResponse(**analysis.model_dump(), total_calories=total, warnings=sanity_warnings(analysis))
