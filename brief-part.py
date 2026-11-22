#!/usr/bin/env python3
"""SessionStart hook: part N of the full brief's stored memories (brief_ab.py › parts).

Claude Code caps each hook's injected context at 10,000 chars, so load-context.py writes the memory lines as parts
and one brief-part.py hook per part injects its own. Silent when there is no part N for this session (old-brief arm,
small store, compact, headless run, or load-context.py did not finish).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brief_ab  # noqa: E402
from headless import is_headless  # noqa: E402


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        n = int(sys.argv[1])
    except Exception:
        return
    if is_headless() or payload.get("source") == "compact":
        return
    text = brief_ab.read_part(payload.get("session_id", ""), n)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))


if __name__ == "__main__":
    main()
