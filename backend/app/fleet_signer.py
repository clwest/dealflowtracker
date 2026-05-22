"""Fleet service-identity signature helper (client side, Move 1 Round 2).

Mirror of `core.services.fleet_auth.compute_signature()` from u-d-b's
PR clwest/donkey-betz-platform#2129. Mathematically identical so the
two sides of the wire agree on the signature base.

Standalone module so this file can stay byte-identical across all 7
fleet repos (Rigby's "DO NOT EDIT EXCEPT THESE CONSTANTS" rule). The
only thing per-repo about signing is the env vars; this module reads
them.

────────────────────────────────────────────────────────────────────────
DO NOT EDIT — this file is a copy of the canonical fleet signer.
Edits should land in contract-concierge first, then back-prop verbatim
to the other 6 fleet repos. The cross-repo copy is what keeps the
signing contract stable.
────────────────────────────────────────────────────────────────────────

Wire shape (matches u-d-b spec section 1.3):

    X-Fleet-App:        dealflowtracker
    X-Fleet-Key-Id:     fs_dealflowtracker_k1
    X-Fleet-Timestamp:  <unix seconds>
    X-Fleet-Nonce:      <uuid4 hex>
    X-Fleet-Signature:  <base64 HMAC-SHA256>

Signature base:

    METHOD + "\\n" + PATH + "\\n" + APP + "\\n" + KEY_ID + "\\n"
        + TIMESTAMP + "\\n" + NONCE + "\\n" + SHA256_HEX(RAW_BODY)

Key contract: the HMAC verify key is **SHA256(secret)**, not the raw
secret. Both sides agree on this so the server can verify with the
hash it stores. Captured signatures cannot be inverted to recover
the original secret.

Env vars consumed:
    FLEET_APP_SLUG          — fleet identity (e.g. "contract-concierge")
    FLEET_KEY_ID            — key identifier (e.g. "fs_contractconcierge_k1")
    FLEET_SERVICE_SECRET    — raw secret minted by u-d-b's provisioning
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode


HEADER_APP = "X-Fleet-App"
HEADER_KEY_ID = "X-Fleet-Key-Id"
HEADER_TIMESTAMP = "X-Fleet-Timestamp"
HEADER_NONCE = "X-Fleet-Nonce"
HEADER_SIGNATURE = "X-Fleet-Signature"


def _canonicalize_querystring(query: str) -> str:
    """Match u-d-b's `_canonicalize_querystring`: percent-encode then
    sort (k, v) tuples lexicographically. Multi-value params sort by
    value, not arrival order."""
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    encoded = [(quote(k, safe=""), quote(v, safe="")) for k, v in pairs]
    encoded.sort()
    return urlencode(encoded, safe="")


def _build_signature_base(
    method: str,
    path: str,
    query: str,
    app_slug: str,
    key_id: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    method_upper = method.upper()
    if method_upper in ("GET", "DELETE", "HEAD"):
        canon_query = _canonicalize_querystring(query)
        canonical_path = f"{path}?{canon_query}" if canon_query else path
    else:
        canonical_path = path

    body_hash = hashlib.sha256(body or b"").hexdigest()

    return "\n".join(
        [
            method_upper,
            canonical_path,
            app_slug,
            key_id,
            timestamp,
            nonce,
            body_hash,
        ]
    )


def compute_signature(
    *,
    method: str,
    path: str,
    query: str,
    app_slug: str,
    key_id: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    secret_hash: str,
) -> str:
    """Compute the base64 HMAC-SHA256 signature for a request.

    `secret_hash` must be SHA256(raw_secret) — the same key u-d-b's
    server uses for verification. Use `derive_verify_key(raw_secret)`
    when you only have the raw secret from env vars.
    """
    base = _build_signature_base(
        method=method,
        path=path,
        query=query,
        app_slug=app_slug,
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    digest = hmac.new(
        secret_hash.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def derive_verify_key(raw_secret: str) -> str:
    """Compute SHA256(secret) — the actual HMAC key both sides agree on.

    Apps typically call this once at startup and cache the result.
    """
    return hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()


def fleet_signature_headers(
    *,
    method: str,
    path: str,
    query: str,
    body: bytes,
    app_slug: Optional[str] = None,
    key_id: Optional[str] = None,
    raw_secret: Optional[str] = None,
) -> Optional[dict[str, str]]:
    """Build the five X-Fleet-* headers for a request.

    Returns None when the fleet env vars aren't set — the caller should
    fall back to unsigned mode in that case. When set, returns a dict
    ready to merge into the outbound request headers.

    Args (all optional, env-driven by default):
        method/path/query/body: the request you're about to send.
        app_slug, key_id, raw_secret: override env if set.
    """
    app = app_slug or os.environ.get("FLEET_APP_SLUG", "")
    kid = key_id or os.environ.get("FLEET_KEY_ID", "")
    secret = raw_secret or os.environ.get("FLEET_SERVICE_SECRET", "")
    if not (app and kid and secret):
        return None

    verify_key = derive_verify_key(secret)
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    sig = compute_signature(
        method=method,
        path=path,
        query=query,
        app_slug=app,
        key_id=kid,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
        secret_hash=verify_key,
    )
    return {
        HEADER_APP: app,
        HEADER_KEY_ID: kid,
        HEADER_TIMESTAMP: timestamp,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: sig,
    }


__all__ = [
    "HEADER_APP",
    "HEADER_KEY_ID",
    "HEADER_TIMESTAMP",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "compute_signature",
    "derive_verify_key",
    "fleet_signature_headers",
]
