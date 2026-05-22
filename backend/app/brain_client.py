"""DealFlowTracker — Brain bridge client.

Thin sync wrapper around unified-donkey-betz's Personal Assistant
endpoint. The PA (Rigby) is the "brain" for the fleet; this client lets
this app ask Rigby a question and wait for a deliberated answer
without leaking the underlying POST-then-poll dance into view code.

Pattern: app HTTP → u-d-b /api/pa/chat/ → returns task_id
→ poll /api/pa/chat/status/<task_id>/ until completed → return answer.

Config (env vars, all consumed by `ask()`):
- BRAIN_URL          base URL of u-d-b. Default for compose: host.docker.internal:8000.
- BRAIN_TOKEN        PA API token (donkeyking's local token by default).
- BRAIN_CONVERSATION optional thread-id; if absent, each call starts a fresh thread.
- BRAIN_HOST_HEADER  override Host header so Django's ALLOWED_HOSTS sees a permitted name.

The token + URL are runtime-loaded so a single bad value doesn't fail
module import. Calls return a structured dict; errors are surfaced as
`{"ok": False, "error": "..."}` rather than raised — view code stays
clean.

────────────────────────────────────────────────────────────────────────
DO NOT EDIT EXCEPT THESE CONSTANTS (Session 1128 Phase 2B):
- The `DEFAULT_APP_SLUG` module-level constant
- The default `workspace` parameter on `ask()`
- The `"source"` and inner `"source"` values inside `payload`
Everything else must stay byte-identical across the 7 fleet repos so
that the next round (Phase 2C) can pull this file into a shared
package without per-repo divergence patches.
────────────────────────────────────────────────────────────────────────

Session 1128 Phase 2B contract additions (back-prop from contract-concierge):
- Sends `context.app_slug` so u-d-b's fleet_routing.resolve() can apply
  per-app allowlists / defaults.
- Sends an optional top-level `routing` block when the caller passes
  any of (mode, agent, role). The block follows the Phase 1 shape:
  {"mode": "hint" | "force", "agent": "<snake_case>", "role": "<snake_case>"}.
- Propagates a `context.request_id` so logs on u-d-b's side can be
  joined to this app's logs without a manual trace_id hand-off.
- Surfaces u-d-b's response `routing` block back to the caller so
  fleet UIs can show whether a force-dispatch actually fired
  (`routing.phase2_dispatched`) and which agent ran.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

DEFAULT_URL = "http://host.docker.internal:8000"
DEFAULT_TIMEOUT_SECONDS = 90
POLL_INTERVAL_SECONDS = 1.5
# Per-repo constant — the only value that legitimately differs between
# fleet brain_client.py copies. Must match the keys in u-d-b's
# `config/fleet_agent_routing.json`.
DEFAULT_APP_SLUG = "dealflowtracker"


def _http_request(
    url: str,
    method: str = "GET",
    data: Optional[dict] = None,
    token: Optional[str] = None,
    host_header: Optional[str] = None,
) -> tuple[dict, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    # Override Host so Django's ALLOWED_HOSTS sees a permitted name
    # (host.docker.internal is the *route* we use to reach native u-d-b,
    # but the receiving Django still binds localhost / 127.0.0.1).
    if host_header:
        headers["Host"] = host_header
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=headers,
        method=method,
    )
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
    app_slug: Optional[str] = None,
    agent: Optional[str] = None,
    role: Optional[str] = None,
    mode: Optional[str] = None,
    request_id: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send a message to u-d-b's PA and return its response.

    Args:
      message: the user's question / instruction.
      conversation_id: optional thread id; reused across turns if set.
      workspace: u-d-b workspace tag (used for VIP-scoped sessions).
      user_id: stable id for the caller, threaded into PA context.
      app_slug: fleet app identifier (e.g. "contract-concierge") — used
        by u-d-b's fleet routing for allowlist / default resolution.
        Defaults to this module's DEFAULT_APP_SLUG.
      agent: optional u-d-b AGENT_MAP key (snake_case form from
        `fleet_agent_routing.json`). Sent inside `routing.agent`.
      role: optional role name (e.g. "legal_drafting"). Sent inside
        `routing.role` and resolved server-side via the routing config's
        `roles` map. Mutually meaningful with `agent`; if both, agent
        wins.
      mode: "hint" or "force". Required when sending any routing
        request. The Phase 2A dispatcher in u-d-b only short-circuits
        on `mode=force` AND the app's `force_allowed` AND the
        requested agent in the app's allowlist.
      request_id: optional trace id; auto-generated when omitted.
      timeout_seconds: how long to wait for the PA task to complete.

    Returns a dict with keys:
      ok (bool), answer (str on success), error (str on failure),
      conversation_id (str), trace_id (str — the PA task_id),
      latency_ms (int), intent (str | None), tool_runs (list),
      routing (dict | None — u-d-b's RoutingDecision when fleet routing
      ran; includes `phase2_dispatched: bool` so callers can see if
      force-dispatch actually fired).
    """
    base = os.environ.get("BRAIN_URL", DEFAULT_URL).rstrip("/")
    token = os.environ.get("BRAIN_TOKEN", "")
    convo = conversation_id or os.environ.get("BRAIN_CONVERSATION") or None
    resolved_app_slug = app_slug or DEFAULT_APP_SLUG
    resolved_request_id = request_id or uuid.uuid4().hex

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
            "app_slug": resolved_app_slug,
            "request_id": resolved_request_id,
        },
    }
    if convo:
        payload["conversation_id"] = convo

    # Only include `routing` when the caller explicitly asked for it.
    # Rigby's rule (Session 1128): don't silently default to hint mode
    # for every call — that would invite drift. Routing absent → u-d-b
    # falls back to its normal intent detection.
    if any(v is not None for v in (mode, agent, role)):
        routing: dict[str, Any] = {"requested_by": "fleet_app"}
        if mode is not None:
            routing["mode"] = mode
        if agent is not None:
            routing["agent"] = agent
        if role is not None:
            routing["role"] = role
        payload["routing"] = routing

    host_override = os.environ.get("BRAIN_HOST_HEADER", "localhost")
    submit, status = _http_request(
        f"{base}/api/pa/chat/", "POST", payload, token, host_header=host_override
    )
    if status != 200 or not submit.get("success") or not submit.get("task_id"):
        return {
            "ok": False,
            "error": submit.get("error") or f"PA submit returned HTTP {status}",
        }

    task_id = submit["task_id"]
    deadline = started + timeout_seconds

    while time.monotonic() < deadline:
        poll = _http_request(
            f"{base}/api/pa/chat/status/{task_id}/",
            "GET",
            token=token,
            host_header=host_override,
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
                "routing": poll.get("routing"),
                "request_id": resolved_request_id,
            }
        if task_status == "failed":
            return {
                "ok": False,
                "error": poll.get("error", "PA task failed"),
                "trace_id": task_id,
                "request_id": resolved_request_id,
            }
        time.sleep(POLL_INTERVAL_SECONDS)

    return {
        "ok": False,
        "error": f"PA task did not complete within {timeout_seconds}s",
        "trace_id": task_id,
        "request_id": resolved_request_id,
    }
