# ADR 0001 — Backend-first modular Python architecture

**Status:** Accepted for development prototype (2026-11-01)

**Context:** The supplied specification mandates a testable backend before UI.
No complete UX specification or reference-application list was provided.

**Decision:** Keep domain validation in Python services using immutable models
and one SQLite gateway. No UI or web server is introduced in this milestone.

**Consequence:** Service behavior is testable without a Windows environment.
Future PySide6 screens must depend on services rather than direct SQL queries.
