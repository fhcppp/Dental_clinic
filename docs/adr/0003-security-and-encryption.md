# ADR 0003 — Block real-data use until security design is implemented

**Status:** Security gate pending (2026-11-01)

**Context:** Patient and tooth-state data are sensitive, and offline does not
mean secure. A caller-provided audit actor is not authentication.

**Decision:** Build synthetic-only backend first; do not introduce a hardcoded
encryption key or claim database encryption. Defer selection of a reviewed
crypto library/key custody model until requirements and threat review.

**Consequence:** Clinical deployment is prohibited in this milestone.
Authentication, RBAC, encrypted storage, integrity-protected audit and secure
backup remain blockers, tracked in the security docs.
