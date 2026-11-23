"""Full brief arm (Mnemo knowledge-delivery ticket 27, 2026-11-22).

Prompt replay: on 40 real prompts that need a stored memory, the 15-memory / 80-char brief scored like no memory
(22.5% vs 17.5% on Opus 5.5), the whole curated catalog at session start 77.5% (Sonnet 5.5), per-prompt retrieval 40-52%.
The full arm shows every curated memory get_memories returns (this project, then all projects; 50 each, min_importance
1) at the server's full preview length. 20% of sessions stay on the old brief, whose header now also names its arm.
"""
import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import brief_ab  # noqa: E402


def _mem(i, project="p"):
    return {"id": f"{i:08d}-1111-1111-1111-111111111111", "type": "decision", "importance": 3 + i % 5,
            "preview": f"fact-{i} " + "y" * 180 + f" end-{i}", "tags": [], "project": project, "scope": "user",
            "created_at": "2026-11-01T10:00:00+00:00"}


class _MCP(BaseHTTPRequestHandler):
    calls: list = []
    MEMS = [_mem(i) for i in range(60)]
    OLD_SERVER = False                        # an old server rejects the unknown preview_chars argument

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p = body.get("params", {})
        if p.get("name"):
            _MCP.calls.append((p["name"], p.get("arguments", {})))
        args = p.get("arguments", {})
        if self.OLD_SERVER and "preview_chars" in args:
            res = {"content": [{"type": "text", "text": "Unexpected keyword argument preview_chars"}], "isError": True}
        else:
            cap = 200 if args.get("preview_chars") else 50
            mems = (self.MEMS[:min(cap, args.get("limit", 10))]
                    if p.get("name") == "get_memories" and not args.get("tags") else [])
            res = {"content": [{"type": "text", "text": json.dumps(mems)}]}
        out = f"data: {json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': res})}\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("mcp-session-id", "s1")
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *a):
        pass


def _run(tmp_path, arm, source="startup"):
    _MCP.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _MCP)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    proj = tmp_path / "p"
    proj.mkdir(exist_ok=True)
    (proj / "project.json").write_text('{"id": "p"}')
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL=http://127.0.0.1:{srv.server_port}\nMNEMO_HOOK_KEY=k\n")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "MNEMO_BRIEF_ARM": arm}
    r = subprocess.run([sys.executable, str(ROOT / "load-context.py")], env=env, capture_output=True, text=True,
                       input=json.dumps({"session_id": "t", "cwd": str(proj), "source": source}), timeout=30)
    srv.shutdown()
    return json.loads(r.stdout[r.stdout.index("{"):])["hookSpecificOutput"]["additionalContext"], list(_MCP.calls)


def _with_parts(tmp_path, ctx):
    """The full arm's memory lines live in the brief-part hooks' parts file (brief_ab.py › parts)."""
    f = brief_ab.PARTS_DIR.name
    d = tmp_path / ".mnemo" / f
    parts = [json.loads(x.read_text())["parts"] for x in d.glob("*.json")] if d.is_dir() else []
    return ctx + "\n" + "\n".join(p for ps in parts for p in ps)


def test_full_arm_shows_every_memory_untruncated(tmp_path):
    ctx, calls = _run(tmp_path, "full")
    assert "arm: full" in ctx
    ctx = _with_parts(tmp_path, ctx)
    for i in range(60):                       # whole memories, all of them
        assert f"fact-{i} " in ctx and f"end-{i}" in ctx, i
    gm = [a for n, a in calls if n == "get_memories" and not a.get("tags")]
    assert {a.get("project") for a in gm} >= {"p", "*"}
    assert all(a.get("limit") == 200 and a.get("preview_chars") == 400 and a.get("min_importance") == 1
               and "query" not in a for a in gm)


def test_full_arm_falls_back_on_an_old_server(tmp_path):
    _MCP.OLD_SERVER = True
    try:
        ctx, calls = _run(tmp_path, "full")
    finally:
        _MCP.OLD_SERVER = False
    assert "arm: full" in ctx and "fact-0 " in _with_parts(tmp_path, ctx)          # still a brief, from the 50-cap call
    gm = [a for n, a in calls if n == "get_memories" and not a.get("tags")]
    assert any("preview_chars" not in a and a.get("limit") == 50 for a in gm)


def test_brief_arm_keeps_the_old_brief(tmp_path):
    ctx, calls = _run(tmp_path, "brief")
    assert "Session brief" in ctx and "arm: brief" in ctx
    assert "end-0" not in ctx                 # 80-char previews, as before
    gm = [a for n, a in calls if n == "get_memories" and not a.get("tags")]
    assert gm[0].get("limit") == 15


def test_project_memories_survive_the_budget_first():
    proj = [{"id": "p1", "type": "note", "importance": 2, "preview": "project-note " + "z" * 300}]
    other = [{"id": f"o{i}", "type": "anti-pattern", "importance": 9, "preview": f"other-{i} " + "z" * 300}
             for i in range(10)]
    lines, _ = brief_ab.full_lines(brief_ab.merge(proj, other), budget=700)
    assert "project-note" in lines[0]


def test_full_lines_survives_malformed_rows():
    lines, omitted = brief_ab.full_lines([{"type": "note", "importance": "?", "preview": "ok-row"}, "junk",
                                          {"type": "episode", "preview": "session summary"}])
    assert len(lines) == 1 and "ok-row" in lines[0] and omitted == 0


def test_arm_split_is_stable_and_mostly_full():
    arms = [brief_ab.arm(f"session-{i}") for i in range(2000)]
    assert arms == [brief_ab.arm(f"session-{i}") for i in range(2000)]
    share = arms.count("brief") / len(arms)
    assert 0.15 < share < 0.25 and set(arms) == {"brief", "full"}
