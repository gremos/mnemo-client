#!/usr/bin/env python3
"""wiki-map.py — SessionStart (startup/resume/clear/compact): the wiki's index.md as the session's wiki map
(team wiki copy; the Personal wiki for sessions inside ~/Documents/code/Personal — never both).

Reads the local read-only copy of the wiki (wiki_ab.LOCAL_ROOT, shipped from the laptop's git checkout), so it needs
no Mnemo server, key or network. Arm control gets nothing (wiki_ab.arm). Caches the page list for wiki-topic.py.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wiki_ab  # noqa: E402

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if wiki_ab.arm(payload.get("session_id", "")) == "control":
    sys.exit(0)
root = wiki_ab.root_for(payload.get("cwd", ""))
pages = wiki_ab.local_pages(root)
block = wiki_ab.local_map_block(root)
if not pages or not block:
    sys.exit(0)
wiki_ab.save_cache(pages, root)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "[wiki] " + block.strip()}}))
