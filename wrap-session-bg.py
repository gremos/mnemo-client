#!/usr/bin/env python3
"""
mnemo Background Mend Script

Called by the Stop hook after Claude exits. Reads the session conversation JSONL,
sends the text to Azure OpenAI for structured extraction (corrections, approvals,
outcome, summary, wiki_summary), then calls wrap_session via the Mnemo MCP API.

If AZURE_OPENAI_* credentials are not set locally, the raw conversation text is sent
to the server via the session_text param and extraction happens server-side.

Runs fully detached — no user delay, no Claude token cost.

Usage (from hook):
    python3 mnemo-mend-bg.py <session_id> <cwd>

Requires env vars (from ~/.mnemo.env or environment):
    MNEMO_HOOK_KEY (or MNEMO_ADMIN_TOKEN), MNEMO_HOST, MNEMO_PORT

Optional (Azure extraction runs locally if set; otherwise delegated to server):
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_VERSION
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow importing sibling modules (mnemo_wiki_resolver, mnemo_wiki_write)
_plugin_dir = Path(__file__).parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))

# ---------------------------------------------------------------------------
# Logging — writes to /tmp so it's visible for debugging without cluttering repo
# ---------------------------------------------------------------------------
session_id = sys.argv[1] if len(sys.argv) > 1 else "unknown"
log_path = str(Path(tempfile.gettempdir()) / f"mnemo-mend-{session_id[:8]}.log")
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("mnemo-mend")

# ---------------------------------------------------------------------------
# Resolve config
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

def _cfg(key: str, default: str = "") -> str:
    return os.getenv(key) or _env.get(key, default)

AZURE_ENDPOINT   = _cfg("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY    = _cfg("AZURE_OPENAI_API_KEY")
AZURE_DEPLOYMENT = _cfg("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
AZURE_API_VER    = _cfg("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
MNEMO_KEY = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_API_TOKEN")
    or _cfg("MNEMO_HOOK_KEY") or _cfg("MNEMO_ADMIN_TOKEN") or _cfg("MNEMO_API_KEY")
)
_mnemo_base = (
    os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
    or os.getenv("MCP_URL", "").replace("/mcp/", "").rstrip("/")
    or f"http://{_cfg('MNEMO_HOST', 'localhost')}:{_cfg('MNEMO_PORT', '80')}"
).rstrip("/")
MCP_URL = _mnemo_base + "/mcp/"
CLI_BASE = _mnemo_base

# pc_id — read from plugin data dir (survives plugin updates)
_plugin_data_dir = os.environ.get("CLAUDE_PLUGIN_DATA", os.path.expanduser("~/.mnemo"))
_pc_config: dict = {}
try:
    with open(os.path.join(_plugin_data_dir, "config.json")) as _cf:
        _pc_config = json.load(_cf)
except Exception:
    pass
PC_ID: str = _pc_config.get("pc_id", "") or ""

# ---------------------------------------------------------------------------
# Conversation JSONL helpers
# ---------------------------------------------------------------------------

def _encode_cwd(cwd: str) -> str:
    """Replicate Claude Code's project directory encoding: non-alphanum → '-'."""
    return re.sub(r"[^a-zA-Z0-9.]", "-", cwd)


def _find_jsonl(session_id: str, cwd: str) -> Path | None:
    projects_dir = Path.home() / ".claude" / "projects"
    encoded = _encode_cwd(cwd)
    candidate = projects_dir / encoded / f"{session_id}.jsonl"
    if candidate.exists():
        return candidate
    # Fallback: search all project dirs for this session_id
    for f in projects_dir.rglob(f"{session_id}.jsonl"):
        return f
    return None


