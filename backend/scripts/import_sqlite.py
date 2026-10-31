"""One-off import of meals from the old SQLite file into Supabase Postgres.

Usage (from backend/):
    .venv/bin/python scripts/import_sqlite.py --db data/calories.db --owner <auth user uuid> [--force]

Uses the service-role key (backend/.env). Refuses if the owner has no profile,
or already has meals unless --force. All rows go in one request, so a failure
does not leave a partial import.
"""
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import config  # noqa: E402


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def _read_rows(db_path: Path) -> list[dict]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT eaten_at, meal_type, items_json, total_calories FROM meals ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    return [
        {"eaten_at": at, "meal_type": kind, "items": json.loads(items), "total_calories": total}
        for at, kind, items, total in rows
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import SQLite meals into Supabase.")
    p.add_argument("--db", required=True, type=Path, help="path to the SQLite file")
    p.add_argument("--owner", required=True, help="auth user UUID that will own the meals")
    p.add_argument("--force", action="store_true", help="import even if the owner already has meals")
    args = p.parse_args(argv)

    try:
        owner = str(uuid.UUID(args.owner))
    except ValueError:
        return _fail("--owner must be a UUID")
    if not args.db.is_file():
        return _fail(f"SQLite file not found: {args.db}")
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
        return _fail("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (backend/.env)")

    try:
        rows = _read_rows(args.db)
    except (sqlite3.Error, ValueError) as e:
        return _fail(f"Could not read meals from {args.db}: {type(e).__name__}")

    key = config.SUPABASE_SERVICE_ROLE_KEY
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(base_url=config.SUPABASE_URL + "/rest/v1", headers=headers,
                          timeout=config.SUPABASE_TIMEOUT) as c:
            r = c.get("/profiles", params={"id": f"eq.{owner}", "select": "id"})
            if r.status_code != 200:
                return _fail(f"Supabase rejected the profile lookup (HTTP {r.status_code})")
            if not r.json():
                return _fail("Owner has no profile; sign in once and choose a role first.")
            if not args.force:
                r = c.get("/meals", params={"user_id": f"eq.{owner}", "select": "id", "limit": "1"})
                if r.status_code != 200:
                    return _fail(f"Supabase rejected the meals lookup (HTTP {r.status_code})")
                if r.json():
                    return _fail("Owner already has meals; use --force to import anyway.")
            if rows:
                r = c.post("/meals", json=[{**row, "user_id": owner} for row in rows])
                if r.status_code not in (200, 201, 204):
                    return _fail(f"Supabase rejected the import (HTTP {r.status_code})")
    except httpx.HTTPError as e:
        return _fail(f"Could not reach Supabase: {type(e).__name__}")

    print(f"Imported {len(rows)} meals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
