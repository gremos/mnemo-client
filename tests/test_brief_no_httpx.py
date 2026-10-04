"""load-context.py must deliver the session brief under a bare python3 without httpx (102's gremos
profile lost every brief to a swallowed ImportError, 2026-10). A local fake MCP server answers."""
import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
MEM = {"id": "11111111-1111-1111-1111-111111111111", "type": "anti-pattern", "importance": 9,
       "preview": "Wrong: probe. Correct: probe-ok.", "tags": [], "project": "p", "scope": "user"}


class _MCP(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        name = body.get("params", {}).get("name")
        text = json.dumps([MEM] if name == "get_memories" else [])
        out = f"data: {json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': {'content': [{'type': 'text', 'text': text}]}})}\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("mcp-session-id", "s1")
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *a):
        pass


def test_brief_without_httpx(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _MCP)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    block = tmp_path / "block"
    block.mkdir()
    (block / "httpx.py").write_text("raise ImportError('no httpx here')\n")
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL=http://127.0.0.1:{srv.server_port}\nMNEMO_HOOK_KEY=k\n")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(block)}
    payload = json.dumps({"session_id": "t", "cwd": str(tmp_path), "source": "startup"})
    r = subprocess.run([sys.executable, str(ROOT / "load-context.py")], input=payload, env=env,
                       capture_output=True, text=True, timeout=30)
    srv.shutdown()
    assert r.stdout.startswith("{"), r.stdout[:400]
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "Session brief" in ctx and "probe-ok" in ctx


def test_brief_hook_fires_on_resume():
    """A resumed session (claude --resume) never got a brief: the matcher was 'startup' only."""
    import re
    hooks = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["hooks"]["SessionStart"]
    m = next(e["matcher"] for e in hooks if any("load-context.py" in str(h.get("args", "")) + h["command"] for h in e["hooks"]))
    assert re.fullmatch(m, "startup") and re.fullmatch(m, "resume") and re.fullmatch(m, "clear")
    assert re.fullmatch(m, "compact")          # compact re-sends only the wiki map (map arms)


def test_brief_in_session_worktree_names_the_repo(tmp_path):
    """akostantopoulos 2026-10-02: a session in <repo>/.claude/worktrees/s-... got 's-...' as its project."""
    srv = HTTPServer(("127.0.0.1", 0), _MCP)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    wt = tmp_path / "infra-azure-gyp" / ".claude" / "worktrees" / "s-20261002-054510"
    wt.mkdir(parents=True)
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL=http://127.0.0.1:{srv.server_port}\nMNEMO_HOOK_KEY=k\n")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(ROOT / "load-context.py")], env=env, capture_output=True, text=True,
                       input=json.dumps({"session_id": "t", "cwd": str(wt), "source": "startup"}), timeout=30)
    srv.shutdown()
    ctx = json.loads(r.stdout[r.stdout.index("{"):])["hookSpecificOutput"]["additionalContext"]
    assert 'brief for "infra-azure-gyp"' in ctx, ctx[:120]
