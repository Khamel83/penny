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

## Reusable macOS app skills

For Notes tasks, read [apple-notes](.agents/skills/apple-notes/SKILL.md); for
Reminders tasks, read [apple-reminders](.agents/skills/apple-reminders/SKILL.md).
For another project's Mac access setup or choosing a computer-use route, read
[apple-apps](.agents/skills/apple-apps/SKILL.md). For Apple Events, denied access
or uncertain delivery, read
[apple-effects-reliability](.agents/skills/apple-effects-reliability/SKILL.md).
These skills keep each project's caller, target and receipts separate. Penny
continues to use its existing Apple-effect ledger and transport.

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

Keep one current checkpoint and replace superseded facts. Keep each long
writeup in a dated history/evidence file and link it from the relevant record.
For document-size warnings or compaction, follow the
[working-document contract](https://github.com/Khamel83/docs/blob/main/templates/WORKING_DOCUMENTS.md).
Preserve previous bytes, active decisions and every unresolved task.

A change is not done until it is deployed and verified. If the repository has
a deploy command or automation, run it (or confirm it ran) and check the
result. Registration steps the deploy depends on (for example a consumer list
or catalog entry) are part of the change. Never leave a "remember to run X"
step for the owner; if something truly needs the owner, write it in
`HANDOFF.md` as a blocker with the exact command.

infra owns active repository membership and explicit PR merge exclusions.
Janitor's standing worker merges every PR type after the latest trusted,
non-dismissed OCI reviewer Bot PASS for the exact current commit. A stale,
superseded or contradictory PASS does not qualify. It uses GitHub's normal merge endpoint
and records independent readback. Labels, authors and changed paths do not
restrict eligibility. infra owns improvements to the reviewer and PASS
process. Verify the merged PR and its merge receipt before reporting completion.
<!-- janitor:end:working-docs -->
<!-- janitor:begin:fresh-source -->
## Start from the current remote branch

At the start of repository work, run `git fetch origin` and discover the actual
default branch with `git ls-remote --symref origin HEAD`; do not assume its name.
Start each new branch or
worktree from the fetched `origin/<default>` commit. If fetch fails, report
that source freshness is unknown before starting new changes. Preserve a dirty,
diverged, or active checkout; use a separate worktree for new work instead of
moving its branch or files. Check the fetched source commit again before a
release or a claim that source is current.
<!-- janitor:end:fresh-source -->
<!-- janitor:begin:global-work -->
## Source records for the global work view

This repository owns its work in TODO.md and GitHub issues and pull requests.
The global view reads the default branch and native GitHub records; it does
not own another task list. Keep completed evidence with its source links.
Use stable task IDs when available. Explicit GitHub links identify related
records; matching text alone does not establish a dependency or completion.
A pull request that finishes a TODO line puts `Closes-TODO: <the line's text>`
in its body; a TODO line that gets its own issue or PR carries that full URL.
After merge, Janitor ticks such lines and appends the evidence link.
Development progress and runtime acceptance are separate facts. Missing or
stale source evidence stays unknown. Generated summaries must not become new
copies of the underlying tasks. Janitor distributes this contract; Infra's
catalog defines project membership and lifecycle.
<!-- janitor:end:global-work -->
