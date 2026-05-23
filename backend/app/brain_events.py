"""Contract Concierge — upstream fleet event subscriber.

Connects to u-d-b's `GET /api/fleet/events/stream` over a signed
fleet request, parses the SSE wire format, and yields envelopes as
plain dicts. The downstream view layer is responsible for per-user
filtering + re-emitting to the browser.

Pattern (locked with Rigby — 2-hop fan-out):

    u-d-b           ──(signed SSE)──>   contract-concierge backend
    (app_slug                            (filters per-user, re-emits
     channel)                             on user-session SSE)
                                                │
                                                ▼
                                          browser EventSource
                                          (JWT in query param)

Why this lives in the app, not u-d-b: only this app knows which user
owns which artifact metadata. u-d-b only knows app_slug-granularity.

────────────────────────────────────────────────────────────────────────
DO NOT EDIT EXCEPT THESE CONSTANTS (Session 1129 Move 3 Round 1):
- The `DEFAULT_APP_SLUG` constant
- The default `path` value on `subscribe_fleet_events()`
Everything else must stay byte-identical across the 7 fleet repos so
Phase 2C can pull this into a shared package without per-repo
divergence patches.
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)


DEFAULT_URL = "http://host.docker.internal:8000"
# Per-repo constant — matches the keys in u-d-b's fleet_agent_routing.json.
DEFAULT_APP_SLUG = "dealflowtracker"


def _build_signed_headers(method: str, path: str, query: str, body: bytes):
    """Build the X-Fleet-* headers via the shared signer module."""
    try:
        from app.fleet_signer import fleet_signature_headers
    except Exception:
        return None
    return fleet_signature_headers(
        method=method,
        path=path,
        query=query,
        body=body,
    )


async def subscribe_fleet_events(
    *,
    path: str = "/api/fleet/events/stream",
    host_header: Optional[str] = None,
) -> AsyncIterator[dict]:
    """Async generator yielding event envelopes from u-d-b.

    Yields parsed SSE events as dicts of the shape:
        {"id": ..., "event": ..., "data": {<envelope>}}

    Behavior:
    - Opens a streaming GET with fleet-signed headers.
    - Reconnects with exponential backoff (capped at 30s) on transport
      errors. We never raise to the caller — a long-lived subscriber
      should keep going across transient outages.
    - Yields nothing on keep-alive comment lines (`: ping`); the caller
      relies on this generator to send its own heartbeats downstream.
    """
    base = os.environ.get("BRAIN_URL", DEFAULT_URL).rstrip("/")
    host_override = host_header or os.environ.get("BRAIN_HOST_HEADER", "localhost")
    url = f"{base}{path}"

    backoff = 1.0
    while True:
        sig_headers = _build_signed_headers("GET", path, "", b"")
        if sig_headers is None:
            logger.warning(
                "[brain-events] fleet env vars not set; cannot subscribe"
            )
            # Give up — there's no way to recover without env config.
            return

        headers = dict(sig_headers)
        headers["Accept"] = "text/event-stream"
        headers["Host"] = host_override
        # No timeout on read — SSE streams idle on purpose.
        timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode(errors="replace")[:300]
                        logger.warning(
                            "[brain-events] upstream returned HTTP %d: %s",
                            resp.status_code, body,
                        )
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30.0)
                        continue
                    backoff = 1.0  # reset on a successful connect.
                    logger.info("[brain-events] upstream SSE connected")

                    buf: list[str] = []
                    async for line in resp.aiter_lines():
                        if line == "":
                            # End of one event.
                            if buf:
                                evt = _parse_event(buf)
                                if evt is not None:
                                    yield evt
                                buf = []
                            continue
                        if line.startswith(":"):
                            # SSE comment / keep-alive. Skip silently.
                            continue
                        buf.append(line)
        except asyncio.CancelledError:
            logger.info("[brain-events] cancelled — closing upstream")
            raise
        except Exception as e:
            logger.warning(
                "[brain-events] upstream connection error: %s (retry in %.1fs)",
                e, backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue


def _parse_event(lines: list[str]) -> Optional[dict]:
    """Turn a list of SSE field lines into a normalized event dict."""
    out: dict = {}
    data_parts: list[str] = []
    for ln in lines:
        if ln.startswith("event:"):
            out["event"] = ln[6:].strip()
        elif ln.startswith("id:"):
            out["id"] = ln[3:].strip()
        elif ln.startswith("data:"):
            data_parts.append(ln[5:].lstrip())
    if data_parts:
        raw = "\n".join(data_parts)
        try:
            out["data"] = json.loads(raw)
        except json.JSONDecodeError:
            out["data"] = raw
    return out or None


__all__ = ["subscribe_fleet_events"]
