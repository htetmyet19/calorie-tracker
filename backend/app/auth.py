"""Verify Supabase access tokens (JWTs) and expose the logged-in user to routes."""
import json

import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel

from . import config

_ASYMMETRIC_ALGS = ("ES256", "RS256")

# Created on first use so importing this module works with an empty SUPABASE_URL.
_jwks_client: jwt.PyJWKClient | None = None
_jwks_url: str | None = None


class AuthError(Exception):
    """The token is missing, malformed, expired or not trusted."""


class AuthUnavailable(Exception):
    """The signing keys could not be fetched; not the user's fault, so not a 401."""


class User(BaseModel):
    id: str
    token: str


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client, _jwks_url
    if not config.SUPABASE_URL:
        raise AuthError("SUPABASE_URL is not configured")
    url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if _jwks_client is None or _jwks_url != url:
        _jwks_client, _jwks_url = jwt.PyJWKClient(url), url  # caches fetched keys
    return _jwks_client


def verify_token(token: str) -> str:
    """Return the token's `sub` (user id), or raise AuthError / AuthUnavailable."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256" and config.SUPABASE_JWT_SECRET:
            key = config.SUPABASE_JWT_SECRET
        elif alg in _ASYMMETRIC_ALGS:
            try:
                signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            except (jwt.PyJWKClientConnectionError, TimeoutError, json.JSONDecodeError) as e:
                raise AuthUnavailable(str(e)) from e
            # The header alg must match the key type, or decode would fail with a TypeError.
            if signing_key.algorithm_name != alg:
                raise AuthError("token algorithm does not match signing key")
            key = signing_key.key
        else:
            raise AuthError(f"unsupported algorithm: {alg}")
        # `algorithms` is pinned to the header alg we vetted above, never "none".
        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except (jwt.PyJWTError, ValueError, TypeError) as e:
        raise AuthError(str(e)) from e
    sub = claims["sub"]
    if not isinstance(sub, str) or not sub:
        raise AuthError("invalid sub")
    return sub


def current_user(authorization: str | None = Header(None)) -> User:
    """FastAPI dependency: `Authorization: Bearer <token>` -> User, else 401."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "not_logged_in")
    try:
        return User(id=verify_token(token), token=token)
    except AuthUnavailable:
        raise HTTPException(503, "Login service unreachable. Try again in a minute.")
    except AuthError:
        raise HTTPException(401, "not_logged_in")
