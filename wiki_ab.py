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
# Personal wiki (laptop only): the git checkout itself, read directly; personal and team knowledge never mix.
PERSONAL_ROOT = Path(os.environ.get("MNEMO_PERSONAL_WIKI_DIR", os.path.expanduser("~/Documents/code/Personal/wiki")))
PERSONAL_PREFIX = os.environ.get("MNEMO_PERSONAL_CODE_DIR", os.path.expanduser("~/Documents/code/Personal"))


def root_for(cwd: str) -> Path:
    """The wiki a session sees: the Personal wiki for sessions inside ~/Documents/code/Personal (when present),
    otherwise the team wiki copy."""
    c = os.path.normpath(cwd or "") + os.sep
    if c.startswith(os.path.normpath(PERSONAL_PREFIX) + os.sep) and (PERSONAL_ROOT / "index.md").is_file():
        return PERSONAL_ROOT
    return LOCAL_ROOT


def label(root: Path) -> str:
    return "personal wiki" if root == PERSONAL_ROOT else "team wiki"
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


def local_pages(root: Path | None = None) -> list[dict]:
    """Pages of the local copy: id = path under wiki/ without .md, title = the page's H1, summary = its index.md
    line (when it has one)."""
    root, out = root or LOCAL_ROOT, []
    summaries = index_summaries(root)
    for f in sorted((root / "wiki").rglob("*.md")):
        rel = f.relative_to(root / "wiki").with_suffix("").as_posix()
        try:
            t = title_of(f.read_text(errors="replace")[:4000]) or rel
        except OSError:
            continue
        page = {"id": rel, "title": t, "domain": rel.split("/")[0], "path": str(f)}
        if rel in summaries:
            page["summary"] = summaries[rel]
        out.append(page)
    return out


def index_summaries(root: Path) -> dict[str, str]:
    """index.md's one-line summary per page: "- [[id]] — summary" (Obsidian, Personal wiki) or
    "- [Title](/id) — summary" (ADO page link, team wiki since 2026-10-06)."""
    try:
        lines = (root / "index.md").read_text(errors="replace").splitlines()
    except OSError:
        return {}
    return {(m.group(1) or m.group(2)): m.group(3).strip() for m in
            (_SUMMARY.match(l) for l in lines) if m}


_SUMMARY = re.compile(r"\s*-\s*(?:\[\[([^\]|]+)\]\]|\[[^\]]*\]\(/([^)#\s]+)\))\s+—\s+(.+)")


def title_of(preview: str) -> str | None:
    m = re.search(r"(?m)^#\s+([^\n]+)", preview or "") or re.search(r"#\s+([^\n#]+?)(?:\s{2,}|$)", preview or "")
    return m.group(1).strip() if m else None


def map_block(pages: list[dict], root: Path | None = None) -> str:
    """The session's wiki map: the wiki's own index.md (pages are listed for the topic matcher only)."""
    return local_map_block(root or LOCAL_ROOT)


# Claude Code injects at most 10,000 chars per hook (over it: a 2 KB preview). The team index.md grew to ~40 KB, so
# from 2026-11-24 sessions saw only its first ~20 rows. The map is now compact: every page name under its folder
# heading, summaries cut to the widest width that fits, full summaries left in index.md.
MAP_CHARS = 9000
_PAGE_REF = re.compile(r"\[\[([^\]|]+)\]\]|\]\(/([^)#\s]+)\)")
_SUMMARY_WIDTHS = (200, 140, 100, 70, 45, 25, 0)


def _index_rows(idx: str) -> list[tuple[str, str, str]]:
    """index.md as (heading, page path under it, summary) rows; list form "- [[id]] — s" / "- [T](/id) — s" and
    table form "| [[id]] | s | date |"."""
    rows, heading, prefix = [], "", ""
    for line in idx.splitlines():
        if line.startswith("## "):
            heading = line[3:].split(" — ")[0].strip()
            prefix = heading if heading.endswith("/") else None      # folder headings only (team: "## Products/")
            rows.append((heading, "", ""))
            continue
        refs = list(_PAGE_REF.finditer(line))
        if not refs:
            continue
        ids = [m.group(1) or m.group(2) for m in refs]
        if line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            summary = cells[1] if len(cells) > 1 else ""
        else:                                                    # after the last link: a title may hold " — "
            rest = line[refs[-1].end():]
            summary = rest.split(" — ", 1)[1].strip() if " — " in rest else ""
        for n, pid in enumerate(ids):                                # "[A](/a) · [B](/b)": every page counts
            rel = pid[len(prefix):] if prefix and pid.startswith(prefix) else pid
            rows.append((heading, rel, summary if n == 0 else ""))
    return rows


def _render(rows: list[tuple[str, str, str]], width: int) -> list[str]:
    out = []
    for heading, rel, summary in rows:
        if not rel:
            out.append(f"    ## {heading}")
        elif width and summary:
            s = summary if len(summary) <= width else summary[:width - 1].rstrip() + "…"
            out.append(f"    - {rel} — {s}")
        else:
            out.append(f"    - {rel}")
    return out


def _render_grouped(rows: list[tuple[str, str, str]]) -> list[str]:
    """Densest form: per heading, pages grouped by sub-folder on one line, `F/: a · b` (= F/a, F/b)."""
    out, groups = [], {}
    def flush():
        out.extend(f"    {f + '/: ' if f else ''}{' · '.join(names)}" for f, names in groups.items())
        groups.clear()
    for heading, rel, _ in rows:
        if not rel:
            flush()
            out.append(f"    ## {heading}")
        else:
            folder, _, leaf = rel.rpartition("/")
            groups.setdefault(folder, []).append(leaf)
    flush()
    return out


