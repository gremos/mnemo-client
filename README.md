# mnemo-client

Claude Code plugin — long-term memory layer via the [Mnemo MCP server](https://github.com/gremos/mcp-memory).

## Install

```bash
claude plugin install mnemo@mnemo-marketplace
```

When prompted, enter your Mnemo server URL and API token.

> **Note (Claude Code ≤ 2.1.146):** If the credential prompt doesn't appear, set them manually:
>
> In `~/.claude/settings.json` → `pluginConfigs.mnemo@mnemo-marketplace.options.server_url`  
> In `~/.claude/plugins/cache/mnemo-marketplace/mnemo/<version>/.mcp.json`:
> ```json
> {"mcpServers":{"mnemo":{"type":"http","url":"<server_url>/mcp/","headers":{"Authorization":"Bearer <token>"}}}}
> ```

## Wiki auto-compile (Linux)

After plugin install, enable the daily wiki compile timer:

```bash
bash "$(ls ~/.claude/plugins/cache/mnemo-marketplace/mnemo/*/compile-wiki-setup.sh | tail -1)"
```

This installs a systemd user timer that compiles pending `raw/auto/` drafts into wiki pages every morning at 07:00 — only when there is content to compile.

Logs: `~/.local/share/compile-wiki-auto/`

## What it does

- **SessionStart hook** — loads top memories + active lesson directives as context
- **PreToolUse hook** — evaluates Bash commands against active lessons
- **UserPromptSubmit hook** — detects user corrections for the RL loop
- **Stop hook** — wraps the session: extracts corrections/decisions via LLM, calls `wrap_session`, auto-drafts wiki entries for notable sessions
- **`/mnemo:memload`** — manual context reload after `/compact`
- **`/mnemo:memsave`** — manual session close
