# Backup and restore design — planned

There is **no implemented backup or restore feature**. Do not rely on copying
a live SQLite `.sqlite3` file while writers may be active. The future backup
service should use SQLite's online backup API for a consistent snapshot,
then authenticated encryption with a managed key, tamper detection and
rotation. Never upload backup files to GitHub.

Future restore must verify authentication tags, schema version, snapshot
integrity, available disk space and clinic identity before replacing data.
Require an operator confirmation, maintain a known-good recovery snapshot and
perform scheduled restoration drills in an isolated environment using
synthetic records. Document recovery-point and recovery-time objectives with
the clinic before deployment.
