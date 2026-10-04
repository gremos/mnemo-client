"""Wiki map + topic pointer A/B (knowledge-delivery ticket 10)."""
import json
import os
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import wiki_ab  # noqa: E402

TITLES = ["Endpoint Management — Intune / Microsoft Defender", "Telephony — 3CX PBX", "Coherence Layer",
          "CRM Reconciliation", "Jira → ADO Bridge (gyp-weu-02-jira-ado-func)", "Agora Pipeline Overview",
          "Agora Enrichers", "Infrastructure Overview", "Security Overview"]
ITEMS = [{"id": f"{i:08d}-0000-0000-0000-000000000000", "tags": ["wiki-page", "domain:infra"],
          "preview": f"--- tags: [x] updated: 2026-06-01 ---  # {t}  body"} for i, t in enumerate(TITLES)]
ITEMS.append(dict(ITEMS[2], id="99999999-dup"))          # second version of the same page


def test_arm_stable_spread_and_override(monkeypatch):
    monkeypatch.delenv("MNEMO_WIKI_ARM", raising=False)
    arms = [wiki_ab.arm(f"s-{i}") for i in range(300)]
    assert set(arms) == set(wiki_ab.ARMS) and wiki_ab.arm("s-7") == wiki_ab.arm("s-7")
    assert min(arms.count(a) for a in wiki_ab.ARMS) > 70
    monkeypatch.setenv("MNEMO_WIKI_ARM", "map")
    assert wiki_ab.arm("anything") == "map"


def test_pages_dedup_and_topic_matching():
    pages = wiki_ab.pages_from(ITEMS)
    assert len(pages) == len(TITLES)
    m = lambda q: [p["title"] for p in wiki_ab.topic_matches(q, pages)]
    assert m("intune defender policy blocks the laptops") == [TITLES[0]]
    assert m("why is intune not enrolling the laptops?") == []          # one plain word: left to the map
    assert m("restart the 3cx trunk") == [TITLES[1]]
    assert m("the coherence layer flagged it") == []                    # single-concept title: left to the map
    assert m("run crm reconciliation for nace 4332") == [TITLES[3]]
    assert m("the jira ado sync failed") == [TITLES[4]]
    assert m("please fix the failing test in the overview page") == []
    assert m("refactor the security of the api") == []
    block = wiki_ab.map_block(pages)
    assert all(t in block for t in TITLES) and "get_memory" in block


class _MCP(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        args = body.get("params", {}).get("arguments", {})
        rows = ITEMS if args.get("project") == "wiki:xo" else []
        out = f"data: {json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': {'content': [{'type': 'text', 'text': json.dumps(rows)}]}})}\n\n"
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("mcp-session-id", "s1"); self.end_headers(); self.wfile.write(out.encode())

    def log_message(self, *a):
        pass


def _run(script, home, payload, arm):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "MNEMO_WIKI_ARM": arm, "CLAUDE_PLUGIN_DATA": str(home / "pd")}
    r = subprocess.run([sys.executable, str(ROOT / script)], input=json.dumps(payload), env=env,
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""


def test_brief_map_arm_vs_control_and_compact(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _MCP); threading.Thread(target=srv.serve_forever, daemon=True).start()
    (tmp_path / ".mnemo.env").write_text(f"MNEMO_BASE_URL=http://127.0.0.1:{srv.server_port}\nMNEMO_HOOK_KEY=k\n")
    start = {"session_id": "t", "cwd": str(tmp_path), "source": "startup"}
    ctl = _run("load-context.py", tmp_path, start, "control")
    mp = _run("load-context.py", tmp_path, start, "map")
    assert "Wiki map" not in ctl and "Wiki map" in mp and "Telephony — 3CX PBX" in mp
    comp = {"session_id": "t", "cwd": str(tmp_path), "source": "compact"}
    assert "Wiki map" in _run("load-context.py", tmp_path, comp, "map")
    assert _run("load-context.py", tmp_path, comp, "control") == ""
    srv.shutdown()


def test_topic_hook_points_once_per_page(tmp_path):
    (tmp_path / "pd").mkdir()
    (tmp_path / "pd" / "wiki-map.json").write_text(json.dumps(wiki_ab.pages_from(ITEMS)))
    p = {"session_id": "s", "prompt": "restart the 3cx trunk"}
    first = _run("wiki-topic.py", tmp_path, p, "map_topic")
    assert "Telephony — 3CX PBX" in first and "get_memory" in first
    assert _run("wiki-topic.py", tmp_path, p, "map_topic") == ""          # once per session
    assert _run("wiki-topic.py", tmp_path, {**p, "session_id": "s2"}, "map") == ""   # other arms: nothing
