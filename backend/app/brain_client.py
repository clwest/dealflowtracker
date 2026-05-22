"""MentorForge — Brain bridge client.

Thin sync wrapper around unified-donkey-betz's Personal Assistant
endpoint. The PA (Rigby) is the "brain" for the fleet; this client lets
MentorForge ask Rigby a question and wait for a deliberated answer
without leaking the underlying POST-then-poll dance into view code.

Pattern: MentorForge HTTP → u-d-b /api/pa/chat/ → returns task_id
→ poll /api/pa/chat/status/<task_id>/ until completed → return answer.

Config (env vars, all consumed by `ask()`):
- BRAIN_URL          base URL of u-d-b. Default for compose: host.docker.internal:8000.
- BRAIN_TOKEN        PA API token (donkeyking's local token by default).
- BRAIN_CONVERSATION optional thread-id; if absent, each call starts a fresh thread.

The token + URL are runtime-loaded so a single bad value doesn't fail
module import. Calls return a structured dict; errors are surfaced as
`{"ok": False, "error": "..."}` rather than raised — view code stays
clean.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

DEFAULT_URL = "http://host.docker.internal:8000"
DEFAULT_TIMEOUT_SECONDS = 90
POLL_INTERVAL_SECONDS = 1.5


def _http_request(
    url: str,
    method: str = "GET",
    data: Optional[dict] = None,
    token: Optional[str] = None,
    host_header: Optional[str] = None,
    fleet_path: Optional[str] = None,
    fleet_query: str = "",
) -> tuple[dict, int]:
    """Issue an HTTP request to u-d-b.

    When FLEET_* env vars are set, also computes and attaches the
    X-Fleet-* signature headers per Move 1 of the fleet routing arc.
    `fleet_path` is the canonical path used in the signature base
    (e.g. ``/api/pa/chat/``) — the caller knows the path; we don't
    re-parse the URL to extract it.
    """
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    # Override Host so Django's ALLOWED_HOSTS sees a permitted name
    # (host.docker.internal is the *route* we use to reach native u-d-b,
    # but the receiving Django still binds localhost / 127.0.0.1).
    if host_header:
        headers["Host"] = host_header

    raw_body = json.dumps(data).encode() if data else b""
    req = urllib.request.Request(
        url,
        data=raw_body if data else None,
        headers=headers,
        method=method,
    )

    # Sign request if fleet env vars set (FLEET_APP_SLUG +
    # FLEET_KEY_ID + FLEET_SERVICE_SECRET). When absent we silently
    # skip signing — the request still reaches u-d-b via user-auth
    # token; any routing block claim will be stripped server-side
    # (Move 1 enforcement).
    if fleet_path:
        try:
            from app.fleet_signer import fleet_signature_headers
            fh = fleet_signature_headers(
                method=method,
                path=fleet_path,
                query=fleet_query,
                body=raw_body,
            )
            if fh:
                for k, v in fh.items():
                    req.add_header(k, v)
        except Exception:
            # Signing must never block the request; fall through unsigned.
            pass
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        try:
            return json.loads(body), e.code
        except json.JSONDecodeError:
            return {"error": body}, e.code
    except urllib.error.URLError as e:
        return {"error": f"URL error: {e.reason}"}, 0


def ask(
    message: str,
    *,
    conversation_id: Optional[str] = None,
    workspace: str = "mentorforge",
    user_id: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send a message to u-d-b's PA and return its response.

    Returns a dict with keys:
      ok (bool), answer (str on success), error (str on failure),
      conversation_id (str), trace_id (str — the PA task_id), latency_ms (int).
    """
    base = os.environ.get("BRAIN_URL", DEFAULT_URL).rstrip("/")
    token = os.environ.get("BRAIN_TOKEN", "")
    convo = conversation_id or os.environ.get("BRAIN_CONVERSATION") or None

    if not token:
        return {
            "ok": False,
            "error": "BRAIN_TOKEN not configured. Set it in the api service env.",
        }

    started = time.monotonic()
    payload: dict[str, Any] = {
        "message": message,
        "source": "mentorforge",
        "platform": "brain-bridge",
        "context": {
            "source": "mentorforge",
            "platform": "brain-bridge",
            "workspace": workspace,
            "user_id": user_id,
        },
    }
    if convo:
        payload["conversation_id"] = convo

    host_override = os.environ.get("BRAIN_HOST_HEADER", "localhost")
    submit, status = _http_request(
        f"{base}/api/pa/chat/",
        "POST",
        payload,
        token,
        host_header=host_override,
        fleet_path="/api/pa/chat/",
    )
    if status != 200 or not submit.get("success") or not submit.get("task_id"):
        return {
            "ok": False,
            "error": submit.get("error") or f"PA submit returned HTTP {status}",
        }

    task_id = submit["task_id"]
    deadline = started + timeout_seconds

    while time.monotonic() < deadline:
        poll_path = f"/api/pa/chat/status/{task_id}/"
        poll = _http_request(
            f"{base}{poll_path}",
            "GET",
            token=token,
            host_header=host_override,
            fleet_path=poll_path,
        )[0]
        task_status = poll.get("status", "unknown")
        if task_status == "completed":
            # u-d-b PA returns the answer in `content` (along with intent,
            # tool_runs, profile_completeness, etc). We pass through the
            # most useful subset; the raw response is available via the
            # PA's status endpoint by trace_id if a caller needs more.
            return {
                "ok": True,
                "answer": poll.get("content") or poll.get("response") or poll.get("answer") or "",
                "conversation_id": poll.get("conversation_id") or convo or "",
                "trace_id": poll.get("trace_id") or task_id,
                "intent": poll.get("intent"),
                "tool_runs": poll.get("tool_runs", []),
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        if task_status == "failed":
            return {
                "ok": False,
                "error": poll.get("error", "PA task failed"),
                "trace_id": task_id,
            }
        time.sleep(POLL_INTERVAL_SECONDS)

    return {
        "ok": False,
        "error": f"PA task did not complete within {timeout_seconds}s",
        "trace_id": task_id,
    }
