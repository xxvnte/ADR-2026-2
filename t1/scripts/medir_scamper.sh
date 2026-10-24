#!/bin/bash
source "$(dirname "$0")/common.sh"
IP=$1; ET=$2
if [ -z "$IP" ] || [ -z "$ET" ]; then echo "uso: bash scripts/medir_scamper.sh <IP> <etiqueta>"; exit 1; fi
OUT="$BASE/data/scamper/$ET"; mkdir -p "$OUT"
sudo -v

CASES=(
 "trace_udp|trace -P udp -d 33435"
 "trace_icmp|trace -P icmp"
 "trace_udp-paris|trace -P udp-paris -d 33435"
 "trace_icmp-paris|trace -P icmp-paris"
 "trace_tcp|trace -P tcp -d 80"
 "trace_tcp-ack|trace -P tcp-ack -d 80"
 "lb_udp-dport|tracelb -P udp-dport"
 "lb_icmp-echo|tracelb -P icmp-echo"
 "lb_udp-sport|tracelb -P udp-sport"
 "lb_tcp-sport|tracelb -P tcp-sport"
 "lb_tcp-ack-sport|tracelb -P tcp-ack-sport"
)

for c in "${CASES[@]}"; do
  NAME=${c%%|*}; CMD=${c#*|}
  echo "=== $ET / $NAME ==="
  rm -f "$OUT/$NAME".{pcap,warts,txt}
  sudo tcpdump -i "$IFACE" -n -U -Z root -w "$OUT/$NAME.pcap" "host $IP or icmp" 2>/dev/null &
  sleep 1
  sudo scamper -O warts -o "$OUT/$NAME.warts" -c "$CMD" -i "$IP"
  sleep 2
  sudo pkill -INT -f "tcpdump -i $IFACE -n -U -Z root"
  wait 2>/dev/null
  sc_wartsdump "$OUT/$NAME.warts" > "$OUT/$NAME.txt"
done
echo "Listo: $OUT"