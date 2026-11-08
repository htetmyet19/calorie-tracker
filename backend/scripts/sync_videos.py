"""Check the exercise video library and push it to the database.

Usage (from backend/):
    .venv/bin/python scripts/sync_videos.py            # check only: labels, live links, gaps
    .venv/bin/python scripts/sync_videos.py --apply    # also write to Supabase

Edit data/exercise_videos.json by hand; every video must be watched and
approved first. --apply uses the service-role key (backend/.env): it upserts
live videos by youtube_id and hides (active = false) rows that are dead or no
longer in the file. Rows are never deleted, so old routines keep their titles.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.video_library import (DEFAULT_PATH, EQUIPMENT, LEVELS, LinkCheckFailed,  # noqa: E402
                               coverage, is_live, load_library)

# Combinations a trial client is most likely to pick; a 0 here means some routines will fail.
GAP_LEVELS = ("beginner", "intermediate")
GAP_EQUIPMENT = ("none", "dumbbells")


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def _service() -> httpx.Client:
    key = config.SUPABASE_SERVICE_ROLE_KEY
    return httpx.Client(base_url=config.SUPABASE_URL.rstrip("/") + "/rest/v1",
                        headers={"apikey": key, "Authorization": f"Bearer {key}"},
                        timeout=config.SUPABASE_TIMEOUT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--apply", action="store_true", help="write to Supabase")
    args = ap.parse_args()

    try:
        entries = load_library(args.file)
    except ValueError as e:
        return _fail(f"The library file has problems:\n{e}")
    print(f"{len(entries)} videos in {args.file}")

    dead = []
    try:
        with httpx.Client(timeout=10) as yt:
            for e in entries:
                if not is_live(e["youtube_id"], yt):
                    dead.append(e["youtube_id"])
    except LinkCheckFailed as e:
        return _fail(f"Couldn't check the links with YouTube ({e}). Nothing was changed; try again later.")
    for yid in dead:
        print(f"DEAD or private: {yid}")

    live = [e for e in entries if e["youtube_id"] not in dead]
    cov = coverage(live)
    gaps = [k for k, n in cov.items()
            if n == 0 and k[0] != "mobility" and k[1] in GAP_LEVELS and k[2] in GAP_EQUIPMENT]
    gaps.sort(key=lambda k: (LEVELS.index(k[1]), EQUIPMENT.index(k[2]), k[0]))
    for cat, lv, eq in gaps:
        print(f"GAP: no {cat} video for {lv} clients with equipment '{eq}'")
    if not gaps:
        print("No gaps for beginner/intermediate clients with no equipment or dumbbells.")

    if not args.apply:
        print("Check only. Run with --apply to write to Supabase.")
        return 0
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
        return _fail("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set (backend/.env).")

    with _service() as db:
        if live:
            r = db.post("/exercise_videos", params={"on_conflict": "youtube_id"},
                        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                        json=[{**e, "active": True} for e in live])
            if r.status_code >= 300:
                return _fail(f"Upsert failed: Supabase returned {r.status_code}")
        r = db.get("/exercise_videos", params={"select": "youtube_id", "active": "is.true"})
        if r.status_code != 200:
            return _fail(f"Reading the library failed: Supabase returned {r.status_code}")
        keep = {e["youtube_id"] for e in live}
        hide = sorted(row["youtube_id"] for row in r.json() if row["youtube_id"] not in keep)
        if hide:
            r = db.patch("/exercise_videos", params={"youtube_id": f"in.({','.join(hide)})"},
                         headers={"Prefer": "return=minimal"}, json={"active": False})
            if r.status_code >= 300:
                return _fail(f"Hiding old videos failed: Supabase returned {r.status_code}")
    print(f"Applied: {len(live)} active, {len(hide)} hidden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
