#!/usr/bin/env bash
# Gate a mnemo-client release tag on the test suite passing.
#
# The sanctioned way to cut a release: `claude plugin tag` itself has no concept
# of tests, so this wraps it. Catches bugs (like the 2026-07-16 regex-anchor bug,
# which shipped through 3 commits before being caught by manual testing) before
# a release tag exists at all, not just verified after distribution.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "== running pytest gate =="
if ! python3 -m pytest tests/ -q; then
    echo "== tests FAILED — refusing to tag =="
    exit 1
fi

echo "== tests passed — tagging =="
claude plugin tag --push "$@"
