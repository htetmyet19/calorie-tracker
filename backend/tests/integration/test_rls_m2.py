import httpx
import pytest

from app import config

pytestmark = pytest.mark.integration

DAY = "2026-10-31"


def _download(user, bucket, path) -> int:
    with httpx.Client(base_url=config.SUPABASE_URL + "/storage/v1",
                      headers={"apikey": config.SUPABASE_PUBLISHABLE_KEY,
                               "Authorization": f"Bearer {user.token}"},
                      timeout=config.SUPABASE_TIMEOUT) as c:
        return c.get(f"/object/authenticated/{bucket}/{path}").status_code


def test_settings_owner_only(make_user, rest):
    a, b = make_user("client"), make_user("client")
    r = rest(a.token).post("/client_settings", json={"user_id": a.id, "height_cm": 170})
    assert r.status_code == 201
    r = rest(b.token).get("/client_settings", params={"user_id": f"eq.{a.id}"})
    assert r.status_code == 200 and r.json() == []
    r = rest(b.token).post("/client_settings", json={"user_id": a.id})
    assert r.status_code in (401, 403)


def test_weight_unique_per_day(make_user, rest):
    a = make_user("client")
    row = {"user_id": a.id, "logged_on": DAY, "weight_kg": 70}
    assert rest(a.token).post("/weight_logs", json=row).status_code == 201
    assert rest(a.token).post("/weight_logs", json=row).status_code == 409


def test_weight_range(make_user, rest):
    a = make_user("client")
    r = rest(a.token).post("/weight_logs", json={
        "user_id": a.id, "logged_on": "2026-10-30", "weight_kg": 29.99})
    assert r.status_code == 400
    r = rest(a.token).post("/weight_logs", json={
        "user_id": a.id, "logged_on": "2026-10-29", "weight_kg": 300.00})
    assert r.status_code == 201


def _seed_tracking(service, a):
    assert service.post("/client_settings", json={"user_id": a.id}).status_code == 201
    w = service.post("/weight_logs", json={"user_id": a.id, "logged_on": DAY, "weight_kg": 70})
    assert w.status_code == 201
    c = service.post("/checkins", json={"user_id": a.id, "checked_on": DAY,
                                        "weight_log_id": w.json()[0]["id"]})
    assert c.status_code == 201
    p = service.post("/progress_photos", json={
        "user_id": a.id, "checkin_id": c.json()[0]["id"], "pose": "front",
        "photo_path": f"{a.id}/p.jpg"})
    assert p.status_code == 201


TABLES = ["client_settings", "weight_logs", "checkins", "progress_photos"]


def test_trainer_reads_client_tracking(make_user, rest, link, service):
    a, t = make_user("client"), make_user("trainer")
    _seed_tracking(service, a)
    ln = link(a, t, "active")
    for tbl in TABLES:
        r = rest(t.token).get(f"/{tbl}", params={"user_id": f"eq.{a.id}"})
        assert r.status_code == 200 and len(r.json()) == 1, tbl
    r = service.patch("/coaching_links", params={"id": f"eq.{ln['id']}"},
                      json={"status": "ended"})
    assert r.status_code == 200
    for tbl in TABLES:
        r = rest(t.token).get(f"/{tbl}", params={"user_id": f"eq.{a.id}"})
        assert r.status_code == 200 and r.json() == [], tbl


def test_push_subscriptions_never_visible_to_trainer(make_user, rest, link, service):
    a, t = make_user("client"), make_user("trainer")
    r = service.post("/push_subscriptions", json={
        "user_id": a.id, "endpoint": f"https://push.example/{a.id}", "p256dh": "k", "auth": "s"})
    assert r.status_code == 201
    link(a, t, "active")
    r = rest(t.token).get("/push_subscriptions", params={"user_id": f"eq.{a.id}"})
    assert r.status_code == 200 and r.json() == []
    own = rest(a.token).get("/push_subscriptions")
    assert len(own.json()) == 1


