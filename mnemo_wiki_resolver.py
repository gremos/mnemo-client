#!/usr/bin/env python3
"""
mnemo_wiki_resolver — central wiki routing for all mnemo plugin components.

Routing rules:
  - Walk up from cwd for nearest .mnemo-wiki marker.
  - Marker found + valid (path exists, has SCHEMA.md) → use it.
  - Marker found but invalid → log warning, return None.  NEVER fall back to
    default: a broken team marker must not silently write to a personal wiki.
  - No marker found → use/create default wiki.

Discovery rule (for compile runner):
  - Union of ~/.mnemo/wikis.list + ~/Documents/code/*/.mnemo-wiki scan + default.
  - wikis.list is compile-only; never used to route an unmarked cwd.

Importable API:
    from mnemo_wiki_resolver import (
        resolve_wiki_root, resolve_wiki_auto_dir,
        discover_wikis, parse_marker, ensure_default_wiki,
    )

CLI:
    python3 mnemo_wiki_resolver.py resolve-auto --cwd <path> [--create-default]
    python3 mnemo_wiki_resolver.py discover [--create-default]
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Platform detection (canonical source — imported by compile-wiki-setup.py)
# ---------------------------------------------------------------------------

def detect_platform() -> str:
    sys_name = platform.system()
    if sys_name == "Windows":
        return "windows"
    if sys_name == "Darwin":
        return "macos"
    if sys_name == "Linux":
        try:
            ver = Path("/proc/version").read_text().lower()
            if "microsoft" in ver or "wsl" in ver:
                return "wsl"
        except OSError:
            pass
        return "linux"
    return "unknown"


_PLATFORM = detect_platform()

# ---------------------------------------------------------------------------
# .mnemo-wiki marker parser
# ---------------------------------------------------------------------------

def parse_marker(marker_path: Path) -> dict:
    """
    Parse a .mnemo-wiki file.  Returns dict with keys:
      root   -> Path (wiki root, expanded and made absolute, may not exist yet)
      scope  -> 'user' | 'team'
      valid  -> bool (root exists and contains SCHEMA.md)
      error  -> str | None

    File format (lines; order matters):
      First plain (non-key=value, non-comment) line: wiki root path (linux/macos).
      wsl=<path>     : override on WSL
      windows=<path> : override on Windows
      scope=user|team: visibility (default user)
    """
    result: dict = {"root": None, "scope": "user", "valid": False, "error": None}
    try:
        lines = marker_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        result["error"] = f"unreadable: {exc}"
        return result

    plain_root: str | None = None
    overrides: dict[str, str] = {}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip().lower()
            v = v.strip()
            if k in ("wsl", "windows", "macos"):
                overrides[k] = v
            elif k == "scope":
                result["scope"] = v if v in ("user", "team") else "user"
        elif plain_root is None:
            plain_root = line

    # Pick platform-specific path
    raw_root = overrides.get(_PLATFORM) or plain_root
    if not raw_root:
        result["error"] = "no root path in marker"
        return result

    root = Path(os.path.expanduser(raw_root)).expanduser().resolve()
    result["root"] = root
    if not root.exists():
        result["error"] = f"wiki root does not exist: {root}"
        return result
    if not (root / "SCHEMA.md").exists():
        result["error"] = f"wiki root has no SCHEMA.md: {root}"
        return result

    result["valid"] = True
    return result


# ---------------------------------------------------------------------------
# Walk-up marker finder
# ---------------------------------------------------------------------------

def _find_marker(start: Path) -> Path | None:
    """Walk up directory tree from start, return first .mnemo-wiki found."""
    current = start if start.is_dir() else start.parent
    home = Path.home()
    for _ in range(20):  # max depth
        candidate = current / ".mnemo-wiki"
        if candidate.is_file():
            return candidate
        if current == current.parent or current == home.parent:
            break
        current = current.parent
    return None


# ---------------------------------------------------------------------------
# Public routing API
# ---------------------------------------------------------------------------

def resolve_wiki_root(cwd: str | Path, create_default: bool = False) -> Path | None:
    """
    Return the wiki root Path for the given cwd, or None.

    Privacy invariant: if a .mnemo-wiki marker is found but invalid, log a
    warning and return None — never fall back to the default personal wiki.
    """
    cwd_path = Path(os.path.expanduser(str(cwd))).resolve() if cwd else Path.home()
    marker = _find_marker(cwd_path)

    if marker is not None:
        parsed = parse_marker(marker)
        if parsed["valid"]:
            return parsed["root"]
        # Marker exists but is broken — do NOT silently fall to default
        print(
            f"[mnemo-wiki] WARNING: .mnemo-wiki at {marker} is invalid"
            f" ({parsed['error']}) — skipping wiki write to protect privacy.",
            file=sys.stderr,
        )
        return None

    # No marker found
    if create_default:
        return ensure_default_wiki()
    return None


def resolve_wiki_auto_dir(cwd: str | Path, create_default: bool = False) -> Path | None:
    """Return <wiki_root>/raw/auto/ for the given cwd, or None."""
    root = resolve_wiki_root(cwd, create_default=create_default)
    if root is None:
        return None
    auto_dir = root / "raw" / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)
    return auto_dir


# ---------------------------------------------------------------------------
# Discovery for compile runner
# ---------------------------------------------------------------------------

def discover_wikis(create_default: bool = False) -> list[Path]:
    """
    Return all configured wiki roots: wikis.list + marker scan + default.
    Each entry is validated (exists + has SCHEMA.md).  Deduped.
    """
    seen: set[Path] = set()
    roots: list[Path] = []

    def _add(p: Path) -> None:
        p = p.resolve()
        if p in seen:
            return
        if not p.exists() or not (p / "SCHEMA.md").exists():
            return
        seen.add(p)
        roots.append(p)

    # 1. wikis.list (compile-only registry)
    wikis_list = Path.home() / ".mnemo" / "wikis.list"
    if wikis_list.is_file():
        for line in wikis_list.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                _add(Path(os.path.expanduser(line)))

    # 2. Scan ~/Documents/code/*/.mnemo-wiki (one level deep)
    code_dir = Path.home() / "Documents" / "code"
    if code_dir.is_dir():
        for marker in sorted(code_dir.glob("*/.mnemo-wiki")):
            parsed = parse_marker(marker)
            if parsed["valid"] and parsed["root"]:
                _add(parsed["root"])

    # 3. Default wiki (if it exists or if create_default=True)
    default = _default_wiki_path()
    if default is not None and (default.exists() or create_default):
        if create_default and not default.exists():
            _scaffold_wiki(default)
        if default.exists():
            _add(default)

    return roots


# ---------------------------------------------------------------------------
# Default wiki
# ---------------------------------------------------------------------------

def _default_wiki_path() -> Path | None:
    """Return the preferred default wiki root path (not yet created)."""
    docs = Path.home() / "Documents"
    if docs.is_dir():
        return docs / "Mnemo" / "wiki"
    # Fallback if ~/Documents is unavailable
    return Path.home() / ".mnemo" / "wiki"


def ensure_default_wiki() -> Path:
    """
    Create and register the default personal wiki if it does not exist.
    Returns the wiki root path.
    """
    root = _default_wiki_path()
    if root is None:
        root = Path.home() / ".mnemo" / "wiki"
    if not root.exists():
        _scaffold_wiki(root)
    return root


def _scaffold_wiki(root: Path) -> None:
    """Create a bare wiki skeleton from bundled templates."""
    plugin_dir = Path(__file__).parent
    templates_dir = plugin_dir / "templates" / "wiki"

    for subdir in ("raw", "raw/auto", "raw/processed", "wiki"):
        (root / subdir).mkdir(parents=True, exist_ok=True)

    # Write from templates if available; fall back to minimal inline defaults
    for fname, template_name, inline in (
        ("SCHEMA.md",  "SCHEMA.md.template",  _SCHEMA_DEFAULT),
        ("index.md",   "index.md.template",   _INDEX_DEFAULT),
        ("log.md",     "log.md.template",     _LOG_DEFAULT),
    ):
        dest = root / fname
        if dest.exists():
            continue
        tmpl = templates_dir / template_name
        if tmpl.is_file():
            dest.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            dest.write_text(inline, encoding="utf-8")

    # Register in ~/.mnemo/wikis.list
    wikis_list = Path.home() / ".mnemo" / "wikis.list"
    wikis_list.parent.mkdir(parents=True, exist_ok=True)
    existing = wikis_list.read_text(encoding="utf-8") if wikis_list.is_file() else ""
    root_str = str(root)
    if root_str not in existing:
        with wikis_list.open("a", encoding="utf-8") as f:
            f.write(root_str + "\n")

    print(f"[mnemo-wiki] Created default wiki at {root}", file=sys.stderr)


# Minimal inline fallbacks when templates/ directory is missing
_SCHEMA_DEFAULT = """\
# Mnemo Wiki — Schema & Conventions

