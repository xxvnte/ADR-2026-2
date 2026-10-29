import sys, ipaddress
from adr_utils import *

def ips(h):
    out = []
    for hop in h:
        for i in hop:
            if i not in out:
                out.append(i)
    return out

ida = ips(hops(resultados(sys.argv[1])[0]))
vue = ips(hops(resultados(sys.argv[2])[0]))
pub = lambda l: [i for i in l if ipaddress.ip_address(i).is_global]

def ases(l):
    return list(dict.fromkeys(asn(i)[0] for i in pub(l) if asn(i)[0] != "?"))

a_ida, a_vue = ases(ida), ases(vue)
comunes_ip = [i for i in ida if i in vue]
comunes_as = [a for a in a_ida if a in a_vue]
valor = lambda i: int(ipaddress.ip_address(i))
consec = [(a, b) for a in ida for b in vue if a != b and abs(valor(a) - valor(b)) == 1]

print(f"IPs únicas ida/vuelta: {len(ida)}/{len(vue)} (públicas {len(pub(ida))}/{len(pub(vue))})")
print("AS ida:    ", " ".join(a_ida))
print("AS vuelta: ", " ".join(a_vue))
print("AS comunes:", " ".join(comunes_as) or "ninguno")
print("IPs comunes:", " ".join(comunes_ip) or "ninguna")
print("IPs consecutivas (posibles extremos de un mismo enlace):", consec or "ninguna")
