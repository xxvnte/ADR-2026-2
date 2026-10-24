import sys
from adr_utils import *

for mid in sys.argv[1:]:
    for res in resultados(mid):
        print(f"\n**Medición {mid} — sonda {res.get('prb_id')} → {res.get('dst_addr')} ({res.get('proto')})**\n")
        print("| HOP | IP | AS | Nombre del AS |\n| --- | -- | -- | ------------- |")
        for i, ips in enumerate(hops(res), 1):
            if not ips:
                print(f"| {i} | * | | |")
                continue
            for ip in ips:
                a, n = asn(ip)
                print(f"| {i} | {ip} | {a} | {n} |")