# Production readiness — NO-GO (2026-11-01)

**NO-GO: never store real patient data in this milestone.** This is not a
production-ready clinical backend. The backend intentionally refuses to open
plain SQLite without `allow_insecure_plaintext_for_tests=True`.

## Confirmed blockers

1. A maintained, distributable Windows SQLCipher-compatible Python build has
   not been installed or validated. Encryption at rest, SQLite temporary files,
   WAL, wrong-key tests and packaging are **NOT DONE / UNVERIFIED**.
2. All legacy patient, clinical, financial, imaging and reporting service methods
   still expose direct unauthenticated entry points and caller-chosen actor IDs.
   Full service-level RBAC and trusted actor binding are **NOT DONE**.
3. DPAPI key protection is only mock-tested on Linux. Actual Windows DPAPI,
   key recovery, filesystem ACLs, clean install and package tests are UNVERIFIED.
4. The v3 keyed audit chain is an improvement, but its test-mode key is public,
   it has no independently anchored anti-truncation checkpoint, and the complete
   clinic workflow is not yet protected by authenticated actor contexts.
5. Atomic full dataset backup restore, offline scheduling, key rotation and
   disaster recovery on replacement Windows systems are unfinished.
6. Currency is explicitly required by the newer `FinanceService` path and
   invoice minor units respect that configuration; the older clinical
   `money_minor` helper is still fixed to two decimals and clinic settings are
   not persisted as required. These paths must be unified.
7. Ruff and mypy were not available locally; an attempted installation failed
   due to DNS resolution. No new GitHub CI run or Windows validation was done.

## Evidence

Local Linux Python 3.13.5, synthetic fixtures only:

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
```

Results at this checkpoint: **65/65 unittest**, **65/65 pytest (14 subtests)**,
compilation passed. This evidence is *not* Windows or security certification.
See `docs/PRODUCTION_ACCEPTANCE_REPORT.md` for the separate requirement matrix.

## External gates

Real Windows x64 SQLCipher/DPAPI and recovery tests, clinic user acceptance,
independent security review and qualified privacy/regulatory assessment are
required before a release. Do not merge draft PR #1 or build the UI as a
substitute for resolving backend blockers.
