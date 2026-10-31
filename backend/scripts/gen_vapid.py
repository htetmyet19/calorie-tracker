"""Print a new VAPID key pair as .env lines. Never writes files.

Usage (from backend/):  .venv/bin/python scripts/gen_vapid.py
Paste the two lines into backend/.env and into the Vercel project's environment variables.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    v = Vapid()
    v.generate_keys()
    public = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    print(f"VAPID_PUBLIC_KEY={b64url(public)}")
    print(f"VAPID_PRIVATE_KEY={b64url(private)}")


if __name__ == "__main__":
    main()
