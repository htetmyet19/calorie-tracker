"""Fixtures for integration tests against the local Supabase stack.

Users are created through the real auth API and act through PostgREST with
their own JWT, so Row Level Security is exercised exactly as in production.
"""
import uuid
from dataclasses import dataclass

import httpx
import pytest

from app import config

PASSWORD = "Test-password-123!"


@dataclass
class TestUser:
    __test__ = False  # not a pytest test class
    id: str
    token: str


def _require_config():
    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY
            and config.SUPABASE_SERVICE_ROLE_KEY):
        pytest.fail("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY / "
                    "SUPABASE_SERVICE_ROLE_KEY are not configured (backend/.env)")


def _client(headers: dict, base: str = "") -> httpx.Client:
    return httpx.Client(base_url=config.SUPABASE_URL + base, headers=headers,
                        timeout=config.SUPABASE_TIMEOUT)


@pytest.fixture(scope="session")
def service():
    """PostgREST client using the service key (bypasses RLS). Setup only."""
    _require_config()
    key = config.SUPABASE_SERVICE_ROLE_KEY
    with _client({"apikey": key, "Authorization": f"Bearer {key}",
                  "Prefer": "return=representation"}, "/rest/v1") as c:
        yield c


@pytest.fixture
def make_user(service):
    def _make(role: str | None = "client") -> TestUser:
        key = config.SUPABASE_SERVICE_ROLE_KEY
        email = f"it-{uuid.uuid4().hex}@example.com"
        try:
            with _client({"apikey": key, "Authorization": f"Bearer {key}"}, "/auth/v1") as a:
                r = a.post("/admin/users", json={"email": email, "password": PASSWORD,
                                                 "email_confirm": True})
                assert r.status_code in (200, 201), f"create user failed: {r.status_code}"
                uid = r.json()["id"]
            with _client({"apikey": config.SUPABASE_PUBLISHABLE_KEY}, "/auth/v1") as a:
                r = a.post("/token", params={"grant_type": "password"},
                           json={"email": email, "password": PASSWORD})
                assert r.status_code == 200, f"sign in failed: {r.status_code}"
                token = r.json()["access_token"]
        except httpx.TransportError as e:
            pytest.fail(f"Supabase stack unreachable at {config.SUPABASE_URL}: {e!r}")
        if role is not None:
            r = service.post("/profiles", json={"id": uid, "role": role})
            assert r.status_code == 201, f"profile insert failed: {r.status_code} {r.text}"
        return TestUser(id=uid, token=token)
    return _make


@pytest.fixture
def rest():
    clients = []

    def _rest(token: str) -> httpx.Client:
        c = _client({"apikey": config.SUPABASE_PUBLISHABLE_KEY,
                     "Authorization": f"Bearer {token}"}, "/rest/v1")
        clients.append(c)
        return c
    yield _rest
    for c in clients:
        c.close()


@pytest.fixture
def link(service):
    def _link(client: TestUser, trainer: TestUser, status: str) -> dict:
        r = service.post("/coaching_links", json={
            "client_id": client.id, "trainer_id": trainer.id, "status": status})
        assert r.status_code == 201, f"link insert failed: {r.status_code} {r.text}"
        return r.json()[0]
    return _link


@pytest.fixture
def add_meal(service):
    def _add(user: TestUser, calories: float = 500) -> dict:
        r = service.post("/meals", json={
            "user_id": user.id, "eaten_at": "2026-10-31T12:00:00",
            "meal_type": "lunch", "items": [{"name": "rice"}],
            "total_calories": calories})
        assert r.status_code == 201, f"meal insert failed: {r.status_code} {r.text}"
        return r.json()[0]
    return _add


@pytest.fixture(scope="session")
def storage():
    """Storage API client using the service key (bypasses RLS). Setup only."""
    _require_config()
    key = config.SUPABASE_SERVICE_ROLE_KEY
    with _client({"apikey": key, "Authorization": f"Bearer {key}"}, "/storage/v1") as c:
        yield c


@pytest.fixture
def upload_object():
    def _upload(user: TestUser, bucket: str, path: str, data: bytes = b"\xff\xd8\xff",
                content_type: str = "image/jpeg") -> int:
        with _client({"apikey": config.SUPABASE_PUBLISHABLE_KEY,
                      "Authorization": f"Bearer {user.token}"}, "/storage/v1") as c:
            r = c.post(f"/object/{bucket}/{path}", content=data,
                       headers={"Content-Type": content_type})
        return r.status_code
    return _upload
