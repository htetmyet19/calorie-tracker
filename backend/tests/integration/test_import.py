import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import import_sqlite  # noqa: E402

ROWS = [
    ("2026-10-01T08:15", "breakfast", [{"name": "oats", "calories": 300}], 300.0),
    ("2026-10-01T13:00", "lunch", [{"name": "rice", "calories": 520.5}], 520.5),
    ("2026-10-02T19:30", "dinner", [{"name": "dal", "calories": 410}], 410.0),
]


def _make_db(path: Path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE meals (id INTEGER PRIMARY KEY AUTOINCREMENT, eaten_at TEXT NOT NULL, "
                "meal_type TEXT NOT NULL, items_json TEXT NOT NULL, total_calories REAL NOT NULL)")
    for at, kind, items, total in ROWS:
        con.execute("INSERT INTO meals (eaten_at, meal_type, items_json, total_calories) VALUES (?,?,?,?)",
                    (at, kind, json.dumps(items), total))
    con.commit()
    con.close()


@pytest.mark.integration
def test_import_copies_all_meals(make_user, service, tmp_path):
    owner = make_user("client")
    db = tmp_path / "old.db"
    _make_db(db)

    assert import_sqlite.main(["--db", str(db), "--owner", owner.id]) == 0
    r = service.get("/meals", params={"user_id": f"eq.{owner.id}", "order": "eaten_at"})
    got = r.json()
    assert [(m["eaten_at"][:16], m["meal_type"], m["total_calories"]) for m in got] == [
        (at, kind, total) for at, kind, _, total in ROWS]
    assert got[1]["items"] == ROWS[1][2]

    assert import_sqlite.main(["--db", str(db), "--owner", owner.id]) == 1
    r = service.get("/meals", params={"user_id": f"eq.{owner.id}"})
    assert len(r.json()) == 3
