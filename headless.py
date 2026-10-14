"""Is this hook running inside a programmatic Claude run (`claude -p`, Agent SDK)?

Claude Code sets CLAUDE_CODE_ENTRYPOINT: `cli` / `claude-vscode` for a person at the keyboard,
`sdk-*` or `mcp` for automation. No human reads an automated run's context and nobody corrects it,
so the hooks inject nothing and log no corrections there.
"""
import os
import re


def is_headless(environ=os.environ) -> bool:
    return bool(re.match(r"(sdk-|mcp)", environ.get("CLAUDE_CODE_ENTRYPOINT") or ""))
