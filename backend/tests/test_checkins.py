"""Check-in routes with fake auth, Store and Storage; no network."""
import datetime
import logging

import pytest
from fastapi.testclient import TestClient

from app.auth import User, current_user
from app.main import app, get_storage
from app.storage import StorageError
from app.store import get_store

PROFILE = {"id": "u1", "role": "client", "display_name": "Asha"}


class FakeCheckinStore:
    user = User(id="u1", token="t")

    def __init__(self):
        self.checkins = {}   # id -> {id, user_id, checked_on, weight_kg}
        self.photos = {}     # id -> {id, checkin_id, pose, photo_path}
        self.reminders_reset = 0
        self.weights = []
        self.next_id = 1

    def get_profile(self):
        return PROFILE

    def create_checkin(self, day, kg):
        if kg is not None:
            self.weights.append((day, kg))
        row = {"id": self.next_id, "user_id": "u1", "checked_on": day.isoformat(), "weight_kg": kg}
        self.checkins[self.next_id] = row
        self.next_id += 1
        return row

    def checkin_on(self, day):
        for r in self.list_checkins(100):
            if r["checked_on"] == day.isoformat() and r["user_id"] == "u1":
                return r
        return None

    def upsert_weight(self, day, kg):
        # Like the real tables: a check-in already linked to that day's log sees the new value.
        self.weights.append((day, kg))
        for r in self.checkins.values():
            if r["checked_on"] == day.isoformat() and r["weight_kg"] is not None:
                r["weight_kg"] = kg

    def reset_reminders(self):
        self.reminders_reset += 1

    def get_checkin(self, checkin_id):
        row = self.checkins.get(checkin_id)
        return row if row and row["user_id"] == "u1" else None

    def list_checkins(self, limit):
        rows = sorted(self.checkins.values(), key=lambda r: (r["checked_on"], r["id"]), reverse=True)
        return [{**r, "photos": [p for p in self.photos.values() if p["checkin_id"] == r["id"]]}
                for r in rows[:limit]]

    def photo_for_pose(self, checkin_id, pose):
        for p in self.photos.values():
            if p["checkin_id"] == checkin_id and p["pose"] == pose:
                return dict(p)  # a copy, like a real read
        return None

    def upsert_photo(self, checkin_id, pose, path):
        found = self.photo_for_pose(checkin_id, pose)
        if found is None:
            row = {"id": 100 + len(self.photos), "checkin_id": checkin_id, "pose": pose}
            self.photos[row["id"]] = row
        else:
            row = self.photos[found["id"]]
        row["photo_path"] = path
        return dict(row)

    def delete_photo_returning(self, photo_id):
        row = self.photos.get(photo_id)
        if row is None or row.get("owner", "u1") != "u1":
            return None
        return self.photos.pop(photo_id)


class FakeStorage:
    def __init__(self):
        self.objects = set()
        self.removed = []
        self.calls = []
        self.remove_error = None
        self.sign_fail = set()

    def signed_upload_url(self, bucket, path):
        self.calls.append("signed_upload_url")
        return f"http://sb.test/up/{bucket}/{path}"

    def exists(self, bucket, path):
        self.calls.append("exists")
        return path in self.objects

    def signed_url(self, bucket, path, expires=300):
        self.calls.append("signed_url")
        if path in self.sign_fail:
            raise StorageError(404)
        assert expires == 300
        return f"http://sb.test/sign/{path}"

    def remove(self, bucket, paths):
        self.calls.append("remove")
        if self.remove_error:
            raise self.remove_error
        self.removed.append((bucket, list(paths)))


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def env():
    store, storage = FakeCheckinStore(), FakeStorage()
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app), store, storage


def _make(client, day="2026-10-31", **kw):
    return client.post("/api/checkins", json={"checked_on": day, **kw})


def test_create_without_weight(env):
    client, store, _ = env
    r = _make(client)
    assert r.status_code == 201
    assert r.json() == {"id": 1, "checked_on": "2026-10-31", "weight_kg": None, "photos": []}
    assert store.weights == []


