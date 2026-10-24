#!/bin/bash
source "$(dirname "$0")/common.sh"
MODO=$1
PIDS=${2:-"31416 12734 870"}
PROTOS=${3:-"UDP ICMP TCP"}
if [ "$MODO" != "ida" ] && [ "$MODO" != "vuelta" ]; then echo "uso: ... ida|vuelta [sondas] [protocolos]"; exit 1; fi
if [ -z "$RIPE_KEY" ] || [ -z "$MI_SONDA" ] || [ -z "$MI_IP" ]; then echo "Faltan variables en .env"; exit 1; fi

declare -A DEST=( [31416]=138.204.228.2 [12734]=200.14.48.134 [870]=37.79.153.66 )
CSV="$BASE/data/ripe/mediciones.csv"; mkdir -p "$BASE/data/ripe"
[ -f "$CSV" ] || echo "modo,sonda,target,protocolo,id_medicion" > "$CSV"

for pid in $PIDS; do
  for proto in $PROTOS; do
    if [ "$MODO" = "ida" ]; then TARGET=${DEST[$pid]}; SRC=$MI_SONDA; else TARGET=$MI_IP; SRC=$pid; fi
    BODY=$(jq -n --arg t "$TARGET" --arg p "$proto" --arg s "$SRC" --arg d "$MODO $proto sonda $pid" '
      {definitions:[({type:"traceroute",af:4,target:$t,protocol:$p,description:$d}
                    + (if $p=="TCP" then {port:80} else {} end))],
       probes:[{requested:1,type:"probes",value:$s}],
       is_oneoff:true}')
    RESP=$(curl -s -X POST "https://atlas.ripe.net/api/v2/measurements/" \
      -H "Authorization: Key $RIPE_KEY" -H "Content-Type: application/json" -d "$BODY")
    ID=$(echo "$RESP" | jq -r '.measurements[0] // empty')
    echo "$MODO,$pid,$TARGET,$proto,${ID:-ERROR}" | tee -a "$CSV"
    [ -z "$ID" ] && echo "$RESP"
    sleep 2
  done
done