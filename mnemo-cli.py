#!/usr/bin/env python3
"""
mnemo cold-path CLI for /mnemo:memsave

draft_lesson and wrap_session live on the server's /cli/* REST path, not on /mcp/, so a Claude
session has no tool for them. memsave runs this script instead. It reads the key from
~/.mnemo.env itself, so the model never reads that file.

Usage:
    echo '{"directive": ..., "rationale": ..., "delivery": "claude_md", "project": ...}' \
        | python3 mnemo-cli.py draft-lesson
    python3 mnemo-cli.py wrap --summary "..." --outcome success [--project P]
        [--corrections N] [--memory-helped yes|no] [--session-id ID]

--session-id defaults to $CLAUDE_CODE_SESSION_ID, which Claude Code exports to Bash. Prints the
server's JSON reply; exits 1 on an HTTP error, 2 on a usage or config error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


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

def _cfg(key: str, default: str = "") -> str:
    return os.getenv(key) or _env.get(key, default)

MNEMO_KEY = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_API_TOKEN")
    or _cfg("MNEMO_HOOK_KEY") or _cfg("MNEMO_ADMIN_TOKEN") or _cfg("MNEMO_API_KEY")
)
_mnemo_base = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
    or (os.getenv("MNEMO_BASE_URL") or _cfg('MNEMO_BASE_URL', '')).rstrip("/")
    or os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{_cfg('MNEMO_HOST', 'localhost')}:{_cfg('MNEMO_PORT', '80')}"
).rstrip("/")


def _post(path: str, body: dict, session_id: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {MNEMO_KEY}"}
    if session_id:
        headers["X-Session-Id"] = session_id
    req = urllib.request.Request(_mnemo_base + path, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, {"error": raw.decode(errors="replace")[:300]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mnemo-cli.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("draft-lesson", help="POST the lesson JSON on stdin to /cli/draft_lesson")
    w = sub.add_parser("wrap", help="register + wrap this session")
    w.add_argument("--summary", required=True)
    w.add_argument("--outcome", required=True, choices=["success", "partial", "failure"])
    w.add_argument("--project")
    w.add_argument("--corrections", type=int)
    w.add_argument("--memory-helped", choices=["yes", "no"])
    w.add_argument("--session-id", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    args = p.parse_args(argv)

    if not MNEMO_KEY:
        print("mnemo-cli: no MNEMO_HOOK_KEY in ~/.mnemo.env", file=sys.stderr)
        return 2

    if args.cmd == "draft-lesson":
        status, out = _post("/cli/draft_lesson", json.load(sys.stdin))
    else:
        if not args.session_id:
            # Without X-Session-Id the server closes the user's latest session, not this one.
            print("mnemo-cli: no --session-id and no $CLAUDE_CODE_SESSION_ID", file=sys.stderr)
            return 2
        _post("/cli/register_claude_session", {"claude_session_id": args.session_id}, args.session_id)
        body: dict = {"summary": args.summary, "outcome": args.outcome}
        if args.project:
            body["project"] = args.project
        if args.corrections is not None:
            body["corrections"] = args.corrections
        if args.memory_helped:
            body["memory_helped"] = args.memory_helped == "yes"
        status, out = _post("/cli/wrap_session", body, args.session_id)

    print(json.dumps(out))
    return 0 if status < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
