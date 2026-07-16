#!/usr/bin/env bash
# Install a --plugin-dir launcher shim in place of the real `claude` binary on PATH.
#
# Works regardless of invocation method (plain shell, VS Code integrated terminal,
# VS Code extension spawn, Claude Code's own daemon/spare-process pool) since all
# of them resolve `claude` via a PATH lookup -- unlike a .bashrc shell function,
# which VS Code Remote-SSH's daemon architecture was found to bypass entirely
# (2026-07-16 incident: the wrapper never fired because sessions were handed off
# from a pre-forked spare process, not re-exec'd through an interactive shell).
#
# Idempotent: safe to re-run every agent cycle. Detects an already-installed shim
# and only rewrites it if the --plugin-dir target changed.
#
# One-time caveat: any Claude Code daemon / spare-process pool already running
# before this install won't pick up the new shim until it's restarted -- those
# processes were forked from the OLD real binary path and don't re-resolve PATH.
set -euo pipefail

REPO_DIR="${1:?usage: install-launcher.sh <repo-dir> [target-path]}"
# target-path defaults to `command -v claude` -- overridable (2nd arg) so this
# script's logic is testable against an arbitrarily-named file, not just `claude`.
MARKER="# mnemo-fleet-agent launcher shim"

CLAUDE_PATH="${2:-$(command -v claude 2>/dev/null)}"
if [ -z "$CLAUDE_PATH" ]; then
    exit 0  # nothing on PATH yet; nothing to shim
fi

if grep -q "$MARKER" "$CLAUDE_PATH" 2>/dev/null; then
    # Already a shim -- check whether it points at this repo already.
    if grep -qF "$REPO_DIR" "$CLAUDE_PATH" 2>/dev/null; then
        exit 0  # up to date, nothing to do
    fi
    # Points at a stale path (e.g. repo moved) -- find the real binary it wraps.
    REAL_TARGET=$(grep -oP '(?<=exec ")[^"]+(?=" --plugin-dir)' "$CLAUDE_PATH" 2>/dev/null || echo "")
else
    REAL_TARGET="$CLAUDE_PATH.real"
    mv "$CLAUDE_PATH" "$REAL_TARGET"
fi

if [ -z "$REAL_TARGET" ] || [ ! -x "$REAL_TARGET" ]; then
    exit 0  # couldn't determine the real binary -- fail open, don't break `claude`
fi

cat > "$CLAUDE_PATH" <<SHIMEOF
#!/usr/bin/env bash
$MARKER (installed $(date -u +%Y-%m-%d))
exec "$REAL_TARGET" --plugin-dir "$REPO_DIR" "\$@"
SHIMEOF
chmod +x "$CLAUDE_PATH"
