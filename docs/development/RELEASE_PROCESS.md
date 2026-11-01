# Release process — future gate

1. Establish a complete requirements baseline with the clinic and reviewers.
2. Close critical privacy/security gaps and threat-model findings.
3. Verify migration upgrades, offline behavior, concurrent edits and complete
   backup/recovery on a clean Windows system.
4. Obtain clinical/operational acceptance and check any applicable legal
   requirements before handling real data.
5. Create reproducible artifacts and signed installers, document checksums,
   attach only public-safe binaries, then tag the tested commit.
6. Have an authorized maintainer approve and publish the release.

`v0.1.0` in project metadata describes an internal prototype milestone, **not**
a production release. No stable Git tag, installer or public GitHub release is
created as part of this work.

## Production release gate

Do not tag, release or merge based solely on passing Linux tests. The critical
requirements listed in PRODUCTION_READINESS.md must be closed and verified.