def test_meal_update_only_photo_path(make_user, rest, add_meal):
    a = make_user("client")
    m = add_meal(a)
    r = rest(a.token).patch("/meals", params={"id": f"eq.{m['id']}"},
                            json={"photo_path": f"{a.id}/m.jpg"},
                            headers={"Prefer": "return=representation"})
    assert r.status_code == 200 and r.json()[0]["photo_path"] == f"{a.id}/m.jpg"
    r = rest(a.token).patch("/meals", params={"id": f"eq.{m['id']}"},
                            json={"total_calories": 1})
    assert r.status_code in (401, 403)


def test_deletion_failures_hidden(make_user, rest, service):
    a = make_user("client")
    service.post("/deletion_failures", json={"kind": "storage", "ref": f"x/{a.id}",
                                             "last_error": "boom"})
    r = rest(a.token).get("/deletion_failures")
    assert (r.status_code == 200 and r.json() == []) or r.status_code in (401, 403)


def test_storage_own_folder_only(make_user, link, upload_object):
    a, b, t = make_user("client"), make_user("client"), make_user("trainer")
    assert upload_object(a, "meal-photos", f"{a.id}/x.jpg") == 200
    assert upload_object(a, "meal-photos", f"{b.id}/x.jpg") in (400, 403)
    assert _download(b, "meal-photos", f"{a.id}/x.jpg") in (400, 404)
    assert _download(a, "meal-photos", f"{a.id}/x.jpg") == 200
    link(a, t, "active")
    assert _download(t, "meal-photos", f"{a.id}/x.jpg") == 200


def test_bucket_limits(make_user, upload_object):
    a = make_user("client")
    assert upload_object(a, "meal-photos", f"{a.id}/big.jpg",
                         data=b"\xff" * (400 * 1024)) in (400, 413)
    assert upload_object(a, "meal-photos", f"{a.id}/t.txt", data=b"hi",
                         content_type="text/plain") in (400, 415)


def test_meal_photo_path_must_be_in_owner_folder(make_user, rest, add_meal, service):
    a, b = make_user("client"), make_user("client")
    m = add_meal(a)
    for bad in (f"{b.id}/x.jpg", f"{a.id}/../{b.id}/x.jpg"):
        r = rest(a.token).patch("/meals", params={"id": f"eq.{m['id']}"},
                                json={"photo_path": bad})
        assert r.status_code in (400, 403), bad
    row = service.get("/meals", params={"id": f"eq.{m['id']}"}).json()[0]
    assert row["photo_path"] is None
    r = rest(a.token).patch("/meals", params={"id": f"eq.{m['id']}"},
                            json={"photo_path": f"{a.id}/x.jpg"},
                            headers={"Prefer": "return=representation"})
    assert r.status_code == 200 and r.json()[0]["photo_path"] == f"{a.id}/x.jpg"


def test_progress_photo_path_must_be_in_owner_folder(make_user, rest, service):
    a, b = make_user("client"), make_user("client")
    c = service.post("/checkins", json={"user_id": a.id, "checked_on": DAY}).json()[0]
    poses = iter(["front", "side", "back", "front"])
    for bad in (f"{b.id}/x.jpg", f"{a.id}/../{b.id}/x.jpg"):
        r = rest(a.token).post("/progress_photos", json={
            "user_id": a.id, "checkin_id": c["id"], "pose": next(poses), "photo_path": bad})
        assert r.status_code in (400, 403), bad
    r = rest(a.token).post("/progress_photos", json={
        "user_id": a.id, "checkin_id": c["id"], "pose": "back", "photo_path": f"{a.id}/ok.jpg"})
    assert r.status_code == 201


def test_owner_cannot_set_photo_removed(make_user, rest, add_meal):
    # Only the daily job (service role) sets the 90-day flag.
    u = make_user()
    m = add_meal(u)
    r = rest(u.token).patch("/meals", params={"id": f"eq.{m['id']}"}, json={"photo_removed": True})
    assert r.status_code in (401, 403)
