#!/usr/bin/env python3
"""
mnemo Correction Sweep — client-side, per-user, hourly (systemd timer).

Why this exists: the live UserPromptSubmit correction hook only fires in
INTERACTIVE sessions. Fleet users run headless cli+child / sdk sessions where it
never fires, and the async Stop-hook wrap almost never completes, so their
sessions close via server auto_wrap with zero correction signal — even though
their transcripts contain real corrections (measured: ~92 across 4 fleet users,
0 captured).

This sweep decouples correction capture from the flaky session-exit hook. It
scans FINISHED local transcripts, detects correction turns with the same
deterministic regex the live hook uses, pairs each correction to the tool action
that immediately preceded it (precise attribution), and records it via
/cli/record_lesson_miss — the primitive that derives a specific trigger, drafts
a pending guardrail, and marks the corpus. Passing the REAL tool action (not
tool_name="unknown") is what makes these misses yield validatable guardrails
rather than junk soft_instructions.

Idempotent: a per-session marker file guarantees each session is swept once.
Only sessions idle > STALE_MIN are processed (finished, won't grow). Fail-open.

urllib only (stdlib) — launched by bare python3; httpx is not guaranteed present.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# stdlib time is allowed here (real CLI script, not a workflow sandbox)
import time

log = logging.getLogger("mnemo-sweep")

STALE_MIN = int(os.getenv("MNEMO_SWEEP_STALE_MIN", "15"))
MAX_SESSIONS = int(os.getenv("MNEMO_SWEEP_MAX_SESSIONS", "200"))
STATE_DIR = Path(os.path.expanduser("~/.mnemo/swept"))
DRY_RUN = "--dry-run" in sys.argv

# ---------------------------------------------------------------------------
# Correction heuristic — shared with track-correction.py (bilingual EN/GR).
# Import the sibling module from the plugin dir; fall back to a no-op if absent.
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mnemo_correction_patterns import is_correction as _is_correction
except Exception:  # fail-open: never let a missing module break the sweep
    def _is_correction(_text: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# normalize_action — minimal port of app/tools/lessons.py:normalize_action
# so the action we send matches what evaluate_action logged (trigger derivation).
# ---------------------------------------------------------------------------

_CD_PREFIX = re.compile(r"^cd\s+\S+\s+&&\s+")
_SUDO_PREFIX = re.compile(r"^sudo\s+")
_TIME_PREFIX = re.compile(r"^time\s+")
_ENV_VAR_PREFIX = re.compile(r"^(?:[A-Z_][A-Z0-9_]*=[^\s]*\s+)+")
_SEGMENT_SPLITTER = re.compile(r"\s*(?:&&|;|\|\||\|)\s*")
_RUNNER_PREFIXES = re.compile(r"^(?:poetry\s+run|uv\s+run|npx|python\s+-m|pnpm\s+run|cargo\s+run)\b")


def _strip_wrappers(cmd: str) -> str:
    if _RUNNER_PREFIXES.match(cmd):
        return cmd
    changed = True
    while changed:
        changed = False
        for pat in (_SUDO_PREFIX, _TIME_PREFIX, _ENV_VAR_PREFIX):
            s = pat.sub("", cmd, count=1)
            if s != cmd:
                cmd = s.strip()
                changed = True
    return cmd


def normalize_action(tool_name: str, tool_input: dict) -> str | None:
    """Return a single normalized action string (or None if not matchable)."""
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return tool_input.get("file_path") or None
    if tool_name == "Bash":
        raw = tool_input.get("command", "")
    else:
        return None  # only Bash/Edit/Write actions yield derivable triggers
    raw = _CD_PREFIX.sub("", raw.strip())
    raw = re.sub(r"\s+", " ", raw).strip()
    segments = [_strip_wrappers(s.strip()) for s in _SEGMENT_SPLITTER.split(raw) if s.strip()]
    segments = [s for s in segments if s]
    if not segments:
        return None
    return " && ".join(segments)


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _tool_uses(content) -> list[tuple[str, dict]]:
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                out.append((b.get("name", ""), b.get("input", {}) or {}))
    return out


def pair_corrections(jsonl_path: Path) -> list[dict]:
    """Walk the transcript; for each correcting user turn, pair it with the most
    recent preceding tool action. Returns list of {tool_name, normalized_action,
    correction_text}. Prose-only corrections (no prior tool action) are skipped —
    nothing to guard."""
    pairs: list[dict] = []
    last_tool: tuple[str, str] | None = None  # (tool_name, normalized_action)
    try:
        lines = jsonl_path.read_text(errors="replace").splitlines()
    except Exception:
        return pairs
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if t not in ("user", "assistant"):
            continue
        msg = obj.get("message", {}) or {}
        content = msg.get("content", "")
        if t == "assistant":
            for name, tin in _tool_uses(content):
                na = normalize_action(name, tin)
                if na:
                    last_tool = (name, na)
            continue
        # user turn
        text = _text_of(content).strip()
        if not text:
            continue  # tool_result / non-prose user turn
        if _is_correction(text) and last_tool is not None:
            pairs.append({
                "tool_name": last_tool[0],
                "normalized_action": last_tool[1],
                "correction_text": text[:400],
            })
            last_tool = None  # one correction consumes the action it rejected
    return pairs


# ---------------------------------------------------------------------------
# Project resolution (mirror track-correction.py)
# ---------------------------------------------------------------------------

def _project_for(cwd: str | None) -> str | None:
    if not cwd:
        return None
    p = Path(cwd)
    for parent in [p, *p.parents]:
        mf = parent / ".mnemo-project"
        if mf.exists():
            try:
                return mf.read_text().strip() or None
            except Exception:
                return None
    return p.name or None


def _cwd_of(jsonl_path: Path) -> str | None:
    try:
        for line in jsonl_path.read_text(errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("cwd"):
                return obj["cwd"]
    except Exception:
        pass
    # fall back: reconstruct from the munged project-dir name (-home-user-...)
    name = jsonl_path.parent.name
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return None


# ---------------------------------------------------------------------------
# Config + POST
# ---------------------------------------------------------------------------

def _load_env() -> dict:
    for path in (os.path.expanduser("~/.claude/skills/mnemo/.env"), os.path.expanduser("~/.mnemo.env")):
        try:
            out = {}
            for line in open(path):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
            return out
        except Exception:
            pass
    return {}


_ENV = _load_env()
API_KEY = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_API_TOKEN")
    or os.getenv("MNEMO_HOOK_KEY") or _ENV.get("MNEMO_HOOK_KEY")
    or os.getenv("MNEMO_API_KEY") or _ENV.get("MNEMO_API_KEY", "")
)
BASE = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
    or os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{os.getenv('MNEMO_HOST') or _ENV.get('MNEMO_HOST', 'localhost')}:{os.getenv('MNEMO_PORT') or _ENV.get('MNEMO_PORT', '80')}"
).rstrip("/")


def _post(path: str, body: dict, session_id: str | None = None) -> bool:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    if session_id:
        headers["X-Session-Id"] = session_id
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            resp.read()
            return True
    except Exception as e:
        log.warning("%s failed: %s", path, e)
        return False


def _post_miss(project: str | None, session_id: str, pair: dict) -> bool:
    body = {
        "tool_name": pair["tool_name"],
        "normalized_action": pair["normalized_action"],
        "correction_text": pair["correction_text"],
        "session_id": session_id,
    }
    if project:
        body["project"] = project
    return _post("/cli/record_lesson_miss", body, session_id)


# --- LLM refinement trigger: register the session (activates it server-side) then
# wrap_session with session_text so the existing server-side Azure extraction runs
# (language-agnostic; higher precision than regex; also drafts anti_patterns and
# closes the session properly, fixing the auto_wrap-with-no-signal leak). ---

_MAX_TEXT = 40_000
_MAX_MSG = 3000


def _session_text(jsonl_path: Path) -> str:
    parts: list[str] = []
    total = 0
    try:
        lines = jsonl_path.read_text(errors="replace").splitlines()
    except Exception:
        return ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue
        txt = _text_of((obj.get("message", {}) or {}).get("content", "")).strip()
        if len(txt) < 5:
            continue
        prefix = "USER" if obj["type"] == "user" else "ASSISTANT"
        chunk = f"{prefix}: {txt[:_MAX_MSG]}"
        parts.append(chunk)
        total += len(chunk)
        if total > _MAX_TEXT:
            break
    return "\n\n".join(parts)


def _trigger_llm(project: str | None, session_id: str, cwd: str | None, n_regex: int, jsonl: Path) -> bool:
    text = _session_text(jsonl)
    if len(text) < 200:
        return False  # nothing substantive to extract
    reg = {"claude_session_id": session_id, "origin": "correction_sweep"}
    if project:
        reg["project"] = project
    _post("/cli/register_claude_session", reg, session_id)
    wrap = {
        "summary": "correction sweep (background)",
        "outcome": "partial",
        "corrections": n_regex,          # seeds the server extraction gate
        "project": project,
        "session_text": text,
        "auto_captured": True,
    }
    return _post("/cli/wrap_session", wrap, session_id)


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not API_KEY and not DRY_RUN:
        log.info("no API key — exit")
        return 0

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    projects_dir = Path(os.path.expanduser("~/.claude/projects"))
    if not projects_dir.exists():
        log.info("no projects dir — exit")
        return 0

    now = time.time()
    swept = recorded = sessions = 0
    for jsonl in sorted(projects_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        if sessions >= MAX_SESSIONS:
            break
        session_id = jsonl.stem
        marker = STATE_DIR / f"{session_id}.done"
        if marker.exists():
            continue
        # only finished (idle) sessions
        if (now - jsonl.stat().st_mtime) < STALE_MIN * 60:
            continue
        sessions += 1
        pairs = pair_corrections(jsonl)
        if pairs:
            cwd = _cwd_of(jsonl)
            project = _project_for(cwd)
            for pr in pairs:
                if DRY_RUN:
                    log.info("[dry-run] %s | proj=%s | tool=%s | action=%r | corr=%r",
                             session_id[:8], project, pr["tool_name"],
                             pr["normalized_action"][:80], pr["correction_text"][:60])
                    recorded += 1
                elif _post_miss(project, session_id, pr):
                    recorded += 1
            # LLM refinement pass (language-agnostic, higher precision): only for
            # correction-bearing sessions the regex flagged — bounds Azure cost.
            if DRY_RUN:
                log.info("[dry-run] %s | would trigger LLM wrap (corrections=%d)",
                         session_id[:8], len(pairs))
            else:
                _trigger_llm(project, session_id, cwd, len(pairs), jsonl)
        if not DRY_RUN:
            try:
                marker.write_text(str(int(now)))
            except Exception:
                pass
        swept += 1
    log.info("sweep done: sessions_examined=%d swept=%d corrections_recorded=%d dry_run=%s",
             sessions, swept, recorded, DRY_RUN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