def _extract_text(content) -> str:
    """Flatten content (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def _load_conversation(jsonl_path: Path, max_messages: int = 80) -> list[dict]:
    """Load the last N user/assistant messages from the session JSONL."""
    messages = []
    try:
        for line in jsonl_path.read_text(errors="replace").splitlines():
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
            msg = obj.get("message", {})
            role = msg.get("role", t)
            text = _extract_text(msg.get("content", "")).strip()
            if text:
                messages.append({"role": role, "text": text})
    except Exception as e:
        log.warning("Failed to read JSONL: %s", e)
    return messages[-max_messages:]


_SYSTEM_NOISE_PATTERNS = [
    re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.DOTALL),
    re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.DOTALL),
    re.compile(r"<command-name>.*?</command-name>", re.DOTALL),
    re.compile(r"<command-message>.*?</command-message>", re.DOTALL),
    re.compile(r"<command-args>.*?</command-args>", re.DOTALL),
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
    re.compile(r"<task-notification>.*?</task-notification>", re.DOTALL),
]

_SKILL_BOILERPLATE_RE = re.compile(
    r"^Base directory for this skill:.*?(?=ARGUMENTS:|$)", re.DOTALL
)


def _clean_message(text: str) -> str:
    """Strip system-injected noise (skill boilerplate, XML tags, command output)."""
    for pat in _SYSTEM_NOISE_PATTERNS:
        text = pat.sub("", text)

    # Skill instruction blocks — keep only the ARGUMENTS: line
    m = _SKILL_BOILERPLATE_RE.search(text)
    if m:
        args_match = re.search(r"ARGUMENTS:\s*(.+)", text[m.start():], re.DOTALL)
        text = text[:m.start()] + (args_match.group(1).strip() if args_match else "")

    # Context continuation — strip the preamble, keep the summary
    if text.lstrip().startswith("This session is being continued from"):
        lines = text.split("\n", 3)
        text = lines[3] if len(lines) > 3 else ""

    return text.strip()


_MAX_CONVERSATION_CHARS = 40_000
_MAX_MESSAGE_CHARS = 3000


def _build_conversation_text(messages: list[dict]) -> str:
    cleaned = []
    for m in messages:
        text = _clean_message(m["text"])
        if len(text) < 5:
            continue
        prefix = "USER" if m["role"] == "user" else "ASSISTANT"
        cleaned.append((prefix, text[:_MAX_MESSAGE_CHARS]))

    # Budget: prioritize user messages, keep first + last if over budget
    total = sum(len(t) for _, t in cleaned)
    if total > _MAX_CONVERSATION_CHARS:
        user_msgs = [(i, p, t) for i, (p, t) in enumerate(cleaned) if p == "USER"]
        asst_msgs = [(i, p, t) for i, (p, t) in enumerate(cleaned) if p == "ASSISTANT"]
        # Keep all user messages, trim assistant messages from the middle
        budget_left = _MAX_CONVERSATION_CHARS - sum(len(t) for _, _, t in user_msgs)
        if budget_left > 0 and asst_msgs:
            keep_n = max(2, len(asst_msgs) * budget_left // sum(len(t) for _, _, t in asst_msgs))
            half = max(1, keep_n // 2)
            kept_asst = asst_msgs[:half] + asst_msgs[-half:]
        else:
            kept_asst = []
        all_kept = sorted(user_msgs + kept_asst, key=lambda x: x[0])
        cleaned = [(p, t) for _, p, t in all_kept]

    return "\n\n".join(f"{p}: {t}" for p, t in cleaned)

# ---------------------------------------------------------------------------
# Azure OpenAI extraction
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = """\
You analyze Claude Code conversation logs to extract RL feedback signals for a memory system.

Count only clear, unambiguous signals from the USER — not from system-injected content.

