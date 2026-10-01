"""Hooks must resolve the Mnemo server from MNEMO_BASE_URL (~/.mnemo.env), the single client source
since 2026-09-26. They used to fall back to localhost:80, which dropped every correction on the VMs.

Each hook resolves `_mnemo_base = ( ... ).rstrip("/")` at module top level; the test executes the file
up to and including that block in a fresh namespace with HOME pointing at a temp dir, so nothing is
sent anywhere."""
import io
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOKS = ["track-correction.py", "load-context.py", "wrap-session-bg.py"]
ENV_KEYS = ("CLAUDE_PLUGIN_OPTION_SERVER_URL", "MCP_URL", "MNEMO_HOST", "MNEMO_PORT", "MNEMO_BASE_URL")


PAYLOAD = json.dumps({"session_id": "probe-session", "cwd": "/tmp", "hook_event_name": "UserPromptSubmit",
                      "prompt": "no, that's wrong — undo it", "source": "startup"})


def _resolve(script: str, home: pathlib.Path, monkeypatch) -> str:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MNEMO_HOOK_KEY", "k")             # hooks exit before resolving without a key
    monkeypatch.setattr(sys, "stdin", io.StringIO(PAYLOAD))
    src = (ROOT / script).read_text()
    start = src.index("_mnemo_base = (")
    end = src.index(').rstrip("/")', src.index("\n)", start) - 1) + len(').rstrip("/")')
    ns: dict = {"__name__": "probe", "__file__": str(ROOT / script)}
    exec(compile(src[:end] + "\n", script, "exec"), ns)
    return ns["_mnemo_base"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".mnemo.env").write_text("MNEMO_BASE_URL=https://mnemo.example.test/\nMNEMO_HOOK_KEY=k\n")
    return tmp_path


@pytest.mark.parametrize("script", HOOKS)
def test_hook_uses_mnemo_base_url_from_env_file(home, monkeypatch, script):
    assert _resolve(script, home, monkeypatch) == "https://mnemo.example.test"


@pytest.mark.parametrize("script", HOOKS)
def test_plugin_option_still_wins(home, monkeypatch, script):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_SERVER_URL", "https://option.example.test")
    assert _resolve(script, home, monkeypatch) == "https://option.example.test"


@pytest.mark.parametrize("script", HOOKS)
def test_without_base_url_falls_back_like_before(tmp_path, monkeypatch, script):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    assert _resolve(script, tmp_path, monkeypatch) == "http://localhost:80"


def _setup_mod(home: pathlib.Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("cws", ROOT / "compile-wiki-setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._MNEMO_ENV, mod._CLAUDE_JSON = home / ".mnemo.env", home / ".claude.json"
    return mod


def test_mcp_self_heal_uses_mnemo_base_url(home):
    """Session-start self-heal used to rewrite mcpServers.mnemo to http://localhost/mcp/ on the VMs."""
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
    _setup_mod(home).setup_mcp_config()
    srv = json.loads((home / ".claude.json").read_text())["mcpServers"]["mnemo"]
    assert srv["url"] == "https://mnemo.example.test/mcp/"


def test_mcp_self_heal_legacy_host_port_still_works(tmp_path):
    (tmp_path / ".mnemo.env").write_text("MNEMO_HOST=h.test\nMNEMO_PORT=3456\nMNEMO_HOOK_KEY=k\n")
    (tmp_path / ".claude.json").write_text("{}")
    _setup_mod(tmp_path).setup_mcp_config()
    assert json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]["mnemo"]["url"] == "http://h.test:3456/mcp/"
