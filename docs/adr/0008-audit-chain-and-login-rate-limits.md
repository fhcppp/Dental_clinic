# ADR 0008 — Keyed audit chain and local login throttling

Status: Accepted for development; NOT production-approved (2026-11-01).

## Context

Schema v2 contained plain `audit_events` without cryptographic chaining; failed
login attempts were not persisted. Both weaknesses are critical because this is
an offline clinical-record application.

## Decision

1. Use the existing `PRAGMA user_version` migrations, extend to **v3** without
   dropping tables, IDs or old records. Copy the old database before migrating;
   this is currently permitted **only in synthetic plaintext test mode**.
2. Add `audit_chain` with contiguous sequence numbers, `event_id`, prior MAC,
   HMAC-SHA-256 and key version. Every `audit_events` insertion executes an
   SQLite `AFTER INSERT` trigger inside the caller's `BEGIN IMMEDIATE`
   transaction. A missing/broken HMAC function aborts the entire transaction.
3. Canonical event serialization uses UTF-8 `json.dumps` with sorted field keys,
   `ensure_ascii=False`, compact separators, fixed schema id, sequence, event
   ID, UTC time, actor id, action, subject type/id and previous MAC. Genesis
   MAC is 64 ASCII zeroes. HMAC key derivation uses HKDF-SHA256 from the
   externally protected master key with the audit-specific context and version.
   The database never contains the audit key.
4. For reproducible synthetic test runs **only**, the explicitly insecure
   SQLite test mode uses a public constant test MAC key. This provides no
   security against an attacker and MUST NEVER be used with real records.
5. Backfill all previous events inside the v2→v3 migration and protect audit
   rows/chain entries from normal UPDATE/DELETE with triggers. Verify the chain
   on subsequent `initialize` calls. External signed/anchored checkpoints are
   still needed to detect complete tail truncation or total database rollback.
6. Add bounded `auth_login_attempts` records keyed by SHA-256 of normalized
   username, without storing entered passwords. After five failures, apply
   a temporary 15-second delay, then exponential increases capped at 15
   minutes. Attempts serialize through the same database write transaction.
   Successful login clears the attempt record. Unknown and known accounts
   return the same generic error and perform password-hash work. There is no
   permanent lockout. Admin recovery remains **not implemented**.

## Rejected alternatives

- Unkeyed hash chain inside editable SQLite: attackers could recompute it.
- Logging after business commit: audit failure could leave unlogged mutations.
- Permanent username locks: creates denial-of-service opportunities.

## Limitations / decision gate

Windows SQLCipher integration, production key protection and session-based
actor enforcement are not implemented. The first three requirements prevent
clinical deployment despite local migration/audit tests passing. Key rotation,
anti-rollback checkpointing and audited backup activation remain open.
