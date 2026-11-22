"""The full brief arrives in parts of < 10,000 chars (2026-11-22, live on 101).

Claude Code replaces one hook's injected context over 10,000 chars with a 2 KB preview and a file path
(`<persisted-output>`): the 2.6.0 full brief reached sessions as ~7 memories. Each hook has its own cap (two 9.3k
hooks both arrived whole, one 19k hook was cut), so load-context.py keeps the header and directives and hands the
memory lines to brief-part.py hooks, one per part.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import brief_ab  # noqa: E402
from test_brief_full import _MCP, _mem, _run  # noqa: E402


def test_split_keeps_every_part_under_the_cap():
    lines = [f"    • [note] fact-{i} " + "y" * 400 for i in range(150)]
    parts = brief_ab.split_parts(lines)
    assert all(len(p) < 10000 for p in parts)
    joined = "\n".join(parts)
    assert all(f"fact-{i} " in joined for i in range(150))
    assert parts[0].startswith("[mnemo] Stored memories, part 1/")


def test_parts_round_trip_and_stale_files_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_ab, "PARTS_DIR", tmp_path)
    brief_ab.write_parts("s1", ["A", "B"])
    assert brief_ab.read_part("s1", 2, wait=0.1) == "B"
    assert brief_ab.read_part("s1", 3, wait=0.1) is None
    assert brief_ab.read_part("other", 1, wait=0.1) is None
    assert brief_ab.read_part("s1", 1, wait=0.1, started=__import__("time").time() + 60) is None   # an earlier start


def _part(tmp_path, n, source="startup"):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(ROOT / "brief-part.py"), str(n)], env=env, capture_output=True, text=True,
                       input=json.dumps({"session_id": "t", "source": source}), timeout=30)
    if not r.stdout.strip():
        return ""
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_full_brief_and_its_parts_each_fit_and_carry_every_memory(tmp_path):
    _MCP.MEMS = [_mem(i) for i in range(120)]           # ~120 x 230 chars: far over one hook's 10k
    try:
        ctx, _ = _run(tmp_path, "full")
    finally:
        _MCP.MEMS = [_mem(i) for i in range(60)]
    assert len(ctx) < 10000 and "arm: full" in ctx
    parts = [p for p in (_part(tmp_path, n) for n in range(1, brief_ab.MAX_PARTS + 1)) if p]
    assert parts and all(len(p) < 10000 for p in parts)
    allx = ctx + "\n".join(parts)
    assert all(f"fact-{i} " in allx and f"end-{i}" in allx for i in range(120))


def test_parts_stay_silent_on_compact_and_for_the_old_brief(tmp_path):
    ctx, _ = _run(tmp_path, "brief")
    assert all(_part(tmp_path, n) == "" for n in (1, 2))
    _run(tmp_path, "full")
    assert _part(tmp_path, 1, source="compact") == ""


def test_plugin_registers_every_part_hook():
    hooks = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["hooks"]["SessionStart"]
    args = [" ".join(h.get("args", [])) for e in hooks for h in e["hooks"]]
    for n in range(1, brief_ab.MAX_PARTS + 1):
        assert any(a.endswith(f"brief-part.py {n}") for a in args), n


def test_a_part_ignores_parts_written_before_it_started(tmp_path, monkeypatch):
    """/resume or /clear: the previous start's file for the same session must not be served to the new start."""
    import time
    monkeypatch.setattr(brief_ab, "PARTS_DIR", tmp_path)
    brief_ab.write_parts("s1", ["OLD"])
    assert brief_ab.read_part("s1", 1, wait=0.2, started=time.time() + 10) is None
    assert brief_ab.read_part("s1", 1, wait=0.2, started=time.time()) == "OLD"


def test_parts_file_is_private(tmp_path, monkeypatch):
    d = tmp_path / "parts"
    monkeypatch.setattr(brief_ab, "PARTS_DIR", d)
    brief_ab.write_parts("s1", ["memory text"])
    f = next(d.glob("*.json"))
    assert (f.stat().st_mode & 0o777) == 0o600 and (d.stat().st_mode & 0o777) == 0o700


def test_cap_text_keeps_a_hook_under_ten_thousand():
    assert len(brief_ab.cap_text("x" * 20000)) < 10000
    assert brief_ab.cap_text("short") == "short"
