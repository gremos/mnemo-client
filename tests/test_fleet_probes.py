"""
Tests for fleet-probes.py's own logic -- the thing that watches for bugs
also gets tested for its own bugs, at the same pre-tag gate.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "fleet_probes", Path(__file__).resolve().parent.parent / "fleet-probes.py"
)
fleet_probes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fleet_probes)


def test_probe_guard_passes_against_real_guard_action():
    result = fleet_probes.probe_guard()
    assert result["status"] == "pass", result


def test_probe_memory_reports_fail_on_exception(monkeypatch):
    def _boom(tool, arguments):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(fleet_probes, "_mcp_call", _boom)
    result = fleet_probes.probe_memory()
    assert result["status"] == "fail"
    assert "connection refused" in result["reason"]


def test_probe_wiki_reports_fail_on_exception(monkeypatch):
    def _boom(tool, arguments):
        raise RuntimeError("timeout")
    monkeypatch.setattr(fleet_probes, "_mcp_call", _boom)
    result = fleet_probes.probe_wiki()
    assert result["status"] == "fail"
    assert "timeout" in result["reason"]


def test_probe_memory_passes_on_valid_response(monkeypatch):
    def _ok(tool, arguments):
        return {"content": [{"type": "text", "text": "[]"}]}
    monkeypatch.setattr(fleet_probes, "_mcp_call", _ok)
    result = fleet_probes.probe_memory()
    assert result["status"] == "pass"
