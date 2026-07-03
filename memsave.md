---
name: memsave
description: Session close — draft lessons from corrections, batch-review pending/stale, call wrap_session.
---

# /mnemo:memsave — Session Close

Run this at the end of a session to capture what was learned.

## Procedure

1. **Scan the conversation for corrections** — any time the user said "no", "wrong", "don't do that", or corrected your output.
   For each correction, call `draft_lesson()` — the server handles dedup.
   Never call `save_memory(type="anti-pattern")` — use `draft_lesson` instead.

2. **Judge whether retrieved memory materially helped this session** — did anything
   surfaced at session start or via `get_memories`/`search_wiki` actually change what
   you did (avoided a repeat mistake, gave you the right file/pattern/context faster)?
   Answer honestly; "n/a, nothing was retrieved" is a legitimate `no`. This is a
   self-report signal, not a graded test — don't strain for a `yes`.

3. **Call `wrap_session`** with a brief summary of what was accomplished, plus
   `memory_helped: true/false` from step 2 (omit only if truly undecidable — e.g.
   a near-empty session with no retrieval at all).
   The server auto-promotes up to 20 pending lessons that pass the quality gate
   (directive ≥ 30 chars, rationale ≥ 20 chars, imperative verb for claude_md,
   trigger present for jit_hook). The response includes `lesson_sweep.promoted`
   and `lesson_sweep.kept_pending_reasons`.

4. **Report** — N lessons drafted, N auto-promoted (from `lesson_sweep.promoted`),
   session wrapped. If `lesson_sweep.kept_pending > 0`, check
   `lesson_sweep.kept_pending_reasons`:
   - `missing_specific_trigger`: lesson from a correction has no safe trigger
     pattern — mention the directive so the user can add a trigger manually.
   - `too_short_directive` / `too_short_rationale`: draft is too vague to enforce.
   - Other reasons: surface the count only, no action needed.

## Rules

- Never skip `wrap_session` — it feeds the RL loop.
- Never call `save_memory(type="episode")` directly — that's `wrap_session`'s job.
- Never call `save_memory(type="anti-pattern")` — use `draft_lesson` instead.
- Zero corrections is a positive signal — still wrap.
