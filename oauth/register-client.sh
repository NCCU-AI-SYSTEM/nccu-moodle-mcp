#!/usr/bin/env sh
# Register (or re-register) the ChatGPT OAuth client in Hydra via the Admin API.
# The Admin API is not published; we reach it from a throwaway curl container on
# the compose network. Run after the stack is up:  ./oauth/register-client.sh
#
# Reads OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET / OAUTH_REDIRECT_URI from .env.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f $ROOT/docker-compose.oauth.yml"

if [ -f "$ROOT/.env" ]; then
  set -a; . "$ROOT/.env"; set +a
fi

: "${OAUTH_CLIENT_ID:?set OAUTH_CLIENT_ID in .env}"
: "${OAUTH_CLIENT_SECRET:?set OAUTH_CLIENT_SECRET in .env}"
: "${OAUTH_REDIRECT_URI:?set OAUTH_REDIRECT_URI in .env}"

JSON=$(cat <<JSONEOF
{"client_id":"$OAUTH_CLIENT_ID","client_secret":"$OAUTH_CLIENT_SECRET","grant_types":["authorization_code","refresh_token"],"response_types":["code"],"scope":"openid offline moodle","redirect_uris":["$OAUTH_REDIRECT_URI"],"token_endpoint_auth_method":"client_secret_post"}
JSONEOF
)

CMD="curl -sS -X DELETE http://hydra:4445/admin/clients/$OAUTH_CLIENT_ID >/dev/null 2>&1 || true; \
curl -sS -o /dev/null -w '%{http_code}' -X POST http://hydra:4445/admin/clients \
  -H 'Content-Type: application/json' -d '$JSON'"

echo "Registering client '$OAUTH_CLIENT_ID'…"
CODE=$($COMPOSE run --rm -T client-register "$CMD")
echo "  Admin API responded: HTTP $CODE"
case "$CODE" in
  20*) : ;;
  *) echo "  Client creation failed (expected 201)."; exit 1 ;;
esac

echo
echo "Configure the ChatGPT connector with:"
echo "  Authorization URL: ${PUBLIC_URL:-<PUBLIC_URL>}/oauth2/auth"
echo "  Token URL:         ${PUBLIC_URL:-<PUBLIC_URL>}/oauth2/token"
echo "  Client ID:         $OAUTH_CLIENT_ID"
echo "  Client Secret:     (the OAUTH_CLIENT_SECRET from .env)"
echo "  Scopes:            openid offline moodle"
echo "  MCP endpoint:      ${PUBLIC_URL:-<PUBLIC_URL>}/mcp"
