# Penny Agent Operating Contract

Penny is a local-first voice-capture pipeline. The canonical SQLite ledger is
written before transcription, routing, provider work, or downstream delivery.
Read [`README.md`](README.md) and the active documents under [`docs/`](docs/)
before changing the pipeline.

Keep audio, transcripts, manifests, tokens, provider responses, and personal
content local unless the user explicitly approves a narrow transfer. A local
receipt, archive copy, provider response, or downstream message proves only its
own boundary. Do not treat a passing test as proof of launchd registration,
macOS privacy permission, provider receipt, or downstream delivery.

## Foundational agent tooling (validated 2026-08-26)

Before any model or gateway request, run `git status --short --branch`, read the
ledger and current operational contract, and identify whether the task is
read-only, local mutation, or external delivery.

### Claude Code

```bash
claude
claude -p "<bounded task with no raw capture content>"
claude --permission-mode plan -p "<review or audit task>"
```

Use `claude --help` before version-sensitive options. Do not use
`--dangerously-skip-permissions` for routine work.

### Codex

```bash
codex
codex exec --sandbox read-only "<review or audit task>"
codex exec --sandbox workspace-write "<bounded implementation task>"
```

Do not use full host access or approval bypass for routine capture, transcript,
or outbox work.

### Antigravity (`agy`)

```bash
agy --mode plan --print-timeout=600s -p "<review or audit task>"
```

The installed CLI currently exposes `plan` and `accept-edits` modes. Do not
copy `fast` or `code` mode names without rechecking `agy --help`. Pass
`--effort` only when current model/agent compatibility is verified. Use
`-p` or `--print="..."`; never use bare `--print`.

### Gateway2000

```bash
g2k-check
g2k -p "<ordinary minimized task>"
g2k-bg -p "<bounded background task>"
g2k-sensitive -p "<explicitly authorized sensitive task>"
```

Do not send raw audio, transcripts, personal-provider content, or credentials
to Gateway2000 without explicit approval. `g2k-check` proves isolated client
readiness only; a gateway response does not prove Maya, Slack, Apple, Tasks,
Hermes, or backup delivery.

### Completion evidence

Report ledger state, local receipt/archive state, runtime state, provider state,
and each downstream delivery state separately. Stop when a required permission,
receipt, or downstream effect is not proven.

## Risk-tiered development workflow

This workflow is authoritative for changes made in Penny. Penny's local-first
durability, immutable-capture, ledger, receipt, backup, privacy, and
agent-invocation contracts take precedence over imported generic workflow
guidance, tool defaults, and convenience. The operational contracts in
`README.md` and `docs/reliability.md` remain authoritative for system
behavior. A conflicting generic instruction must be ignored, not blended into
the Penny contract.

Workflow artifacts include plans, designs, issue or review text, task prompts,
subagent prompts and results, logs, and receipts. They MUST contain metadata
only. Never persist raw capture content, transcripts, credentials, tokens,
provider payloads, or personal content in them. Use identifiers, bounded
states, hashes, counts, and redacted error classes instead.

### Tier 1: reliability and delivery changes

Use the full workflow for any change that can affect durable state, routing,
delivery, archive, backup, authentication, or transcription quality:

1. **Discover requirements.** Read the applicable README, reliability contract,
   active handoff, source, and tests. Record acceptance criteria, invariants,
   evidence boundaries, failure states, recovery/rollback limits, and required
   permissions. Do not copy private capture material into the record.
2. **Review the design.** Describe the data/state transition, interfaces,
   idempotency and failure behavior, privacy boundary, and observability
   before implementation. Obtain an independent design review and resolve or
   explicitly carry forward every material risk.
3. **Write an implementation plan.** Name the files/symbols, migration or
   compatibility work, behavioral checks, receipt/evidence needed, and
   rollback path. Split work into bounded, independently reviewable steps.
4. **Run red/green behavioral verification.** Add or use a focused behavioral
   test or bounded reproduction that demonstrates the required behavior failing
   before the fix, then implement the smallest complete change and demonstrate
   it passing. Verify boundaries, transitions, idempotency, and real failures;
   do not substitute source-text or mock-only assertions.
5. **Execute bounded subagent work.** High-risk changes require bounded
   subagent execution for implementation or review slices. Each subagent gets
   one narrow step, explicit files and acceptance criteria, no credentials or
   private content, no unrestricted host access, and no external delivery.
   Review its diff and output before accepting it. A subagent must not widen
   scope, invent fallback behavior, or treat a local test as runtime/provider
   proof.
6. **Review the result.** Independently compare the diff with the requirements,
   design, privacy rules, evidence boundaries, and existing invocation
   contracts. Reject missing callers, silent data loss, unbounded retries,
   leaked artifacts, and unproven external effects.
7. **Perform final verification.** Run the focused behavioral checks, relevant
   local trust checks, and any applicable suite. Report ledger, local
   receipt/archive, runtime, provider, and each downstream delivery state
   separately. A passing test never proves launchd registration, macOS privacy
   permission, provider receipt, or downstream delivery.

### Tier 2: documentation and mechanical changes

For wording-only documentation, formatting, comments, or other mechanical
changes with no behavior, contract, state, routing, or security impact, use a
lightweight path: inspect the target and its governing contract, make the
smallest change, and run the narrow consistency or formatting check. Full
requirements/design/plan/red-green/subagent ceremony is not required. The
metadata-only artifact rule, privacy boundaries, existing tool invocation
contracts, and final focused verification still apply. Reclassify as Tier 1
immediately if the change could affect runtime behavior or a contract.


## Canonical references

- [`README.md`](README.md) — pipeline authority and boundaries
- [`docs/reliability.md`](docs/reliability.md) — reliability contract
- [Claude Code CLI](https://code.claude.com/docs/en/cli-usage)
- [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)
- [Gateway2000 README](https://github.com/Khamel83/gateway2000/blob/main/README.md) and its `docs/RUNBOOK.md` are the route and client detail; `agy --help` is the Antigravity syntax source.
