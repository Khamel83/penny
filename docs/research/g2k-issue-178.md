# Infra incident: penny / penny.doctor-readiness — issue #178

Incident marker: `infra-incident:70f416e08012bef7550c690ec152cade6eac6763c3ce1d555d704a420f2dfac8:9`

## Blocker

No sanitized failure metadata is available in this worktree or its history:
observed Doctor component/reason codes, timestamps, deployed source revision,
or the catalog declaration behind the repeated fresh failures are absent.
The literal check id `penny.doctor-readiness` is a runtime observation, not a
build/test, and repository CI has no doctor/readiness job.

`_default_probe_drop` already treats a missing database, a missing
`drop_deliveries` table, and `DatabaseError` as non-failures; all 38
`tests/test_doctor.py` cases pass. No failing or skipped test identifies a
regression, so no source repair can be selected without the specific failed
check output.

## Required to proceed

Human/Infra must supply sanitized metadata for the three fresh failures
(component, reason code, timestamp, observed deployed revision), the matching
catalog declaration, and the permitted deployment boundary. Then reproduce
the specific failed check locally before selecting a repair.

No source, configuration, credential, or runtime mutation performed.
Refs #178
