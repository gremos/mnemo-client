#!/usr/bin/env python3
"""
Cross-platform installer for the Mnemo wiki auto-compile timer.

Called automatically by load-context.py on first plugin use (sentinel check).
Can also be run manually:  python3 compile-wiki-setup.py

Platforms:
  Linux  + systemd  → systemd user timer
  Linux  no systemd → crontab (also used for WSL)
  WSL               → crontab
  macOS             → launchd LaunchAgent
  Windows           → Task Scheduler (schtasks)
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SENTINEL = Path.home() / ".local/share/compile-wiki-auto/.installed"
LOG_DIR  = Path.home() / ".local/share/compile-wiki-auto"


# ---------------------------------------------------------------------------
# Platform detection
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


def _systemd_available() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True, timeout=3,
        )
        return r.returncode in (0, 1)  # 0=running, 1=degraded — both usable
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Installers
# ---------------------------------------------------------------------------

_SHIM_SH = '''\
#!/usr/bin/env bash
# Shim — delegates to plugin dir so plugin updates take effect automatically.
exec bash "${HOME}/.claude/plugins/mnemo-current/compile-wiki-auto.sh" "$@"
'''

_SHIM_PS1 = '''\
# Shim — delegates to plugin dir so plugin updates take effect automatically.
& "$env:USERPROFILE\\.claude\\plugins\\mnemo-current\\compile-wiki-auto.ps1" @args
'''

_SHIM_SENTINEL = Path.home() / ".local/share/compile-wiki-auto/.shim-installed"


def _install_shim_sh(bin_dir: Path) -> Path:
    """Write the bash shim to ~/.local/bin/compile-wiki-auto.sh and return it."""
    script = bin_dir / "compile-wiki-auto.sh"
    script.write_text(_SHIM_SH, encoding="utf-8")
    script.chmod(0o755)
    _SHIM_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    _SHIM_SENTINEL.touch()
    return script


def _install_shim_ps1(bin_dir: Path) -> Path:
    """Write the PowerShell shim to ~/.local/bin/compile-wiki-auto.ps1 and return it."""
    script = bin_dir / "compile-wiki-auto.ps1"
    script.write_text(_SHIM_PS1, encoding="utf-8")
    _SHIM_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    _SHIM_SENTINEL.touch()
    return script


def _install_linux_systemd(plugin_root: str) -> None:
    bin_dir = Path.home() / ".local/bin"
    unit_dir = Path.home() / ".config/systemd/user"
    bin_dir.mkdir(parents=True, exist_ok=True)
    unit_dir.mkdir(parents=True, exist_ok=True)

    script = _install_shim_sh(bin_dir)

    for unit in ("compile-wiki.service", "compile-wiki.timer"):
        shutil.copy(Path(plugin_root) / unit, unit_dir / unit)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "compile-wiki.timer"], check=False)
    print(f"Wiki auto-compile: systemd user timer enabled (daily 07:00) via {script}.")


def _install_crontab(plugin_root: str) -> None:
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    script = _install_shim_sh(bin_dir)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cron_line = (
        f"0 7 * * * {script} >> {LOG_DIR}/cron.log 2>&1"
    )

    existing = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    if cron_line in existing:
        print("Wiki auto-compile: crontab entry already present.")
        return

    new_cron = existing.rstrip("\n") + ("\n" if existing.strip() else "") + cron_line + "\n"
    subprocess.run(["crontab", "-"], input=new_cron, text=True, check=False)
    print("Wiki auto-compile: crontab entry added (daily 07:00).")


def _install_macos(plugin_root: str) -> None:
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    script = _install_shim_sh(bin_dir)

    agents_dir = Path.home() / "Library/LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_dst = agents_dir / "com.mnemo.compile-wiki.plist"

    template = (Path(plugin_root) / "com.mnemo.compile-wiki.plist").read_text()
    plist_content = template.replace("__HOME__", str(Path.home()))
    plist_dst.write_text(plist_content)

    subprocess.run(["launchctl", "unload", str(plist_dst)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_dst)], check=False)
    print(f"Wiki auto-compile: launchd agent loaded ({plist_dst}) via {script}.")


def _install_windows(plugin_root: str) -> None:
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    script = _install_shim_ps1(bin_dir)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.run([
        "schtasks", "/create", "/f",
        "/tn", "MnemoCompileWiki",
        "/tr", f'powershell.exe -WindowStyle Hidden -NonInteractive -File "{script}"',
        "/sc", "daily",
        "/st", "07:00",
    ], check=False)
    print(f"Wiki auto-compile: Windows Task Scheduler task created ({script}).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if SENTINEL.exists():
        return

    plat = detect_platform()
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).parent))

    try:
        if plat == "linux":
            if _systemd_available():
                _install_linux_systemd(plugin_root)
            else:
                _install_crontab(plugin_root)
        elif plat in ("wsl", "unknown"):
            _install_crontab(plugin_root)
        elif plat == "macos":
            _install_macos(plugin_root)
        elif plat == "windows":
            _install_windows(plugin_root)
        else:
            return  # unsupported — skip silently

        SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        SENTINEL.touch()

    except Exception as e:
        print(f"Wiki auto-compile setup failed (non-fatal): {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
