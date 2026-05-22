"""Tests for the fleet_signer module (Round 2 of Move 1).

The critical property is **wire-compatibility with u-d-b's verifier**:
both sides must compute the same signature from the same inputs. We
re-implement u-d-b's canonical signature base here as the oracle so
this test catches any drift in either copy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid

from app.fleet_signer import (
    HEADER_APP,
    HEADER_KEY_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    compute_signature,
    derive_verify_key,
    fleet_signature_headers,
)


def _udb_oracle_signature(
    *,
    method,
    path,
    query,
    app_slug,
    key_id,
    timestamp,
    nonce,
    body,
    secret_hash,
) -> str:
    """Independent re-implementation of u-d-b's signature base.

    Inline rather than imported to catch drift between the two copies.
    """
    from urllib.parse import parse_qsl, quote, urlencode

    method_upper = method.upper()
    if method_upper in ("GET", "DELETE", "HEAD"):
        if query:
            pairs = parse_qsl(query, keep_blank_values=True)
            encoded = [(quote(k, safe=""), quote(v, safe="")) for k, v in pairs]
            encoded.sort()
            canon_query = urlencode(encoded, safe="")
            canonical_path = f"{path}?{canon_query}"
        else:
            canonical_path = path
    else:
        canonical_path = path

    body_hash = hashlib.sha256(body or b"").hexdigest()
    base = "\n".join(
        [method_upper, canonical_path, app_slug, key_id, timestamp, nonce, body_hash]
    )
    digest = hmac.new(
        secret_hash.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


class TestCompute:
    def test_signature_matches_udb_oracle(self):
        ts = str(int(time.time()))
        n = uuid.uuid4().hex
        kwargs = dict(
            method="POST",
            path="/api/pa/chat/",
            query="",
            app_slug="contract-concierge",
            key_id="fs_contractconcierge_k1",
            timestamp=ts,
            nonce=n,
            body=b'{"message":"hi"}',
            secret_hash="known_verify_key_64chars" + "0" * 40,
        )
        ours = compute_signature(**kwargs)
        oracle = _udb_oracle_signature(**kwargs)
        assert ours == oracle

    def test_get_includes_querystring(self):
        ts = str(int(time.time()))
        n = uuid.uuid4().hex
        kwargs = dict(
            method="GET",
            path="/api/fleet/artifacts",
            query="limit=20&type=contract_draft",
            app_slug="contract-concierge",
            key_id="fs_contractconcierge_k1",
            timestamp=ts,
            nonce=n,
            body=b"",
            secret_hash="qs_key_64chars" + "0" * 50,
        )
        ours = compute_signature(**kwargs)
        oracle = _udb_oracle_signature(**kwargs)
        assert ours == oracle

    def test_get_querystring_order_normalizes(self):
        ts = str(int(time.time()))
        n = uuid.uuid4().hex
        common = dict(
            method="GET",
            path="/api/fleet/artifacts",
            app_slug="contract-concierge",
            key_id="fs_contractconcierge_k1",
            timestamp=ts,
            nonce=n,
            body=b"",
            secret_hash="order_key_64chars" + "0" * 47,
        )
        sig_a = compute_signature(query="a=1&b=2", **common)
        sig_b = compute_signature(query="b=2&a=1", **common)
        assert sig_a == sig_b


class TestDeriveVerifyKey:
    def test_sha256_hex_is_64_chars(self):
        secret = "any-32-byte-random-base64-string"
        vk = derive_verify_key(secret)
        assert len(vk) == 64
        # Stable across calls
        assert vk == derive_verify_key(secret)

    def test_different_secrets_different_keys(self):
        assert derive_verify_key("a") != derive_verify_key("b")


class TestFleetSignatureHeaders:
    def test_env_vars_unset_returns_none(self, monkeypatch):
        for v in ("FLEET_APP_SLUG", "FLEET_KEY_ID", "FLEET_SERVICE_SECRET"):
            monkeypatch.delenv(v, raising=False)
        out = fleet_signature_headers(
            method="POST", path="/api/pa/chat/", query="", body=b""
        )
        assert out is None

    def test_env_vars_set_returns_five_headers(self, monkeypatch):
        monkeypatch.setenv("FLEET_APP_SLUG", "contract-concierge")
        monkeypatch.setenv("FLEET_KEY_ID", "fs_contractconcierge_k1")
        monkeypatch.setenv("FLEET_SERVICE_SECRET", "any-32-byte-random-string")
        out = fleet_signature_headers(
            method="POST", path="/api/pa/chat/", query="", body=b'{"x":1}'
        )
        assert out is not None
        assert set(out.keys()) == {
            HEADER_APP,
            HEADER_KEY_ID,
            HEADER_TIMESTAMP,
            HEADER_NONCE,
            HEADER_SIGNATURE,
        }
        assert out[HEADER_APP] == "contract-concierge"
        assert out[HEADER_KEY_ID] == "fs_contractconcierge_k1"
        assert int(out[HEADER_TIMESTAMP]) > 0  # valid integer timestamp
        # signature is base64
        base64.b64decode(out[HEADER_SIGNATURE], validate=True)

    def test_override_args_take_priority(self, monkeypatch):
        # env vars set but explicit args should override
        monkeypatch.setenv("FLEET_APP_SLUG", "env-app")
        monkeypatch.setenv("FLEET_KEY_ID", "env-key")
        monkeypatch.setenv("FLEET_SERVICE_SECRET", "env-secret")
        out = fleet_signature_headers(
            method="POST",
            path="/api/x",
            query="",
            body=b"",
            app_slug="override-app",
            key_id="override-key",
            raw_secret="override-secret",
        )
        assert out[HEADER_APP] == "override-app"
        assert out[HEADER_KEY_ID] == "override-key"

    def test_partial_env_returns_none(self, monkeypatch):
        monkeypatch.setenv("FLEET_APP_SLUG", "x")
        monkeypatch.setenv("FLEET_KEY_ID", "y")
        monkeypatch.delenv("FLEET_SERVICE_SECRET", raising=False)
        out = fleet_signature_headers(
            method="POST", path="/api/x", query="", body=b""
        )
        assert out is None
