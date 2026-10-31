"""Tiny SQLite storage for logged meals. Items are stored as JSON on the meal row."""
import json
import sqlite3
from contextlib import contextmanager

from . import config
from .schemas import FoodItem, MealIn, MealOut


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                eaten_at TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_calories REAL NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_meals_eaten_at ON meals(eaten_at)")


def _row_to_meal(row: sqlite3.Row) -> MealOut:
    return MealOut(
        id=row["id"],
        eaten_at=row["eaten_at"],
        meal_type=row["meal_type"],
        items=[FoodItem(**i) for i in json.loads(row["items_json"])],
        total_calories=row["total_calories"],
    )


def add_meal(meal: MealIn) -> MealOut:
    total = round(sum(i.calories for i in meal.items))
    items_json = json.dumps([i.model_dump() for i in meal.items])
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO meals (eaten_at, meal_type, items_json, total_calories) VALUES (?, ?, ?, ?)",
            (meal.eaten_at, meal.meal_type, items_json, total),
        )
        meal_id = cur.lastrowid
    return MealOut(id=meal_id, total_calories=total, **meal.model_dump())


def meals_on(date: str) -> list[MealOut]:
    # eaten_at is 'YYYY-MM-DDTHH:MM' in the user's local time, so a prefix match selects the day.
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM meals WHERE eaten_at LIKE ? ORDER BY eaten_at", (f"{date}%",)
        ).fetchall()
    return [_row_to_meal(r) for r in rows]


def delete_meal(meal_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        return cur.rowcount > 0
