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

## Canonical references

- [`README.md`](README.md) — pipeline authority and boundaries
- [`docs/reliability.md`](docs/reliability.md) — reliability contract
- [Claude Code CLI](https://code.claude.com/docs/en/cli-usage)
- [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)
- [Gateway2000 README](https://github.com/Khamel83/gateway2000/blob/main/README.md) and its `docs/RUNBOOK.md` are the route and client detail; `agy --help` is the Antigravity syntax source.
<!-- janitor:begin:capability -->
## Shared agent capability: g2k

g2k is the shared remote model-routing and GitHub issue-to-PR capability for
this workspace.

A model may be running locally on the Mac or another machine, but g2k's
provider access, unattended workers, routing, state, and credentials live on
the OCI VM. Local machines are callers or observers, not alternate g2k homes.

Use g2k/OMP when available instead of creating another provider integration.
Use GitHub issues and pull requests for durable work. Do not assume that local
provider credentials, filesystem state, or a local g2k daemon exists. See
`INFRA.md` for the machine-specific access path and boundaries.
<!-- janitor:end:capability -->
<!-- janitor:begin:working-docs -->
## Keep the working docs current

Update these files whenever they become wrong, not on every turn, and commit
them with the work they describe:

- `TODO.md`: when you start, finish, add, or drop a task. Mark finished items
  `[x]` with evidence; strike dropped items with a reason.
- `CONTEXT.md`: when the owner makes a decision or the verified state changes.
- `HANDOFF.md`: before you stop or hand off: what is done, what is in flight,
  the next step, and the commands that recheck it.
- `INFRA.md`: when a host, service, port, credential location, or deploy path
  changes.

A change is not done until it is deployed and verified. If the repository has
a deploy command or automation, run it (or confirm it ran) and check the
result. Registration steps the deploy depends on (for example a consumer list
or catalog entry) are part of the change. Never leave a "remember to run X"
step for the owner; if something truly needs the owner, write it in
`HANDOFF.md` as a blocker with the exact command.
<!-- janitor:end:working-docs -->
