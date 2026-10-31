"""Storage wrapper against a mocked transport; no network."""
import httpx
import pytest

from app import config, store
from app.auth import User
from app.storage import Storage, StorageError, UploadRejected, new_path

USER = User(id="u1", token="user-jwt")


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "http://sb.test")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "pub-key")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "svc-key")


def use(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)
    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(wrapped)))
    return seen


def test_upload_url_headers_and_body(monkeypatch):
    seen = use(monkeypatch, lambda r: httpx.Response(200, json={"Key": "k"}))
    Storage(USER).upload("meal-photos", "u1/a b.jpg", b"DATA", "image/jpeg")
    r = seen[0]
    assert (r.method, str(r.url)) == ("POST", "http://sb.test/storage/v1/object/meal-photos/u1/a%20b.jpg")
    assert r.headers["authorization"] == "Bearer user-jwt"
    assert r.headers["apikey"] == "pub-key"
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-upsert"] == "false"
    assert r.content == b"DATA"
    assert "svc-key" not in str(r.headers)


def test_upload_upsert_header(monkeypatch):
    seen = use(monkeypatch, lambda r: httpx.Response(200, json={}))
    Storage(USER).upload("b", "u1/x.jpg", b"1", "image/png", upsert=True)
    assert seen[0].headers["x-upsert"] == "true"


def test_upload_4xx_is_rejected(monkeypatch):
    use(monkeypatch, lambda r: httpx.Response(400, json={"statusCode": "403", "message": "secret"}))
    with pytest.raises(UploadRejected) as e:
        Storage(USER).upload("b", "u1/x.jpg", b"1", "image/jpeg")
    assert e.value.status == 400
    assert "secret" not in str(e.value)


@pytest.mark.parametrize("call", [
    lambda s: s.upload("b", "u1/x.jpg", b"1", "image/jpeg"),
    lambda s: s.signed_url("b", "u1/x.jpg"),
    lambda s: s.signed_upload_url("b", "u1/x.jpg"),
    lambda s: s.exists("b", "u1/x.jpg"),
    lambda s: s.remove("b", ["u1/x.jpg"]),
])
def test_5xx_is_store_unavailable(monkeypatch, call):
    use(monkeypatch, lambda r: httpx.Response(503))
    with pytest.raises(store.StoreUnavailable):
        call(Storage(USER))


def test_network_error_is_store_unavailable_without_url(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("http://sb.test/leak")
    use(monkeypatch, boom)
    with pytest.raises(store.StoreUnavailable) as e:
        Storage(USER).exists("b", "u1/x.jpg")
    assert str(e.value) == "ConnectError"


def test_signed_url_made_absolute(monkeypatch):
    seen = use(monkeypatch, lambda r: httpx.Response(200, json={"signedURL": "/object/sign/b/u1/x.jpg?token=T"}))
    url = Storage(USER).signed_url("b", "u1/x.jpg", expires=300)
    assert url == "http://sb.test/storage/v1/object/sign/b/u1/x.jpg?token=T"
    assert str(seen[0].url) == "http://sb.test/storage/v1/object/sign/b/u1/x.jpg"
    assert seen[0].method == "POST"
    assert seen[0].read() == b'{"expiresIn":300}'
    assert seen[0].headers["authorization"] == "Bearer user-jwt"


def test_signed_url_already_absolute_is_kept(monkeypatch):
    use(monkeypatch, lambda r: httpx.Response(200, json={"signedURL": "https://cdn.test/x?token=T"}))
    assert Storage(USER).signed_url("b", "u1/x.jpg") == "https://cdn.test/x?token=T"


def test_signed_url_4xx_raises_storage_error(monkeypatch):
    use(monkeypatch, lambda r: httpx.Response(400, json={}))
    with pytest.raises(StorageError):
        Storage(USER).signed_url("b", "u1/x.jpg")


def test_signed_upload_url(monkeypatch):
    seen = use(monkeypatch, lambda r: httpx.Response(200, json={"url": "/object/upload/sign/b/u1/x.jpg?token=T"}))
    assert Storage(USER).signed_upload_url("b", "u1/x.jpg") == \
        "http://sb.test/storage/v1/object/upload/sign/b/u1/x.jpg?token=T"
    assert (seen[0].method, seen[0].url.path) == ("POST", "/storage/v1/object/upload/sign/b/u1/x.jpg")


def test_exists_uses_head_and_maps_status(monkeypatch):
    codes = iter([200, 400, 404])
    seen = use(monkeypatch, lambda r: httpx.Response(next(codes)))
    s = Storage(USER)
    assert s.exists("b", "u1/x.jpg") is True
    assert s.exists("b", "u1/y.jpg") is False
    assert s.exists("b", "u1/z.jpg") is False
    assert (seen[0].method, seen[0].url.path) == ("HEAD", "/storage/v1/object/authenticated/b/u1/x.jpg")


def test_remove_sends_prefixes(monkeypatch):
    seen = use(monkeypatch, lambda r: httpx.Response(200, json=[]))
    Storage(USER).remove("b", ["u1/a.jpg", "u1/b.jpg"])
    r = seen[0]
    assert (r.method, str(r.url)) == ("DELETE", "http://sb.test/storage/v1/object/b")
    assert r.read() == b'{"prefixes":["u1/a.jpg","u1/b.jpg"]}'


def test_remove_empty_makes_no_request(monkeypatch):
    seen = use(monkeypatch, lambda r: httpx.Response(200))
    Storage(USER).remove("b", [])
    assert seen == []


def test_new_path_is_in_users_folder():
    p = new_path("abc")
    assert p.startswith("abc/") and p.endswith(".jpg") and ".." not in p
    assert new_path("abc") != p
