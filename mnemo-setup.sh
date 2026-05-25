#!/usr/bin/env bash
# Configure Mnemo by writing ~/.mnemo.env
# Usage: mnemo-setup.sh <server_url> <api_token>
# Example: mnemo-setup.sh http://localhost mcp_admin_s3cur3_2026
# Example: mnemo-setup.sh http://gremolap.xo.gr mcp_admin_s3cur3_2026
set -e

if [ $# -ne 2 ]; then
  echo "Usage: $(basename "$0") <server_url> <api_token>" >&2
  echo "  server_url  — base URL of the Mnemo server (e.g. http://localhost)" >&2
  echo "  api_token   — admin token from the server's .env" >&2
  exit 1
fi

SERVER_URL="$1"
API_TOKEN="$2"

HOST=$(python3 -c "from urllib.parse import urlparse; u=urlparse('$SERVER_URL'); print(u.hostname or 'localhost')")
PORT=$(python3 -c "from urllib.parse import urlparse; u=urlparse('$SERVER_URL'); p=u.port; print(p if p and p not in (80,443) else '')")

cat > "$HOME/.mnemo.env" <<EOF
MNEMO_HOST=${HOST}
MNEMO_PORT=${PORT}
MNEMO_ADMIN_TOKEN=${API_TOKEN}
EOF

chmod 600 "$HOME/.mnemo.env"
echo "Mnemo configured: ${HOST}${PORT:+:$PORT}"
echo "Restart Claude Code to connect."
