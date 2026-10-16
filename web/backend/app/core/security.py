from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

import jwt
from jwt import PyJWTError
from cryptography.fernet import Fernet, InvalidToken

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 120_000
SECRET_ENCRYPTION_PREFIX = "fernet:v1:"


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_text = base64.b64encode(salt).decode("ascii")
    hash_text = base64.b64encode(hashed).decode("ascii")
    return f"{ALGORITHM}${iterations}${salt_text}${hash_text}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, hash_text = encoded.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(hash_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def create_access_token(
    subject: str,
    *,
    secret_key: str,
    expires_in_seconds: int,
    token_version: int = 0,
) -> str:
    payload = {
        "sub": subject,
        "exp": int(time.time()) + expires_in_seconds,
        "iat": int(time.time()),
        "nonce": secrets.token_urlsafe(12),
        "token_version": token_version,
    }
    return jwt.encode(payload, _jwt_signing_key(secret_key), algorithm="HS256")


def _create_legacy_access_token(
    subject: str,
    *,
    secret_key: str,
    expires_in_seconds: int,
) -> str:
    payload = {
        "sub": subject,
        "exp": int(time.time()) + expires_in_seconds,
        "nonce": secrets.token_urlsafe(12),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_text = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret_key.encode("utf-8"),
        payload_text.encode("ascii"),
        hashlib.sha256,
    ).digest()
    signature_text = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload_text}.{signature_text}"


def decode_access_token(token: str, *, secret_key: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, _jwt_signing_key(secret_key), algorithms=["HS256"])
        if not isinstance(payload, dict):
            return None
        return payload
    except PyJWTError:
        return _decode_legacy_access_token(token, secret_key=secret_key)


def _decode_legacy_access_token(token: str, *, secret_key: str) -> dict[str, Any] | None:
    try:
        payload_text, signature_text = token.split(".", 1)
        expected_signature = hmac.new(
            secret_key.encode("utf-8"),
            payload_text.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual_signature = base64.urlsafe_b64decode(_add_padding(signature_text))
        if not hmac.compare_digest(expected_signature, actual_signature):
            return None

        payload_bytes = base64.urlsafe_b64decode(_add_padding(payload_text))
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            return None

        exp = payload.get("exp")
        if not isinstance(exp, int) or exp < int(time.time()):
            return None
        payload["_legacy"] = True
        return payload
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return None


def _add_padding(value: str) -> str:
    return value + "=" * (-len(value) % 4)


def encrypt_secret(value: str, *, secret_key: str) -> str:
    token = Fernet(_fernet_key(secret_key)).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{SECRET_ENCRYPTION_PREFIX}{token}"


def decrypt_secret(
    value: str,
    *,
    secret_key: str,
    fallback_secret_keys: tuple[str, ...] = (),
) -> str:
    decrypted, _needs_rotation = decrypt_secret_with_metadata(
        value,
        secret_key=secret_key,
        fallback_secret_keys=fallback_secret_keys,
    )
    return decrypted


def decrypt_secret_with_metadata(
    value: str,
    *,
    secret_key: str,
    fallback_secret_keys: tuple[str, ...] = (),
) -> tuple[str, bool]:
    if value.startswith(SECRET_ENCRYPTION_PREFIX):
        token = value.removeprefix(SECRET_ENCRYPTION_PREFIX).encode("ascii")
        for index, candidate_key in enumerate(_unique_secret_keys(secret_key, fallback_secret_keys)):
            try:
                return Fernet(_fernet_key(candidate_key)).decrypt(token).decode("utf-8"), index > 0
            except InvalidToken:
                continue
        raise ValueError("Invalid encrypted secret.")

    for candidate_key in _unique_secret_keys(secret_key, fallback_secret_keys):
        try:
            return _decrypt_legacy_secret(value, secret_key=candidate_key), True
        except (ValueError, UnicodeDecodeError, binascii.Error):
            continue
    raise ValueError("Invalid encrypted secret.")


def is_legacy_encrypted_secret(value: str) -> bool:
    return bool(value) and not value.startswith(SECRET_ENCRYPTION_PREFIX)


def _fernet_key(secret_key: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode("utf-8")).digest())


def _jwt_signing_key(secret_key: str) -> bytes:
    return hashlib.sha256(secret_key.encode("utf-8")).digest()


def _unique_secret_keys(secret_key: str, fallback_secret_keys: tuple[str, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    for key in (secret_key, *fallback_secret_keys):
        if key and key not in keys:
            keys.append(key)
    return tuple(keys)


def _encrypt_legacy_secret(value: str, *, secret_key: str) -> str:
    salt = secrets.token_bytes(16)
    value_bytes = value.encode("utf-8")
    key_stream = _derive_key_stream(secret_key, salt, len(value_bytes))
    encrypted = bytes(byte ^ key_stream[index] for index, byte in enumerate(value_bytes))
    return ".".join(
        [
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(encrypted).decode("ascii").rstrip("="),
        ]
    )


def _decrypt_legacy_secret(value: str, *, secret_key: str) -> str:
    salt_text, encrypted_text = value.split(".", 1)
    salt = base64.urlsafe_b64decode(_add_padding(salt_text))
    encrypted = base64.urlsafe_b64decode(_add_padding(encrypted_text))
    key_stream = _derive_key_stream(secret_key, salt, len(encrypted))
    decrypted = bytes(byte ^ key_stream[index] for index, byte in enumerate(encrypted))
    return decrypted.decode("utf-8")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 8}{value[-4:]}"


def _derive_key_stream(secret_key: str, salt: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        counter_bytes = counter.to_bytes(4, "big")
        chunks.append(
            hmac.new(
                secret_key.encode("utf-8"),
                salt + counter_bytes,
                hashlib.sha256,
            ).digest()
        )
        counter += 1
    return b"".join(chunks)[:length]
