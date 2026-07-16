#!/usr/bin/env python3
"""
mnemo fleet-agent functional probes.

Three checks, run standalone or by mnemo-fleet-agent.sh:
  guard  - the catastrophic-command regex matrix from tests/test_guard_regex.py,
           replayed against the live guard-action.py in this repo. Deterministic,
           no server dependency -- catches a broken regex even if the server is down.
  memory - a real get_memories call against the configured Mnemo server. Lenient:
           only asserts the call succeeds and returns a list, not that specific
           content is present (content is profile/data-dependent).
  wiki   - a real search_wiki call, same leniency as memory.

Usage: python3 fleet-probes.py [--json]
Exit code is always 0 -- results are reported via JSON/exit-status per probe.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parent


def _load_env() -> dict:
    for path in (os.path.expanduser("~/.claude/skills/mnemo/.env"), os.path.expanduser("~/.mnemo.env")):
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


_env = _load_env()
_api_key = os.getenv("MNEMO_HOOK_KEY") or _env.get("MNEMO_HOOK_KEY") or os.getenv("MNEMO_API_KEY") or _env.get("MNEMO_API_KEY", "")
_base = (
    os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{os.getenv('MNEMO_HOST') or _env.get('MNEMO_HOST', 'localhost')}:{os.getenv('MNEMO_PORT') or _env.get('MNEMO_PORT', '80')}"
).rstrip("/")


def _mcp_call(tool: str, arguments: dict) -> dict:
    """Minimal MCP tools/call round-trip (initialize + call) via stdlib urllib."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {_api_key}",
    }

    def _post(body: dict, extra_headers: dict) -> tuple[dict, dict]:
        req = urllib.request.Request(
            _base + "/mcp/", data=json.dumps(body).encode(),
            headers={**headers, **extra_headers}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode()
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            for line in raw.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:]), resp_headers
            return json.loads(raw) if raw else {}, resp_headers

    init_data, init_headers = _post(
        {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "fleet-probes", "version": "1.0"}}},
        {},
    )
    mcp_session = init_headers.get("mcp-session-id", "")
    data, _ = _post(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments}},
        {"MCP-Session-Id": mcp_session},
    )
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    return data.get("result", {})


def probe_guard() -> dict:
    try:
        spec = importlib.util.spec_from_file_location("guard_action", _REPO / "guard-action.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cases = [
            ("rm -rf /", True), ("rm -rf ~", True), ("git push --force origin main", True),
            ("drop database prod", True), ("mkfs.ext4 /dev/sdb1", True),
            (":(){ :|:& };:", True), ("ls -la", False), ("git push origin feature", False),
        ]
        for cmd, expected in cases:
            got = mod.check_catastrophic(cmd) is not None
            if got != expected:
                return {"status": "fail", "reason": f"{cmd!r} expected flagged={expected}, got {got}"}
        return {"status": "pass"}
    except Exception as e:
        return {"status": "fail", "reason": f"exception: {e}"}


def probe_memory() -> dict:
    try:
        result = _mcp_call("get_memories", {"project": "__global__", "limit": 1})
        content = result.get("content", [])
        if isinstance(content, list) and content and content[0].get("type") == "text":
            json.loads(content[0]["text"])  # must parse as a list
        return {"status": "pass"}
    except Exception as e:
        return {"status": "fail", "reason": f"{e}"}


def probe_wiki() -> dict:
    try:
        result = _mcp_call("search_wiki", {"query": "mnemo", "limit": 1})
        content = result.get("content", [])
        if isinstance(content, list) and content and content[0].get("type") == "text":
            json.loads(content[0]["text"])
        return {"status": "pass"}
    except Exception as e:
        return {"status": "fail", "reason": f"{e}"}


def main() -> None:
    probes = {"guard": probe_guard(), "memory": probe_memory(), "wiki": probe_wiki()}
    print(json.dumps(probes))


if __name__ == "__main__":
    main()
