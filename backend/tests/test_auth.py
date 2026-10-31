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


# --- ES256 / RS256 via a stubbed JWKS (no network) ---

import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from app import auth  # noqa: E402
from app.auth import AuthUnavailable  # noqa: E402

_EC_KEY = ec.generate_private_key(ec.SECP256R1())
_EC_PEM = _EC_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_EC_PUBLIC_PEM = _EC_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


class _StubJWKS:
    def __init__(self, error=None):
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(_EC_KEY.public_key()))
        self.signing_key = jwt.PyJWK(jwk, algorithm="ES256")
        self.error = error

    def get_signing_key_from_jwt(self, token):
        if self.error:
            raise self.error
        return self.signing_key


@pytest.fixture
def jwks(monkeypatch):
    stub = _StubJWKS()
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: stub)
    return stub


def es_tok(**overrides):
    return tok(secret=_EC_PEM, alg="ES256", **overrides)


def test_es256_valid_token_returns_sub(jwks):
    assert verify_token(es_tok(sub="u2")) == "u2"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _raw_token(header: dict, key: bytes = b"", digest=hashlib.sha256) -> str:
    # PyJWT refuses to sign these attack tokens, so build them by hand.
    claims = {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600}
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    sig = hmac.new(key, signing_input.encode(), digest).digest()
    return f"{signing_input}.{_b64(sig)}"


def test_header_alg_mismatching_jwks_key_rejected(jwks):
    # Header claims RS256 but the JWKS key is EC: must be AuthError, not a 500.
    with pytest.raises(AuthError):
        verify_token(_raw_token({"alg": "RS256", "typ": "JWT", "kid": "k1"}))


def test_hs256_signed_with_public_key_rejected(monkeypatch, jwks):
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "")
    forged = _raw_token({"alg": "HS256", "typ": "JWT"}, key=_EC_PUBLIC_PEM)
    with pytest.raises(AuthError):
        verify_token(forged)


def test_jwks_unreachable_raises_unavailable(monkeypatch):
    stub = _StubJWKS(error=jwt.PyJWKClientConnectionError("down"))
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: stub)
    with pytest.raises(AuthUnavailable):
        verify_token(es_tok())


@pytest.mark.parametrize(
    "error",
    [jwt.PyJWKClientConnectionError("down"), json.JSONDecodeError("bad", "<html>", 0)],
)
def test_current_user_503_when_jwks_unavailable(monkeypatch, client, error):
    stub = _StubJWKS(error=error)
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: stub)
    r = client.get("/me", headers={"Authorization": f"Bearer {es_tok()}"})
    assert r.status_code == 503
    assert r.json() == {"detail": "Login service unreachable. Try again in a minute."}


def test_es256_rejected_when_supabase_url_unset(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    with pytest.raises(AuthError):
        verify_token(es_tok())
