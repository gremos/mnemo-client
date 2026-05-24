---
name: wiki-save
description: Save a curated wiki entry for the current session to the nearest configured wiki.
---

# /mnemo:wiki-save — Save Session to Wiki

Run this to write a human-curated wiki entry from the current session.
The entry lands in `raw/` (not `raw/auto/`) — it is higher-confidence than
machine-generated drafts and will be given priority in the next compile.

## How routing works

The target wiki is the **nearest** `.mnemo-wiki` marker found by walking up from
the current working directory (`cwd`). Example:

| cwd | .mnemo-wiki found at | Routes to |
|---|---|---|
| `~/Documents/code/XO/agora-poc/` | `~/Documents/code/XO/.mnemo-wiki` | XO wiki |
| `~/Documents/code/XO/Endoscopiki/` | `~/Documents/code/XO/Endoscopiki/.mnemo-wiki` | Endoscopiki personal wiki (if marker exists there) |
| `~/Documents/code/XO/Endoscopiki/` | `~/Documents/code/XO/.mnemo-wiki` (fallback) | XO wiki |
| `/tmp/scratch/` | none found | Default personal wiki (`~/Documents/Mnemo/wiki/`) |

**If a marker is found but invalid** (broken path or no `SCHEMA.md`) the write is
aborted — no silent leak into a different wiki.

## Procedure

1. Synthesize a concise wiki entry from this session. Include:
   - **What was accomplished** (outcome in 1–2 sentences)
   - **Key decisions** (rationale, alternatives rejected)
   - **Anti-patterns found** (wrong commands tried; correct form)
   - **Commands / patterns that worked** (reusable knowledge)
   - **What to do next** (if applicable)

   Length: 100–400 words. No credentials, IPs, tokens, or secrets.

2. Determine the project slug: use the Mnemo project name for this cwd, or the
   repo/directory name if unknown. Lowercase, hyphenated (e.g. `agora-poc`).

3. Write the body to a temp file and call:

   ```bash
   cat /tmp/wiki-body.txt | python3 "${CLAUDE_PLUGIN_ROOT}/mnemo_wiki_write.py" \
       --cwd "$PWD" \
       --project "<slug>" \
       --slug "<slug>" \
       --source user \
       --title "<short title>"
   ```

   If the command exits 1, the sanitizer blocked the write — the body contained a
   secret or credential. Remove the offending content and retry.
   If it exits 2, there is a configuration problem (report to the user).

4. Report: path where the file was written, which wiki it targeted, and the
   log.md entry that was appended.

## Rules

- Write to `raw/` (not `raw/auto/`) — this is a curated entry.
- Never include secrets (the sanitizer enforces this, but do not try).
- If the session had no meaningful outcome (exploration only, no decisions,
  no anti-patterns), say so and skip the write — noise degrades the wiki.
- Do not call `wrap_session` or `save_memory` from this command — those are
  handled by `/mnemo:memsave`.
