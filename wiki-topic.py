#!/usr/bin/env python3
"""wiki-topic.py — UserPromptSubmit: point at the wiki page (team, or Personal in Personal projects) when a prompt names its subject.

Arm map_topic only (wiki_ab.arm). Uses the wiki map cached by the session brief (load-context.py), so it
makes no server call; each page is pointed at once per session, at most 2 per prompt. Fails silent.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wiki_ab  # noqa: E402

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
session = payload.get("session_id", "")
if not session or wiki_ab.arm(session) != "map_topic":
    sys.exit(0)
pages = wiki_ab.load_cache(wiki_ab.root_for(payload.get("cwd", "")))
hits = wiki_ab.topic_matches(payload.get("prompt", ""), pages)
if not hits:
    sys.exit(0)
state = wiki_ab.CACHE.parent / "wiki-topic" / f"{session}.json"
try:
    done = set(json.loads(state.read_text()))
except (OSError, json.JSONDecodeError):
    done = set()
new = [p for p in hits if p["id"] not in done]
if not new:
    sys.exit(0)
try:
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(sorted(done | {p["id"] for p in new})))
except OSError:
    pass
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                         "additionalContext": wiki_ab.pointer_text(new)}}))
