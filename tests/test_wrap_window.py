"""Each wrap labels only the messages since the session's previous wrap; the episode carries the running total
(Mnemo ticket 27 correction counter, 2026-11-27)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import wrap_window  # noqa: E402


def _jsonl(path, turns):
    with open(path, "a") as f:
        for role, text in turns:
            f.write(json.dumps({"type": role, "message": {"role": role, "content": text}}) + "\n")


def test_window_starts_after_previous_wrap_with_one_context_reply(tmp_path):
    j = tmp_path / "s.jsonl"
    _jsonl(j, [("user", "first ask"), ("assistant", "first reply")])
    msgs, end = wrap_window.load(j, 0)
    assert [m["text"] for m in msgs] == ["first ask", "first reply"] and end == 2
    _jsonl(j, [("user", "no, that is wrong"), ("assistant", "fixed")])
    msgs, end2 = wrap_window.load(j, end)
    assert [m["text"] for m in msgs] == ["first reply", "no, that is wrong", "fixed"] and end2 == 4
    assert msgs[0]["context"] is True and not msgs[1].get("context")    # the reply a correction answers
    assert wrap_window.load(j, end2) == ([], 4)                         # nothing new: nothing to label


def test_state_accumulates_corrections_per_session(tmp_path):
    st = tmp_path / "wrap-windows.json"
    assert wrap_window.get(st, "s1") == (0, 0)
    wrap_window.put(st, "s1", 4, 2)
    wrap_window.put(st, "s2", 9, 0)
    assert wrap_window.get(st, "s1") == (4, 2)
    wrap_window.put(st, "s1", 7, 5)
    assert wrap_window.get(st, "s1") == (7, 5) and wrap_window.get(st, "s2") == (9, 0)


def test_state_is_bounded_and_survives_a_bad_file(tmp_path):
    st = tmp_path / "wrap-windows.json"
    st.write_text("{not json")
    assert wrap_window.get(st, "x") == (0, 0)
    for i in range(wrap_window.MAX_SESSIONS + 50):
        wrap_window.put(st, f"s{i}", i, 0)
    data = json.loads(st.read_text())
    assert len(data) == wrap_window.MAX_SESSIONS and f"s{wrap_window.MAX_SESSIONS + 49}" in data and "s0" not in data
    assert oct(st.stat().st_mode & 0o777) == "0o600"


def test_two_wraps_label_disjoint_windows_and_send_the_running_total(tmp_path, monkeypatch):
    import importlib.util
    monkeypatch.setattr(sys, "argv", ["wrap-session-bg.py", "sess-1", str(tmp_path)])
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    spec = importlib.util.spec_from_file_location("wrap_bg", pathlib.Path(__file__).resolve().parents[1] / "wrap-session-bg.py")
    bg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bg)
    j = tmp_path / "sess-1.jsonl"
    seen, sent = [], []
    monkeypatch.setattr(wrap_window, "STATE", tmp_path / "data" / "wrap-windows.json")
    for name, val in {"MNEMO_KEY": "k", "AZURE_ENDPOINT": "e", "AZURE_API_KEY": "a"}.items():
        monkeypatch.setattr(bg, name, val)
    monkeypatch.setattr(bg, "_self_heal_shim", lambda: None)
    monkeypatch.setattr(bg, "_find_jsonl", lambda sid, cwd: j)
    monkeypatch.setattr(bg, "_call_azure", lambda text: seen.append(text) or {"corrections": text.count("wrong")})
    monkeypatch.setattr(bg, "_wrap_session", lambda *a, **k: sent.append(a[4]) or {})
    _jsonl(j, [("user", "build the thing please"), ("assistant", "built it"), ("user", "that is wrong, redo")])
    bg.main()
    _jsonl(j, [("assistant", "redone now"), ("user", "still wrong here"), ("assistant", "fixed for real")])
    bg.main()
    bg.main()                                                            # nothing new: no third wrap
    assert sent == [1, 2]                                                # running total, not the overlap
    assert "build the thing" not in seen[1] and "that is wrong" not in seen[1]       # first window not relabelled
    assert seen[1].startswith("ASSISTANT (earlier reply, context only): built it")
    assert "still wrong here" in seen[1] and len(seen) == 2


def test_half_written_last_line_and_replaced_transcript(tmp_path):
    j = tmp_path / "s.jsonl"
    _jsonl(j, [("user", "first ask")])
    with open(j, "a") as f:
        f.write('{"type": "assistant", "message": {"role": "assist')       # Claude Code still writing it
    msgs, end = wrap_window.load(j, 0)
    assert [m["text"] for m in msgs] == ["first ask"] and end == 1          # the partial line is not consumed
    assert wrap_window.load(tmp_path / "s.jsonl", 50)[0][0]["text"] == "first ask"   # offset past the end: start over


def test_concurrent_puts_keep_valid_state(tmp_path):
    import threading
    st = tmp_path / "wrap-windows.json"
    ts = [threading.Thread(target=wrap_window.put, args=(st, f"s{i}", i, 1)) for i in range(40)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(json.loads(st.read_text())) == 40