Return ONLY valid JSON with these fields:
- corrections (int): count of times the user explicitly corrects or rejects Claude's action.
  Examples that ARE corrections:
    - "no, use X instead" / "wrong approach" / "don't do that" / "undo" / "that's not what I asked"
    - User interrupts and redirects: "[Request interrupted by user]" followed by a different instruction
  Examples that are NOT corrections:
    - The word "no" inside a description or technical context (e.g. "no re-poll for new records")
    - Skill instruction text containing words like "don't" or "stop" (these are system boilerplate)
    - User providing new information or clarifications (not a rejection of Claude's work)
- approvals (int): count of explicit user approvals of non-obvious Claude decisions.
  Examples: "yes", "perfect", "exactly", "proceed", "approved", accepting a plan, "looks good"
  NOT approvals: "ok" as acknowledgement, "continue" without context, routine confirmations
- outcome (str): "success" if main task completed satisfactorily,
  "failure" if abandoned or blocked, "partial" if incomplete or mixed
- summary (str): one concise sentence describing what was accomplished
- anti_patterns (list[str]): specific wrong commands or approaches Claude tried that the user
  corrected. Each entry should be a short description. Empty list if none.
- decisions (list[str]): key architectural or design decisions made during the session.
  Each entry should be a short description. Empty list if none.
- wiki_summary (str|null): if the session accomplished something worth preserving as
  institutional knowledge (fixed a real bug, made an architectural decision, discovered
  a pattern, solved a complex problem, changed infra) write a 2-4 sentence summary
  suitable for a technical wiki. Omit credentials, IPs, tokens, UUIDs. If the session was
  routine, trivial, or mostly exploratory with no concrete outcome, return null.
- memory_helped (bool|null): did content retrieved from the memory system (session-start
  context, get_memories/search_wiki results, cited anti-patterns or wiki pages) visibly
  change what Claude did — avoided a repeat mistake, supplied the right file/pattern/
  context faster? Judge only from what's actually visible in the log. null if no memory
  content was retrieved at all, or if it's genuinely unclear either way — don't guess.

Example: {"corrections": 1, "approvals": 2, "outcome": "success",
  "summary": "Implemented X feature and fixed Y bug.",
  "anti_patterns": ["Used git push --force instead of --force-with-lease"],
  "decisions": ["Chose PostgreSQL over Redis for persistence layer"],
  "wiki_summary": "Fixed Docker networking issue by inserting ACCEPT rules at top of FORWARD chain before Cisco VPN drop rules.",
  "memory_helped": true}
"""

def _call_azure(conversation_text: str) -> dict:
    try:
        from openai import AzureOpenAI
    except ImportError:
        log.error("openai package not installed. Run: pip install openai")
        raise

    client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
        api_version=AZURE_API_VER,
    )

    response = client.chat.completions.create(
        model=AZURE_DEPLOYMENT,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user", "content": f"Conversation:\n\n{conversation_text}"},
        ],
        max_tokens=512,
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result = json.loads(raw)
    log.info("Azure extraction: %s", result)
    return result

# ---------------------------------------------------------------------------
# Mnemo REST /cli/* calls (cold path) + MCP calls (hot path: save_memory)
# ---------------------------------------------------------------------------

def _parse_sse(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except Exception:
                pass
    return {}


def _cli_headers() -> dict:
    h = {"Content-Type": "application/json", "Authorization": f"Bearer {MNEMO_KEY}"}
    if PC_ID:
        h["X-PC-Id"] = PC_ID
    return h


def _wrap_session(session_id: str, project: str, summary: str, outcome: str,
                  corrections: int | None, approvals: int,
                  session_text: str | None = None,
                  memory_helped: bool | None = None) -> dict | None:
    """Call /cli/register_claude_session + /cli/wrap_session REST endpoints."""
    try:
        import httpx
    except ImportError:
        log.error("httpx not installed")
        return None

    timeout = 30 if session_text else 8
    try:
        with httpx.Client(timeout=timeout) as client:
            # Register session so wrap_session attributes the episode correctly
            client.post(
                CLI_BASE + "/cli/register_claude_session",
                headers=_cli_headers(),
                json={"claude_session_id": session_id},
            )

            body: dict = {
                "summary": summary,
                "outcome": outcome,
                "corrections": corrections,
                "approvals": approvals,
                "project": project,
                "tags": ["auto-mend"],
            }
            if session_text:
                body["session_text"] = session_text
            if memory_helped is not None:
                body["memory_helped"] = memory_helped

            resp = client.post(
                CLI_BASE + "/cli/wrap_session",
                headers=_cli_headers(),
                json=body,
            )
            resp.raise_for_status()
            result_obj = resp.json()
            log.info("wrap_session response: %s", str(result_obj)[:200])
            return result_obj

    except Exception as e:
        log.error("wrap_session failed: %s", e)
        return None

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_AP_KNOWN_PROGS = {
    "git", "docker", "kubectl", "python", "python3", "bash", "sh", "zsh",
    "kill", "killall", "rm", "pip", "pip3", "npm", "npx", "node", "az",
    "curl", "wget", "scp", "ssh", "psql", "systemctl", "make", "terraform",
}
_AP_TWO_TOKEN_PROGS = {
    "git", "docker", "kubectl", "npm", "npx", "az", "pip", "pip3",
    "terraform", "systemctl", "make",
}
_AP_BACKTICK_RE = re.compile(r"`([^`]+)`")
_AP_PLACEHOLDER_RE = re.compile(r"\s*<[^>]+>")
_AP_PROG_RE = re.compile(
    r"\b(git|docker|kubectl|python3?|bash|sh|rm|kill(?:all)?|pip3?|npm|npx|az|curl|scp|ssh"
    r"|psql|systemctl|make|terraform)\s+\S+",
    re.IGNORECASE,
)


def _extract_ap_trigger(description: str) -> str | None:
    """Extract a JIT trigger pattern from an anti-pattern description string."""
    for m in _AP_BACKTICK_RE.finditer(description):
        cmd = _AP_PLACEHOLDER_RE.sub("", m.group(1)).strip()
        if not cmd:
            continue
        tokens = cmd.split()
        prog = tokens[0].lower().lstrip("./").split("/")[-1]
        if prog in _AP_KNOWN_PROGS:
            n = 2 if prog in _AP_TWO_TOKEN_PROGS and len(tokens) >= 2 else 1
            return " ".join(tokens[:n])[:80]
    m = _AP_PROG_RE.search(description)
    if m:
        tokens = m.group(0).strip().split()
        prog = tokens[0].lower()
        n = 2 if prog in _AP_TWO_TOKEN_PROGS and len(tokens) >= 2 else 1
        return " ".join(tokens[:n])[:80]
    return None


def _draft_lessons_from_anti_patterns(anti_patterns: list[str], project: str) -> None:
    """POST /cli/draft_lesson for each anti-pattern. Fail-silent."""
    if not anti_patterns or not MNEMO_KEY:
        return
    try:
        import httpx
    except ImportError:
        return
    try:
        with httpx.Client(timeout=8) as client:
            for ap in anti_patterns[:5]:
                directive = f"Avoid: {ap[:200]}"
                rationale = "Auto-drafted from session anti-pattern extraction."
                trigger = _extract_ap_trigger(ap)
                delivery = "jit_hook" if trigger else "claude_md"
                triggers = (
                    [{"tool_name": "Bash", "trigger_kind": "bash_substr", "trigger_pattern": trigger}]
                    if trigger else []
                )
                resp = client.post(
                    CLI_BASE + "/cli/draft_lesson",
                    headers=_cli_headers(),
                    json={
                        "directive": directive,
                        "rationale": rationale,
                        "delivery": delivery,
                        "triggers": triggers,
                        "severity": "warn",
                        "project": project,
                    },
                )
                if resp.ok:
                    result = resp.json()
                    lesson_id = result.get("lesson_id")
                    if lesson_id and result.get("ok") and not result.get("duplicate"):
                        state = result.get("state", "pending")
                        reason = result.get("auto_promotion_reason", "unknown")
                        log.info("Drafted lesson %s → %s [%s] (%s)", lesson_id[:8], state, reason, delivery)

        log.info("Drafted %d lesson(s) from anti_patterns", min(len(anti_patterns), 5))
    except Exception as e:
        log.debug("draft_lessons failed (non-critical): %s", e)


def main() -> None:
    if len(sys.argv) < 3:
        log.error("Usage: mnemo-mend-bg.py <session_id> <cwd>")
        return

    _self_heal_shim()

    session_id = sys.argv[1]
    cwd = sys.argv[2]

    if not MNEMO_KEY:
        log.error("MNEMO_HOOK_KEY / MNEMO_ADMIN_TOKEN not set — skipping")
        return

    # Detect project name
    project_file = os.path.join(cwd, ".mnemo-project")
    if os.path.isfile(project_file):
        project = open(project_file).read().strip() or os.path.basename(cwd.rstrip("/"))
    else:
        project = os.path.basename(cwd.rstrip("/")) if cwd else "__global__"

    log.info("Session=%s project=%s cwd=%s", session_id, project, cwd)

    # Find and load conversation
    jsonl = _find_jsonl(session_id, cwd)
    if not jsonl:
        log.warning("JSONL not found for session %s — skipping", session_id)
        return

    messages = _load_conversation(jsonl)
    if not messages:
        log.warning("No messages extracted from %s", jsonl)
        return

    log.info("Loaded %d messages from %s", len(messages), jsonl)
    conversation_text = _build_conversation_text(messages)

    # Try local Azure extraction if credentials are available; otherwise delegate to server
    wiki_summary: str | None = None
    anti_patterns: list = []
    decisions: list = []
    summary = "Session wrapped automatically."
    outcome = "partial"
    corrections = None
    approvals = 0
    memory_helped: bool | None = None
    session_text_for_server: str | None = None

    if AZURE_ENDPOINT and AZURE_API_KEY:
        try:
            extracted = _call_azure(conversation_text)
            summary   = str(extracted.get("summary", summary))[:500]
            raw_out   = extracted.get("outcome", outcome)
            if raw_out in ("success", "partial", "failure"):
                outcome = raw_out
            raw_corr = extracted.get("corrections")
            if raw_corr is not None:
                try:
                    corrections = int(raw_corr)
                except (TypeError, ValueError):
                    pass
            approvals     = int(extracted.get("approvals") or 0)
            anti_patterns = extracted.get("anti_patterns") or []
            decisions     = extracted.get("decisions") or []
            wiki_summary  = extracted.get("wiki_summary") or None
            raw_helped = extracted.get("memory_helped")
            if isinstance(raw_helped, bool):
                memory_helped = raw_helped
            log.info("Local Azure extraction: outcome=%s corrections=%s wiki=%s memory_helped=%s",
                     outcome, corrections, bool(wiki_summary), memory_helped)
        except Exception as e:
            log.error("Local Azure call failed: %s — delegating to server", e)
            session_text_for_server = conversation_text
    else:
        log.info("No local Azure credentials — delegating extraction to server")
        session_text_for_server = conversation_text

    # Wrap session via Mnemo (server runs extraction if session_text provided)
    result = _wrap_session(session_id, project, summary, outcome, corrections, approvals,
                           session_text=session_text_for_server, memory_helped=memory_helped)
    if result is not None:
        log.info("wrap_session completed successfully")
        # If we delegated extraction to the server, read back the extracted data
        if session_text_for_server:
            wiki_summary  = result.get("wiki_summary") or wiki_summary
            anti_patterns = result.get("anti_patterns") or anti_patterns
            decisions     = result.get("decisions") or decisions
            outcome       = result.get("outcome") or outcome
            log.info("Server extraction: outcome=%s wiki=%s anti_patterns=%d",
                     outcome, bool(wiki_summary), len(anti_patterns))
    else:
        log.error("wrap_session failed")

    # Draft lessons from anti-patterns extracted this session
    if anti_patterns:
        _draft_lessons_from_anti_patterns(anti_patterns, project)

    # Auto-save to wiki raw/auto/ if session was wiki-worthy
    if wiki_summary and outcome in ("success", "partial"):
        _maybe_auto_save_wiki(session_id, cwd, wiki_summary, summary, project)


def _maybe_auto_save_wiki(
    session_id: str, cwd: str, wiki_summary: str, session_summary: str, project: str
) -> None:
    """Write an auto-generated wiki entry via mnemo_wiki_write (handles routing + sanitization)."""
    # Classify worthiness: check git activity since session start
    git_worthy = _check_git_activity(cwd)
    text_worthy = len(wiki_summary.strip()) > 80
    if not (git_worthy or text_worthy):
        log.info("Wiki auto-save skipped: insufficient activity signal")
        return

    try:
        from mnemo_wiki_write import write_wiki_entry
    except ImportError as exc:
        log.warning("mnemo_wiki_write not found — skipping wiki auto-save: %s", exc)
        return

    commit_shas = _get_session_commits(cwd, session_id)
    slug = re.sub(r"[^a-z0-9]+", "-", (project or "session").lower())[:30].strip("-")

    ok, msg = write_wiki_entry(
        body=wiki_summary.strip(),
        cwd=cwd,
        project=project,
        slug=slug,
        source="auto-mend",
        title=session_summary[:80],
        extra_frontmatter={
            "mnemo_session_id": session_id,
            "commit_shas": commit_shas,
            "tags": ["auto-generated"],
        },
        create_default=True,
        session_id_to_redact=session_id,
    )

    if ok:
        log.info("Wiki auto-saved: %s", msg)
        _save_wiki_event("wiki_auto_save", project)
    else:
        log.warning("Wiki auto-save failed: %s", msg)
        if "sanitizer" in msg:
            _save_wiki_event("wiki_blocked", project)


def _check_git_activity(cwd: str) -> bool:
    """True if session produced meaningful git changes (files changed >= 2 or lines >= 30)."""
    if not cwd or not Path(cwd).is_dir():
        return False
    start_sha = ""
    try:
        for sf in Path(tempfile.gettempdir()).glob("mnemo-session-*.start"):
            try:
                data = json.loads(sf.read_text())
                if data.get("cwd") == cwd:
                    start_sha = data.get("sha", "")
                    break
            except Exception:
                pass
    except Exception:
        pass

    try:
        if start_sha:
            stat = subprocess.run(
                ["git", "diff", "--shortstat", f"{start_sha}..HEAD"],
                capture_output=True, text=True, cwd=cwd, timeout=5,
            ).stdout.strip()
        else:
            stat = subprocess.run(
                ["git", "diff", "--shortstat", "HEAD~3..HEAD"],
                capture_output=True, text=True, cwd=cwd, timeout=5,
            ).stdout.strip()
        # "3 files changed, 87 insertions(+), 12 deletions(-)"
        files = int(re.search(r"(\d+) file", stat).group(1)) if re.search(r"(\d+) file", stat) else 0
        inserts = int(re.search(r"(\d+) insertion", stat).group(1)) if re.search(r"(\d+) insertion", stat) else 0
        return files >= 2 or inserts >= 30
    except Exception:
        return False


def _get_session_commits(cwd: str, session_id: str) -> list[str]:
    """Return commit SHAs made since session start (max 10)."""
    start_sha = ""
    try:
        for sf in Path(tempfile.gettempdir()).glob("mnemo-session-*.start"):
            try:
                data = json.loads(sf.read_text())
                if data.get("cwd") == cwd:
                    start_sha = data.get("sha", "")
                    break
            except Exception:
                pass
    except Exception:
        pass

    if not start_sha or not cwd or not Path(cwd).is_dir():
        return []
    try:
        out = subprocess.run(
            ["git", "log", "--oneline", f"{start_sha}..HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        ).stdout.strip()
        return [line.split()[0] for line in out.splitlines() if line][:10]
    except Exception:
        return []


def _save_wiki_event(event_type: str, project: str) -> None:
    """Log a wiki event to Mnemo so analyze_memory_performance can track rates."""
    try:
        import httpx as _httpx
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {MNEMO_KEY}",
        }
        if PC_ID:
            headers["X-PC-Id"] = PC_ID
        with _httpx.Client(timeout=5) as c:
            init = c.post(MCP_URL, headers=headers, json={
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "mnemo-mend-bg-wiki", "version": "1.0"}},
            })
            init.raise_for_status()
            headers["MCP-Session-Id"] = init.headers.get("mcp-session-id", "")
            c.post(MCP_URL, headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "save_memory", "arguments": {
                    "content": f"Wiki event: {event_type}",
                    "type": "note",
                    "importance": 3,
                    "project": project,
                    "tags": ["wiki_event", event_type],
                }},
            })
    except Exception as e:
        log.debug("wiki event save failed (non-critical): %s", e)


def _resolve_wiki_auto_dir(cwd: str) -> Path | None:
    """Return the raw/auto/ Path for cwd via .mnemo-wiki marker walk-up."""
    try:
        from mnemo_wiki_resolver import resolve_wiki_auto_dir
        return resolve_wiki_auto_dir(cwd, create_default=True)
    except Exception as exc:
        log.warning("mnemo_wiki_resolver unavailable: %s", exc)
        return None


def _self_heal_shim() -> None:
    """One-shot: rewrite the installed compile-wiki-auto.sh to the shim if it's the old copy."""
    sentinel = Path.home() / ".local/share/compile-wiki-auto/.shim-installed"
    if sentinel.exists():
        return
    installed = Path.home() / ".local/bin/compile-wiki-auto.sh"
    if not installed.exists():
        return
    shim_line = 'exec bash "${HOME}/.claude/plugins/mnemo-current/compile-wiki-auto.sh"'
    try:
        content = installed.read_text(encoding="utf-8")
        if shim_line in content:
            # Already a shim — just write sentinel
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.touch()
            return
        # Overwrite with shim
        shim = f'#!/usr/bin/env bash\n# Shim — delegates to plugin dir so updates take effect automatically.\n{shim_line} "$@"\n'
        installed.write_text(shim, encoding="utf-8")
        installed.chmod(0o755)
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        log.info("Shim self-heal: rewrote %s to delegate to plugin dir", installed)
    except Exception as exc:
        log.warning("Shim self-heal failed (non-fatal): %s", exc)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Unhandled error: %s", e)
