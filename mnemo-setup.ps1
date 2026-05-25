# Configure Mnemo by writing ~/.mnemo.env
# Usage: .\mnemo-setup.ps1 <server_url> <api_token>
# Example: .\mnemo-setup.ps1 http://localhost mcp_admin_s3cur3_2026
param(
    [Parameter(Mandatory, Position=0)][string]$ServerUrl,
    [Parameter(Mandatory, Position=1)][string]$ApiToken
)

$uri  = [System.Uri]$ServerUrl
$host_ = $uri.Host
$port  = if ($uri.Port -gt 0 -and $uri.Port -notin @(80, 443)) { "$($uri.Port)" } else { "" }

$env_path = Join-Path $env:USERPROFILE ".mnemo.env"

@"
MNEMO_HOST=$host_
MNEMO_PORT=$port
MNEMO_ADMIN_TOKEN=$ApiToken
"@ | Set-Content -Encoding UTF8 -NoNewline $env_path

Write-Host "Mnemo configured: $host_$(if ($port) { ":$port" })"
Write-Host "Restart Claude Code to connect."
