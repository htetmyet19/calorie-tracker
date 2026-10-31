"""Supabase Storage, acting as the logged-in user.

Every call carries the user's own JWT and the publishable key, so the
Storage RLS policies (first folder segment = own uid) apply. The service key
is never used here. Errors never include response bodies or credentials.
"""
import urllib.parse
import uuid

import httpx

from . import config
from .auth import User
from .store import StoreUnavailable, _client


class StorageError(Exception):
    """Storage refused a request with a 4xx status."""

    def __init__(self, status: int):
        super().__init__(f"Storage returned {status}")
        self.status = status


class UploadRejected(StorageError):
    """Storage refused an upload (RLS, size, type or duplicate)."""


def new_path(user_id: str) -> str:
    return f"{user_id}/{uuid.uuid4().hex}.jpg"


def _base() -> str:
    return f"{config.SUPABASE_URL.rstrip('/')}/storage/v1"


def _object_path(bucket: str, path: str) -> str:
    # Keep '/' between folder segments; escape everything else.
    return f"{urllib.parse.quote(bucket, safe='')}/{urllib.parse.quote(path, safe='/')}"


class Storage:
    def __init__(self, user: User):
        self.user = user

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {
            "apikey": config.SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {self.user.token}",
            **kwargs.pop("headers", {}),
        }
        try:
            resp = _client().request(method, f"{_base()}{path}", headers=headers, **kwargs)
        except httpx.RequestError as e:
            raise StoreUnavailable(type(e).__name__) from None
        if resp.status_code >= 500:
            raise StoreUnavailable(f"Supabase returned {resp.status_code}")
        return resp

    @staticmethod
    def _absolute(url: str) -> str:
        # Supabase returns '/object/sign/...' without the '/storage/v1' prefix.
        if url.startswith(("http://", "https://")):
            return url
        if not url.startswith("/storage/v1/"):
            url = f"/storage/v1/{url.lstrip('/')}"
        return f"{config.SUPABASE_URL.rstrip('/')}{url}"

    def upload(self, bucket: str, path: str, data: bytes, content_type: str,
               upsert: bool = False) -> None:
        resp = self._request(
            "POST", f"/object/{_object_path(bucket, path)}", content=data,
            headers={"Content-Type": content_type, "x-upsert": "true" if upsert else "false"})
        if not 200 <= resp.status_code < 300:
            raise UploadRejected(resp.status_code)

    def signed_url(self, bucket: str, path: str, expires: int = 300) -> str:
        resp = self._request("POST", f"/object/sign/{_object_path(bucket, path)}",
                             json={"expiresIn": expires})
        if not 200 <= resp.status_code < 300:
            raise StorageError(resp.status_code)
        return self._absolute(resp.json()["signedURL"])

    def signed_upload_url(self, bucket: str, path: str) -> str:
        resp = self._request("POST", f"/object/upload/sign/{_object_path(bucket, path)}")
        if not 200 <= resp.status_code < 300:
            raise StorageError(resp.status_code)
        return self._absolute(resp.json()["url"])

    def exists(self, bucket: str, path: str) -> bool:
        resp = self._request("HEAD", f"/object/authenticated/{_object_path(bucket, path)}")
        return resp.status_code == 200

    def remove(self, bucket: str, paths: list[str]) -> None:
        if not paths:
            return
        resp = self._request("DELETE", f"/object/{urllib.parse.quote(bucket, safe='')}",
                             json={"prefixes": paths})
        if not 200 <= resp.status_code < 300:
            raise StorageError(resp.status_code)
