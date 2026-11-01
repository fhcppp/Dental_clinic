# ADR 0004 — Strictly offline runtime core

**Status:** Accepted for prototype (2026-11-01)

**Context:** A Windows workstation must remain functional without Internet.

**Decision:** Services only use local SQLite and standard library; no API
calls, cloud synchronization or analytics are included. CI and GitHub remain
development tools, not runtime dependencies.

**Consequence:** No remote recovery, synchronization or software update
mechanism exists yet. Windows runtime offline validation is required once the
UI and installer exist.
