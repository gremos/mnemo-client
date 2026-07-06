#!/usr/bin/env python3
"""
mnemo UserPromptSubmit Hook — Correction Detector

Fires before Claude processes each user message. Scans the user's text for
correction markers (no/wrong/don't/undo…) and calls log_user_correction on
Mnemo so wrap_session gets an objective correction count via tool_events instead
of relying on model self-report.

Fail-open (any error → silent exit 0). Hard timeout: 600 ms.
"""
from __future__ import annotations

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Read hook payload
# ---------------------------------------------------------------------------

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)

user_prompt: str = payload.get("prompt", "")
if not user_prompt or not user_prompt.strip():
    sys.exit(0)

claude_session_id: str = payload.get("session_id", "")

# ---------------------------------------------------------------------------
# Correction heuristic
# ---------------------------------------------------------------------------

_text = user_prompt.strip().lower()[:500]

_FP_PATTERNS = [
    r"\bno\s+(problem|worries|issue|big deal|way)\b",
    r"\bno\s+need\b",
    r"that'?s\s+(fine|great|good|perfect|ok|okay|correct|right|exactly)\b",
    r"\bdon'?t\s+(worry|bother|hesitate|mind|sweat)\b",
    r"\b(never ?mind|no need to)\b",
]

_CORRECTION_PATTERNS = [
    r"^\s*no[.!,]?\s*$",
    r"\b(no|nope)[,.!]?\s+(that|this|you|don'?t|please|stop|more|again)\b",
    r"\bdon'?t\s+(do|say|use|write|add|include|create|make|change|remove|delete|run|call)\b",
    r"\bstop\s+(doing|using|adding|writing|saying|that|it|this)\b",
    r"\b(wrong|incorrect|that'?s not right|not correct)\b",
    r"\b(undo|revert|rollback|roll back)\b",
    r"\bthat'?s\s+(not|wrong)\b",
    r"\bactually[,\s]+(no|don'?t|use|do|instead)\b",
    r"\bi\s+(said|meant|asked for|told you|wanted)\b",
    r"\bplease\s+(stop|don'?t)\b",
    # Missed phrasings from session history
    r"\bwait[,.]?\s*(no|actually|that|hold on)\b",
    r"\bno[,.]?\s+actually\b",
    r"\bnot\s+quite\b",
    r"\b(you\s+)?(missed|forgot|skipped)\s+(the|that|this|a|to)\b",
    r"\bthat\s+(doesn'?t|didn'?t|won'?t)\s+work\b",
    r"\bthat'?s\s+(not\s+what\s+i|incomplete|not\s+right)\b",
    r"\bthat'?s\s+not\s+what\s+i\s+(meant|asked|wanted|said)\b",
]


def _is_correction(text: str) -> bool:
    if any(re.search(p, text) for p in _FP_PATTERNS):
        return False
    return any(re.search(p, text) for p in _CORRECTION_PATTERNS)


if not _is_correction(_text):
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
    or os.getenv("MNEMO_ADMIN_TOKEN") or _env.get("MNEMO_ADMIN_TOKEN")
    or os.getenv("MNEMO_API_KEY") or _env.get("MNEMO_API_KEY", "")
)
if not api_key:
    sys.exit(0)

_mnemo_base = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
    or os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{os.getenv('MNEMO_HOST') or _env.get('MNEMO_HOST', 'localhost')}:{os.getenv('MNEMO_PORT') or _env.get('MNEMO_PORT', '80')}"
).rstrip("/")
CLI_BASE = _mnemo_base
# Note: project no longer resolved here — log_user_correction infers it server-side
# from the recovered tool action's session, which is more reliable than a cwd guess.

# ---------------------------------------------------------------------------
# Call log_user_correction (cold → /cli/*) ONLY.
#
# We deliberately do NOT also call record_lesson_miss here. That path was invoked
# with tool_name="unknown" and normalized_action=<the user's prompt prose>, which
# can never yield a derivable trigger — it only ever minted unvalidatable
# soft_instructions that clog the lesson store and never close the RL loop.
#
# log_user_correction already does the right thing server-side: it recovers the
# REAL last tool action for the session and, when that action is genuinely
# triggerable, drafts a lesson_miss with a specific trigger via _derive_triggers —
# the only path that can produce a guardrail able to pass replay precision.
#
# Uses urllib (stdlib), never httpx: this hook is launched by bare `python3` on
# PATH, so httpx is not guaranteed importable in the ambient venv (the same trap
# that silently broke wrap-session-bg.py). urllib always ships with Python3.
# ---------------------------------------------------------------------------

try:
    import urllib.request

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if claude_session_id:
        headers["X-Session-Id"] = claude_session_id

    req = urllib.request.Request(
        CLI_BASE + "/cli/log_user_correction",
        data=b"{}",
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2.0):
        pass

except Exception:
    pass  # fail-open

sys.exit(0)
