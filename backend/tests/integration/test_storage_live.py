"""Storage wrapper and meal photos against the local stack, with real user tokens."""
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import User
from app.storage import Storage, UploadRejected, new_path

pytestmark = pytest.mark.integration

ITEM = {"name": "dal", "portion": "1 bowl", "grams": 200, "calories": 150,
        "protein_g": 8, "carbs_g": 20, "fat_g": 3, "confidence": "high"}
MEAL = {"eaten_at": "2026-10-31T08:00", "meal_type": "breakfast", "items": [ITEM]}
JPEG = b"\xff\xd8\xff\xe0 live-test " + uuid.uuid4().bytes


def _s(user) -> Storage:
    return Storage(User(id=user.id, token=user.token))


def auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.fixture
def api():
    with TestClient(app) as c:
        yield c


def test_upload_signed_url_exists_remove(make_user):
    a, b = make_user(), make_user()
    path = new_path(a.id)
    _s(a).upload("meal-photos", path, JPEG, "image/jpeg")
    assert _s(a).exists("meal-photos", path) is True
    url = _s(a).signed_url("meal-photos", path)
    assert url.startswith("http")
    r = httpx.get(url)
    assert (r.status_code, r.content) == (200, JPEG)
    assert _s(b).exists("meal-photos", path) is False
    _s(a).remove("meal-photos", [path])
    assert _s(a).exists("meal-photos", path) is False


def test_upload_into_other_users_folder_rejected(make_user):
    a, b = make_user(), make_user()
    with pytest.raises(UploadRejected):
        _s(b).upload("meal-photos", new_path(a.id), JPEG, "image/jpeg")


def test_duplicate_upload_rejected_unless_upsert(make_user):
    a = make_user()
    path = new_path(a.id)
    _s(a).upload("meal-photos", path, JPEG, "image/jpeg")
    with pytest.raises(UploadRejected):
        _s(a).upload("meal-photos", path, JPEG, "image/jpeg")
    _s(a).upload("meal-photos", path, b"\xff\xd8\xff2", "image/jpeg", upsert=True)
    _s(a).remove("meal-photos", [path])


def test_signed_upload_url_accepts_put(make_user):
    a = make_user()
    path = new_path(a.id)
    url = _s(a).signed_upload_url("meal-photos", path)
    r = httpx.put(url, content=JPEG, headers={"Content-Type": "image/jpeg"})
    assert r.status_code in (200, 201)
    assert _s(a).exists("meal-photos", path) is True
    _s(a).remove("meal-photos", [path])


def test_meal_photo_end_to_end(api, make_user):
    u = make_user()
    h = auth(u)
    meal = api.post("/api/meals", headers=h, json=MEAL).json()
    mid = meal["id"]
    assert meal["has_photo"] is False
    assert api.get(f"/api/meals/{mid}/photo", headers=h).status_code == 404

    r = api.put(f"/api/meals/{mid}/photo", headers=h, files={"photo": ("p.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 204
    day = api.get("/api/meals", headers=h, params={"date": "2026-10-31"}).json()
    assert day["meals"][0]["has_photo"] is True

    r = api.get(f"/api/meals/{mid}/photo", headers=h, follow_redirects=False)
    assert r.status_code == 307
    got = httpx.get(r.headers["location"])
    assert (got.status_code, got.content) == (200, JPEG)

    # Re-upload replaces the object and removes the old one.
    first = _photo_path(api, u, mid)
    jpeg2 = JPEG + b"-second"
    assert api.put(f"/api/meals/{mid}/photo", headers=h,
                   files={"photo": ("p.jpg", jpeg2, "image/jpeg")}).status_code == 204
    second = _photo_path(api, u, mid)
    assert second != first
    assert _s(u).exists("meal-photos", first) is False
    assert _s(u).exists("meal-photos", second) is True

    # Deleting the meal deletes the file.
    assert api.delete(f"/api/meals/{mid}", headers=h).status_code == 204
    assert _s(u).exists("meal-photos", second) is False


def _photo_path(api, user, meal_id) -> str:
    from app.store import Store
    return Store(User(id=user.id, token=user.token)).meal_photo_path(meal_id)


def test_meal_photo_limits_and_ownership(api, make_user):
    owner, other = make_user(), make_user()
    mid = api.post("/api/meals", headers=auth(owner), json=MEAL).json()["id"]
    files = lambda data, ct="image/jpeg": {"photo": ("p", data, ct)}  # noqa: E731
    assert api.put(f"/api/meals/{mid}/photo", headers=auth(owner),
                   files=files(b"x" * (300 * 1024 + 1))).status_code == 413
    assert api.put(f"/api/meals/{mid}/photo", headers=auth(owner),
                   files=files(b"hi", "text/plain")).status_code == 400
    assert api.put(f"/api/meals/{mid}/photo", headers=auth(other), files=files(JPEG)).status_code == 404
    assert api.put(f"/api/meals/{mid}/photo", headers=auth(owner), files=files(JPEG)).status_code == 204
    assert api.get(f"/api/meals/{mid}/photo", headers=auth(other)).status_code == 404


def test_store_photo_path_ownership_and_delete_returning(make_user, add_meal):
    from app.store import Store
    owner, other = make_user(), make_user()
    row = add_meal(owner)
    so, sx = (Store(User(id=u.id, token=u.token)) for u in (owner, other))
    path = new_path(owner.id)
    assert so.meal_photo_path(row["id"]) is None
    assert sx.meal_photo_path(row["id"]) is False
    assert sx.set_meal_photo(row["id"], new_path(other.id)) is False
    assert so.set_meal_photo(row["id"], path) is True
    assert so.meal_photo_path(row["id"]) == path
    assert sx.delete_meal_returning(row["id"]) is None
    assert so.delete_meal_returning(row["id"])["photo_path"] == path
