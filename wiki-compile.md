---
name: wiki-compile
description: Manually trigger wiki compilation for all configured wikis, compiling raw/ entries into wiki/ pages.
---

# /mnemo:wiki-compile — Compile Wikis

Run the auto-compile pipeline on demand instead of waiting for the daily 07:00 timer.
Processes `raw/auto/` and `raw/` entries → updates `wiki/` pages → uploads to Mnemo.

## Procedure

1. Run the compile script:

   ```bash
   bash ~/.local/bin/compile-wiki-auto.sh
   ```

   This discovers all configured wikis via `mnemo_wiki_resolver.py discover` and
   runs `claude -p ~/.claude/skills/compile-wiki/SKILL.md` for each wiki that has
   pending drafts in `raw/auto/`.

2. If `~/.local/bin/compile-wiki-auto.sh` is missing (new install), fall back to
   per-wiki compile:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/mnemo_wiki_resolver.py" discover | while read wiki_root; do
       [ -d "$wiki_root" ] || continue
       count=$(find "$wiki_root/raw/auto" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l)
       [ "$count" -gt 0 ] || continue
       cd "$wiki_root"
       claude -p ~/.claude/skills/compile-wiki/SKILL.md
   done
   ```

3. After the compile script exits, report:
   - Which wikis were compiled
   - Pages created and updated
   - Whether Mnemo upload succeeded
   - Log location: `~/.local/share/compile-wiki-auto/`

## Notes

- If `raw/auto/` is empty in all wikis, the script exits with "No pending drafts" —
  this is normal. Run `/mnemo:wiki-save` first to queue an entry.
- The daily timer (systemd / cron / launchd / Task Scheduler) also calls this script
  automatically at 07:00.
