# ADR 0005 — Explicit clinic configuration and conservative defaults

Status: Accepted for design / partially integrated. Date: 2026-11-01.

Clinic timezone and currency **have no defaults**: an administrator must explicitly choose a validated IANA timezone and supported currency during first setup. Never silently reuse the OS timezone. `ClinicSettings` models these decisions, but durable first-run setup and authorization remain pending. Supported currency precision is pinned explicitly in `settings.MINOR_UNITS`; unknown codes are rejected, not interpreted as two decimals. Decimal-to-integer minor units uses `ROUND_HALF_UP` for the current supported catalog; tax/rounding policies need separate evaluation.

Defaults: password minimum 12 characters; session idle timeout 15 minutes; absolute lifetime 8 hours; 5 failed login attempts followed by progressive delays (NOT IMPLEMENTED); configurable attachment limit initially 25 MiB; backup retention target 7 daily and 4 weekly (NOT IMPLEMENTED). The current `ClinicSettings` enforces the numeric defaults but is not yet persisted; the attachment vault still enforces its legacy 16 MiB cap. Do not claim the runtime uses all of these settings.

Permission policy: single centralized deny-by-default matrix is required, with opt-in administrator grants for dental assistants. The current legacy services still trust caller-supplied actors: production use is forbidden until Phase 2 completes. Progressive throttling will avoid permanent lockout or account-lockout denial of service by using bounded per-account and per-device delays, logging failed attempts, and protected administrator recovery. These are planned controls, not deployed controls.