## Purpose

Personal knowledge base compiled from Claude Code sessions.

## Taxonomy

- `wiki/projects/`  — per-project notes
- `wiki/concepts/`  — technology concepts and decisions
- `wiki/inbox/`     — unclassified entries (review periodically)

## Conventions

- Pages use `[[links]]` to related pages.
- Frontmatter: `tags`, `updated`, `project`.
- `auto: true` pages are machine-generated drafts — compile-only, not authoritative.

## Seed pages

- `wiki/index.md` — master index
"""

_INDEX_DEFAULT = """\
# Mnemo Wiki Index

Auto-generated knowledge base from Claude Code sessions.

## Projects

<!-- add project links here as pages are compiled -->

## Concepts

<!-- add concept links here -->
"""

_LOG_DEFAULT = """\
# Wiki Log

| Date | Action | Pages Affected |
|---|---|---|
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="mnemo_wiki_resolver")
    sub = parser.add_subparsers(dest="cmd")

    ra = sub.add_parser("resolve-auto", help="Print raw/auto/ path for a cwd")
    ra.add_argument("--cwd", required=True)
    ra.add_argument("--create-default", action="store_true")

    dis = sub.add_parser("discover", help="Print all wiki roots, one per line")
    dis.add_argument("--create-default", action="store_true")

    args = parser.parse_args()

    if args.cmd == "resolve-auto":
        result = resolve_wiki_auto_dir(args.cwd, create_default=args.create_default)
        if result:
            print(result)
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.cmd == "discover":
        roots = discover_wikis(create_default=args.create_default)
        for r in roots:
            print(r)
        # Exit 0 even if empty — compile runner handles the empty case

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli()
