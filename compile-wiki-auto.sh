#!/usr/bin/env bash
# Compile wikis that have pending auto-drafted entries in raw/auto/.
# Skips any wiki with no pending drafts — no API cost on empty runs.
# Triggered daily by systemd user timer compile-wiki.timer.

set -euo pipefail

CLAUDE="${HOME}/.local/bin/claude"
SKILL="${HOME}/.claude/skills/compile-wiki/SKILL.md"
LOG_DIR="${HOME}/.local/share/compile-wiki-auto"
DATE=$(date +%Y-%m-%d)

mkdir -p "$LOG_DIR"

WIKIS=(
    "${HOME}/Documents/code/Personal/wiki"
    "${HOME}/Documents/code/XO/wiki"
)

compiled=0
for wiki_root in "${WIKIS[@]}"; do
    [[ -d "$wiki_root" ]] || continue
    auto_dir="${wiki_root}/raw/auto"
    [[ -d "$auto_dir" ]] || continue
    count=$(find "$auto_dir" -maxdepth 1 -name "*.md" | wc -l)
    (( count > 0 )) || continue

    wiki_name="$(basename "$(dirname "$wiki_root")")-wiki"
    log="${LOG_DIR}/${DATE}-${wiki_name}.log"
    echo "[$(date -Iseconds)] Compiling ${wiki_name} (${count} pending draft(s))..." | tee -a "$log"

    cd "$wiki_root"
    if "$CLAUDE" -p "$SKILL" >> "$log" 2>&1; then
        echo "[$(date -Iseconds)] Done: ${wiki_name}" | tee -a "$log"
        (( compiled++ )) || true
    else
        echo "[$(date -Iseconds)] FAILED: ${wiki_name} — see ${log}" | tee -a "$log"
    fi
done

if (( compiled == 0 )); then
    echo "[$(date -Iseconds)] No pending drafts in any wiki — nothing compiled."
fi
