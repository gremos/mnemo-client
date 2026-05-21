#!/usr/bin/env bash
# Install the wiki auto-compile timer on a new Linux machine.
# Run once after: claude plugin install mnemo@mnemo-marketplace
#
# Usage:
#   bash "$(ls ~/.claude/plugins/cache/mnemo-marketplace/mnemo/*/compile-wiki-setup.sh | tail -1)"

set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p ~/.local/bin ~/.config/systemd/user ~/.local/share/compile-wiki-auto

cp "$SRC/compile-wiki-auto.sh" ~/.local/bin/
chmod +x ~/.local/bin/compile-wiki-auto.sh

cp "$SRC/compile-wiki.service" ~/.config/systemd/user/
cp "$SRC/compile-wiki.timer" ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now compile-wiki.timer

echo "Wiki auto-compile timer enabled."
systemctl --user status compile-wiki.timer --no-pager
