"""
AES-GCM encryption helpers using the Web Crypto API.

Used to encrypt the user's GitHub access token before storing it in AUTH_KV.
The encryption key is held in Worker Secret SESSION_ENCRYPTION_KEY (base64,
32 bytes once decoded).

Ciphertext format (base64-encoded):
    iv (12 bytes) || ciphertext || auth_tag (16 bytes)
"""

from base64 import b64decode, b64encode

import js
from pyodide.ffi import to_js


_AES_GCM_KEY = None  # Cached imported CryptoKey


def _b64_to_bytes(s: str) -> bytes:
    return b64decode(s)


def _bytes_to_b64(data: bytes) -> str:
    return b64encode(data).decode("ascii")


async def _get_key(env) -> object:
    """Import the SESSION_ENCRYPTION_KEY secret as an AES-GCM CryptoKey."""
    global _AES_GCM_KEY
    if _AES_GCM_KEY is not None:
        return _AES_GCM_KEY

    secret_b64 = getattr(env, "SESSION_ENCRYPTION_KEY", None)
    if not secret_b64:
        raise RuntimeError("SESSION_ENCRYPTION_KEY not configured")

    raw = _b64_to_bytes(secret_b64)
    if len(raw) != 32:
        raise RuntimeError(
            f"SESSION_ENCRYPTION_KEY must decode to 32 bytes, got {len(raw)}"
        )

    crypto = js.crypto.subtle
    key = await crypto.importKey(
        "raw",
        to_js(raw),
        to_js({"name": "AES-GCM", "length": 256}),
        False,  # not extractable
        to_js(["encrypt", "decrypt"]),
    )
    _AES_GCM_KEY = key
    return key


async def encrypt(env, plaintext: str) -> str:
    """Encrypt a string with AES-GCM. Returns base64(iv || ciphertext || tag)."""
    key = await _get_key(env)
    iv_bytes = bytes(js.crypto.getRandomValues(js.Uint8Array.new(12)).to_py())

    pt_bytes = plaintext.encode("utf-8")
    ct_buffer = await js.crypto.subtle.encrypt(
        to_js({"name": "AES-GCM", "iv": to_js(iv_bytes)}),
        key,
        to_js(pt_bytes),
    )
    ct_bytes = bytes(js.Uint8Array.new(ct_buffer).to_py())

    return _bytes_to_b64(iv_bytes + ct_bytes)


async def decrypt(env, ciphertext_b64: str) -> str:
    """Decrypt a base64(iv || ciphertext || tag) blob produced by encrypt()."""
    key = await _get_key(env)
    blob = _b64_to_bytes(ciphertext_b64)
    if len(blob) < 12 + 16:
        raise ValueError("Ciphertext too short")
    iv_bytes = blob[:12]
    ct_bytes = blob[12:]

    pt_buffer = await js.crypto.subtle.decrypt(
        to_js({"name": "AES-GCM", "iv": to_js(iv_bytes)}),
        key,
        to_js(ct_bytes),
    )
    pt_bytes = bytes(js.Uint8Array.new(pt_buffer).to_py())
    return pt_bytes.decode("utf-8")
