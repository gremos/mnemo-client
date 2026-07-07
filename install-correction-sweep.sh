#!/usr/bin/env bash
# Install the Mnemo correction sweep as an hourly per-user systemd timer.
#
# Why: the live UserPromptSubmit correction hook only fires in INTERACTIVE
# sessions. Fleet users run headless cli+child / sdk sessions where it never
# fires, so their corrections (incl. Greek) never reach the RL loop. This timer
# runs a bilingual sweep hourly per user, independent of the flaky Stop hook.
#
# Usage (run as root on the VM):
#   ./install-correction-sweep.sh aziogolos akostantopoulos igkiatis pchloros
#
# Idempotent: re-running refreshes the script + units and re-enables the timers.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (installs system-level templated units + per-user bin)" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
USERS=("$@")
if [[ ${#USERS[@]} -eq 0 ]]; then
    echo "usage: $0 <user> [<user> ...]" >&2
    exit 1
fi

# 1. Install the templated units (once, system-wide).
install -m 0644 "$SRC_DIR/systemd/mnemo-correction-sweep@.service" /etc/systemd/system/
install -m 0644 "$SRC_DIR/systemd/mnemo-correction-sweep@.timer"   /etc/systemd/system/
systemctl daemon-reload

# 2. Per user: drop the scripts into ~/.mnemo/bin and enable the timer.
for u in "${USERS[@]}"; do
    home="/home/$u"
    if [[ ! -d "$home" ]]; then
        echo "skip $u — no home dir" >&2
        continue
    fi
    bin="$home/.mnemo/bin"
    install -d -o "$u" -g "$u" -m 0755 "$bin"
    install -o "$u" -g "$u" -m 0755 "$SRC_DIR/mnemo-correction-sweep.py"    "$bin/"
    install -o "$u" -g "$u" -m 0644 "$SRC_DIR/mnemo_correction_patterns.py" "$bin/"
    systemctl enable --now "mnemo-correction-sweep@${u}.timer"
    echo "enabled mnemo-correction-sweep@${u}.timer"
done

echo
echo "Done. Verify:  systemctl list-timers 'mnemo-correction-sweep@*'"
echo "One-off run:   systemctl start mnemo-correction-sweep@<user>.service"
echo "Logs:          journalctl -u mnemo-correction-sweep@<user>.service"
