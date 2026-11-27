"""wrap_window.py — the part of a session each wrap labels (Mnemo ticket 27 correction counter, 2026-11-27).

A session is wrapped several times (session end, resume, compaction). Until 2.6.3 every wrap labelled the last 80
messages of the whole transcript, so windows overlapped and the episode's correction count could be neither summed
nor dated. Now a wrap labels only the lines after the previous wrap (plus the one assistant reply before them, as
context for a correction) and the episode carries the session's running total.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

MAX_SESSIONS = 500
STATE = Path(os.environ.get("CLAUDE_PLUGIN_DATA", os.path.expanduser("~/.mnemo"))) / "wrap-windows.json"


def text_of(content) -> str:
    """Flatten content (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def load(jsonl: Path, start: int) -> tuple[list[dict], int]:
    """User/assistant text messages from line `start` on, led by the last assistant reply before it (context=True);
    ([], end) when nothing new. Returns the line count to start the next window at."""
    msgs, context, end = [], None, 0
    try:
        lines = jsonl.read_text(errors="replace").split("\n")
    except OSError:
        return [], start
    if start > len(lines):                                  # transcript replaced under the same id: start over
        start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue                                        # a line still being written is not consumed
        end = i + 1
        if not isinstance(obj, dict) or obj.get("type") not in ("user", "assistant"):
            continue
        msg = obj.get("message") or {}
        text = text_of(msg.get("content", "")).strip()
        if not text:
            continue
        m = {"role": msg.get("role", obj["type"]), "text": text}
        if i < start:
            if m["role"] == "assistant":
                context = m
        else:
            msgs.append(m)
    if not msgs:
        return [], max(end, start)
    return ([{**context, "context": True}] if context else []) + msgs, end


def _read(state: Path) -> dict:
    try:
        data = json.loads(state.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(state: Path, session_id: str) -> tuple[int, int]:
    """(line the next window starts at, corrections counted in earlier windows)."""
    row = _read(state).get(session_id) or [0, 0]
    return int(row[0]), int(row[1])


def put(state: Path, session_id: str, line: int, corrections: int) -> None:
    """Read-modify-write under a lock: two wraps can end at once (SessionEnd + compaction or nightly close)."""
    state.parent.mkdir(parents=True, exist_ok=True)
    with open(state.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read(state)
        data.pop(session_id, None)
        data[session_id] = [line, corrections]             # newest last; oldest sessions drop first
        data = dict(list(data.items())[-MAX_SESSIONS:])
        fd, tmp = tempfile.mkstemp(dir=state.parent, prefix=".wrap-windows.")   # mode 0600
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, state)
