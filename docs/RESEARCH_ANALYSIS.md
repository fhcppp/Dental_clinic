# Research and reference analysis

## Evidence boundary

Only project specification sections **15–19** were provided for this milestone.
Sections 1–14, including any named reference dental applications, were not
available. Accordingly, **no claim is made that reference applications have
been researched, replicated or licensed**. Obtain the missing requirements
before committing to screen workflows, billing rules or local regulations.

## Engineering considerations

A single-workstation offline dental system needs durable local persistence,
clearly scoped patient/appointment workflows, explicit data security, backup
rehearsals, predictable Windows installation, and verifiable clinical UX.
Compare any future reference applications in a requirements matrix covering
appointment conflicts, FDI dental charts, treatment plans, invoicing,
role-based access, multilingual support, migration/export, and licensing.
Do not copy third-party copyrighted UI/artwork or proprietary data formats.

## Decisions for milestone 1

Use Python standard library and SQLite to validate a small, transparent core
and its constraints. Defer PySide6, payments, clinical data import, encryption
and packaging until the full requirements and security decisions are approved.
