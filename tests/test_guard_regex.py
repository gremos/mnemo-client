"""
Pre-tag gate for guard-action.py's static catastrophic-command patterns.

This is the exact 20-case matrix used to find and verify the 2026-07-16 regex-anchor
bug (git commit fccd9c1) where \\b failed next to punctuation-only tokens and the
guard silently never fired on its own canonical test cases ("rm -rf /",
"git push --force ... main"). Runs against the real CATASTROPHIC list, not a copy,
so the two can never drift apart again.
"""
import importlib.util
from pathlib import Path

# guard-action.py has a hyphen (not a valid module name) -- load it by path.
_spec = importlib.util.spec_from_file_location(
    "guard_action", Path(__file__).resolve().parent.parent / "guard-action.py"
)
_guard_action = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard_action)
check_catastrophic = _guard_action.check_catastrophic


CASES = [
    # (command, should_flag)
    ("rm -rf /", True),
    ("rm -rf ~", True),
    ("rm -rf /*", True),
    ("rm -rf $HOME", True),
    ("rm -rf / --no-preserve-root", True),
    ("rm -rf /home/user", False),
    ("rm -rf ./node_modules", False),
    ("rm -rf /tmp/scratch", False),
    ("git push --force origin main", True),
    ("git push -f origin master", True),
    ("git push --force-with-lease origin main", False),
    ("git push origin feature-branch", False),
    ("git push --force origin feature-branch", False),
    ("drop database prod", True),
    ("mkfs.ext4 /dev/sdb1", True),
    ("dd if=/dev/zero of=/dev/sda", True),
    ("dd if=backup.img of=restore.img", False),
    (":(){ :|:& };:", True),
    ("ls -la", False),
    ("git status", False),
]


def test_catastrophic_matrix():
    failures = []
    for cmd, should_flag in CASES:
        flagged = check_catastrophic(cmd) is not None
        if flagged != should_flag:
            failures.append(f"  {cmd!r}: expected flagged={should_flag}, got {flagged}")
    assert not failures, "guard regex matrix mismatch:\n" + "\n".join(failures)
