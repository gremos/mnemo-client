---
name: memload
description: Load session context — recent decisions, active lessons, known context. Run after /compact or when context is stale.
---

# /mnemo:memload — Session Brief

Reload Mnemo context into the conversation. Use after `/compact`, or when context feels stale mid-session.

## Procedure

1. **Derive a task focus** from the current conversation: 3–8 keywords describing what
   this session is about (the user's request, the file/subsystem in play, the error being
   chased). Example: `"agora enricher google places rate limit"`.
   - If there is no task yet (cold session start, nothing said), skip the focus and use
     browse mode (omit `query`) — there is nothing to be relevant to.

2. Retrieve Tier-2 context for the current project. Pass the task focus as `query` so the
   brief is **relevant to the task**, not just globally important+recent. Without a query,
   `get_memories` ranks by importance+recency only (browse) and misses the memories that
   actually matter for today's work:
   ```
   get_memories(query="<task focus>", memory_type="decision", limit=5)
   get_memories(query="<task focus>", memory_type="note", limit=5)
   get_memories(memory_type="episode", limit=3)   # episodes: keep recency-first (last sessions)
   ```
   Cold start (no focus): drop the `query` argument from the decision/note calls.

3. Retrieve active lesson directives:
   ```
   get_active_lessons(project="<current>")
   ```
   Returns a list of `{directive, rationale, delivery, validated}` — show the `directive`
   only, one line each. Surface `validated` guardrails first (they are enforced).

4. Present as a **Session Brief** under 1500 tokens:
   - **Active lessons** — imperative one-liners (these fire via hook too, but seeing them helps)
   - **Recent decisions** — what was decided, relevant to the task focus
   - **Context** — relevant notes and recent episode summaries

## Why the query matters

`get_memories` blends FTS + vector relevance only when a `query` is passed; with no query it
falls back to importance+recency. In a large project (hundreds of memories) the task-blind
brief surfaces generically-important memories and buries the few that match today's subtask.
Passing the task focus is the difference between a relevant brief and a generic one.

## When to use

- After `/compact` — context was cleared, memories need reloading
- When switching focus to a different area of the project (re-derive the task focus)
- When you suspect stale context (e.g., acting on outdated assumptions)
- The SessionStart hook runs this automatically — don't run manually at session start unless recovering from a problem.
