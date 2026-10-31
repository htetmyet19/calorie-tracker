"""Supabase access-token verification."""
import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import config
from app.auth import AuthError, User, current_user, verify_token

SECRET = "test-secret-at-least-32-characters!!"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", SECRET)


def tok(secret=SECRET, alg="HS256", **overrides):
    claims = {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, secret, alg)


def test_valid_token_returns_sub():
    assert verify_token(tok(sub="u1")) == "u1"


def test_expired_token_rejected():
    with pytest.raises(AuthError):
        verify_token(tok(exp=int(time.time()) - 10))


def test_missing_exp_rejected():
    with pytest.raises(AuthError):
        verify_token(tok(exp=None))


def test_missing_sub_rejected():
    with pytest.raises(AuthError):
        verify_token(tok(sub=None))


def test_wrong_audience_rejected():
    with pytest.raises(AuthError):
        verify_token(tok(aud="anon"))


def test_wrong_signature_rejected():
    with pytest.raises(AuthError):
        verify_token(tok(secret="another-secret-at-least-32-characters!"))


def test_alg_none_rejected():
    with pytest.raises(AuthError):
        verify_token(tok(secret=None, alg="none"))


def test_hs256_rejected_when_secret_unset(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "")
    with pytest.raises(AuthError):
        verify_token(tok())


def test_garbage_token_rejected():
    with pytest.raises(AuthError):
        verify_token("not-a-jwt")


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/me")
    def me(user: User = Depends(current_user)):
        return user.model_dump()

    return TestClient(app)


def test_current_user_requires_bearer(client):
    for headers in ({}, {"Authorization": "Token x"}, {"Authorization": "Bearer "}):
        r = client.get("/me", headers=headers)
        assert r.status_code == 401
        assert r.json() == {"detail": "not_logged_in"}


def test_current_user_rejects_bad_token(client):
    r = client.get("/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json() == {"detail": "not_logged_in"}


def test_current_user_returns_user(client):
    t = tok(sub="u9")
    r = client.get("/me", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200
    assert r.json() == {"id": "u9", "token": t}
