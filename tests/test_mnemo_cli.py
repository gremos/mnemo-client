"""/mnemo:memsave reaches draft_lesson and wrap_session through mnemo-cli.py.

Both live on the cold /cli/* REST path, not on /mcp/, so a session has no tool for them; the model
runs the script instead, which holds the key so the model never reads ~/.mnemo.env. The test runs the
script against a local stub server and checks what it sends."""
import json
import os
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "mnemo-cli.py"


@pytest.fixture
def server():
    calls: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"path": self.path, "headers": dict(self.headers), "body": body})
            status = 422 if body.get("directive") == "bad" else 200
            out = json.dumps({"ok": status == 200, "path": self.path}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", calls
    srv.shutdown()


def _run(base: str, tmp_path, args: list[str], stdin: str = "", **extra_env) -> subprocess.CompletedProcess:
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL={base}/\nMNEMO_HOOK_KEY=test-key\n")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MNEMO_", "CLAUDE_PLUGIN_", "MCP_URL", "CLAUDE_CODE_SESSION_ID"))}
    env.update(HOME=str(tmp_path), **extra_env)
    return subprocess.run([sys.executable, str(CLI), *args], input=stdin, env=env,
                          capture_output=True, text=True, timeout=20)


def test_draft_lesson_posts_stdin_json(server, tmp_path):
    base, calls = server
    lesson = {"directive": "Always run tests", "rationale": "r" * 25, "delivery": "claude_md",
              "project": "demo"}
    r = _run(base, tmp_path, ["draft-lesson"], json.dumps(lesson))
    assert r.returncode == 0, r.stderr
    assert [c["path"] for c in calls] == ["/cli/draft_lesson"]
    assert calls[0]["body"] == lesson
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert json.loads(r.stdout)["ok"] is True


def test_wrap_registers_then_wraps_this_session(server, tmp_path):
    base, calls = server
    r = _run(base, tmp_path, ["wrap", "--session-id", "sid-1", "--summary", "did x",
                              "--outcome", "success", "--project", "demo", "--corrections", "2",
                              "--memory-helped", "no"])
    assert r.returncode == 0, r.stderr
    assert [c["path"] for c in calls] == ["/cli/register_claude_session", "/cli/wrap_session"]
    assert calls[0]["body"] == {"claude_session_id": "sid-1"}
    assert all(c["headers"]["X-Session-Id"] == "sid-1" for c in calls)
    assert calls[1]["body"] == {"summary": "did x", "outcome": "success", "project": "demo",
                                "corrections": 2, "memory_helped": False}


def test_wrap_defaults_to_the_session_id_claude_code_exports(server, tmp_path):
    base, calls = server
    r = _run(base, tmp_path, ["wrap", "--summary", "s", "--outcome", "partial"],
             CLAUDE_CODE_SESSION_ID="sid-env")
    assert r.returncode == 0, r.stderr
    assert all(c["headers"]["X-Session-Id"] == "sid-env" for c in calls)


def test_wrap_without_any_session_id_refuses(server, tmp_path):
    base, calls = server
    r = _run(base, tmp_path, ["wrap", "--summary", "s", "--outcome", "success"])
    assert r.returncode == 2 and calls == []


def test_sends_pc_id_like_the_hooks(server, tmp_path):
    base, calls = server
    (tmp_path / ".mnemo").mkdir()
    (tmp_path / ".mnemo" / "config.json").write_text('{"pc_id": "pc-7"}')
    _run(base, tmp_path, ["draft-lesson"], json.dumps({"directive": "d"}))
    assert {k.lower(): v for k, v in calls[0]["headers"].items()}["x-pc-id"] == "pc-7"


def test_bad_stdin_is_a_usage_error(server, tmp_path):
    base, calls = server
    r = _run(base, tmp_path, ["draft-lesson"], "not json")
    assert r.returncode == 2 and calls == []


def test_http_error_exits_nonzero_and_prints_body(server, tmp_path):
    base, _ = server
    r = _run(base, tmp_path, ["draft-lesson"], json.dumps({"directive": "bad"}))
    assert r.returncode == 1
    assert json.loads(r.stdout)["ok"] is False


def test_memsave_points_at_the_script_not_at_tools():
    text = (ROOT / "memsave.md").read_text()
    assert "mnemo-cli.py draft-lesson" in text and "mnemo-cli.py wrap" in text
