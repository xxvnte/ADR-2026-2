import json, subprocess, ipaddress, urllib.request
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "ripe" / "json"

def resultados(mid):
    """Lee el JSON local si existe; si no, lo descarga y lo guarda (evidencia)."""
    f = CACHE / f"{mid}.json"
    if f.exists():
        return json.loads(f.read_text())
    with urllib.request.urlopen(f"https://atlas.ripe.net/api/v2/measurements/{mid}/results/") as r:
        data = json.load(r)
    if data:   
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=1))
    return data

def hops(res):
    """Devuelve [[ips hop1], [ips hop2], ...] de una entrada de resultados()."""
    out = []
    for h in res.get("result", []):
        ips = []
        for r in h.get("result", []):
            ip = r.get("from")
            if ip and ip not in ips:
                ips.append(ip)
        out.append(ips)
    return out

@lru_cache(None)
def asn(ip):
    """(AS, nombre). Primero RIPEstat por HTTPS; respaldo: whois de Team Cymru."""
    if not ipaddress.ip_address(ip).is_global:
        return "no pública", ""
    try:
        url = f"https://stat.ripe.net/data/prefix-overview/data.json?resource={ip}"
        with urllib.request.urlopen(url, timeout=20) as r:
            a = json.load(r)["data"].get("asns") or []
        if a:
            return f"AS{a[0]['asn']}", a[0].get("holder", "")
    except Exception:
        pass
    try:
        out = subprocess.run(["whois", "-h", "whois.cymru.com", f" -v {ip}"],
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        if len(out) >= 2:
            p = [x.strip() for x in out[-1].split("|")]
            return "AS" + p[0], p[-1]
    except Exception:
        pass
    return "?", ""