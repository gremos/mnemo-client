# compile-wiki-auto.ps1 — Windows wiki auto-compile runner.
# Triggered daily by Windows Task Scheduler (MnemoCompileWiki).
# Skips wikis with no pending raw/auto/ drafts — no API cost on empty runs.

$ErrorActionPreference = "SilentlyContinue"

$ClaudeCmd = (Get-Command claude -ErrorAction SilentlyContinue)
$CLAUDE    = if ($ClaudeCmd) { $ClaudeCmd.Source } else { "claude" }
$SKILL     = "$env:USERPROFILE\.claude\skills\compile-wiki\SKILL.md"
$LOG       = "$env:LOCALAPPDATA\compile-wiki-auto"

$WIKIS = @(
    "$env:USERPROFILE\Documents\code\Personal\wiki",
    "$env:USERPROFILE\Documents\code\XO\wiki"
)

$compiled = 0
foreach ($wiki in $WIKIS) {
    if (-not (Test-Path $wiki)) { continue }
    $auto = "$wiki\raw\auto"
    if (-not (Test-Path $auto)) { continue }
    $count = (Get-ChildItem $auto -Filter "*.md" -ErrorAction SilentlyContinue).Count
    if ($count -eq 0) { continue }

    $parent   = Split-Path (Split-Path $wiki -Parent) -Leaf
    $wikiName = "$parent-wiki"
    $date     = Get-Date -Format "yyyy-MM-dd"
    $log      = "$LOG\$date-$wikiName.log"

    New-Item -ItemType Directory -Force -Path $LOG | Out-Null
    "[$((Get-Date).ToString('o'))] Compiling $wikiName ($count pending draft(s))..." |
        Add-Content -Path $log

    Push-Location $wiki
    & $CLAUDE -p $SKILL 2>&1 | Add-Content -Path $log
    $exit = $LASTEXITCODE
    Pop-Location

    if ($exit -eq 0) {
        "[$((Get-Date).ToString('o'))] Done: $wikiName" | Add-Content -Path $log
        $compiled++
    } else {
        "[$((Get-Date).ToString('o'))] FAILED: $wikiName — see $log" | Add-Content -Path $log
    }
}

if ($compiled -eq 0) {
    "[$((Get-Date).ToString('o'))] No pending drafts in any wiki — nothing compiled." |
        Write-Host
}
