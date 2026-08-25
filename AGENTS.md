# Agent Instructions

## Antigravity CLI (`agy`) invocation contract

When using `agy`, treat target selection, execution mode, and flag syntax as separate compatibility axes.

- Always deliver prompts with `-p "..."` or `--print="..."`; never use bare `--print`.
- Always give `--print-timeout` an explicit unit, e.g. `600s` or `15m`; bare integers are invalid.
- Pass `--effort low|medium|high` only when the selected `gemini-*` model supports it. Omit it for Claude, GPT, and custom agents unless current help explicitly says otherwise.
- Use `--mode plan` for read-only audits, reviews, and design validation. Use `--mode code` only when interactive implementation writes are intended.
- Before invoking, verify the selected model/agent and supported flags when compatibility is uncertain; do not copy a recipe across targets blindly.
- For persistent review or audit trails, capture stdout to an explicit artifact path.

If the command is part of a script or wrapper, preserve these checks at the invocation boundary and fail closed on invalid combinations.
