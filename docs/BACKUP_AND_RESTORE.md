# Encrypted backup and restore — development-only

`BackupService(db, encrypted_attachment_directory).create(path, passphrase)` creates a consistent SQLite snapshot through SQLite's online backup mechanism, packages encrypted attachments and a SHA-256 manifest, then AES-256-GCM encrypts the archive with a key derived from the supplied passphrase via scrypt. Passwords should be long and stored securely outside the clinic application. No network is used.

`BackupService.verify(path, passphrase)` checks AEAD authentication, manifest hashes, schema version and SQLite integrity in a temporary directory. `BackupService.restore_to(path, passphrase, destination_db=new_db, destination_attachments=new_dir)` restores into **new, non-existing destinations** after verification. It deliberately refuses to overwrite the active clinic database. Do not attempt an in-place restore while the application is running.

Current limitations: automatic schedules, retention, Windows DPAPI key handling, true atomic cutover of DB+attachments, backup-size scalability, and encrypted local database-at-rest remain unfinished. A failure during the two final filesystem moves may require manual review. Backups are limited to 128 MiB in this prototype; do not treat this as a production archive engine.

## Migration snapshots are not encrypted clinical backups

The migration-specific `.before-schema-*` files protect against schema transition failure in synthetic/test databases. They do **not** implement safe encrypted production backup, periodic scheduling, retention or staged activation. Never use this plaintext path with real patient data.
