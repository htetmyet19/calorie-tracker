"""Check-ins and progress photos against the local stack, real tokens."""
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0 checkin " + uuid.uuid4().bytes
DAY = "2026-10-31"


def auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.fixture
def api():
    with TestClient(app) as c:
        yield c


def _upload(api, user, cid, pose, data=JPEG):
    r = api.post(f"/api/checkins/{cid}/photos/upload-url", headers=auth(user), json={"pose": pose})
    assert r.status_code == 200, r.text
    put = httpx.put(r.json()["upload_url"], content=data, headers={"content-type": "image/jpeg"})
    assert put.status_code in (200, 201)
    return r.json()["path"]


def test_checkin_full_flow(api, make_user, service):
    a, b = make_user(), make_user()
    h = auth(a)
    assert api.put("/api/settings", headers=h, json={"goal_kcal": 2000}).status_code == 200

    assert service.patch("/client_settings", params={"user_id": f"eq.{a.id}"},
                         json={"reminders_sent": 2}).status_code == 200
    r = api.post("/api/checkins", headers=h, json={"checked_on": DAY, "weight_kg": 70.5})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["weight_kg"] == 70.5 and r.json()["photos"] == []
    assert api.get("/api/settings", headers=h).json()["goal_kcal"] == 2000
    row = service.get("/client_settings", params={"user_id": f"eq.{a.id}"}).json()[0]
    assert row["reminders_sent"] == 0 and row["goal_kcal"] == 2000

    path = _upload(api, a, cid, "front")
    rec = api.post(f"/api/checkins/{cid}/photos", headers=h, json={"pose": "front", "path": path})
    assert rec.status_code == 201, rec.text
    pid = rec.json()["id"]

    lst = api.get("/api/checkins", headers=h, params={"today": DAY}).json()
    assert lst["due"] is False and lst["next_due_on"] == "2026-11-07"
    c = lst["checkins"][0]
    assert c["id"] == cid and c["weight_kg"] == 70.5
    assert [p["pose"] for p in c["photos"]] == ["front"]  # side/back skipped
    got = httpx.get(c["photos"][0]["url"])
    assert (got.status_code, got.content) == (200, JPEG)

    # retry of the same pose replaces the row and deletes the old object
    path2 = _upload(api, a, cid, "front", JPEG + b"-2")
    rec2 = api.post(f"/api/checkins/{cid}/photos", headers=h, json={"pose": "front", "path": path2})
    assert rec2.status_code == 201 and rec2.json()["id"] == pid
    from app.auth import User
    from app.storage import Storage
    s = Storage(User(id=a.id, token=a.token))
    assert s.exists("progress-photos", path) is False
    assert s.exists("progress-photos", path2) is True

    # B sees none of it
    assert api.get("/api/checkins", headers=auth(b), params={"today": DAY}).json() == {
        "checkins": [], "next_due_on": DAY, "due": True}
    assert api.post(f"/api/checkins/{cid}/photos/upload-url", headers=auth(b),
                    json={"pose": "side"}).status_code == 404
    assert api.delete(f"/api/progress-photos/{pid}", headers=auth(b)).status_code == 404

    assert api.delete(f"/api/progress-photos/{pid}", headers=h).status_code == 204
    assert s.exists("progress-photos", path2) is False


def test_record_rejects_missing_and_foreign_paths(api, make_user):
    a, b = make_user(), make_user()
    cid = api.post("/api/checkins", headers=auth(a), json={"checked_on": DAY}).json()["id"]
    r = api.post(f"/api/checkins/{cid}/photos", headers=auth(a),
                 json={"pose": "front", "path": f"{a.id}/{uuid.uuid4().hex}.jpg"})
    assert (r.status_code, r.json()["detail"]) == (400, "photo_not_uploaded")
    r = api.post(f"/api/checkins/{cid}/photos", headers=auth(a),
                 json={"pose": "front", "path": f"{b.id}/x.jpg"})
    assert r.status_code == 400


def test_rls_photo_must_point_at_own_checkin(make_user, rest, service):
    a, b = make_user(), make_user()
    cb = rest(b.token).post("/checkins", json={"user_id": b.id, "checked_on": DAY},
                            headers={"Prefer": "return=representation"})
    assert cb.status_code == 201
    r = rest(a.token).post("/progress_photos", json={
        "user_id": a.id, "checkin_id": cb.json()[0]["id"], "pose": "front",
        "photo_path": f"{a.id}/p.jpg"})
    assert r.status_code in (401, 403)
    # and A cannot link B's weight log to A's check-in
    wb = service.post("/weight_logs", json={"user_id": b.id, "logged_on": DAY, "weight_kg": 70})
    r = rest(a.token).post("/checkins", json={
        "user_id": a.id, "checked_on": DAY, "weight_log_id": wb.json()[0]["id"]})
    assert r.status_code in (401, 403)
    # moving own photo onto B's check-in via update is also refused
    ca = rest(a.token).post("/checkins", json={"user_id": a.id, "checked_on": DAY},
                            headers={"Prefer": "return=representation"}).json()[0]
    pa = rest(a.token).post("/progress_photos", json={
        "user_id": a.id, "checkin_id": ca["id"], "pose": "front", "photo_path": f"{a.id}/q.jpg"},
        headers={"Prefer": "return=representation"}).json()[0]
    r = rest(a.token).patch("/progress_photos", params={"id": f"eq.{pa['id']}"},
                            json={"checkin_id": cb.json()[0]["id"]})
    assert r.status_code in (401, 403)


def test_checkin_does_not_create_settings_row(api, make_user, service):
    from app.auth import User
    from app.store import Store
    a = make_user()
    assert api.post("/api/checkins", headers=auth(a), json={"checked_on": DAY}).status_code == 201
    assert Store(User(id=a.id, token=a.token)).get_settings() is None
    assert service.get("/client_settings", params={"user_id": f"eq.{a.id}"}).json() == []
    # the one-time browser-settings move still works afterwards
    assert api.put("/api/settings", headers=auth(a), params={"only_if_empty": "1"},
                   json={"goal_kcal": 1800}).status_code == 200
