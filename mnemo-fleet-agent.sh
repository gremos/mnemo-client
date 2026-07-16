#!/usr/bin/env bash
# mnemo fleet agent — one per profile, run on a timer (see systemd/mnemo-fleet-agent.timer).
#
# Each cycle: force-reset this clone to the latest mnemo--v* tag (disposable clone --
# any local edit is wiped every cycle, never silently accumulates, see the
# 2026-07-16 incident where two profiles' local plugin clones drifted from origin
# for weeks undetected), re-run the launcher install (idempotent), run the
# functional probe matrix, and POST the result to Mnemo's /cli/fleet_report.
#
# Never crashes the timer: git/network/probe failures are caught and reported,
# not raised. Reports every cycle (not just on version change) so a probe
# regression between tags -- server-side breakage, not a code change -- is
# caught too.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${MNEMO_FLEET_PROFILE:-$(hostname)-$(whoami)}"

cd "$REPO_DIR" || exit 0

_MNEMO_ENV="$HOME/.mnemo.env"
[ -f "$_MNEMO_ENV" ] && . "$_MNEMO_ENV" 2>/dev/null
MNEMO_HOST="${MNEMO_HOST:-localhost}"
MNEMO_PORT="${MNEMO_PORT:-80}"
MNEMO_HOOK_KEY="${MNEMO_HOOK_KEY:-${MNEMO_ADMIN_TOKEN:-}}"

FETCH_ERROR=false
if ! git fetch --tags origin >/dev/null 2>&1; then
    FETCH_ERROR=true
fi

LATEST_TAG=$(git tag -l 'mnemo--v*' | sort -V | tail -1)
if [ -n "$LATEST_TAG" ]; then
    git reset --hard "$LATEST_TAG" >/dev/null 2>&1
fi

COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
VERSION=$(python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])" 2>/dev/null || echo "unknown")

# Idempotent launcher install -- no-op if already installed at the current target.
if [ -f "$REPO_DIR/scripts/install-launcher.sh" ]; then
    bash "$REPO_DIR/scripts/install-launcher.sh" "$REPO_DIR" >/dev/null 2>&1
fi

PROBES=$(python3 "$REPO_DIR/fleet-probes.py" 2>/dev/null || echo '{}')

if [ -n "$MNEMO_HOOK_KEY" ]; then
    python3 - "$PROFILE" "$COMMIT_SHA" "$VERSION" "$FETCH_ERROR" "$PROBES" \
        "$MNEMO_HOST" "$MNEMO_PORT" "$MNEMO_HOOK_KEY" <<'PYEOF'
import json, sys, urllib.request

profile, sha, version, fetch_error, probes_json, host, port, key = sys.argv[1:9]
body = {
    "profile": profile, "commit_sha": sha, "version": version,
    "probes": json.loads(probes_json), "fetch_error": fetch_error == "true",
}
req = urllib.request.Request(
    f"http://{host}:{port}/cli/fleet_report",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=8)
except Exception:
    pass  # next cycle retries; report is current-state only
PYEOF
fi