def test_create_with_weight(env):
    client, store, _ = env
    r = _make(client, weight_kg=70.5)
    assert r.status_code == 201
    assert r.json()["weight_kg"] == 70.5
    assert len(store.weights) == 1


@pytest.mark.parametrize("kg", [29.9, 300.1])
def test_weight_out_of_range(env, kg):
    assert _make(env[0], weight_kg=kg).status_code == 422


def test_bad_date(env):
    assert _make(env[0], day="2026-13-40").status_code == 400


def test_same_day_returns_existing_checkin_with_photos(env):
    client, store, storage = env
    first = _make(client, day="2026-10-30", weight_kg=70.5)
    assert first.status_code == 201
    cid = first.json()["id"]
    storage.objects.add("u1/a.jpg")
    client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/a.jpg"})
    again = _make(client, day="2026-10-30")
    assert again.status_code == 200
    body = again.json()
    assert body["id"] == cid and body["checked_on"] == "2026-10-30" and body["weight_kg"] == 70.5
    assert [(p["pose"], p["url"]) for p in body["photos"]] == [("front", "http://sb.test/sign/u1/a.jpg")]
    assert len(store.checkins) == 1
    assert store.weights == [(datetime.date(2026, 10, 30), 70.5)]  # no weight given: none written


def test_same_day_with_weight_upserts_it(env):
    client, store, _ = env
    cid = _make(client, day="2026-10-30", weight_kg=70.5).json()["id"]
    again = _make(client, day="2026-10-30", weight_kg=71)
    assert again.status_code == 200
    assert again.json()["id"] == cid and again.json()["weight_kg"] == 71
    assert store.weights[-1] == (datetime.date(2026, 10, 30), 71)
    assert len(store.checkins) == 1


def test_checked_on_more_than_a_day_ahead_is_400(env):
    client, store, _ = env
    today = datetime.datetime.now(datetime.timezone.utc).date()
    r = _make(client, day=(today + datetime.timedelta(days=2)).isoformat())
    assert (r.status_code, r.json()["detail"]) == (400, "checked_on is in the future")
    assert store.checkins == {}
    assert _make(client, day=(today + datetime.timedelta(days=1)).isoformat()).status_code == 201


def test_create_resets_reminders(env):
    client, store, _ = env
    _make(client)
    assert store.reminders_reset == 1


def test_upload_url_for_other_users_checkin_404(env):
    client, store, storage = env
    store.checkins[5] = {"id": 5, "user_id": "u2", "checked_on": "2026-10-31", "weight_kg": None}
    r = client.post("/api/checkins/5/photos/upload-url", json={"pose": "front"})
    assert r.status_code == 404
    assert storage.calls == []
    assert client.post("/api/checkins/99/photos/upload-url", json={"pose": "front"}).status_code == 404


