# Testing

Run the dependency-free backend suite from the repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Windows PowerShell equivalent: `$env:PYTHONPATH='src'; py -m unittest discover -s tests -v`.
CI installs the package and optional dev tools and runs Ruff and mypy.

Current integration tests use a unique temporary directory and synthetic
patient values. They verify migration idempotency/version rejection, foreign
keys, patient validation, parameterized SQL, booking overlap constraints,
boundary times, timezone normalization, cancel/reschedule/deactivate behavior,
FDI rules, transaction rollback, audit record cardinality and a two-thread
booking race. They do **not** test production security, encryption, access
control, Windows UI, regulatory compliance or recovery from disk failure.

## Development snapshot 2026-11-01

Synthetic Linux tests: 65 unittest and 65 pytest passed (14 pytest subtests),
Python 3.13.5. Ruff/mypy unavailable (DNS prevented installation); Windows
verification, SQLCipher tests and real clinical acceptance NOT EXECUTED.
See PRODUCTION_ACCEPTANCE_REPORT.md for acceptance-level evidence.
