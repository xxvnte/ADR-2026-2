#!/bin/bash
source "$(dirname "$0")/common.sh"
ok(){ echo "OK     $1"; }; fail(){ echo "FALLA  $1"; }

for t in scamper sc_wartsdump tcpdump tshark jq curl python3 docker; do
  command -v $t >/dev/null && ok "$t" || fail "$t no está instalado"
done
IP_ACTUAL=$(curl -4 -s ifconfig.me)
[ "$IP_ACTUAL" = "$MI_IP" ] && ok "IP pública = $MI_IP" \
  || fail "IP pública actual ($IP_ACTUAL) != MI_IP ($MI_IP): ¿VPN activa o cambió la IP?"
echo "Interfaz de salida: $IFACE"
[ -n "$RIPE_KEY" ]  && ok "RIPE_KEY definida"  || fail "RIPE_KEY vacía (.env)"
[ -n "$MI_SONDA" ]  && ok "MI_SONDA definida"  || fail "MI_SONDA vacía (.env)"