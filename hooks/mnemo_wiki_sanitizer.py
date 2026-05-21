"""
mnemo_wiki_sanitizer — fail-closed pre-write secret scanner.

Usage:
    from mnemo_wiki_sanitizer import is_clean, scan

    if is_clean(text):
        write(text)
    else:
        hits = scan(text)
        for h in hits: log(h)
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Known env-var name denylist — built from mcp-memory/.env.example keys
# and any live values in ~/.claude/skills/mnemo/.env
# ---------------------------------------------------------------------------

_DENYLIST_NAMES: set[str] = {
    "POSTGRES_PASSWORD", "REDIS_PASSWORD", "ADMIN_TOKEN",
    "ENCRYPTION_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
    "AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_SECRET",
    "GOOGLE_API_KEY", "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_SECRET",
    "CAPSOLVER_API_KEY", "MNEMO_ADMIN_TOKEN", "MNEMO_HOOK_KEY",
    "DATABASE_URL", "SECRET_KEY", "API_KEY", "ACCESS_TOKEN",
    "REFRESH_TOKEN", "PRIVATE_KEY", "AUTH_TOKEN", "BEARER_TOKEN",
}

_LIVE_SECRETS: set[str] = set()


def _load_live_secrets() -> None:
    for env_path in (
        os.path.expanduser("~/.claude/skills/mnemo/.env"),
        os.path.expanduser("~/.mnemo.env"),
    ):
        if not os.path.isfile(env_path):
            continue
        try:
            for line in open(env_path, errors="replace"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    val = line.split("=", 1)[1].strip()
                    if len(val) >= 8:
                        _LIVE_SECRETS.add(val)
        except Exception:
            pass


_load_live_secrets()

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_HIGH_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")
_RE_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_RE_HEX_SECRET = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_RE_AZURE_GUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_RE_NON_RFC1918_IPV4 = re.compile(
    r"\b(?!(?:10|127)\.\d+\.\d+\.\d+)"
    r"(?!172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)"
    r"(?!192\.168\.\d+\.\d+)"
    r"(?!0\.0\.0\.0)"
    r"(?!255\.255\.255\.255)"
    r"(\d{1,3}\.){3}\d{1,3}\b"
)
_RE_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9+/=_\-]{16,}")
_RE_ENV_VAR_NAME = re.compile(r"\b([A-Z][A-Z0-9_]{4,})\s*[=:]")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    rule: str
    match: str
    context: str


def scan(text: str) -> list[Hit]:
    """Return a list of secret hits found in text. Empty list = clean."""
    hits: list[Hit] = []

    # Live secrets (exact substring match)
    for secret in _LIVE_SECRETS:
        if secret in text:
            hits.append(Hit("live_secret", secret[:8] + "...", "exact match from .env"))

    # JWT
    for m in _RE_JWT.finditer(text):
        hits.append(Hit("jwt", m.group()[:20] + "...", "JWT token pattern"))

    # Bearer token
    for m in _RE_BEARER.finditer(text):
        hits.append(Hit("bearer_token", m.group()[:20] + "...", "Bearer header value"))

    # 32+ hex chars (API keys, UUIDs with no dashes, etc.)
    for m in _RE_HEX_SECRET.finditer(text):
        val = m.group()
        if _shannon_entropy(val) >= 3.5:
            hits.append(Hit("hex_secret", val[:12] + "...", "high-entropy hex string"))

    # Azure GUID
    for m in _RE_AZURE_GUID.finditer(text):
        hits.append(Hit("azure_guid", m.group(), "Azure subscription/tenant/client GUID"))

    # Non-RFC1918 IPv4
    for m in _RE_NON_RFC1918_IPV4.finditer(text):
        hits.append(Hit("public_ip", m.group(), "public IP address"))

    # High-entropy tokens (20+ chars, entropy >= 4.2)
    for m in _RE_HIGH_ENTROPY_TOKEN.finditer(text):
        val = m.group()
        if len(val) >= 20 and _shannon_entropy(val) >= 4.2:
            hits.append(Hit("high_entropy_token", val[:12] + "...", f"entropy={_shannon_entropy(val):.1f}"))

    # Known env-var names in text
    for m in _RE_ENV_VAR_NAME.finditer(text):
        name = m.group(1)
        if name in _DENYLIST_NAMES:
            hits.append(Hit("env_var_name", name, "known secret variable name"))

    # Deduplicate by rule+match
    seen: set[str] = set()
    deduped: list[Hit] = []
    for h in hits:
        key = f"{h.rule}:{h.match}"
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    return deduped


def is_clean(text: str) -> bool:
    """Return True if text passes all sanitization checks."""
    return len(scan(text)) == 0
