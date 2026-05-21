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
# Call evaluate_action
# ---------------------------------------------------------------------------

def _parse_sse(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return {}

try:
    import httpx

    with httpx.Client(timeout=0.8) as client:
        init_resp = client.post(
            MCP_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pre-tool-hook", "version": "2.1"},
                },
            },
        )
        init_resp.raise_for_status()
        mcp_session_id = init_resp.headers.get("mcp-session-id", "")

        mcp_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {api_key}",
            "MCP-Session-Id": mcp_session_id,
        }

        args: dict = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "session_id": session_id,
        }
        if project:
            args["project"] = project

        eval_resp = client.post(
            MCP_URL,
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {"name": "evaluate_action", "arguments": args},
            },
        )
        eval_resp.raise_for_status()

        data = _parse_sse(eval_resp.text)
        content = data.get("result", {}).get("content", [])
        result: dict = {}
        if isinstance(content, list) and content:
            raw = content[0].get("text", "{}")
            result = json.loads(raw) if isinstance(raw, str) else {}

except Exception:
    sys.exit(0)

# ---------------------------------------------------------------------------
# Act on decision
# ---------------------------------------------------------------------------

decision = result.get("decision", "allow")
directive = result.get("directive") or ""
rationale = result.get("rationale") or ""

if decision == "deny":
    reason = directive or "Lesson block: action not permitted."
    if rationale:
        reason += f"\n{rationale}"
    sys.stderr.write(f"[Mnemo] BLOCKED: {reason}\n")
    sys.exit(2)

if decision == "warn" and directive:
    lines = ["**Mnemo — lesson directive:**\n", f"  {directive}"]
    if rationale:
        lines.append(f"  _{rationale}_")
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    sys.stdout.write(json.dumps(out))

sys.exit(0)