def local_map_block(root: Path | None = None) -> str:
    """Compact wiki map: every page of index.md under its folder heading, summaries shortened to fit MAP_CHARS."""
    root = root or LOCAL_ROOT
    try:
        idx = (root / "index.md").read_text(errors="replace")
    except OSError:
        return ""
    sha = (root / ".wiki-commit").read_text().strip()[:8] if (root / ".wiki-commit").is_file() else "?"
    where = f"local copy at {root} @ {sha}" if sha != "?" else f"git checkout at {root}"
    head = (f"  Wiki map ({label(root)}, {where}; page p is {root}/wiki/p.md, or {root}/wiki/D/p.md under a folder "
            f"heading `## D/`; `F/: a · b` lists pages F/a and F/b; full summaries in {root}/index.md — on a subject "
            f"listed here, Read the page before deciding and cite it):\n")
    rows = _index_rows(idx)
    for lines in [_render(rows, w) for w in _SUMMARY_WIDTHS] + [_render_grouped(rows)]:
        if len(head) + len("\n".join(lines)) <= MAP_CHARS:
            return head + "\n".join(lines)
    lines, cut = _render_grouped(rows), 0
    tail = lambda: f"\n    … +{cut} more pages listed in {root}/index.md"
    while lines and len(head) + len("\n".join(lines)) + len(tail()) > MAP_CHARS:
        last = lines.pop()
        if not last.lstrip().startswith("##"):
            names = last.split(": ", 1)[-1].split(" · ")
            keep = names[:len(names) // 2]
            cut += len(names) - len(keep)
            if keep:
                lines.append(last[:len(last) - len(" · ".join(names))] + " · ".join(keep))
    return head + "\n".join(lines) + tail()


def cache_path(root: Path | None = None) -> Path:
    """One page cache per wiki, so a Personal session never overwrites the team session's pages (and vice versa)."""
    return CACHE if root != PERSONAL_ROOT else CACHE.with_name("wiki-map-personal.json")


def save_cache(pages: list[dict], root: Path | None = None) -> None:
    try:
        cache_path(root).parent.mkdir(parents=True, exist_ok=True)
        cache_path(root).write_text(json.dumps(pages))
    except OSError:
        pass


def load_cache(root: Path | None = None) -> list[dict]:
    try:
        return json.loads(cache_path(root).read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text.lower()) if w not in _GENERIC]


_HOST = re.compile(r"\b[a-z]{2,}[0-9]{2,}[a-z0-9]*\b")     # host/system name: crd01, lobdb01, xoss01, kiwi03


def _summary_codes(page: dict) -> set[str]:
    return set(_HOST.findall(re.sub(r"\([^)]*\)", "", page.get("summary", "").lower())))


def topic_matches(prompt: str, pages: list[dict], limit: int = 2) -> list[dict]:
    """Pages whose subject the prompt names: a code-like title token (digit or hyphen: gpml01, 3cx, socks5,
    xoagents01) or two title tokens together. Measured on 5,268 real prompts (2026-10-04): matching any
    title-unique word fired on 6.9% of prompts, mostly noise ("server", "pipeline"); this rule fires on 1.0%
    with mostly relevant hits. Recall is left to the full map (map arms).
    A code names the subject only when it leads the title: a code in parentheses is a qualifier (KIWI01 in
    "Plesk / Postfix Operations (KIWI01 / gyp.gr)" hosts many systems; 0/4 real kiwi01 prompts were about
    Plesk); it still counts as an ordinary title token. Not excluded: the session's own workspace name —
    GPML01 prompts come from a GPML01 workspace and the page helped there (replay 2026-10-04).
    A host name in the page's index.md summary also names its subject when at most 2 pages' summaries carry it
    ("LOBDB01 SQL estate: CRD01 disk cap" -> crd01): 6 of 7 questions about that page got no pointer from the
    title alone. Body text and sub-headings are not used: they mention hosts a page is not about (cardinal01 in
    an agora page). On 4,248 real prompts (2026-10-06) the pointer fires on 5.1% (was 3.65%); new hits checked by hand."""
    words = set(re.findall(r"[a-z0-9][a-z0-9\-]{2,}", (prompt or "").lower()))
    summary_codes = {p["id"]: _summary_codes(p) for p in pages}
    shared = {}
    for c in (c for s in summary_codes.values() for c in s):
        shared[c] = shared.get(c, 0) + 1
    hits = []
    for p in pages:
        toks = set(_tokens(p["title"]))
        qualifiers = set(_tokens(" ".join(re.findall(r"\(([^)]*)\)", p["title"]))))
        codes = {t for t in toks - qualifiers if (re.search(r"\d", t) or "-" in t)}
        codes |= {c for c in summary_codes[p["id"]] if shared[c] <= 2}
        if (codes & words) or len(toks & words) >= 2:
            hits.append(p)
    return hits[:limit]


def pointer_text(pages: list[dict]) -> str:
    items = "; ".join(f"{p['title']} — Read {p['path']}" for p in pages)
    return (f"[wiki] Relevant wiki page(s) for this request: {items}. "
            f"Open it before deciding on this subject and cite it; if it is stale or wrong, say so.")
