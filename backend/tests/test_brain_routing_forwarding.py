"""Session 1128 Phase 2B — invariant test for fleet brain routing.

Rigby's required test per app: prove `/api/brain/ask` forwards
`context.app_slug` + `routing.{mode,agent,role}` to u-d-b's
`/api/pa/chat/`, and preserves the response `routing` block back to
the caller.

This test mocks `app.brain_client._http_request` so we never actually
touch the network — we just assert the payload shape going outbound,
and the response shape coming back through `/api/brain/ask`.
"""

from __future__ import annotations

import os
from unittest.mock import patch

# brain_client.ask() short-circuits when BRAIN_TOKEN isn't set. Provide
# a placeholder before importing the app so the brain route reaches
# our mocked _http_request.
os.environ.setdefault("BRAIN_TOKEN", "test-token")
# Some fleet apps require DATABASE_URL at import time (SQLAlchemy engine
# is constructed at module load). A throwaway sqlite file is fine for
# tests that only exercise the brain route.
os.environ.setdefault("DATABASE_URL", "sqlite:///./_test_brain_routing.db")

from fastapi.testclient import TestClient

from app.auth import create_token
from app.main import app

client = TestClient(app)


def _auth_header() -> dict[str, str]:
    token = create_token("test-user-1", "test@example.com")
    return {"Authorization": f"Bearer {token}"}

def _fake_http_response(routing_block: dict | None = None):
    """Build a stand-in for `_http_request` that returns POST submit, then poll completed."""
    calls: list[tuple[str, str, dict | None]] = []

    def fake(url, method="GET", data=None, token=None, host_header=None):
        calls.append((url, method, data))
        if method == "POST":
            return ({"success": True, "task_id": "fake-task-1"}, 200)
        body: dict = {
            "status": "completed",
            "content": "ok",
            "conversation_id": "pa-x",
            "trace_id": "trace-x",
            "intent": "fleet_force_dispatch",
            "tool_runs": [],
        }
        if routing_block is not None:
            body["routing"] = routing_block
        return (body, 200)

    return fake, calls


class TestBrainAskForwarding:
    def test_no_routing_fields_does_not_send_routing_block(self):
        fake, calls = _fake_http_response()
        with patch("app.brain_client._http_request", side_effect=fake):
            resp = client.post(
                "/api/brain/ask",
                json={"message": "hello"},
        headers=_auth_header(),
            )
        assert resp.status_code == 200
        _, post_method, post_data = calls[0]
        assert post_method == "POST"
        assert post_data is not None
        assert "routing" not in post_data, (
            "routing must be absent when caller didn't pass mode/agent/role"
        )
        assert post_data["context"]["app_slug"] == "dealflowtracker"
        assert post_data["context"]["workspace"] == "dealflowtracker"
        assert post_data["context"]["request_id"]

    def test_force_routing_forwarded_into_payload(self):
        fake, calls = _fake_http_response(
            routing_block={
                "app_slug": "dealflowtracker",
                "resolved_agent": "content_writer_agent",
                "routed_to": "ContentWriterAgent",
                "phase2_dispatched": True,
            }
        )
        with patch("app.brain_client._http_request", side_effect=fake):
            resp = client.post(
                "/api/brain/ask",
                json={
                    "message": "do the thing",
                    "mode": "force",
                    "agent": "content_writer_agent",
                },
        headers=_auth_header(),
            )
        assert resp.status_code == 200
        _, _, post_data = calls[0]
        assert post_data is not None
        assert post_data.get("routing") == {
            "requested_by": "fleet_app",
            "mode": "force",
            "agent": "content_writer_agent",
        }
        assert post_data["context"]["app_slug"] == "dealflowtracker"
        body = resp.json()
        assert body["routing"]["phase2_dispatched"] is True
        assert body["routing"]["routed_to"] == "ContentWriterAgent"

    def test_hint_with_role_only_no_agent(self):
        fake, calls = _fake_http_response()
        with patch("app.brain_client._http_request", side_effect=fake):
            resp = client.post(
                "/api/brain/ask",
                json={
                    "message": "advise me",
                    "mode": "hint",
                    "role": "content_writing",
                },
        headers=_auth_header(),
            )
        assert resp.status_code == 200
        _, _, post_data = calls[0]
        assert post_data is not None
        assert post_data["routing"] == {
            "requested_by": "fleet_app",
            "mode": "hint",
            "role": "content_writing",
        }
