# Factory voice handoff

## Factory voice handoff — implementation authorized November8

Owner authorized end-to-end implementation, deployment and validation across
Penny, Drop and Factory. Native owner order is [INF-334](https://factory.khamel.com/INF/issues/INF-334),
source implementation [INF-335](https://factory.khamel.com/INF/issues/INF-335).
Preserve existing Penny capture/transcription/durable Drop outbox and Apple
Notes/Reminders behavior. Maya remains an independent store-only reader.
Factory Coordinator will own interpretation, action delegation, status and outputs;
Drop remains immutable capture/archive/transport. Do not replay historical notes.
Keep producer_id/transcript_id, transcript SHA and Drop UUID on the native order;
Paperclip allocates its own ticket number. Retry must return the same order.
Source identity and requested work remain distinct from completion receipts.

Goal is fewer running systems: prefer existing scheduling/event transport for a
finite connector that replaces Dispatch voice triage rather than a second model
router/daemon. Operator verified old OCI triage timer enabled, cursor2027 and
nine unresolved ownership children; preserve them separately at cutover. Current
runtime intake has NOT switched; no historical replay or service retirement done.
Penny current /ready ready atb4181aa; this is readiness, not Factory end-to-end proof.
Root owns live credentials/cutover/deployment; implementation agent owns source.

Root isolated this work under .worktrees/voice-factory-integration (Penny) and
Drop .worktrees/voice-integration to preserve runtime and peer checkouts. Retain
until reviewed source/merge/deployment/acceptance; clean up only after checking
unpublished files and linked runtime paths. Next: qualify source contract and
replay tests, then install the exact reviewed source and prove capture->Drop->
native task->useful output with independently visible status/notification.
