"""The curated exercise-demo library: labels, file checks and coverage.

The source of truth is data/exercise_videos.json, edited by hand and pushed to
the database by scripts/sync_videos.py. Nothing here opens a network connection itself: is_live is handed a client.
"""
import json
import re
from itertools import product
from pathlib import Path

import httpx

CATEGORIES = ("warm_up", "push", "pull", "legs", "core", "cardio", "mobility")
LEVELS = ("beginner", "intermediate", "advanced")       # low → high
EQUIPMENT = ("none", "dumbbells", "gym")                # low → high

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "exercise_videos.json"
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def usable(video: dict, level: str, equipment: str) -> bool:
    """Matching is cumulative: lower levels and lesser equipment are always allowed."""
    return (LEVELS.index(video["level"]) <= LEVELS.index(level)
            and EQUIPMENT.index(video["equipment"]) <= EQUIPMENT.index(equipment))


def _entry_errors(e: dict) -> list[str]:
    errs = []
    if not isinstance(e.get("youtube_id"), str) or not YOUTUBE_ID.match(e["youtube_id"]):
        errs.append("youtube_id must be the 11-character ID from the video URL")
    for field in ("title", "channel"):
        if not isinstance(e.get(field), str) or not e[field].strip():
            errs.append(f"{field} is missing")
    for field, allowed in (("category", CATEGORIES), ("level", LEVELS), ("equipment", EQUIPMENT)):
        if e.get(field) not in allowed:
            errs.append(f"{field} must be one of {', '.join(allowed)}")
    if "active" in e and not isinstance(e["active"], bool):
        errs.append("active must be true or false")
    d = e.get("duration_sec")
    if not isinstance(d, int) or isinstance(d, bool) or d <= 0:
        errs.append("duration_sec must be a whole number above 0")
    return errs


def validate_entries(entries: list[dict]) -> list[str]:
    """One message per bad entry (naming its youtube_id); empty when all are valid."""
    errors, seen = [], set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            errors.append(f"entry {i + 1}: not an object")
            continue
        name = e.get("youtube_id") or f"entry {i + 1}"
        errs = _entry_errors(e)
        if errs:
            errors.append(f"{name}: {'; '.join(errs)}")
        elif e["youtube_id"] in seen:
            errors.append(f"{name}: duplicate youtube_id")
        seen.add(e.get("youtube_id"))
    return errors


def load_library(path: Path = DEFAULT_PATH) -> list[dict]:
    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        raise ValueError("the library file must hold a JSON list")
    errors = validate_entries(entries)
    if errors:
        raise ValueError("\n".join(errors))
    return entries


def upsert_rows(entries: list[dict]) -> list[dict]:
    """Rows for the database; an entry marked "active": false in the file stays hidden."""
    return [{**e, "active": e.get("active", True)} for e in entries]


def coverage(entries: list[dict]) -> dict[tuple[str, str, str], int]:
    """For each (category, level, equipment): active videos a client with that level and equipment can use."""
    active = [e for e in entries if e.get("active", True)]
    return {
        (c, lv, eq): sum(1 for e in active if e["category"] == c and usable(e, lv, eq))
        for c, lv, eq in product(CATEGORIES, LEVELS, EQUIPMENT)
    }


class LinkCheckFailed(Exception):
    """YouTube couldn't be asked (network error or outage): don't treat videos as dead."""


OEMBED_URL = "https://www.youtube.com/oembed"


def is_live(youtube_id: str, client: httpx.Client) -> bool:
    """True if the video is public and embeddable, False if it is gone or private.

    client is an httpx.Client supplied by the caller (scripts/sync_videos.py).
    """
    try:
        r = client.get(OEMBED_URL, params={
            "url": f"https://www.youtube.com/watch?v={youtube_id}", "format": "json"})
    except httpx.HTTPError as e:
        raise LinkCheckFailed(type(e).__name__) from None
    if r.status_code == 200:
        return True
    if r.status_code in (401, 403, 404):
        return False
    raise LinkCheckFailed(f"YouTube returned {r.status_code}")
