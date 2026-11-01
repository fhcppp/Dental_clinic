# Windows desktop packaging — NOT IMPLEMENTED

The backend is a standard-library Python package, not a `.exe`. The planned
Windows interface is PySide6, with an independently reviewed installer,
application manifest, code signing, secure database-data directory, access
controls and repeatable build scripts. Avoid bundling private keys or real
patient databases. Runtime operation must be independent of GitHub.

Release verification will need a clean Windows VM, offline startup and
functional test, schema migration test, backup/restore test, permissions and
storage verification, dependency license/SBOM review and signature validation.
No Windows build has been attempted or validated in this milestone.
