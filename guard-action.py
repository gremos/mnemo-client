#!/usr/bin/env python3
"""
mnemo PreToolUse Hook — v2.1

Fires before Bash/Edit/Write/NotebookEdit. Calls evaluate_action on the server,
which does exact-match trigger matching against active lessons and returns a
structured decision.

  allow  → exit 0 silently (no match, or holdout suppression)
  warn   → inject directive as additionalContext
  deny   → exit 2 (blocks tool) with directive as reason

Fail-open (any error → silent exit 0). Hard timeout: 800 ms.
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Read hook input
# ---------------------------------------------------------------------------

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool_name = payload.get("tool_name", "")
tool_input = payload.get("tool_input", {})
session_id = payload.get("session_id", "unknown")

if tool_name not in {"Bash", "Edit", "Write", "NotebookEdit"}:
    sys.exit(0)

# ---------------------------------------------------------------------------
# Resolve config: plugin env vars > legacy env files
# ---------------------------------------------------------------------------

def _load_legacy_env() -> dict:
    for path in (
        os.path.expanduser("~/.claude/skills/mnemo/.env"),
        os.path.expanduser("~/.mnemo.env"),
    ):
        try:
            result: dict = {}
            for line in open(path):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    result[k.strip()] = v.strip()
            return result
        except Exception:
            pass
    return {}

_env = _load_legacy_env()

api_key = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_API_TOKEN")
    or os.getenv("MNEMO_HOOK_KEY") or _env.get("MNEMO_HOOK_KEY")
    or os.getenv("MNEMO_API_KEY") or _env.get("MNEMO_API_KEY", "")
)
if not api_key:
    sys.exit(0)

_mnemo_base = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
    or os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{os.getenv('MNEMO_HOST') or _env.get('MNEMO_HOST', 'localhost')}:{os.getenv('MNEMO_PORT') or _env.get('MNEMO_PORT', '80')}"
).rstrip("/")
MCP_URL = _mnemo_base + "/mcp/"

cwd = payload.get("cwd", "")
project = None
if cwd:
    import pathlib
    _p = pathlib.Path(cwd)
    for parent in [_p, *_p.parents]:
        _mnemo_proj = parent / ".mnemo-project"
        if _mnemo_proj.exists():
            try:
                project = _mnemo_proj.read_text().strip()
            except Exception:
                pass
            break
    if not project:
        project = _p.name or None

# ---------------------------------------------------------------------------
# Static catastrophic-command guard (v2.2 — RL enforcement removed).
#
# The learned/statistical guardrail loop (server evaluate_action) is being retired:
# it caught 0 repeats in its lifetime and every past correction was benign, never
# "must-block". This hook no longer calls the server. Instead it surfaces a
# NON-BLOCKING warning for a tiny, tightly-scoped set of irreversible commands.
# It NEVER denies (never exits 2) — a false block gets the hook hand-disabled per
# VM and destroys fleet parity. Pure safety reminder, zero server round-trip.
# ---------------------------------------------------------------------------
import re

_CATASTROPHIC = [
    # \b doesn't fire next to punctuation-only tokens (bare "/", "~", "-f", "--force")
    # since \b needs a word char on one side -- (?=\s|$) anchors on whitespace/EOL instead.
    (r"\brm\s+-[a-z]*r[a-z]*\s+(/|~|/\*|\$HOME)(?=\s|$)", "a recursive delete of a root/home path"),
    (r"\bgit\s+push\b.*(?:^|\s)(-f|--force)(?=\s|$).*\b(main|master|prod|production|release)\b",
     "a force-push to a protected branch"),
    (r"\bdrop\s+database\b", "a DROP DATABASE"),
    (r"\bmkfs\b", "a filesystem format"),
    (r"\bdd\s+if=.*\bof=/dev/", "a raw write to a block device"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "a fork bomb"),
]

_probe = tool_input.get("command", "") if tool_name == "Bash" else ""

for _pat, _why in _CATASTROPHIC:
    if _probe and re.search(_pat, _probe, re.IGNORECASE):
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    f"**Mnemo — catastrophic-command guard:** this looks like {_why}. "
                    "It is irreversible — double-check the target before running."
                ),
            }
        }
        sys.stdout.write(json.dumps(out))
        break

sys.exit(0)
