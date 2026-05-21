#!/usr/bin/env bash
# mnemo Auto-Wrap Stop Hook
#
# Fires at the end of every Claude session. If the session retrieved memories
# but was never wrapped, spawns mnemo-mend-bg.py in the background to call
# Azure OpenAI for extraction and wrap_session — without blocking the user.
#
# Config: reads CLAUDE_PLUGIN_OPTION_* env vars set by the plugin, with
# fallback to ~/.claude/skills/mnemo/.env and ~/.mnemo.env for legacy installs.

set -euo pipefail

INPUT=$(cat)

# 1. If hook already fired this stop cycle, allow exit unconditionally.
HOOK_ACTIVE=$(echo "$INPUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print('1' if d.get('stop_hook_active') else '')" \
    2>/dev/null || echo "")
[[ -n "$HOOK_ACTIVE" ]] && exit 0

# 2. Extract session_id and cwd from hook payload.
SESSION_ID=$(echo "$INPUT" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('session_id',''))" \
    2>/dev/null || echo "")
[[ -z "$SESSION_ID" ]] && exit 0

CWD=$(echo "$INPUT" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('cwd',''))" \
    2>/dev/null || echo "")

# 3. Resolve config: plugin env vars > legacy env files.
MNEMO_API_KEY="${CLAUDE_PLUGIN_OPTION_API_TOKEN:-${MNEMO_API_KEY:-}}"
MNEMO_BASE="${CLAUDE_PLUGIN_OPTION_SERVER_URL:-}"

if [[ -z "${MNEMO_API_KEY:-}" ]]; then
    for _env_path in "${HOME}/.claude/skills/mnemo/.env" "${HOME}/.mnemo.env"; do
        if [[ -f "$_env_path" ]]; then
            # shellcheck disable=SC1090
            source "$_env_path"
            break
        fi
    done
    MNEMO_API_KEY="${MNEMO_API_KEY:-${MNEMO_HOOK_KEY:-${MNEMO_ADMIN_TOKEN:-}}}"
fi
[[ -z "${MNEMO_API_KEY:-}" ]] && exit 0

if [[ -z "${MNEMO_BASE:-}" ]]; then
    MNEMO_HOST="${MNEMO_HOST:-localhost}"
    MNEMO_PORT="${MNEMO_PORT:-80}"
    MNEMO_BASE="http://${MNEMO_HOST}:${MNEMO_PORT}"
fi
MNEMO_BASE="${MNEMO_BASE%/}"

# 4. Check if this session needs wrapping.
RESULT=$(curl -sf --max-time 2 \
    -H "Authorization: Bearer ${MNEMO_API_KEY}" \
    "${MNEMO_BASE}/admin/check-wrap/${SESSION_ID}" 2>/dev/null || echo "")
[[ -z "$RESULT" ]] && exit 0

WRAP_NEEDED=$(echo "$RESULT" | python3 -c \
    "import json,sys; print('1' if json.load(sys.stdin).get('wrap_needed') else '')" \
    2>/dev/null || echo "")
[[ -z "$WRAP_NEEDED" ]] && exit 0

# 5. Spawn background mend — exit immediately so the user is not blocked.
MEND_SCRIPT="$(dirname "$0")/wrap-session-bg.py"
[[ ! -f "$MEND_SCRIPT" ]] && exit 0

PYTHON="${MNEMO_PYTHON:-python3}"

nohup "$PYTHON" "$MEND_SCRIPT" "$SESSION_ID" "$CWD" \
    >> "/tmp/mnemo-mend-${SESSION_ID:0:8}.log" 2>&1 &
disown

exit 0
