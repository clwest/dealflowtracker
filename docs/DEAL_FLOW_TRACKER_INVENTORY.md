---
title: "Deal Flow Tracker Platform Inventory"
status: stub
generator: <wire this to your stack's inventory command>
command: <e.g. python manage.py generate_platform_inventory>
---

# Deal Flow Tracker Platform Inventory

> **This document is regenerated.** Do not hand-edit — once the generator is
> wired up, run it to refresh. Until then, this is a stub placeholder.
> Last regenerated: _stub (generator not yet implemented, 2026-05-21)_.

Companion to [`DEAL_FLOW_TRACKER_WHAT_IT_IS.md`](DEAL_FLOW_TRACKER_WHAT_IT_IS.md) —
the narrative doc. This file is the runtime-truth complement.

---

## Executive Summary

| Metric | Value | Source |
|---|---|---|
| TBD | _stub_ | <registry / loader> |

<Populate once the generator script exists. Each row should cite where the
value comes from (function, table, config key) — never hand-maintained.>

---

## Table of Contents

Sections to populate (adapt to your stack):

1. Agents / Services
2. Database Models
3. API Routes
4. Background Tasks
5. Scheduled Jobs
6. Integrations
7. LLM Providers
8. Infrastructure (workers, queues, DBs)
9. Code Statistics
10. Doc-vs-Reality Verifier State

---

## Verifier State (placeholder)

Once `verify_doc_claims` is wired up, the final section of this inventory
should embed the drift rollup:

| Doc | OK | Drift | Error |
|---|---|---|---|
| _(nothing registered yet)_ | 0 | 0 | 0 |

Full drift list: `python manage.py verify_doc_claims --only-drift`.

---

*Stub generated 2026-05-21. Replace this content as soon as the runtime
generator exists — the pattern only pays off once regeneration is automated.*
