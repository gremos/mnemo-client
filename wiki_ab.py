"""wiki_ab.py — team wiki map + topic pointers (Mnemo ADR-0011, knowledge-delivery ticket 10).

Karpathy pattern: the wiki is plain markdown in git (laptop = single writer). Every profile holds a read-only copy
(wiki-distribute.sh): the session gets the wiki's own index.md as its map (wiki-map.py) and, when a prompt names a
page's subject, a pointer to the page file (wiki-topic.py); Claude opens pages with Read. No Mnemo server involved.
Replay 2026-10-05 (8 on-subject prompts): local file map opened the expected page 7/8 vs Mnemo get_memory map 6/8,
same cost. Arms (stable per session): 20% control (no map), 80% map_topic; `map` is an override only.
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
# Local read-only copy of the team wiki (index.md + SCHEMA.md + wiki/, stamped with the source commit), shipped from
# the laptop's git checkout to every profile (Karpathy pattern: plain files, index first, pages opened in full).
LOCAL_ROOT = Path(os.environ.get("MNEMO_WIKI_DIR", os.path.expanduser("~/.local/share/xo-wiki")))
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


def local_pages(root: Path = LOCAL_ROOT) -> list[dict]:
    """Pages of the local copy: id = path under wiki/ without .md, title = the page's H1."""
    out = []
    for f in sorted((root / "wiki").rglob("*.md")):
        rel = f.relative_to(root / "wiki").with_suffix("").as_posix()
        try:
            t = title_of(f.read_text(errors="replace")[:4000]) or rel
        except OSError:
            continue
        out.append({"id": rel, "title": t, "domain": rel.split("/")[0], "path": str(f)})
    return out


def title_of(preview: str) -> str | None:
    m = re.search(r"(?m)^#\s+([^\n]+)", preview or "") or re.search(r"#\s+([^\n#]+?)(?:\s{2,}|$)", preview or "")
    return m.group(1).strip() if m else None


def map_block(pages: list[dict]) -> str:
    """The session's wiki map: the local copy's index.md (pages are listed for the topic matcher only)."""
    return local_map_block(LOCAL_ROOT)


def local_map_block(root: Path = LOCAL_ROOT) -> str:
    """The wiki's own index.md (every page, one line each) with the absolute page location."""
    try:
        idx = (root / "index.md").read_text(errors="replace")
        sha = (root / ".wiki-commit").read_text().strip()[:8] if (root / ".wiki-commit").is_file() else "?"
    except OSError:
        return ""
    body = "\n".join("    " + l for l in idx.splitlines() if l.strip() and not l.startswith(("# ", "_")))
    return (f"  Wiki map (team wiki, local copy at {root} @ {sha}; page [[x]] is {root}/wiki/x.md — on a subject "
            f"listed here, Read the page before deciding and cite it):\n" + body)


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
    items = "; ".join(f"{p['title']} — Read {p['path']}" for p in pages)
    return (f"[wiki] Relevant team wiki page(s) for this request: {items}. "
            f"Open it before deciding on this subject and cite it; if it is stale or wrong, say so.")
