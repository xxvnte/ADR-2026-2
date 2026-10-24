import sys, getpass
import ndex2
from adr_utils import *

id_ida, id_vuelta, nombre = sys.argv[1], sys.argv[2], sys.argv[3]

net = ndex2.nice_cx_network.NiceCXNetwork()
net.set_name(nombre)
net.set_network_attribute("description",
    f"Traceroute RIPE Atlas ida (medicion {id_ida}) y vuelta (medicion {id_vuelta}).")

nodos = {}
def nodo(ip):
    if ip not in nodos:
        n = net.create_node(ip)
        nodos[ip] = n
        if not ip.startswith("*"):
            a, nom = asn(ip)
            net.set_node_attribute(n, "asn", a)
            net.set_node_attribute(n, "as_name", nom)
    return nodos[ip]

def cargar(mid, sentido):
    data = resultados(mid)
    if not data:
        print(f"Sin resultados en {mid} ({sentido}); ese sentido no entra al grafo.")
        return
    prev = None
    for i, ips in enumerate(hops(data[0]), 1):
        actual = ips or [f"* ({sentido} hop {i})"]   
        if prev:
            for a in prev:
                for b in actual:
                    net.create_edge(edge_source=nodo(a), edge_target=nodo(b), edge_interaction=sentido)
        prev = actual

cargar(id_ida, "ida")
cargar(id_vuelta, "vuelta")

user = input("Usuario NDEx: ")
pwd = getpass.getpass("Password NDEx: ")
url = net.upload_to("https://www.ndexbio.org", user, pwd)
uuid = str(url).rstrip("/").split("/")[-1]
print("URL:", url)
print("UUID:", uuid)

try:
    ndex2.client.Ndex2("https://www.ndexbio.org", user, pwd).make_network_public(uuid)
    print("Red marcada como pública")
except Exception as e:
    print("Hazlo a mano en la web (Visibility -> Public):", e)