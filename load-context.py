#!/usr/bin/env python3
"""
mnemo Auto-Prime SessionStart Hook

Fires at every session start. Calls mnemo get_memories (browse mode) and injects
the top memories as additionalContext so Claude starts each session with relevant
knowledge loaded — without needing a manual /mnemo:memload command.

Install: Claude plugin (gremos/mnemo-client). Configured via plugin userConfig.
Fails gracefully: exits 0 silently if mnemo is unreachable or key is missing.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Read hook input
# ---------------------------------------------------------------------------

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)

session_id = payload.get("session_id", "")
cwd = payload.get("cwd", "")
source = payload.get("source", "startup")

# Don't re-prime on compact/clear — only on genuine session start or resume
if source in ("compact", "clear"):
    sys.exit(0)

# ---------------------------------------------------------------------------
# Resolve config: plugin env vars > legacy env files
# ---------------------------------------------------------------------------

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

api_key = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_API_TOKEN")
    or os.getenv("MNEMO_HOOK_KEY") or _env.get("MNEMO_HOOK_KEY")
    or os.getenv("MNEMO_ADMIN_TOKEN") or _env.get("MNEMO_ADMIN_TOKEN")
    or os.getenv("MNEMO_API_KEY") or _env.get("MNEMO_API_KEY", "")
)
if not api_key:
    sys.exit(0)

_mnemo_base = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
    or os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{os.getenv('MNEMO_HOST') or _env.get('MNEMO_HOST', 'localhost')}:{os.getenv('MNEMO_PORT') or _env.get('MNEMO_PORT', '80')}"
).rstrip("/")
MCP_URL = _mnemo_base + "/mcp/"

wiki_paths_raw = os.getenv("MNEMO_WIKI_PATHS") or _env.get("MNEMO_WIKI_PATHS", "")

# ---------------------------------------------------------------------------
# pc_id — persisted in plugin data dir, survives plugin updates
# ---------------------------------------------------------------------------

_plugin_data_dir = os.environ.get("CLAUDE_PLUGIN_DATA", os.path.expanduser("~/.mnemo"))
_pc_config_path = os.path.join(_plugin_data_dir, "config.json")
_pc_config: dict = {}
try:
    with open(_pc_config_path) as _cf:
        _pc_config = json.load(_cf)
except Exception:
    pass

_pc_id: str = _pc_config.get("pc_id", "")
if not _pc_id:
    # Try legacy location
    try:
        _pc_id = json.load(open(os.path.expanduser("~/.mnemo/config.json"))).get("pc_id", "")
    except Exception:
        pass
if not _pc_id:
    _pc_id = str(uuid.uuid4())
    try:
        os.makedirs(_plugin_data_dir, exist_ok=True)
        _pc_config["pc_id"] = _pc_id
        with open(_pc_config_path, "w") as _cf:
            json.dump(_pc_config, _cf)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Derive project name from cwd + git context for query-aware priming
# ---------------------------------------------------------------------------

_project_file = os.path.join(cwd, ".mnemo-project") if cwd else None
if _project_file and os.path.isfile(_project_file):
    project = open(_project_file).read().strip() or os.path.basename(cwd.rstrip("/"))
else:
    project = os.path.basename(cwd.rstrip("/")) if cwd else None

def _mnemo_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    try:
        if "microsoft" in open("/proc/version").read().lower():
            return "wsl"
    except Exception:
        pass
    return "linux"

_project_wiki_path: str = ""
_project_wiki_scope: str = "user"
if cwd:
    _platform = _mnemo_platform()
    _d = cwd
    for _ in range(8):
        _wf = os.path.join(_d, ".mnemo-wiki")
        if os.path.isfile(_wf):
            try:
                _wf_lines = open(_wf).read().splitlines()
                _fallback = ""
                for _l in _wf_lines:
                    _l = _l.strip()
                    if not _l or _l.startswith("#"):
                        continue
                    if "=" in _l:
                        _k, _v = _l.split("=", 1)
                        _k = _k.strip()
                        if _k == _platform:
                            _project_wiki_path = os.path.expanduser(_v.strip())
                        elif _k == "scope":
                            _project_wiki_scope = _v.strip()
                    elif not _fallback:
                        _fallback = os.path.expanduser(_l)
                if not _project_wiki_path:
                    _project_wiki_path = _fallback
            except Exception:
                pass
            break
        _parent = os.path.dirname(_d)
        if _parent == _d:
            break
        _d = _parent

_query: str | None = None
_recent_paths: list[str] = []
_start_sha: str = ""

if cwd and os.path.isdir(cwd):
    try:
        import subprocess
        _branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=cwd, timeout=2,
        ).stdout.strip()
        _log = subprocess.run(
            ["git", "log", "--oneline", "-5", "--no-merges"],
            capture_output=True, text=True, cwd=cwd, timeout=2,
        ).stdout.strip()
        _diff_out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~5..HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=2,
        ).stdout.strip()
        _recent_paths = [p for p in _diff_out.splitlines() if p]
        _sha_out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=2,
        ).stdout.strip()
        _start_sha = _sha_out[:40] if _sha_out else ""

        _path_terms = list(dict.fromkeys(
            os.path.splitext(os.path.basename(p))[0].replace("_", " ").replace("-", " ")
            for p in _recent_paths
        ))[:5]
        _parts = [p for p in [project, _branch, _log] + _path_terms if p]
        if _parts:
            _query = " ".join(_parts)[:300]
    except Exception:
        pass

# Fallback when there's no git context (e.g. claude launched from a non-repo dir like
# ~): seed the query from the project/cwd name so search_wiki and query-aware retrieval
# still fire instead of being skipped entirely. Engineers launching from $HOME were
# getting zero wiki retrieval because _query stayed None.
if not _query and project:
    _query = project

if session_id and _start_sha:
    try:
        _sidecar = str(Path(tempfile.gettempdir()) / f"mnemo-session-{session_id[:8]}.start")
        with open(_sidecar, "w") as _sf:
            _sf.write(json.dumps({"sha": _start_sha, "cwd": cwd}))
    except Exception:
        pass

# Auto-install compile-wiki scheduler on first plugin use (fail-silent, never blocks session start)
_COMPILE_WIKI_SENTINEL = Path.home() / ".local/share/compile-wiki-auto/.installed"
if not _COMPILE_WIKI_SENTINEL.exists():
    try:
        import importlib.util as _ilu
        _setup_script = Path(__file__).parent / "compile-wiki-setup.py"
        if _setup_script.exists():
            _spec = _ilu.spec_from_file_location("compile_wiki_setup", _setup_script)
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _mod.main()
    except Exception:
        pass

# Self-heal settings.json.mcpServers from ~/.mnemo.env (survives plugin install/update).
# MCP is initialized before hooks run, so this write takes effect on the NEXT restart.
try:
    import importlib.util as _ilu2
    _setup_script2 = Path(__file__).parent / "compile-wiki-setup.py"
    if _setup_script2.exists():
        _spec2 = _ilu2.spec_from_file_location("compile_wiki_setup2", _setup_script2)
        _mod2 = _ilu2.module_from_spec(_spec2)
        _spec2.loader.exec_module(_mod2)
        _mod2.setup_mcp_config()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Wiki pointer scanner
# ---------------------------------------------------------------------------

def _get_wiki_roots(wd: str) -> list[str]:
    if _project_wiki_path:
        return [_project_wiki_path]
    if wiki_paths_raw:
        return [os.path.expanduser(p.strip()) for p in wiki_paths_raw.split(":") if p.strip()]
    if wd:
        if "/XO/" in wd:
            return [os.path.expanduser("~/Documents/code/XO/wiki")]
        if "/Personal/" in wd:
            return [os.path.expanduser("~/Documents/code/Personal/wiki")]
        return [
            os.path.expanduser("~/Documents/code/XO/wiki"),
            os.path.expanduser("~/Documents/code/Personal/wiki"),
        ]
    return []


def _scan_wiki_pointers(proj: str | None, wd: str, rpaths: list[str]) -> list[dict]:
    wiki_candidates = _get_wiki_roots(wd)
    path_kws = {
        os.path.splitext(os.path.basename(p))[0].lower().replace("_", "-")
        for p in rpaths
    }
    proj_kw = (proj or "").lower()
    results: list[dict] = []

    for root in wiki_candidates:
        for subdir in ("raw", os.path.join("raw", "auto"), ""):
            scan_dir = os.path.join(root, subdir) if subdir else root
            if not os.path.isdir(scan_dir):
                continue
            for fname in os.listdir(scan_dir):
                if not fname.endswith(".md") or fname.startswith("_") or fname in ("index.md", "log.md"):
                    continue
                fpath = os.path.join(scan_dir, fname)
                try:
                    with open(fpath, errors="replace") as _fh:
                        head = _fh.read(600)
                except Exception:
                    continue

                fm_text = ""
                if head.startswith("---"):
                    end = head.find("---", 3)
                    if end > 0:
                        fm_text = head[3:end].lower()

                title = fname.replace(".md", "").replace("-", " ")
                for _line in head.splitlines():
                    if _line.startswith("# "):
                        title = _line[2:].strip()
                        break

                score = 0
                if proj_kw and proj_kw in (fm_text + fname.lower()):
                    score += 3
                for kw in path_kws:
                    if kw in fm_text or kw in fname.lower():
                        score += 2
                if len(fname) >= 10 and fname[:4].isdigit():
                    try:
                        import datetime
                        days_old = (datetime.date.today() - datetime.date.fromisoformat(fname[:10])).days
                        score += 2 if days_old < 30 else (1 if days_old < 90 else 0)
                    except Exception:
                        pass

                if score > 0:
                    display = fpath.replace(os.path.expanduser("~"), "~")
                    results.append({"path": display, "title": title, "score": score})

    results.sort(key=lambda r: -r["score"])
    return results[:3]

# ---------------------------------------------------------------------------
# Call mnemo via MCP
# ---------------------------------------------------------------------------

def _parse_sse(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return {}

memories: list = []
pending_memories: list = []
active_lessons: list = []
wiki_hits: list = []

try:
    import httpx

    with httpx.Client(timeout=4) as client:
        init_resp = client.post(
            MCP_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "auto-prime-hook", "version": "1.0"},
                },
            },
        )
        init_resp.raise_for_status()
        mcp_session_id = init_resp.headers.get("mcp-session-id", "")

        _mcp_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {api_key}",
            "MCP-Session-Id": mcp_session_id,
            "X-Tool-Name": "auto_prime",
        }
        # Attribute every prime call to the real Claude session. Without this the
        # server fell back to Redis active-session (set only if worklog registered
        # first), so auto_prime / search_wiki under-logged — making coverage look
        # far lower than it is. session_id is always known here.
        if session_id:
            _mcp_headers["X-Session-Id"] = session_id
        if _pc_id:
            _mcp_headers["X-PC-Id"] = _pc_id

        # NB: no register_claude_session call — it is a /cli-only endpoint, not an MCP
        # tool, so the MCP tools/call always failed (wasted round-trip). Session
        # attribution now rides the X-Session-Id header set above.

        args: dict = {"limit": 15, "scope": "both"}
        if _query:
            args["query"] = _query
            args["min_importance"] = 4
        else:
            args["min_importance"] = 5
        if project:
            args["project"] = project

        mem_resp = client.post(
            MCP_URL,
            headers=_mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 2,
                "method": "tools/call",
                "params": {"name": "get_memories", "arguments": args},
            },
        )
        mem_resp.raise_for_status()

        data = _parse_sse(mem_resp.text)
        content = data.get("result", {}).get("content", [])
        if isinstance(content, list) and content:
            raw = content[0].get("text", "[]")
            memories = json.loads(raw) if isinstance(raw, str) else []

        # Semantic wiki retrieval — runs 2nd (right after memories) so it fits inside the
        # 5s hook budget even on slow network paths; it was the last of 6 calls before and
        # got truncated for engineers. Best-effort: a wiki failure must not abort the prime
        # (pending/lessons/brief still run). The fs-pointer scan later injects file PATHS;
        # this surfaces page CONTENT by meaning, using the project/git-derived query.
        if _query:
            try:
                wiki_resp = client.post(
                    MCP_URL,
                    headers=_mcp_headers,
                    json={
                        "jsonrpc": "2.0", "id": 5,
                        "method": "tools/call",
                        "params": {"name": "search_wiki",
                                   "arguments": {"query": _query, "limit": 3}},
                    },
                )
                wiki_resp.raise_for_status()
                wiki_data = _parse_sse(wiki_resp.text)
                wiki_content = wiki_data.get("result", {}).get("content", [])
                if isinstance(wiki_content, list) and wiki_content:
                    raw = wiki_content[0].get("text", "[]")
                    wiki_hits = json.loads(raw) if isinstance(raw, str) else []
            except Exception:
                pass

        pending_args: dict = {"limit": 5, "scope": "both", "tags": ["pending_review"]}
        if project:
            pending_args["project"] = project
        pending_resp = client.post(
            MCP_URL,
            headers=_mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 3,
                "method": "tools/call",
                "params": {"name": "get_memories", "arguments": pending_args},
            },
        )
        pending_resp.raise_for_status()
        pending_data = _parse_sse(pending_resp.text)
        pending_content = pending_data.get("result", {}).get("content", [])
        if isinstance(pending_content, list) and pending_content:
            raw = pending_content[0].get("text", "[]")
            pending_memories = json.loads(raw) if isinstance(raw, str) else []

        lessons_args: dict = {}
        if project:
            lessons_args["project"] = project
        lessons_resp = client.post(
            MCP_URL,
            headers=_mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 4,
                "method": "tools/call",
                "params": {"name": "get_active_lessons", "arguments": lessons_args},
            },
        )
        lessons_resp.raise_for_status()
        lessons_data = _parse_sse(lessons_resp.text)
        lessons_content = lessons_data.get("result", {}).get("content", [])
        if isinstance(lessons_content, list) and lessons_content:
            raw = lessons_content[0].get("text", "[]")
            active_lessons = json.loads(raw) if isinstance(raw, str) else []

except Exception:
    sys.exit(0)

# ---------------------------------------------------------------------------
# Format context string
# ---------------------------------------------------------------------------

def _type_priority(m: dict) -> int:
    return {"anti-pattern": 0, "decision": 1, "primer": 2,
            "solution": 3, "command": 4, "note": 5, "episode": 6}.get(m.get("type", "note"), 5)

memories_sorted = sorted(memories, key=lambda m: (_type_priority(m), -m.get("importance", 5)))

pitfalls = [m for m in memories_sorted if m.get("type") == "anti-pattern"]
context_mems = [m for m in memories_sorted if m.get("type") != "anti-pattern"]

CHAR_BUDGET = 2000
char_used = 0

pitfall_lines = []
for m in pitfalls:
    imp = m.get("importance", "?")
    preview = m.get("preview", "")[:200].replace("\n", " ")
    line = f"    • [imp={imp}] {preview}"
    if char_used + len(line) > CHAR_BUDGET:
        break
    pitfall_lines.append(line)
    char_used += len(line)

context_lines = []
for m in context_mems:
    type_ = m.get("type", "note")
    imp = m.get("importance", "?")
    preview = m.get("preview", "")[:80].replace("\n", " ")
    line = f"    • [{type_}, imp={imp}] {preview}"
    if char_used + len(line) > CHAR_BUDGET:
        break
    context_lines.append(line)
    char_used += len(line)

directive_lines: list[str] = []
for _les in active_lessons[:5]:
    _sev = _les.get("severity", "warn")
    _directive = (_les.get("directive") or "")[:160].replace("\n", " ")
    if not _directive:
        continue
    _prefix = "DENY" if _sev == "deny" else "warn"
    _dline = f"    • [{_prefix}] {_directive}"
    if char_used + len(_dline) > CHAR_BUDGET:
        break
    directive_lines.append(_dline)
    char_used += len(_dline)

proj_label = f'"{project}"' if project else "all projects"
if not pitfall_lines and not context_lines and not directive_lines:
    lines = [f'[mnemo] No memories loaded (project={proj_label}). Use save_memory to start building context.']
else:
    lines = [f"[mnemo] Session brief for {proj_label}:"]
    if directive_lines:
        omitted_d = len(active_lessons) - len(directive_lines)
        suffix = f" (+{omitted_d} omitted)" if omitted_d else ""
        lines.append(f"  Active directives — ENFORCED{suffix}:")
        lines.extend(directive_lines)
    if pitfall_lines:
        omitted_p = len(pitfalls) - len(pitfall_lines)
        suffix = f" (+{omitted_p} omitted)" if omitted_p else ""
        lines.append(f"  Known pitfalls — CHECK BEFORE EXECUTING{suffix}:")
        lines.extend(pitfall_lines)
    if context_lines:
        omitted_c = len(context_mems) - len(context_lines)
        suffix = f" (+{omitted_c} omitted)" if omitted_c else ""
        lines.append(f"  Context{suffix}:")
        lines.extend(context_lines)

if pending_memories:
    pending_budget = 400
    pending_used = 0
    pending_lines = []
    for m in pending_memories:
        type_ = m.get("type", "note")
        imp = m.get("importance", "?")
        preview = m.get("preview", "")[:150].replace("\n", " ")
        line = f"    • [{type_}, imp={imp}] {preview}"
        if pending_used + len(line) > pending_budget:
            break
        pending_lines.append(line)
        pending_used += len(line)
    if pending_lines:
        lines.append("\n  Pending rules (review → add to CLAUDE.md):")
        lines.extend(pending_lines)
        if len(pending_lines) < len(pending_memories):
            lines.append(f"  (+{len(pending_memories) - len(pending_lines)} more — get_memories(tags=[\"pending_review\"]))")

# Semantic wiki hits (page excerpts by meaning) rank above raw file pointers below.
if wiki_hits:
    wh_budget = 600
    wh_used = 0
    wh_lines = []
    for w in wiki_hits:
        body = w.get("preview") or w.get("content") or ""
        # Skip leading YAML frontmatter (--- … ---) so the excerpt is prose, not tags.
        if body.lstrip().startswith("---"):
            _rest = body.lstrip()[3:]
            _end = _rest.find("---")
            if _end != -1:
                body = _rest[_end + 3:]
        excerpt = body.lstrip("# \n").replace("\n", " ").strip()[:180]
        if not excerpt:
            continue
        line = f"    • {excerpt}"
        if wh_used + len(line) > wh_budget:
            break
        wh_lines.append(line)
        wh_used += len(line)
    if wh_lines:
        lines.append("  Wiki (semantic search — page excerpts):")
        lines.extend(wh_lines)

wiki_ptrs = _scan_wiki_pointers(project, cwd, _recent_paths)
if wiki_ptrs:
    wiki_budget = 300
    wiki_used = 0
    wiki_lines = []
    for wp in wiki_ptrs:
        line = f"    • {wp['path']} — {wp['title']}"
        if wiki_used + len(line) > wiki_budget:
            break
        wiki_lines.append(line)
        wiki_used += len(line)
    if wiki_lines:
        lines.append("  Wiki context (Read if relevant):")
        lines.extend(wiki_lines)

_wiki_roots_active = _get_wiki_roots(cwd) if cwd else []
_index_budget = 500
_index_used = 0
for _wr in _wiki_roots_active[:2]:
    _idx_path = os.path.join(_wr, "index.md")
    if not os.path.isfile(_idx_path):
        continue
    try:
        _idx_raw = open(_idx_path, errors="replace").read(_index_budget - _index_used + 200)
    except Exception:
        continue
    _wiki_name = os.path.basename(_wr)
    _idx_lines = [f"    {l}" for l in _idx_raw.splitlines() if l.strip()][:18]
    if not _idx_lines:
        continue
    _block_lines = [f"  Wiki index ({_wiki_name}):"] + _idx_lines
    _block_str = "\n".join(_block_lines)
    if _index_used + len(_block_str) > _index_budget:
        remaining = _index_budget - _index_used
        if remaining > 80:
            _block_str = _block_str[:remaining].rsplit("\n", 1)[0] + "\n    …"
        else:
            break
    lines.append(_block_str)
    _index_used += len(_block_str)
    if _index_used >= _index_budget:
        break

_pending_wikis: list[str] = []
for _wr in _wiki_roots_active[:2]:
    _auto_dir = os.path.join(_wr, "raw", "auto")
    if not os.path.isdir(_auto_dir):
        continue
    _count = sum(1 for f in os.listdir(_auto_dir) if f.endswith(".md"))
    if _count:
        _pending_wikis.append(f"{os.path.basename(_wr)} ({_count})")
if _pending_wikis:
    lines.append(f"  Wiki drafts pending compile: {', '.join(_pending_wikis)} — run compile-wiki from the wiki root to update")

# Promote the fused memory+wiki retrieval primitive. recall() blends both into one
# cited answer with gap analysis; without this signpost the model calls get_memories
# and search_wiki separately and never uses the fusion (observed: 0 recall calls fleet-wide).
if pitfall_lines or context_lines or wiki_hits:
    lines.append('  → recall("your question") — one cited answer synthesized over memory + wiki; prefer it over separate get_memories + search_wiki for a specific question.')

context = "\n".join(lines)

# Prepend setup hint if ~/.mnemo.env is missing (new install or unconfigured machine)
if not (Path.home() / ".mnemo.env").exists():
    _plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "~/.claude/plugins/mnemo-current")
    _hint = (
        f"⚠️  Mnemo not configured. Run to set up:\n"
        f"  bash {_plugin_root}/mnemo-setup.sh <server_url> <api_token>\n"
        f"  # Example: bash {_plugin_root}/mnemo-setup.sh http://localhost mcp_admin_token\n"
        f"Then restart Claude Code."
    )
    context = _hint + ("\n\n" + context if context else "")

# ---------------------------------------------------------------------------
# Output JSON for Claude Code to inject as additionalContext
# ---------------------------------------------------------------------------

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }
}))
sys.exit(0)
