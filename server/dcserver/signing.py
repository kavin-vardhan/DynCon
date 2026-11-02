"""Signing — two different jobs, two different keys.

1. **Manifests and pack records: RSA-2048 / RS256** (PKCS#1 v1.5 + SHA-256). The key pair is
   generated on first run into data/keys/ and the public key is handed to the game at
   /client-config, so the game can prove a manifest came from us before it mounts anything.

   The signed bytes are the *canonical JSON* of the manifest with the "signature" field
   removed: keys sorted, no whitespace, UTF-8, no trailing newline. A verifier rebuilds
   exactly those bytes from the parsed object. The signed manifest deliberately contains
   no floating-point numbers, so there is nothing to disagree about when the verifier is
   not Python - the game's own verifier is C++, and rebuilds those bytes itself.

2. **File URLs: HMAC-SHA256** over "<pack_id>/<name>|<expiry>" with a secret generated on
   first run. That is what makes /files links signed and expiring without a session. In AWS
   mode the same interface is served by a boto3 presigned URL instead.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

PRIVATE_NAME = "dc_demo_private.pem"
PUBLIC_NAME = "dc_demo_public.pem"
URL_SECRET_NAME = "url_secret.bin"
SIGNATURE_ALG = "RS256-canonical-json-v1"


def canonical_json(obj: Any) -> bytes:
    """The exact bytes that get signed."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UrlSignatureError(Exception):
    """Base for a bad or expired file link."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


class UrlExpired(UrlSignatureError):
    pass


class UrlBadSignature(UrlSignatureError):
    pass


class UrlSigner:
    def __init__(self, secret: bytes):
        self.secret = secret

    def sign(self, pack_id: str, name: str, exp: int) -> str:
        msg = f"{pack_id}/{name}|{int(exp)}".encode("utf-8")
        return base64.urlsafe_b64encode(hmac.new(self.secret, msg, hashlib.sha256).digest()).decode().rstrip("=")

    def verify(self, pack_id: str, name: str, exp: int, sig: str, now: datetime) -> None:
        expected = self.sign(pack_id, name, exp)
        if not hmac.compare_digest(expected, sig or ""):
            raise UrlBadSignature("This download link is not signed by this server.")
        if now.timestamp() > int(exp):
            raise UrlExpired("This download link has expired — ask the server to resolve the slot again.")


class KeyStore:
    """The RS256 key pair, generated on first run and then left alone."""

    def __init__(self, keys_dir: str | Path):
        self.dir = Path(keys_dir)
        self._private: rsa.RSAPrivateKey | None = None
        self._public_pem: str | None = None
        self._url_secret: bytes | None = None

    # ---- lifecycle -------------------------------------------------------------------

    def ensure(self) -> "KeyStore":
        self.dir.mkdir(parents=True, exist_ok=True)
        priv_path = self.dir / PRIVATE_NAME
        if not priv_path.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv_path.write_bytes(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            (self.dir / PUBLIC_NAME).write_bytes(key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
        secret_path = self.dir / URL_SECRET_NAME
        if not secret_path.exists():
            secret_path.write_bytes(os.urandom(32))
        self._private = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
        self._public_pem = (self.dir / PUBLIC_NAME).read_text(encoding="utf-8")
        self._url_secret = secret_path.read_bytes()
        return self

    # ---- accessors -------------------------------------------------------------------

    @property
    def private(self) -> rsa.RSAPrivateKey:
        if self._private is None:
            self.ensure()
        assert self._private is not None
        return self._private

    @property
    def public_pem(self) -> str:
        if self._public_pem is None:
            self.ensure()
        assert self._public_pem is not None
        return self._public_pem

    @property
    def url_signer(self) -> UrlSigner:
        if self._url_secret is None:
            self.ensure()
        assert self._url_secret is not None
        return UrlSigner(self._url_secret)

    def fingerprint(self) -> str:
        der = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return sha256_hex(der)[:16]

    # ---- signing ---------------------------------------------------------------------

    def sign_bytes(self, payload: bytes) -> str:
        return base64.b64encode(self.private.sign(payload, padding.PKCS1v15(), hashes.SHA256())).decode("ascii")

    def sign(self, obj: Any) -> str:
        return self.sign_bytes(canonical_json(obj))

    def verify(self, obj: Any, signature: str) -> bool:
        try:
            self.private.public_key().verify(
                base64.b64decode(signature), canonical_json(obj),
                padding.PKCS1v15(), hashes.SHA256())
            return True
        except (InvalidSignature, ValueError):
            return False


def verify_bytes_with_public_pem(public_pem: str, payload: bytes, signature: str) -> bool:
    """What the game client does with the envelope: verify the exact bytes it was given,
    with nothing but the public key, before it parses or believes any of them."""
    try:
        public = serialization.load_pem_public_key(public_pem.encode("utf-8"))
        public.verify(base64.b64decode(signature), payload,
                      padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_with_public_pem(public_pem: str, obj: Any, signature: str) -> bool:
    """The same check for the flat form: canonicalise the object, then verify."""
    return verify_bytes_with_public_pem(public_pem, canonical_json(obj), signature)
