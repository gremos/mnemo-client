---
name: wiki-init
description: Scaffold a new wiki for a project or workspace, with routing configured via a .mnemo-wiki marker.
---

# /mnemo:wiki-init — Initialise a Wiki

Create a new wiki for a project or workspace.  After this, the Mnemo Stop hook
and `/mnemo:wiki-save` will automatically route sessions from that cwd to this wiki.

## When to use

- You want a **separate company wiki** for a workspace (e.g. `~/Documents/code/XO/`)
- You want a **project-specific wiki** that overrides a parent workspace marker
  (e.g. `~/Documents/code/XO/Endoscopiki/` should write to a Personal-scope wiki,
  not the XO team wiki)
- A new team member is setting up Mnemo and wants their own wiki

**Nearest-marker-wins rule:** placing a `.mnemo-wiki` inside a subdirectory overrides
any parent marker.  This is how you route a project to a different wiki than its
workspace default.

## Procedure

1. Ask the user:
   - **Workspace path** — which directory to route from (the `.mnemo-wiki` marker goes
     here). Default: current `cwd`.
   - **Wiki root path** — where to create the wiki. Default: `<workspace>/../wiki`
     or `~/Documents/Mnemo/wiki` if no good default exists.
   - **Scope** — `user` (personal, only you) or `team` (visible to all team members
     via `search_wiki`). Default: `user`.

2. Create the wiki skeleton if it does not exist:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/mnemo_wiki_resolver.py" discover --create-default
   ```

   Then scaffold manually if the path is non-default:

   ```
   <wiki_root>/
     raw/            # human-reviewed intake files
     raw/auto/       # machine-generated drafts (auto: true)
     raw/processed/  # processed intake files (archived after compile)
     wiki/           # compiled output pages
     SCHEMA.md       # taxonomy and conventions — EDIT THIS
     index.md        # master page index
     log.md          # compile history
   ```

   Copy templates from `${CLAUDE_PLUGIN_ROOT}/templates/wiki/` to the wiki root.

3. Write the `.mnemo-wiki` marker:

   ```
   <workspace_path>/.mnemo-wiki
   ```

   Content (adapt paths for WSL/Windows if relevant):

   ```
   ~/path/to/wiki_root
   wsl=/mnt/c/path/to/wiki_root
   windows=C:/path/to/wiki_root
   scope=user
   ```

4. Register the wiki root in `~/.mnemo/wikis.list` (one path per line).

5. Report: workspace path, wiki root, scope, and confirm that the next session
   in `<workspace_path>` will route to this wiki.

## Example — Endoscopiki subproject override

Situation: `~/Documents/code/XO/.mnemo-wiki` routes all XO work to the XO team wiki.
Endoscopiki is an XO directory but should write to a personal wiki.

```
# In ~/Documents/code/XO/Endoscopiki/.mnemo-wiki:
~/Documents/code/Personal/wiki
scope=user
```

Now sessions under `.../XO/Endoscopiki/` write to Personal wiki.
Sessions under any other `.../XO/...` path still write to XO wiki.
