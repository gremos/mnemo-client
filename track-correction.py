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
cwd: str = payload.get("cwd", "")

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
MCP_URL = _mnemo_base + "/mcp/"
CLI_BASE = _mnemo_base

_project: str | None = None
if cwd:
    import pathlib as _pathlib
    _p = _pathlib.Path(cwd)
    for _parent in [_p, *_p.parents]:
        _mf = _parent / ".mnemo-project"
        if _mf.exists():
            try:
                _project = _mf.read_text().strip() or None
            except Exception:
                pass
            break
    if not _project:
        _project = _p.name or None

# ---------------------------------------------------------------------------
# Call log_user_correction (cold → /cli/*) + record_lesson_miss (hot → /mcp/)
# ---------------------------------------------------------------------------

try:
    import httpx

    cli_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if claude_session_id:
        cli_headers["X-Session-Id"] = claude_session_id

    mcp_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {api_key}",
    }

    with httpx.Client(timeout=2.0) as client:
        # log_user_correction is cold → /cli/
        client.post(
            CLI_BASE + "/cli/log_user_correction",
            headers=cli_headers,
            json={},
        )

        # record_lesson_miss is hot → /mcp/ (still a model-facing tool)
        init_resp = client.post(
            MCP_URL,
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "correction-detect-hook", "version": "1.0"},
                },
            },
        )
        init_resp.raise_for_status()
        mcp_headers["MCP-Session-Id"] = init_resp.headers.get("mcp-session-id", "")
        if claude_session_id:
            mcp_headers["X-Session-Id"] = claude_session_id

        miss_args: dict = {
            "tool_name": "unknown",
            "normalized_action": user_prompt.strip()[:120],
            "correction_text": user_prompt.strip()[:400],
            "session_id": claude_session_id or "unknown",
        }
        if _project:
            miss_args["project"] = _project
        client.post(
            MCP_URL,
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {"name": "record_lesson_miss", "arguments": miss_args},
            },
        )

except Exception:
    pass  # fail-open

sys.exit(0)
