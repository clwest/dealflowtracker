"""Regression guard: prove `/api/fleet/*` calls carry signing headers.

Rigby's Session 1129 follow-up after Move 2 Round 1: PR #11's
squash-merge silently lost the `_http_request` fleet_path patch. We
caught it only because the live smoke failed. This test prevents that
class of regression by patching `urllib.request.urlopen` at the very
edge and inspecting the actual Request headers that go on the wire.

If a future merge or refactor strips signing from `_http_request`, OR
removes the `fleet_path` arg threading from `push_artifact` /
`pull_artifact`, this test fails immediately with a clear diff
between expected and observed headers.

Identical across all 7 fleet repos.
"""

from __future__ import annotations

import io
import json
import os
from unittest.mock import MagicMock, patch

# Pre-set env so fleet_signer runs end-to-end
os.environ.setdefault("BRAIN_TOKEN", "test-token")
os.environ.setdefault("BRAIN_URL", "http://test.local")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_test_fleet_signing_regression.db")
os.environ["FLEET_APP_SLUG"] = "dealflowtracker"
os.environ["FLEET_KEY_ID"] = "fs_dealflowtracker_k1_test"
os.environ["FLEET_SERVICE_SECRET"] = "regression-test-secret-32-bytes-rand"


def _header_present(req, header_name: str) -> bool:
    """Case-insensitive header lookup. urllib normalizes header names
    via `.capitalize()` when storing — so `req.has_header("X-Fleet-App")`
    misses (the lookup is literal). Lowercase-compare both sides."""
    needle = header_name.lower()
    return any(k.lower() == needle for k in req.headers) or any(
        k.lower() == needle for k in req.unredirected_hdrs
    )


def _capture_request(method_response_body: bytes = b'{"id":"x","sha256":"y","size_bytes":0,"created_at":"z","artifact_type":"t"}',
                     status_code: int = 201):
    """Return (mock_urlopen, captured_requests) — patch urlopen and
    collect every Request object that flies through it."""
    captured = []

    def fake_urlopen(req, timeout=30):
        captured.append(req)
        resp = MagicMock()
        resp.read = MagicMock(return_value=method_response_body)
        resp.status = status_code
        return resp

    return fake_urlopen, captured


class TestSigningHeadersOnFleetEndpoints:
    """Every `/api/fleet/*` call MUST carry X-Fleet-* signature headers."""

    def test_push_artifact_signs_request(self):
        from app.brain_client import push_artifact

        fake_urlopen, captured = _capture_request()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            push_artifact({"hello": "world"}, artifact_type="test")

        assert len(captured) == 1, "push_artifact must issue exactly one HTTP request"
        req = captured[0]
        # All five X-Fleet-* headers present (urllib lowercases them
        # internally in `unredirected_hdrs` AND `headers` — check both)
        for header_name in (
            "X-Fleet-App",
            "X-Fleet-Key-Id",
            "X-Fleet-Timestamp",
            "X-Fleet-Nonce",
            "X-Fleet-Signature",
        ):
            assert _header_present(req, header_name), (
                f"missing required signing header: {header_name}. "
                f"Outbound headers were: {dict(req.headers)}"
            )

    def test_pull_artifact_signs_request(self):
        from app.brain_client import pull_artifact

        fake_urlopen, captured = _capture_request(
            method_response_body=b'{"id":"x","payload":{},"artifact_type":"t","metadata":{},"sha256":"y","size_bytes":0,"created_at":"z","created_by":{"app_slug":"contract-concierge"}}',
            status_code=200,
        )
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            pull_artifact("some-uuid")

        assert len(captured) == 1
        req = captured[0]
        for header_name in (
            "X-Fleet-App",
            "X-Fleet-Key-Id",
            "X-Fleet-Timestamp",
            "X-Fleet-Nonce",
            "X-Fleet-Signature",
        ):
            assert _header_present(req, header_name), (
                f"missing required signing header: {header_name}"
            )

    def test_pa_chat_ask_also_signs(self):
        """The brain bridge `/api/pa/chat/` call should sign too — it's not
        fleet-only, but signing is what gates routing-block enforcement."""
        from app.brain_client import ask

        fake_urlopen, captured = _capture_request(
            method_response_body=b'{"success":true,"task_id":"t1","status":"processing"}',
            status_code=200,
        )
        # ask() POSTs then polls — but the poll body would 404 with our
        # mock. Force completion by patching POSTs only.
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            # ask() will POST then start polling; we just need the POST
            # to capture. The poll will get the same fake response which
            # will fail JSON parsing and eventually time out — but the
            # POST is the only call we care about asserting.
            try:
                # Use a tiny timeout via env so polling exits fast
                ask("hi", timeout_seconds=1)
            except Exception:
                pass

        # First call is the POST to /api/pa/chat/ — it must be signed
        assert len(captured) >= 1
        post_req = captured[0]
        assert post_req.method == "POST"
        assert "/api/pa/chat/" in post_req.full_url
        for header_name in (
            "X-Fleet-App",
            "X-Fleet-Signature",
        ):
            assert _header_present(post_req, header_name), (
                f"POST /api/pa/chat/ must sign: missing {header_name}"
            )


class TestSigningHeadersSkippedWhenEnvUnset:
    """When fleet env vars aren't set, signing must skip silently — no
    headers added, request still issued."""

    def test_no_env_no_signing(self, monkeypatch):
        # Strip all three FLEET_* env vars
        for key in ("FLEET_APP_SLUG", "FLEET_KEY_ID", "FLEET_SERVICE_SECRET"):
            monkeypatch.delenv(key, raising=False)

        from app.brain_client import push_artifact

        fake_urlopen, captured = _capture_request()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            push_artifact({"hello": "world"}, artifact_type="test")

        # Request was still made — but no signing headers
        assert len(captured) == 1
        req = captured[0]
        for header_name in (
            "X-Fleet-App",
            "X-Fleet-Signature",
        ):
            assert not _header_present(req, header_name), (
                f"signing header {header_name} must NOT appear when env unset"
            )
