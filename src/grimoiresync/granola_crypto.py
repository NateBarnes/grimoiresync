"""Decrypt Granola's on-disk state (cache-v6.json.enc, supabase.json.enc).

Granola (v1+) encrypts its local state with a per-install DEK:

  Keychain "Granola Safe Storage" / "Granola Key"
     -> PBKDF2-HMAC-SHA1(salt=b"saltysalt", iter=1003, dkLen=16)
     -> AES-128-CBC(IV=16 * 0x20) over `storage.dek` (after stripping "v10" prefix)
     -> base64-decoded -> 32-byte DEK
     -> AES-256-GCM(DEK) decrypts cache-v6.json.enc and supabase.json.enc.
        File layout: IV(12) || ciphertext || tag(16)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import subprocess
import threading
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

log = logging.getLogger(__name__)

GRANOLA_DIR = Path.home() / "Library/Application Support/Granola"
DEK_FILE = GRANOLA_DIR / "storage.dek"
CACHE_ENC = GRANOLA_DIR / "cache-v6.json.enc"
SUPABASE_ENC = GRANOLA_DIR / "supabase.json.enc"

_KC_SERVICE = "Granola Safe Storage"
_KC_ACCOUNT = "Granola Key"

_PBKDF2_SALT = b"saltysalt"
_PBKDF2_ITER = 1003
_AES128_IV = b" " * 16
_SAFESTORAGE_PREFIX = b"v10"

_GCM_IV_LEN = 12
_GCM_TAG_LEN = 16

_dek_lock = threading.Lock()
_cached_dek: bytes | None = None


class GranolaCryptoError(RuntimeError):
    """Raised when any step of the Granola decryption chain fails."""


def _fetch_keychain_secret() -> bytes:
    try:
        # No timeout: the first call after install pops a Keychain dialog the
        # user must answer ("Always Allow" whitelists `security` for this item
        # so future calls succeed silently — required for the background daemon).
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", _KC_SERVICE, "-a", _KC_ACCOUNT, "-w"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise GranolaCryptoError(
            f"Could not read Granola Safe Storage from Keychain. "
            f"`security` exited {e.returncode}: {e.stderr.decode(errors='replace').strip()}"
        ) from e
    except FileNotFoundError as e:
        raise GranolaCryptoError("`security` binary not found (non-macOS host?)") from e
    return result.stdout.rstrip(b"\n")


def _pkcs7_unpad(data: bytes) -> bytes:
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise GranolaCryptoError(f"bad PKCS7 padding (last byte={pad})")
    return data[:-pad]


def _safestorage_decrypt(blob: bytes, key: bytes) -> bytes:
    if not blob.startswith(_SAFESTORAGE_PREFIX):
        raise GranolaCryptoError(
            f"storage.dek missing v10 prefix: {blob[:4]!r}"
        )
    d = Cipher(algorithms.AES(key), modes.CBC(_AES128_IV)).decryptor()
    pt_padded = d.update(blob[len(_SAFESTORAGE_PREFIX):]) + d.finalize()
    return _pkcs7_unpad(pt_padded)


def get_dek() -> bytes:
    """Load and cache the 32-byte data encryption key."""
    global _cached_dek
    with _dek_lock:
        if _cached_dek is not None:
            return _cached_dek
        if not DEK_FILE.exists():
            raise GranolaCryptoError(f"DEK file missing: {DEK_FILE}")
        secret = _fetch_keychain_secret()
        ss_key = hashlib.pbkdf2_hmac("sha1", secret, _PBKDF2_SALT, _PBKDF2_ITER, 16)
        b64_dek = _safestorage_decrypt(DEK_FILE.read_bytes(), ss_key)
        dek = base64.b64decode(b64_dek)
        if len(dek) != 32:
            raise GranolaCryptoError(f"DEK length {len(dek)} != 32")
        _cached_dek = dek
        log.debug("Loaded Granola DEK (32 bytes)")
        return dek


def decrypt_file(path: Path, dek: bytes | None = None) -> bytes:
    """Decrypt one of Granola's *.enc files. Returns plaintext bytes."""
    if dek is None:
        dek = get_dek()
    blob = path.read_bytes()
    if len(blob) < _GCM_IV_LEN + _GCM_TAG_LEN:
        raise GranolaCryptoError(f"{path.name} too small to be an encrypted blob ({len(blob)} bytes)")
    iv = blob[:_GCM_IV_LEN]
    tag = blob[-_GCM_TAG_LEN:]
    ct = blob[_GCM_IV_LEN:-_GCM_TAG_LEN]
    d = Cipher(algorithms.AES(dek), modes.GCM(iv, tag)).decryptor()
    try:
        return d.update(ct) + d.finalize()
    except Exception as e:
        raise GranolaCryptoError(f"AES-GCM decrypt of {path.name} failed: {e}") from e


def load_supabase_token() -> str | None:
    """Return the WorkOS access token from supabase.json.enc, or None on failure."""
    if not SUPABASE_ENC.exists():
        return None
    token = _load_supabase_token_impl()
    # Lazy import: health.py imports from sync_state/models, but crypto is the
    # lower-level module — avoid an import-time cycle by deferring this lookup.
    try:
        from . import health
        health.get_monitor().record_decryption(
            success=token is not None, what="supabase token"
        )
    except Exception:
        log.debug("Could not report decryption outcome to HealthMonitor", exc_info=True)
    return token


def _load_supabase_token_impl() -> str | None:
    try:
        plaintext = decrypt_file(SUPABASE_ENC)
        sb = json.loads(plaintext)
        tokens_field = sb.get("workos_tokens")
        if not tokens_field:
            return None
        tokens = json.loads(tokens_field) if isinstance(tokens_field, str) else tokens_field
        return tokens.get("access_token")
    except GranolaCryptoError:
        log.warning("Failed to decrypt supabase.json.enc", exc_info=True)
        return None
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("supabase.json.enc decrypted but token extraction failed", exc_info=True)
        return None


def load_cache_state() -> dict | None:
    """Return the decrypted cache-v6.json.enc payload, or None on failure."""
    if not CACHE_ENC.exists():
        return None
    try:
        return json.loads(decrypt_file(CACHE_ENC))
    except (GranolaCryptoError, json.JSONDecodeError):
        log.warning("Failed to decrypt cache-v6.json.enc", exc_info=True)
        return None
