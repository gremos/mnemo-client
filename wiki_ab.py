"""wiki_ab.py — wiki map + topic pointers, A/B by session (Mnemo ADR-0010, knowledge-delivery ticket 10).

Measured 2026-10-04: in sessions whose prompts raised a subject with its own wiki page, Claude looked at the
wiki in 25% (engineers 1/20) and the session-start hook delivered the matching page 0/32 times (its query
is the folder name; the brief showed 500 chars of index.md = 4/33 entries). Arms (stable per session; 2.4.1: 20% control, 80% map_topic):
  control    today's brief (500-char index excerpt)
  map        full wiki map (every page: title + id) in the brief, re-sent after compaction
  map_topic  map + a one-line pointer when a prompt names a page's subject (wiki-topic.py)
The map comes from Mnemo's wiki:xo pages (identical on both instances), not local files: the VMs' local
wiki copies are stale and have no index.md. Pages open with get_memory(<id>) on every profile.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

ARMS = ("control", "map", "map_topic")
CONTROL_SHARE = 20      # % of sessions kept on the control brief; the rest get map_topic (map: override only)
CACHE = Path(os.environ.get("CLAUDE_PLUGIN_DATA", os.path.expanduser("~/.mnemo"))) / "wiki-map.json"
_GENERIC = {"overview", "management", "standard", "standards", "operations", "common", "status", "structure",
            "platform", "conventions", "policy", "data", "guide", "phase", "team", "layer", "score", "user",
            "users", "azure", "microsoft", "shared", "infrastructure", "automation", "story", "lifecycle",
            "claude", "code", "wiki", "mnemo", "contract", "migration", "backup", "config", "decision",
            "runbook", "runbooks", "workers", "detail", "sectors", "boards", "security", "with", "from", "into", "and", "the"}


def arm(session_id: str) -> str:
    forced = os.environ.get("MNEMO_WIKI_ARM")       # tests / live verification only
    if forced in ARMS:
        return forced
    # 2.4.0 split sessions 3 ways. Controlled replay 2026-10-04 (12 prompts x 3 arms): the expected page was
    # opened 0/8 control, 6/8 map, 8/8 map_topic at equal median cost, so map_topic ships and a control
    # share stays for the live readout (wiki_ab_report.py).
    return "control" if int(hashlib.sha1((session_id or "").encode()).hexdigest(), 16) % 100 < CONTROL_SHARE else "map_topic"


def title_of(preview: str) -> str | None:
    m = re.search(r"(?m)^#\s+([^\n]+)", preview or "") or re.search(r"#\s+([^\n#]+?)(?:\s{2,}|$)", preview or "")
    return m.group(1).strip() if m else None


def domain_of(tags: list[str]) -> str:
    return next((t.split(":", 1)[1] for t in tags or [] if t.startswith("domain:")), "other")


def pages_from(items: list[dict]) -> list[dict]:
    """get_memories(project='wiki:xo', tags=['wiki-page']) rows -> [{id, title, domain}], one per title."""
    seen, out = set(), []
    for m in items:
        t = title_of(m.get("preview") or m.get("content") or "")
        if t and t not in seen:
            seen.add(t)
            out.append({"id": m["id"], "title": t, "domain": domain_of(m.get("tags"))})
    return sorted(out, key=lambda p: (p["domain"], p["title"]))


def map_block(pages: list[dict]) -> str:
    lines = ["  Wiki map (team wiki:xo — on a subject listed here, open the page with get_memory(\"<id>\") "
             "before deciding and cite it):"]
    dom = None
    for p in pages:
        if p["domain"] != dom:
            dom = p["domain"]
            lines.append(f"    [{dom}]")
        lines.append(f"      {p['title']} — {p['id'][:8]}")
    return "\n".join(lines)


def save_cache(pages: list[dict]) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(pages))
    except OSError:
        pass


def load_cache() -> list[dict]:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text.lower()) if w not in _GENERIC]


def topic_matches(prompt: str, pages: list[dict], limit: int = 2) -> list[dict]:
    """Pages whose subject the prompt names: a code-like title token (digit or hyphen: gpml01, 3cx, socks5,
    xoagents01) or two title tokens together. Measured on 5,268 real prompts (2026-10-04): matching any
    title-unique word fired on 6.9% of prompts, mostly noise ("server", "pipeline"); this rule fires on 1.0%
    with mostly relevant hits. Recall is left to the full map (map arms).
    A code names the subject only when it leads the title: a code in parentheses is a qualifier (KIWI01 in
    "Plesk / Postfix Operations (KIWI01 / gyp.gr)" hosts many systems; 0/4 real kiwi01 prompts were about
    Plesk); it still counts as an ordinary title token. Not excluded: the session's own workspace name —
    GPML01 prompts come from a GPML01 workspace and the page helped there (replay 2026-10-04)."""
    words = set(re.findall(r"[a-z0-9][a-z0-9\-]{2,}", (prompt or "").lower()))
    hits = []
    for p in pages:
        toks = set(_tokens(p["title"]))
        qualifiers = set(_tokens(" ".join(re.findall(r"\(([^)]*)\)", p["title"]))))
        codes = {t for t in toks - qualifiers if (re.search(r"\d", t) or "-" in t)}
        if (codes & words) or len(toks & words) >= 2:
            hits.append(p)
    return hits[:limit]


def pointer_text(pages: list[dict]) -> str:
    items = "; ".join(f"{p['title']} — get_memory(\"{p['id']}\")" for p in pages)
    return (f"[wiki] Relevant team wiki page(s) for this request: {items}. "
            f"Open it before deciding on this subject and cite it; if it is stale or wrong, say so.")
