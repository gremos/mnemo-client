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
    for s in ("sk_test_9f8e", "72f988bf", "abcdefghijklmnop", "eyJhbGci", "a3f9c2e8b1d4"):
        assert s not in out
    assert "MNEMO_HOOK_KEY=***" in out and "# Storage account" in out
    assert "10.1.119.101" in out and "52.174.10.20" in out      # IPs are kept, public and private (user decision)


def test_redact_leaves_clean_text_unchanged():
    t = "# GPML01\nRun `systemctl is-active postfix` every minute; alert after 5 min below 1.\n"
    assert S.redact(t) == t and S.is_clean_redacted(t)


def test_wordlike_paths_kept_real_secret_shapes_still_masked():
    import mnemo_wiki_sanitizer as S
    keep = ["scripts/Invoke-EmployeeOffboarding.ps1", "infra/GPML01/runbooks/cutover-saturday",
            "packer_conf.pkr.hcl and docs/runbooks/sql-estate-holistic-check-2026-10-03.md",
            "GYP-WEU-02-RES01-PRDENV-LOBDB01-phase1",
            "https://dev.azure.com/XOITEngineers/XO-Cloud-Intelligence/_git/infra-azure-gyp?path=/docs/adr/0009-gpml01-fail2ban-gr-geoip.md",
            "docs/adr/0012-gpml01-resize-d8ads-v6-to-d4ads-v6.md",
            "/resourceGroups/GYP-WEU-02-RES01-PRDENV-XODB01/providers/Microsoft.Compute/virtualMachines/WEU02PRDXODB01",
            "Critical-VmHealth-HeartbeatMissing-WEU02PRDXODB01", "-ResourceGroupName", "kubernetes/apps/ak01/xogrla01dcr01/base",
            "/runs/gpml01-cutover-20260725-153000/", "infra/3CX01/apps/3cx01-cdr/2026"]
    for t in keep:
        assert S.redact(t) == t, t
        assert S.is_clean_redacted(t), t
    # fabricated secret shapes (not real values)
    storage_key = "q7Zt9Kp2Lm4Xv8Rb1Nc6Ws3Hd5Jf0Ga+Ye2Ui7Oo4Pp9Qq1Rr6Ss3Tt8Uu5Vv0Ww2Xx7Yy4Zz9Aa1Bb6Cc3Dd8Ee5Ff0Gg2Hh7Ii==" 
    gh = "ghp_" + "Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7c"
    client_secret = "Xq8Q~" + "aB3dE6fG9hI2jK5lM8nO1pQ4rS7tU0vW3xY6z"
    sas = "sig=" + "Zk3Lp9Qx2Wm7Rt5Yv8Bn1Hc4Jd6Fs0Ga3Ke9Ut"
    for t in (storage_key, gh, client_secret, sas, "AbC12/xYz98/QwE45/rTy76/uIo10",
              "k3j9x2m8q7w4z1v6b5n0c8p2/l4h7"):
        assert "***" in S.redact(t), t


def test_live_secrets_only_secret_named_values(tmp_path, monkeypatch):
    import mnemo_wiki_sanitizer as S
    env = tmp_path / "x.env"
    env.write_text("MNEMO_HOST=10.20.30.40\nMNEMO_BASE_URL=https://mnemo.example\nMNEMO_HOOK_KEY=hk_fake_value_123456\n"
                   "export AZURE_OPENAI_API_KEY='fakeazurekeyvalue99'\n")
    monkeypatch.setattr(S, "_LIVE_SECRETS", set())
    S._load_live_secrets((str(env),))
    assert S._LIVE_SECRETS == {"hk_fake_value_123456", "fakeazurekeyvalue99"}
    assert S.redact("host 10.20.30.40 key hk_fake_value_123456") == "host 10.20.30.40 key ***"
