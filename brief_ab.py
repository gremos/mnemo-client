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
FULL_BUDGET = 64000     # chars (~16k tokens, cached after the first turn): room for a ~150-memory store at 400 chars, as
                        # replayed; lessons and pending keep their own budgets
PAGE = {"limit": 200, "preview_chars": 400}   # Mnemo server >= ticket 27: whole memories, bigger page
OLD_CAP = 50            # get_memories' cap on older servers


def arm(session_id: str) -> str:
    forced = os.environ.get("MNEMO_BRIEF_ARM")      # tests / live verification only
    if forced in ARMS:
        return forced
    h = int(hashlib.sha256(("brief:" + (session_id or "")).encode()).hexdigest(), 16)
    return "brief" if h % 100 < CONTROL_SHARE else "full"


def merge(*lists: list[dict]) -> list[dict]:
    """First occurrence wins; each row keeps `_src`, the index of the list it came from, so full_lines keeps this
    project's memories (list 0) ahead of the cross-project ones when the budget cuts."""
    seen, out = set(), []
    for src, lst in enumerate(lists):
        for m in lst or []:
            if not isinstance(m, dict):
                continue
            k = m.get("id") or m.get("preview")
            if k not in seen:
                seen.add(k)
                out.append({**m, "_src": src})
    return out


def full_lines(mems: list[dict], budget: int = FULL_BUDGET) -> tuple[list[str], int]:
    """One line per memory, full preview, anti-patterns and decisions first; returns (lines, omitted)."""
    prio = {"anti-pattern": 0, "decision": 1, "primer": 2, "solution": 3, "command": 4, "note": 5}

    def _imp(m: dict) -> int:                     # a malformed row must not cost the whole brief
        try:
            return int(m.get("importance") or 0)
        except (TypeError, ValueError):
            return 0

    kept = [m for m in mems if isinstance(m, dict) and m.get("type") != "episode"]
    ordered = sorted(kept, key=lambda m: (m.get("_src", 0), prio.get(str(m.get("type", "note")), 5), -_imp(m)))
    lines, used = [], 0
    for m in ordered:
        date = str(m.get("created_at") or "")[:10]
        meta = ", ".join(x for x in (str(m.get("type", "note")), str(m.get("project") or ""), date) if x)
        line = f"    • [{meta}] {' '.join(str(m.get('preview', '')).split())}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    return lines, len(ordered) - len(lines)
