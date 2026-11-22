"""brief_ab.py — which session brief a session gets (Mnemo knowledge-delivery ticket 27, 2026-11-22).

Prompt replay on 40 real prompts that need a stored memory: the old brief (15 memories, 80-char previews) scored like
no memory; the whole curated catalog at session start scored 77.5% vs 2.5% without memory (Sonnet 5.5); per-prompt
retrieval 40-52% (it found the needed memory only ~55% of the time). Curated stores are small (~80-150 memories), so
the full arm shows all of them. Arms are stable per session: 20% keep the old brief for the live readout.
"""
from __future__ import annotations

import hashlib
import os

ARMS = ("brief", "full")
CONTROL_SHARE = 20      # % of sessions on the old brief
FULL_BUDGET = 24000     # chars for the full arm's memory lines (~6k tokens); lessons and pending keep their own budgets
PER_CALL = 50           # get_memories' server-side cap


def arm(session_id: str) -> str:
    forced = os.environ.get("MNEMO_BRIEF_ARM")      # tests / live verification only
    if forced in ARMS:
        return forced
    h = int(hashlib.sha256(("brief:" + (session_id or "")).encode()).hexdigest(), 16)
    return "brief" if h % 100 < CONTROL_SHARE else "full"


def merge(*lists: list[dict]) -> list[dict]:
    """First occurrence wins (this project's memories before the cross-project ones)."""
    seen, out = set(), []
    for lst in lists:
        for m in lst or []:
            k = m.get("id") or m.get("preview")
            if k not in seen:
                seen.add(k)
                out.append(m)
    return out


def full_lines(mems: list[dict], budget: int = FULL_BUDGET) -> tuple[list[str], int]:
    """One line per memory, full preview, anti-patterns and decisions first; returns (lines, omitted)."""
    prio = {"anti-pattern": 0, "decision": 1, "primer": 2, "solution": 3, "command": 4, "note": 5}
    ordered = sorted(mems, key=lambda m: (prio.get(m.get("type", "note"), 5), -int(m.get("importance") or 0)))
    lines, used = [], 0
    for m in ordered:
        if m.get("type") == "episode":
            continue
        date = str(m.get("created_at") or "")[:10]
        meta = ", ".join(x for x in (m.get("type", "note"), m.get("project") or "", date) if x)
        line = f"    • [{meta}] {' '.join(str(m.get('preview', '')).split())}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    return lines, len([m for m in ordered if m.get("type") != "episode"]) - len(lines)