def test_upload_url_ok(env):
    client, _, _ = env
    cid = _make(client).json()["id"]
    r = client.post(f"/api/checkins/{cid}/photos/upload-url", json={"pose": "side"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"].startswith("u1/") and body["upload_url"].endswith(body["path"])
    assert client.post(f"/api/checkins/{cid}/photos/upload-url", json={"pose": "x"}).status_code == 422


@pytest.mark.parametrize("path", ["u2/abc.jpg", "u1x/abc.jpg", "u1/../u2/a.jpg", "abc.jpg"])
def test_record_foreign_or_traversal_path_400(env, path):
    client, _, storage = env
    cid = _make(client).json()["id"]
    r = client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": path})
    assert r.status_code == 400
    assert "exists" not in storage.calls


def test_record_missing_object_400(env):
    client, store, _ = env
    cid = _make(client).json()["id"]
    r = client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/a.jpg"})
    assert r.status_code == 400 and r.json()["detail"] == "photo_not_uploaded"
    assert store.photos == {}


def test_record_other_users_checkin_404_before_storage(env):
    client, store, storage = env
    store.checkins[5] = {"id": 5, "user_id": "u2", "checked_on": "2026-10-31", "weight_kg": None}
    r = client.post("/api/checkins/5/photos", json={"pose": "front", "path": "u1/a.jpg"})
    assert r.status_code == 404 and storage.calls == []


def test_record_ok_and_replace_removes_old(env):
    client, store, storage = env
    cid = _make(client).json()["id"]
    storage.objects |= {"u1/a.jpg", "u1/b.jpg"}
    r = client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/a.jpg"})
    assert r.status_code == 201
    first = r.json()
    assert first["pose"] == "front" and first["url"] == "http://sb.test/sign/u1/a.jpg"
    r = client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/b.jpg"})
    assert r.status_code == 201 and r.json()["id"] == first["id"]
    assert store.photos[first["id"]]["photo_path"] == "u1/b.jpg"
    assert storage.removed == [("progress-photos", ["u1/a.jpg"])]


def test_record_same_path_twice_does_not_remove(env):
    client, _, storage = env
    cid = _make(client).json()["id"]
    storage.objects.add("u1/a.jpg")
    for _ in range(2):
        assert client.post(f"/api/checkins/{cid}/photos",
                           json={"pose": "front", "path": "u1/a.jpg"}).status_code == 201
    assert storage.removed == []


def test_replace_remove_failure_is_logged_not_fatal(env, caplog):
    client, store, storage = env
    cid = _make(client).json()["id"]
    storage.objects |= {"u1/a.jpg", "u1/b.jpg"}
    client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/a.jpg"})
    storage.remove_error = StorageError(500)
    with caplog.at_level(logging.WARNING, logger="calorie_tracker"):
        r = client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/b.jpg"})
    assert r.status_code == 201
    assert any("progress_photo_delete_failed" in m and "StorageError" in m for m in caplog.messages)
    assert "u1/a.jpg" not in " ".join(caplog.messages)


def test_list_due_and_next_due(env):
    client, _, _ = env
    r = client.get("/api/checkins", params={"today": "2026-10-31"})
    assert r.json() == {"checkins": [], "next_due_on": "2026-10-31", "due": True}
    _make(client, day="2026-10-28")
    r = client.get("/api/checkins", params={"today": "2026-10-31"}).json()
    assert r["next_due_on"] == "2026-11-04" and r["due"] is False
    assert client.get("/api/checkins", params={"today": "2026-11-04"}).json()["due"] is True


def test_list_requires_valid_today(env):
    client, _, _ = env
    assert client.get("/api/checkins").status_code == 422
    assert client.get("/api/checkins", params={"today": "nope"}).status_code == 400


def test_list_newest_first_with_photos_and_skips_unsignable(env):
    client, _, storage = env
    old = _make(client, day="2026-10-10").json()["id"]
    new = _make(client, day="2026-10-20", weight_kg=70).json()["id"]
    storage.objects |= {"u1/a.jpg", "u1/b.jpg"}
    client.post(f"/api/checkins/{new}/photos", json={"pose": "front", "path": "u1/a.jpg"})
    client.post(f"/api/checkins/{new}/photos", json={"pose": "side", "path": "u1/b.jpg"})
    storage.sign_fail.add("u1/b.jpg")
    r = client.get("/api/checkins", params={"today": "2026-10-31", "limit": 5}).json()
    assert [c["id"] for c in r["checkins"]] == [new, old]
    assert [p["pose"] for p in r["checkins"][0]["photos"]] == ["front"]
    assert r["checkins"][0]["weight_kg"] == 70


def test_delete_photo(env):
    client, store, storage = env
    cid = _make(client).json()["id"]
    storage.objects.add("u1/a.jpg")
    pid = client.post(f"/api/checkins/{cid}/photos", json={"pose": "front", "path": "u1/a.jpg"}).json()["id"]
    assert client.delete(f"/api/progress-photos/{pid}").status_code == 204
    assert storage.removed == [("progress-photos", ["u1/a.jpg"])]
    assert client.delete(f"/api/progress-photos/{pid}").status_code == 404


def test_delete_photo_of_other_user_404(env):
    client, store, storage = env
    store.photos[7] = {"id": 7, "checkin_id": 1, "pose": "front", "photo_path": "u2/a.jpg", "owner": "u2"}
    assert client.delete("/api/progress-photos/7").status_code == 404
    assert storage.removed == []
