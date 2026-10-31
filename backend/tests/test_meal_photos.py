"""Meal photo routes with fake Store and Storage; no network."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.auth import User, current_user
from app.main import app, get_storage
from app.store import StoreUnavailable, get_store
from app.storage import StorageError, UploadRejected

PROFILE = {"id": "u1", "role": "client", "display_name": "Asha"}
LIMIT = 300 * 1024


class FakePhotoStore:
    user = User(id="u1", token="t")

    def __init__(self, photo_path=None, found=True, set_ok=True):
        self.photo_path, self.found, self.set_ok = photo_path, found, set_ok
        self.set_calls = []
        self.deleted_row = None

    def get_profile(self):
        return PROFILE

    def meal_photo_path(self, meal_id):
        return self.photo_path if self.found else False

    def set_meal_photo(self, meal_id, path):
        self.set_calls.append((meal_id, path))
        return self.set_ok

    def delete_meal_returning(self, meal_id):
        return self.deleted_row


class FakeStorage:
    def __init__(self, remove_error=None, upload_error=None):
        self.uploads, self.removed, self.signed = [], [], []
        self.remove_error, self.upload_error = remove_error, upload_error

    def upload(self, bucket, path, data, content_type, upsert=False):
        if self.upload_error:
            raise self.upload_error
        self.uploads.append((bucket, path, data, content_type))

    def remove(self, bucket, paths):
        if self.remove_error:
            raise self.remove_error
        self.removed.append((bucket, list(paths)))

    def signed_url(self, bucket, path, expires=300):
        self.signed.append((bucket, path, expires))
        return "http://sb.test/storage/v1/object/sign/x?token=T"


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def make(store, storage):
    app.dependency_overrides[current_user] = lambda: store.user
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


def put(c, data=b"\xff\xd8\xff", ctype="image/jpeg", mid=1):
    return c.put(f"/api/meals/{mid}/photo", files={"photo": ("p.jpg", data, ctype)})


def test_photo_upload_sets_path():
    st, sg = FakePhotoStore(), FakeStorage()
    r = put(make(st, sg), b"JPEGDATA")
    assert r.status_code == 204
    bucket, path, data, ctype = sg.uploads[0]
    assert (bucket, data, ctype) == ("meal-photos", b"JPEGDATA", "image/jpeg")
    assert path.startswith("u1/") and path.endswith(".jpg")
    assert st.set_calls == [(1, path)]
    assert sg.removed == []


def test_photo_exactly_at_limit_ok():
    assert put(make(FakePhotoStore(), FakeStorage()), b"x" * LIMIT).status_code == 204


def test_photo_too_large_413():
    st, sg = FakePhotoStore(), FakeStorage()
    r = put(make(st, sg), b"x" * (LIMIT + 1))
    assert (r.status_code, r.json()) == (413, {"detail": "Photo is larger than 300 KB."})
    assert sg.uploads == [] and st.set_calls == []


@pytest.mark.parametrize("ctype", ["text/plain", "image/gif", "application/pdf"])
def test_photo_not_image_400(ctype):
    st, sg = FakePhotoStore(), FakeStorage()
    assert put(make(st, sg), ctype=ctype).status_code == 400
    assert sg.uploads == []


@pytest.mark.parametrize("ctype", ["image/png", "image/webp"])
def test_photo_png_webp_accepted(ctype):
    assert put(make(FakePhotoStore(), FakeStorage()), ctype=ctype).status_code == 204


def test_photo_other_users_meal_404():
    st, sg = FakePhotoStore(found=False), FakeStorage()
    assert put(make(st, sg)).status_code == 404
    assert sg.uploads == []


def test_photo_upload_rejected_by_storage_is_400_and_path_unchanged():
    st, sg = FakePhotoStore(), FakeStorage(upload_error=UploadRejected(400))
    assert put(make(st, sg)).status_code == 400
    assert st.set_calls == []


def test_photo_meal_vanished_removes_new_object():
    st, sg = FakePhotoStore(set_ok=False), FakeStorage()
    assert put(make(st, sg)).status_code == 404
    assert sg.removed == [("meal-photos", [sg.uploads[0][1]])]


def test_reupload_removes_old_object():
    st, sg = FakePhotoStore(photo_path="u1/old.jpg"), FakeStorage()
    assert put(make(st, sg)).status_code == 204
    assert sg.removed == [("meal-photos", ["u1/old.jpg"])]
    assert st.set_calls[0][1] != "u1/old.jpg"


def test_reupload_old_removal_failure_still_204(caplog):
    st, sg = FakePhotoStore(photo_path="u1/old.jpg"), FakeStorage(remove_error=StoreUnavailable("x"))
    with caplog.at_level(logging.WARNING):
        assert put(make(st, sg)).status_code == 204
    assert "meal_photo_delete_failed meal_id=1 error=StoreUnavailable" in caplog.text


def test_photo_get_redirects_307():
    st, sg = FakePhotoStore(photo_path="u1/a.jpg"), FakeStorage()
    r = make(st, sg).get("/api/meals/1/photo", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "http://sb.test/storage/v1/object/sign/x?token=T"
    assert sg.signed == [("meal-photos", "u1/a.jpg", 300)]


def test_photo_get_none_404():
    assert make(FakePhotoStore(photo_path=None), FakeStorage()).get("/api/meals/1/photo").status_code == 404


def test_photo_get_not_found_404():
    assert make(FakePhotoStore(found=False), FakeStorage()).get("/api/meals/1/photo").status_code == 404


def test_photo_get_missing_object_404():
    class Missing(FakeStorage):
        def signed_url(self, *a, **k):
            raise StorageError(400)
    assert make(FakePhotoStore(photo_path="u1/a.jpg"), Missing()).get("/api/meals/1/photo").status_code == 404


def test_photo_get_storage_down_is_503():
    class Down(FakeStorage):
        def signed_url(self, *a, **k):
            raise StoreUnavailable("x")
    assert make(FakePhotoStore(photo_path="u1/a.jpg"), Down()).get("/api/meals/1/photo").status_code == 503


def test_delete_meal_removes_photo():
    st, sg = FakePhotoStore(), FakeStorage()
    st.deleted_row = {"id": 1, "photo_path": "u1/a.jpg"}
    assert make(st, sg).delete("/api/meals/1").status_code == 204
    assert sg.removed == [("meal-photos", ["u1/a.jpg"])]


def test_delete_meal_without_photo_skips_storage():
    st, sg = FakePhotoStore(), FakeStorage()
    st.deleted_row = {"id": 1, "photo_path": None}
    assert make(st, sg).delete("/api/meals/1").status_code == 204
    assert sg.removed == []


def test_delete_missing_meal_404():
    assert make(FakePhotoStore(), FakeStorage()).delete("/api/meals/1").status_code == 404


@pytest.mark.parametrize("err", [StoreUnavailable("x"), StorageError(400), RuntimeError("boom secret")])
def test_delete_meal_survives_storage_error(err, caplog):
    st, sg = FakePhotoStore(), FakeStorage(remove_error=err)
    st.deleted_row = {"id": 7, "photo_path": "u1/a.jpg"}
    with caplog.at_level(logging.WARNING):
        assert make(st, sg).delete("/api/meals/7").status_code == 204
    assert f"meal_photo_delete_failed meal_id=7 error={type(err).__name__}" in caplog.text
    assert "secret" not in caplog.text and "u1/a.jpg" not in caplog.text
