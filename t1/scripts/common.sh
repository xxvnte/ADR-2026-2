BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$BASE/.env" ]; then set -a; source <(tr -d '\r' < "$BASE/.env"); set +a; fi
IFACE=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'dev \K\S+' | head -1)