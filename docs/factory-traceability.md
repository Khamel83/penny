# Native Factory traceability — INF-335

Contract qualification only. The existing penny.transcript.v1 builder already
serializes persisted producer_id (installation UUID), transcript_id (positive
ledger integer), transcript_sha256 (SHA256 of exact UTF-8 transcript), recorded_at,
quality_status, historical and notify_slack followed by two newlines and original
text. No metadata or pipeline redesign is necessary. Factory records hash version
sha256:utf8-exact:v1 alongside that schema; Drop's accepted envelope SHA256 is
separate from the transcript hash. The original IDs must never be replaced with
the allocated Drop UUID or native Factory identifier.

Penny's durable outbox/storage receipt is capture acceptance. The native parent
order and child/result documents establish downstream work and completion.
Factory uses one source key per producer_id/transcript_id, excluding hash so an
edited transcript causes visible version conflict rather than a duplicate order.
Original transcript text and immutable Drop link/hash remain in the native task.
No150-word skip applies to Factory. Notes, actions and concepts need no project.

Existing Apple Notes/Reminders effect ledgers and Maya store-only reader remain
untouched. Factory may not replay Penny effects. Existing uncertain/failed outbox
rows remain uncertain/failed until their established reconciliation or owner
disposition; no automatic backfill, reset or historical execution is introduced.

Operator supplies the persisted installation UUID, actual future UTC cutoff and
latest Drop sequence to the Factory runtime config only; never reconstruct or
rotate producer identity. Runtime stays Mac ready b4181aa as supplied in task,
not freshly verified here. No Mac deployment is required for this contract-only
change. Keep captures, credentials, audio and private records out of PR evidence.

Source inspection: transcript_log.py build_drop_payload, queue_drop_delivery;
drop_delivery.py payload_headers, validate_receipt and bounded existing outbox.
Tests remain tests/test_drop_outbox.py and tests/test_drop_delivery.py. This
checkout lacks pytest, so those existing suites have no new local verdict.
Factory's provider-free fixtures exercise the same v1 shape, short Unicode text,
original IDs/hashes and historical/quality/version refusals. No source-only MVP
completion claim. Operator must qualify real capture -> durable Drop -> native
parent/children/result, actual model override readback and unchanged Apple/Maya
behavior. See Factory docs/integration/VOICE_INTAKE.md for activation and rollback.

Retain INF-335-penny for review; no peer cleanup.
