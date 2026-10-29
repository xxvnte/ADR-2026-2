#!/usr/bin/env python3
"""uso: python scripts/pred_vs_obs.py <pcap> <metodo> <ip_origen> [n_paquetes] [ip_destino]"""
import subprocess, sys

pcap, metodo, src = sys.argv[1:4]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 8
DST = sys.argv[5] if len(sys.argv) > 5 else None

fijo   = lambda v: (lambda n, f: v)
sube   = lambda a: (lambda n, f: a + n)
baja   = lambda: (lambda n, f: f - n)
igual1 = lambda: (lambda n, f: f)
rango  = lambda a, b: (lambda n, f: (a, b))
desde  = lambda ancho: (lambda n, f: (f, f + ancho))
ttl3   = lambda: (lambda n, f: 1 + n // 3)
IPID   = ("ip.id", lambda n, f: n + 1)

UDP  = "udp && ip.src=={s} && !icmp"
ECHO = "icmp.type==8 && ip.src=={s} && !icmp.type==11"
SYN  = "tcp.flags.syn==1 && tcp.flags.ack==0 && ip.src=={s} && !icmp"
ACK  = "tcp.flags.ack==1 && tcp.flags.syn==0 && ip.src=={s} && !icmp"

R = {
 # scamper trace
 "udp":        (UDP,  [IPID, ("udp.dstport", sube(33435)), ("udp.checksum", baja())]),
 "icmp":       (ECHO, [IPID, ("icmp.seq", sube(0)), ("icmp.checksum", baja())]),
 "udp-paris":  (UDP,  [IPID, ("udp.dstport", fijo(33435)), ("udp.checksum", lambda n, f: n + 1)]),
 "icmp-paris": (ECHO, [IPID, ("icmp.seq", sube(0)), ("icmp.checksum", igual1())]),
 "tcp":        (SYN,  [IPID, ("tcp.dstport", fijo(80)), ("tcp.seq_raw", igual1())]),
 "tcp-ack":    (ACK,  [IPID, ("tcp.dstport", fijo(80)), ("tcp.seq_raw", igual1())]),
 # scamper tracelb (rangos de ESTA corrida: ajustalos si recapturas)
 "lb-udp-dport":    (UDP,  [("udp.srcport", igual1()), ("udp.dstport", rango(33435, 33442))]),
 "lb-icmp-echo":    (ECHO, [("icmp.seq", sube(0)), ("icmp.checksum", rango(1, 6))]),
 "lb-udp-sport":    (UDP,  [("udp.srcport", desde(9)), ("udp.dstport", fijo(33435))]),
 "lb-tcp-sport":    (SYN,  [("tcp.srcport", desde(5)), ("tcp.dstport", fijo(33435))]),
 "lb-tcp-ack-sport":(ACK,  [("tcp.srcport", desde(5)), ("tcp.dstport", fijo(33435))]),
 # RIPE Atlas (origen 172.17.0.2; usa ip_destino para ignorar el trafico propio de la sonda)
 "ripe-udp":  (UDP,  [("ip.ttl", ttl3()), ("udp.srcport", igual1()), ("udp.dstport", fijo(33435)), ("udp.checksum", igual1())]),
 "ripe-icmp": (ECHO, [("ip.ttl", ttl3()), ("icmp.seq", sube(1)), ("icmp.checksum", fijo(1))]),
 "ripe-tcp":  (SYN,  [("ip.ttl", ttl3()), ("tcp.dstport", fijo(80)), ("tcp.seq_raw", sube(1)), ("tcp.checksum", baja())]),
}

filtro, reglas = R[metodo]
if DST:
    filtro += f" && ip.dst=={DST}"
campos = [c for c, _ in reglas]
cmd = ["tshark", "-r", pcap, "-Y", filtro.format(s=src), "-T", "fields", "-E", "separator=,"]
for c in campos:
    cmd += ["-e", c]
sal = subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()
filas = [l.split(",") for l in sal if l.strip()][:N]
if not filas:
    sys.exit("sin paquetes: revisa el pcap, el metodo, la IP de origen o el filtro\n" + subprocess.run(cmd, capture_output=True, text=True).stderr)

primero = [int(x, 0) for x in filas[0]]
fmt = lambda c, v: hex(v) if ("checksum" in c or c == "ip.id") else str(v)

print("| n | " + " | ".join(f"{c} obs | {c} pred" for c in campos) + " | ¿coincide? |")
print("|" + "---|" * (2 + 2 * len(campos)))
buenos = 0
for n, fila in enumerate(filas):
    celdas, ok = [], True
    for (c, regla), x, f0 in zip(reglas, fila, primero):
        obs, pred = int(x, 0), regla(n, f0)
        if isinstance(pred, tuple):
            bien, ptxt = pred[0] <= obs <= pred[1], f"{pred[0]}-{pred[1]}"
        else:
            bien, ptxt = obs == pred, fmt(c, pred)
        ok = ok and bien
        celdas += [fmt(c, obs), ptxt]
    buenos += ok
    print(f"| {n} | " + " | ".join(celdas) + f" | {'sí' if ok else 'NO'} |")
print(f"\nCoinciden {buenos} de {len(filas)} paquetes.")
