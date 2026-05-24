#!/usr/bin/env python3
"""
mnemo_wiki_write — sanitizer-enforcing wiki entry writer.

CLI reads body from stdin:
    echo "body text" | python3 mnemo_wiki_write.py \\
        --cwd <path> --project <name> --slug <slug> --source user|auto-mend \\
        [--title "Override title"] [--no-create-default]

Steps:
1. Resolve target wiki root (nearest-marker walk-up, or default if no marker).
2. Build full markdown with frontmatter.
3. Write to 0600 temp file in the target directory.
4. Run mnemo_wiki_sanitizer.scan() — on any hit: unlink temp + exit 1.
5. Atomic rename to final path (raw/ for user, raw/auto/ for auto-mend).
6. Append one entry to log.md.

Exit codes:
  0 — written successfully
  1 — sanitizer blocked the write
  2 — configuration / IO error
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve plugin directory so imports work when called as a subprocess
# ---------------------------------------------------------------------------

_plugin_dir = Path(__file__).parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))


def _import_sanitizer():
    try:
        from mnemo_wiki_sanitizer import scan  # noqa: F401
        return scan
    except ImportError as exc:
        print(f"[mnemo-wiki-write] ERROR: mnemo_wiki_sanitizer not found: {exc}", file=sys.stderr)
        return None


def _import_resolver():
    try:
        from mnemo_wiki_resolver import resolve_wiki_root
        return resolve_wiki_root
    except ImportError as exc:
        print(f"[mnemo-wiki-write] ERROR: mnemo_wiki_resolver not found: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Public write function (importable by wrap-session-bg.py)
# ---------------------------------------------------------------------------

def write_wiki_entry(
    *,
    body: str,
    cwd: str,
    project: str,
    slug: str,
    source: str,                    # "user" | "auto-mend"
    title: str = "",
    extra_frontmatter: dict | None = None,
    create_default: bool = True,
    session_id_to_redact: str = "", # UUID to replace with <SESSION_ID> before scan
) -> tuple[bool, str]:
    """
    Write a wiki entry.

    Returns (success, message).
    """
    resolve_wiki_root = _import_resolver()
    if resolve_wiki_root is None:
        return False, "resolver import failed"

    scan = _import_sanitizer()
    if scan is None:
        return False, "sanitizer import failed"

    wiki_root = resolve_wiki_root(cwd, create_default=create_default)
    if wiki_root is None:
        return False, f"could not resolve wiki root for cwd={cwd}"

    today = datetime.date.today().isoformat()
    safe_slug = re.sub(r"[^a-z0-9]+", "-", slug.lower())[:40].strip("-")
    filename = f"{today}-{safe_slug}.md"

    if source == "auto-mend":
        target_dir = wiki_root / "raw" / "auto"
    else:
        target_dir = wiki_root / "raw"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Build frontmatter
    fm_lines = [
        "---",
        f"source: {source}",
        f"date: {today}",
        f"project: {project}",
        f"auto: {'true' if source == 'auto-mend' else 'false'}",
    ]
    if extra_frontmatter:
        for k, v in extra_frontmatter.items():
            fm_lines.append(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}")
    fm_lines.append("---")

    heading = title.strip() or project
    content = "\n".join(fm_lines) + f"\n\n# {heading}\n\n{body.strip()}\n"

    # Strip sensitive UUIDs before scanning
    content_for_scan = content
    if session_id_to_redact:
        content_for_scan = content_for_scan.replace(session_id_to_redact, "<SESSION_ID>")

    hits = scan(content_for_scan)
    if hits:
        summary = ", ".join(f"{h.rule}:{h.match}" for h in hits[:3])
        return False, f"sanitizer blocked write ({summary})"

    # Write to temp file (0600) then atomically rename
    try:
        fd, tmp_path_str = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        tmp_path = Path(tmp_path_str)
        final_path = target_dir / filename
        tmp_path.rename(final_path)
    except Exception as exc:
        try:
            Path(tmp_path_str).unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"write failed: {exc}"

    # Append to log.md
    _append_log(wiki_root, today, source, project, filename)

    return True, str(final_path)


def _append_log(wiki_root: Path, date: str, source: str, project: str, filename: str) -> None:
    log_path = wiki_root / "log.md"
    entry = f"| {date} | {source} | {project} | {filename} |\n"
    try:
        if not log_path.exists():
            log_path.write_text(
                "# Wiki Log\n\n| Date | Source | Project | File |\n|---|---|---|---|\n" + entry,
                encoding="utf-8",
            )
        else:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(entry)
    except Exception as exc:
        print(f"[mnemo-wiki-write] WARNING: could not append to log.md: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mnemo_wiki_write",
        description="Write a sanitized wiki entry. Reads body from stdin.",
    )
    parser.add_argument("--cwd", required=True, help="Working directory to route from")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--slug", required=True, help="Filename slug (alphanumeric+dash)")
    parser.add_argument(
        "--source", required=True, choices=["user", "auto-mend"],
        help="Entry source: 'user' → raw/, 'auto-mend' → raw/auto/",
    )
    parser.add_argument("--title", default="", help="Override H1 title")
    parser.add_argument("--no-create-default", action="store_true",
                        help="Do not create default wiki if no marker found")
    args = parser.parse_args()

    body = sys.stdin.read()
    if not body.strip():
        print("[mnemo-wiki-write] ERROR: empty body on stdin", file=sys.stderr)
        sys.exit(2)

    ok, msg = write_wiki_entry(
        body=body,
        cwd=args.cwd,
        project=args.project,
        slug=args.slug,
        source=args.source,
        title=args.title,
        create_default=not args.no_create_default,
    )

    if ok:
        print(f"[mnemo-wiki-write] Written: {msg}")
        sys.exit(0)
    else:
        print(f"[mnemo-wiki-write] BLOCKED: {msg}", file=sys.stderr)
        sys.exit(1 if "sanitizer" in msg else 2)


if __name__ == "__main__":
    main()
