import sys, ipaddress
from adr_utils import *

ida = hops(resultados(sys.argv[1])[0])
vuelta = hops(resultados(sys.argv[2])[0])[::-1]       
shift = int(sys.argv[3]) if len(sys.argv) > 3 else 0   

while ida and (not ida[0] or not all(ipaddress.ip_address(i).is_global for i in ida[0])):
    ida.pop(0)
ida = [["—"]] * shift + ida

n = max(len(ida), len(vuelta))
print("| HOP | IP IDA | IP VUELTA |\n| --- | ------ | --------- |")
for i in range(n):
    a = (" / ".join(ida[i]) or "*") if i < len(ida) else ""
    b = (" / ".join(vuelta[i]) or "*") if i < len(vuelta) else ""
    print(f"| {i+1} | {a} | {b} |")