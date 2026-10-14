"""`claude -p` runs get no Mnemo context and log no corrections (audit 2026-10-14: 880 of 886 local
sessions were automated; their task prompts tripped the correction regex, e.g. 4 'corrections' in one
rule-hygiene batch, and each got a cross-project brief no human read)."""
import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import headless  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
from test_wiki_ab import _local_wiki  # noqa: E402

MEM = {"id": "11111111-1111-1111-1111-111111111111", "type": "decision", "importance": 9,
       "preview": "probe-ok", "tags": [], "project": "p", "scope": "user"}


def test_headless_entrypoints():
    for ep in ("sdk-cli", "sdk-py", "sdk-ts", "mcp"):
        assert headless.is_headless({"CLAUDE_CODE_ENTRYPOINT": ep}), ep
    for ep in ("cli", "claude-vscode", "", None):
        env = {} if ep is None else {"CLAUDE_CODE_ENTRYPOINT": ep}
        assert not headless.is_headless(env), ep


def _server(hits):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            hits.append(self.path)
            text = json.dumps([MEM] if body.get("params", {}).get("name") == "get_memories" else [])
            out = f"data: {json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': {'content': [{'type': 'text', 'text': text}]}})}\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("mcp-session-id", "s1")
            self.end_headers()
            self.wfile.write(out.encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run(script, home, payload, entrypoint, extra_env=None):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_CODE_ENTRYPOINT": entrypoint,
           "MNEMO_WIKI_ARM": "map_topic", "CLAUDE_PLUGIN_DATA": str(home / "pd"), **(extra_env or {})}
    return subprocess.run([sys.executable, str(ROOT / script)], input=json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=30).stdout


def test_hooks_stay_silent_for_claude_p(tmp_path):
    hits = []
    srv = _server(hits)
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL=http://127.0.0.1:{srv.server_port}\nMNEMO_HOOK_KEY=k\n")
    _local_wiki(tmp_path / "xo-wiki")
    env = {"MNEMO_WIKI_DIR": str(tmp_path / "xo-wiki")}
    start = {"session_id": "t", "cwd": str(tmp_path), "source": "startup"}
    prompt = {"session_id": "t", "cwd": str(tmp_path), "prompt": "no, that's wrong: is gpml01 healthy?"}
    try:
        for script, payload in (("load-context.py", start), ("wiki-map.py", start),
                                ("wiki-topic.py", prompt), ("track-correction.py", prompt)):
            assert _run(script, tmp_path, payload, "sdk-cli", env) == "", script
        assert hits == []
        # the same calls in an interactive session do reach Mnemo and print context
        assert "probe-ok" in _run("load-context.py", tmp_path, start, "cli", env)
        assert "gpml01" in _run("wiki-map.py", tmp_path, start, "cli", env)
        assert hits
    finally:
        srv.shutdown()


def test_greek_correction_reaches_mnemo(tmp_path):
    hits = []
    srv = _server(hits)
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL=http://127.0.0.1:{srv.server_port}\nMNEMO_HOOK_KEY=k\n")
    try:
        _run("track-correction.py", tmp_path, {"session_id": "t", "prompt": "όχι, λάθος αρχείο"}, "cli")
        _run("track-correction.py", tmp_path, {"session_id": "t", "prompt": "δες τα αρχεία στο gpml01"}, "cli")
    finally:
        srv.shutdown()
    assert [h for h in hits if "log_user_correction" in h] and len(hits) == 1, hits
