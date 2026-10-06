"""Wiki map (local index.md) + topic pointer (knowledge-delivery ticket 10, ADR-0011)."""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import wiki_ab  # noqa: E402

TITLES = ["Endpoint Management — Intune / Microsoft Defender", "Telephony — 3CX PBX", "Coherence Layer",
          "CRM Reconciliation", "Jira → ADO Bridge (gyp-weu-02-jira-ado-func)", "Agora Pipeline Overview",
          "Agora Enrichers", "Infrastructure Overview", "Security Overview"]


def _pages(titles):
    return [{"id": f"x/p{i}", "title": t, "domain": "x", "path": f"/w/wiki/x/p{i}.md"} for i, t in enumerate(titles)]


def _run(script, home, payload, arm, extra_env=None):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "MNEMO_WIKI_ARM": arm, "CLAUDE_PLUGIN_DATA": str(home / "pd"),
           **(extra_env or {})}
    r = subprocess.run([sys.executable, str(ROOT / script)], input=json.dumps(payload), env=env,
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""


def test_arm_stable_spread_and_override(monkeypatch):
    monkeypatch.delenv("MNEMO_WIKI_ARM", raising=False)
    arms = [wiki_ab.arm(f"s-{i}") for i in range(300)]
    assert set(arms) == {"control", "map_topic"} and wiki_ab.arm("s-7") == wiki_ab.arm("s-7")
    assert 35 < arms.count("control") < 90
    monkeypatch.setenv("MNEMO_WIKI_ARM", "map")
    assert wiki_ab.arm("anything") == "map"


def test_topic_matching():
    pages = _pages(TITLES)
    m = lambda q: [p["title"] for p in wiki_ab.topic_matches(q, pages)]
    assert m("intune defender policy blocks the laptops") == [TITLES[0]]
    assert m("why is intune not enrolling the laptops?") == []          # one plain word: left to the map
    assert m("restart the 3cx trunk") == [TITLES[1]]
    assert m("the coherence layer flagged it") == []                    # single-concept title: left to the map
    assert m("run crm reconciliation for nace 4332") == [TITLES[3]]
    assert m("the jira ado sync failed") == [TITLES[4]]
    assert m("please fix the failing test in the overview page") == []
    assert m("refactor the security of the api") == []
    plesk = _pages(["Plesk / Postfix Operations (KIWI01 / gyp.gr)", "agora-poc — AI Lead Generation Platform"])
    mp = lambda q: [p["title"] for p in wiki_ab.topic_matches(q, plesk)]
    assert mp("install the mnemo db on kiwi01") == []                   # parenthetical code = qualifier
    assert mp("plesk on kiwi01 rejects mail") == ["Plesk / Postfix Operations (KIWI01 / gyp.gr)"]   # ... still counts as a title token
    assert mp("why cant tests merge on agora-poc?") == ["agora-poc — AI Lead Generation Platform"]  # leading code


def test_topic_hook_points_once_per_page(tmp_path):
    (tmp_path / "pd").mkdir()
    (tmp_path / "pd" / "wiki-map.json").write_text(json.dumps(_pages(TITLES)))
    p = {"session_id": "s", "prompt": "restart the 3cx trunk"}
    first = _run("wiki-topic.py", tmp_path, p, "map_topic")
    assert "Telephony — 3CX PBX" in first and "Read /w/wiki/x/p1.md" in first
    assert _run("wiki-topic.py", tmp_path, p, "map_topic") == ""          # once per session
    assert _run("wiki-topic.py", tmp_path, {**p, "session_id": "s2"}, "control") == ""   # other arms: nothing


def _local_wiki(root):
    (root / "wiki" / "platforms").mkdir(parents=True)
    (root / "wiki" / "platforms" / "gpml01.md").write_text("---\ntags: [x]\n---\n# GPML01 — gyp.gr Mail Server\nbody\n")
    (root / "index.md").write_text("# XO Company Wiki\n_compiled_\n\n## platforms/\n- [[platforms/gpml01]] — mail server\n")
    (root / ".wiki-commit").write_text("abcdef1234\n")


def test_local_source_map_and_pointer(tmp_path, monkeypatch):
    _local_wiki(tmp_path)
    monkeypatch.setattr(wiki_ab, "LOCAL_ROOT", tmp_path)
    pages = wiki_ab.local_pages(tmp_path)
    assert pages == [{"id": "platforms/gpml01", "title": "GPML01 — gyp.gr Mail Server", "domain": "platforms",
                      "path": str(tmp_path / "wiki" / "platforms" / "gpml01.md")}]
    block = wiki_ab.map_block(pages)
    assert "local copy at" in block and "@ abcdef12" in block and "[[platforms/gpml01]] — mail server" in block
    assert "XO Company Wiki" not in block                                  # index title/subtitle dropped
    hits = wiki_ab.topic_matches("check health of gpml01", pages)
    assert "Read " + str(tmp_path / "wiki" / "platforms" / "gpml01.md") in wiki_ab.pointer_text(hits)


def test_brief_uses_local_copy_without_server(tmp_path):
    _local_wiki(tmp_path / "xo-wiki")
    env = {"MNEMO_WIKI_DIR": str(tmp_path / "xo-wiki")}
    start = {"session_id": "t", "cwd": str(tmp_path), "source": "startup"}
    out = _run("wiki-map.py", tmp_path, start, "map_topic", extra_env=env)   # no server, no key
    assert out.startswith("[wiki]") and "local copy at" in out and "[[platforms/gpml01]]" in out
    assert _run("wiki-map.py", tmp_path, {**start, "source": "compact"}, "map_topic", extra_env=env) == out
    assert _run("wiki-map.py", tmp_path, start, "control", extra_env=env) == ""
    assert _run("load-context.py", tmp_path, start, "map_topic", extra_env=env) == ""   # no duplicate map
    assert _run("wiki-map.py", tmp_path, start, "map_topic", extra_env={"MNEMO_WIKI_DIR": str(tmp_path / "none")}) == ""
    topic = {"session_id": "t", "prompt": "is gpml01 healthy?"}
    assert "Read " + str(tmp_path / "xo-wiki" / "wiki" / "platforms" / "gpml01.md") in \
        _run("wiki-topic.py", tmp_path, topic, "map_topic", extra_env=env)


def test_personal_wiki_for_personal_sessions_never_mixed(tmp_path):
    _local_wiki(tmp_path / "xo-wiki")
    pw = tmp_path / "pwiki"; (pw / "wiki" / "projects").mkdir(parents=True)
    (pw / "wiki" / "projects" / "newsbeast.md").write_text("# Newsbeast\nbody\n")
    (pw / "index.md").write_text("# Personal Wiki\n- [[projects/newsbeast]] — Newsbeast perf\n")
    env = {"MNEMO_WIKI_DIR": str(tmp_path / "xo-wiki"), "MNEMO_PERSONAL_WIKI_DIR": str(pw),
           "MNEMO_PERSONAL_CODE_DIR": str(tmp_path / "Personal")}
    personal = {"session_id": "t", "cwd": str(tmp_path / "Personal" / "Newsbeast"), "source": "startup"}
    team = {**personal, "cwd": str(tmp_path / "XO" / "agora")}
    p = _run("wiki-map.py", tmp_path, personal, "map_topic", extra_env=env)
    t = _run("wiki-map.py", tmp_path, team, "map_topic", extra_env=env)
    assert "personal wiki" in p and "[[projects/newsbeast]]" in p and "gpml01" not in p
    assert "team wiki" in t and "[[platforms/gpml01]]" in t and "newsbeast" not in t
    # separate caches: a team-session pointer still works after a personal session started
    q = _run("wiki-topic.py", tmp_path, {"session_id": "t2", "cwd": str(tmp_path / "XO" / "agora"),
                                          "prompt": "is gpml01 healthy?"}, "map_topic", extra_env=env)
    assert "gpml01.md" in q
