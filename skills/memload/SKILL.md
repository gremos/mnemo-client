---
name: memload
description: Load session context — recent decisions, active lessons, known context. Run after /compact or when context is stale.
---

# /mnemo:memload — Session Brief

Reload Mnemo context into the conversation. Use after `/compact`, or when context feels stale mid-session.

## Procedure

1. Retrieve Tier-2 context for the current project:
   ```
   get_memories(memory_type="decision", limit=5)
   get_memories(memory_type="episode", limit=3)
   get_memories(memory_type="note", limit=5)
   ```

2. Retrieve active lesson directives:
   ```
   get_active_lessons(project="<current>")
   ```
   Returns a list of `{directive, rationale, delivery}` — show the `directive` only, one line each.

3. Present as a **Session Brief** under 1500 tokens:
   - **Active lessons** — imperative one-liners (these fire via hook too, but seeing them helps)
   - **Recent decisions** — what was decided
   - **Context** — relevant notes and episode summaries

## When to use

- After `/compact` — context was cleared, memories need reloading
- When switching focus to a different area of the project
- When you suspect stale context (e.g., acting on outdated assumptions)
- The SessionStart hook runs this automatically — don't run manually at session start unless recovering from a problem.
