"""redact(): mask secrets in place instead of dropping the whole wiki note."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import mnemo_wiki_sanitizer as S  # noqa: E402


def test_redact_masks_every_secret_kind_and_keeps_the_note():
    text = ("# Storage account\n"
            "MNEMO_HOOK_KEY=sk_test_9f8e7d6c5b4a39281706f5e4d3c2b1a0\n"
            "tenant 72f988bf-86f1-41af-91ab-2d7cd011db47 and public ip 52.174.10.20, private 10.1.119.101\n"
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345\n"
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U\n"
            "key a3f9c2e8b1d4f6a7c9e2b4d8f1a3c5e7 done\n")
    assert S.scan(text)                                         # dirty before
    out = S.redact(text)
    assert S.is_clean_redacted(out)                             # clean after
    for s in ("sk_test_9f8e", "72f988bf", "52.174.10.20", "abcdefghijklmnop", "eyJhbGci", "a3f9c2e8b1d4"):
        assert s not in out
    assert "MNEMO_HOOK_KEY=***" in out and "# Storage account" in out
    assert "10.1.119.101" in out                                # private IPs are not secrets (not flagged by scan)


def test_redact_leaves_clean_text_unchanged():
    t = "# GPML01\nRun `systemctl is-active postfix` every minute; alert after 5 min below 1.\n"
    assert S.redact(t) == t and S.is_clean_redacted(t)
