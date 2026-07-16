#!/usr/bin/env python3
"""
mnemo PreToolUse Hook — v2.2

Static catastrophic-command guard (RL enforcement removed in v2.2 — the learned/
statistical guardrail loop caught 0 repeats in its lifetime and every past
correction was benign, never "must-block"). This hook makes no server call at all;
it surfaces a NON-BLOCKING warning for a tiny, tightly-scoped set of irreversible
commands. It NEVER denies (never exits 2) — a false block gets the hook hand-
disabled per VM and destroys fleet parity. Pure safety reminder, no dependency on
API keys, server URL, or project resolution — those were vestigial from the old
server-calling version and have been removed; keeping them around previously gated
the entire guard on `api_key` being set, which could silently disable it.

Fail-open (any error → silent exit 0).
"""
from __future__ import annotations

import json
import re
import sys

# ---------------------------------------------------------------------------
# Static catastrophic-command patterns — pure, no I/O, importable for tests.
# \b doesn't fire next to punctuation-only tokens (bare "/", "~", "-f", "--force")
# since \b needs a word char on one side -- (?=\s|$) anchors on whitespace/EOL instead.
# ---------------------------------------------------------------------------

CATASTROPHIC: list[tuple[str, str]] = [
    (r"\brm\s+-[a-z]*r[a-z]*\s+(/|~|/\*|\$HOME)(?=\s|$)", "a recursive delete of a root/home path"),
    (r"\bgit\s+push\b.*(?:^|\s)(-f|--force)(?=\s|$).*\b(main|master|prod|production|release)\b",
     "a force-push to a protected branch"),
    (r"\bdrop\s+database\b", "a DROP DATABASE"),
    (r"\bmkfs\b", "a filesystem format"),
    (r"\bdd\s+if=.*\bof=/dev/", "a raw write to a block device"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "a fork bomb"),
]


def check_catastrophic(command: str) -> tuple[str, str] | None:
    """Return (pattern, why) for the first catastrophic pattern matching `command`, else None."""
    for pat, why in CATASTROPHIC:
        if command and re.search(pat, command, re.IGNORECASE):
            return pat, why
    return None


def _main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    if tool_name not in {"Bash", "Edit", "Write", "NotebookEdit"}:
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "") if tool_name == "Bash" else ""
    match = check_catastrophic(command)
    if match:
        _, why = match
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    f"**Mnemo — catastrophic-command guard:** this looks like {why}. "
                    "It is irreversible — double-check the target before running."
                ),
            }
        }
        sys.stdout.write(json.dumps(out))

    sys.exit(0)


if __name__ == "__main__":
    _main()
