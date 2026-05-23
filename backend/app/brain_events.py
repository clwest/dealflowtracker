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

Session 1130 — Move 3 Round 2:
Adds replay-before-subscribe so reconnects don't silently lose events.
Rigby's lock #3: "canonical recovery path is GET /api/fleet/events/
?since=<last_seq> until exhausted, THEN subscribe to /stream." This
module owns both halves of that recovery; the SSE `Last-Event-ID`
header is set as a best-effort fallback for the rare case where the
explicit replay call fails but the stream still connects.

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

# Move 3 R2: replay endpoint page size when catching up after a
# reconnect. Matches u-d-b's REPLAY_DEFAULT_LIMIT; the client pages
# until len < limit, then attaches the SSE stream.
REPLAY_PAGE_LIMIT = 100
# Bound the number of replay pages per reconnect so a long outage
# doesn't block us forever before we attach to live. 50 pages * 100
# = 5000 events catches well over a day's worth at current traffic.
MAX_REPLAY_PAGES = 50


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


async def _replay_since(
    *,
    base: str,
    host_override: str,
    last_seq: int,
    timeout: httpx.Timeout,
) -> AsyncIterator[dict]:
    """Drain GET /api/fleet/events/?since=<last_seq> until exhausted.

    Yields envelopes in the same shape as the SSE stream so the caller
    can treat replay + live as one continuous source. Caps at
    MAX_REPLAY_PAGES per call to bound recovery time after a long
    outage. If we hit the cap the caller falls back to live + accepts
    the gap (the truncation will surface via a `stream.replay_truncated`
    event from the SSE stream itself).
    """
    path = "/api/fleet/events/"
    since = last_seq
    pages = 0
    async with httpx.AsyncClient(timeout=timeout) as client:
        while pages < MAX_REPLAY_PAGES:
            query = f"since={since}&limit={REPLAY_PAGE_LIMIT}"
            sig_headers = _build_signed_headers("GET", path, query, b"")
            if sig_headers is None:
                logger.warning(
                    "[brain-events] cannot replay; fleet env vars not set"
                )
                return
            headers = dict(sig_headers)
            headers["Host"] = host_override
            url = f"{base}{path}?{query}"
            try:
                resp = await client.get(url, headers=headers)
            except Exception as e:
                logger.warning(
                    "[brain-events] replay request error since=%d: %s",
                    since, e,
                )
                return
            if resp.status_code != 200:
                body = resp.text[:300] if resp.text else ""
                logger.warning(
                    "[brain-events] replay returned HTTP %d since=%d: %s",
                    resp.status_code, since, body,
                )
                return
            try:
                doc = resp.json()
            except Exception as e:
                logger.warning(
                    "[brain-events] replay JSON decode failed since=%d: %s",
                    since, e,
                )
                return
            events = doc.get("events") or []
            for envelope in events:
                # Yield in the SSE-shaped form `_parse_event` produces so
                # downstream consumers can treat replay + live the same.
                yield {
                    "event": envelope.get("type", "fleet_event"),
                    "id": str(envelope.get("seq", "")),
                    "data": envelope,
                }
            since = doc.get("next_since", since)
            pages += 1
            if not doc.get("has_more"):
                if pages == 1 and not events:
                    # First page empty means there's nothing to replay.
                    logger.debug("[brain-events] replay caught up since=%d (no events)", since)
                else:
                    logger.info(
                        "[brain-events] replay drained since→%d after %d page(s)",
                        since, pages,
                    )
                return
    logger.warning(
        "[brain-events] replay capped at %d pages since→%d; live stream will fill the gap",
        MAX_REPLAY_PAGES, since,
    )


async def subscribe_fleet_events(
    *,
    path: str = "/api/fleet/events/stream",
    host_header: Optional[str] = None,
) -> AsyncIterator[dict]:
    """Async generator yielding event envelopes from u-d-b.

    Yields parsed SSE events as dicts of the shape:
        {"id": ..., "event": ..., "data": {<envelope>}}

    Behavior (Move 3 R2):
    - Tracks `last_seq` across the lifetime of the subscriber.
    - Before each SSE connect (initial + reconnects), drains
      `GET /api/fleet/events/?since=<last_seq>` until exhausted, yields
      those events first, then attaches the live stream.
    - Also sends `Last-Event-ID: <last_seq>` on the SSE GET so u-d-b
      can fill any tiny gap between the replay drain and the live
      subscribe (best-effort; canonical recovery is the replay call).
    - Reconnects with exponential backoff (capped at 30s) on transport
      errors. We never raise to the caller — a long-lived subscriber
      should keep going across transient outages.
    - Yields nothing on keep-alive comment lines (`: ping`); the caller
      relies on this generator to send its own heartbeats downstream.
    """
    base = os.environ.get("BRAIN_URL", DEFAULT_URL).rstrip("/")
    host_override = host_header or os.environ.get("BRAIN_HOST_HEADER", "localhost")
    url = f"{base}{path}"

    # Move 3 R2: monotonic seq cursor tracked across reconnects.
    # Starts at 0 (we want everything from the start on first connect
    # in most dev setups; production callers can plug in a persisted
    # last_seq later via an env var if cold-start is heavy).
    last_seq: int = 0

    backoff = 1.0
    # No timeout on read — SSE streams idle on purpose.
    timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
    replay_timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)

    while True:
        # ─── Phase 1: drain replay since last_seq. ──────────────────
        try:
            async for envelope in _replay_since(
                base=base,
                host_override=host_override,
                last_seq=last_seq,
                timeout=replay_timeout,
            ):
                # Bump last_seq as we yield so a crash mid-replay still
                # advances the cursor — next reconnect picks up cleanly.
                data = envelope.get("data") or {}
                seq_val = data.get("seq")
                if isinstance(seq_val, int) and seq_val > last_seq:
                    last_seq = seq_val
                yield envelope
        except asyncio.CancelledError:
            logger.info("[brain-events] cancelled during replay — closing")
            raise
        except Exception as e:
            logger.warning(
                "[brain-events] replay phase error since=%d: %s",
                last_seq, e,
            )
            # Don't return — fall through to live subscribe so we at
            # least don't go dark. The next reconnect retries replay.

        # ─── Phase 2: live SSE subscribe. ───────────────────────────
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
        if last_seq > 0:
            # Best-effort SSE replay shortcut (Rigby's lock #3 fallback).
            headers["Last-Event-ID"] = str(last_seq)
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
                    logger.info(
                        "[brain-events] upstream SSE connected last_seq=%d",
                        last_seq,
                    )

                    buf: list[str] = []
                    async for line in resp.aiter_lines():
                        if line == "":
                            # End of one event.
                            if buf:
                                evt = _parse_event(buf)
                                if evt is not None:
                                    # Advance last_seq from the event data.
                                    data = evt.get("data") or {}
                                    seq_val = data.get("seq") if isinstance(data, dict) else None
                                    if isinstance(seq_val, int) and seq_val > last_seq:
                                        last_seq = seq_val
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
