#!/usr/bin/env bash
# Manual installer for the wiki auto-compile timer.
# Cross-platform: delegates to compile-wiki-setup.py.
#
# Usage (after plugin install):
#   bash "$(ls ~/.claude/plugins/cache/mnemo-marketplace/mnemo/*/compile-wiki-setup.sh | tail -1)"

set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
python3 "$SRC/compile-wiki-setup.py"
