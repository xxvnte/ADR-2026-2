#!/bin/bash
source "$(dirname "$0")/common.sh"
CSV="$BASE/data/ripe/mediciones.csv"; mkdir -p "$BASE/data/ripe/json"
while IFS=, read -r modo pid target proto id; do
  [[ "$id" =~ ^[0-9]+$ ]] || continue
  F="$BASE/data/ripe/json/$id.json"
  curl -s "https://atlas.ripe.net/api/v2/measurements/$id/results/" > "$F"
  echo "$modo $proto sonda $pid -> medición $id: $(jq length "$F") resultado(s)"
done < "$CSV"
{ date; scamper -v 2>&1 | head -1; docker --version; tcpdump --version 2>&1 | head -1
  tshark --version | head -1; python3 --version; uname -r; } > "$BASE/data/versiones.txt"
echo "Versiones guardadas en data/versiones.txt"