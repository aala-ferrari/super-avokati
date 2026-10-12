#!/usr/bin/env python3
"""12 ott 2026 — il paese del visitatore di superavokati.ai dall'indirizzo IP, per la lingua (e quindi la società) della pagina.

Il titolare: «chi sceglie italiano vede Deltalux e il numero italiano, chi sceglie albanese vede Albania Auto Legal Alliance e
il numero albanese; e il sito potrebbe rilevare l'IP e aprire la lingua giusta». Quando il visitatore non ha ancora scelto una
lingua, la pagina iniziale e la pagina d'accesso seguono il paese: Italia (con San Marino e il Vaticano) → italiano, Albania →
albanese. Una scelta fatta col pulsante vince sempre.

Fonte: le statistiche UFFICIALI del registro regionale RIPE NCC (delegated-ripencc-extended-latest, con la sua impronta MD5):
gli indirizzi assegnati ai fornitori registrati in Italia e in Albania. Niente account, niente banche dati commerciali. Il Kosovo
nelle statistiche non è distinguibile (nessuna voce «XK»): lì decide la lingua del browser.

Scrive /etc/nginx/sa-geo/paesi.conf (righe «rete PAESE;» per il `geo $sa_paese` di /etc/nginx/conf.d/sa-paese.conf), prova la
configurazione con `nginx -t` PRIMA di tenerla (altrimenti rimette la vecchia) e ricarica nginx solo se il file è cambiato.
Due righe di prova fisse: 127.0.0.2 = IT, 127.0.0.3 = AL (indirizzi di loopback: da fuori non arrivano mai), per provare dal
server stesso con `curl --interface 127.0.0.2 --resolve superavokati.ai:443:127.0.0.1 https://superavokati.ai/`.

Uso (sull'host, da root):  python3 /opt/sa-geo-paesi.py            # aggiorna (cron mensile)
                           python3 /opt/sa-geo-paesi.py --prova IP…  # in che paese cade un indirizzo, col file attuale
"""
import hashlib
import ipaddress
import os
import shutil
import subprocess
import sys
import time
import urllib.request

URL = "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest"
DEST = "/etc/nginx/sa-geo/paesi.conf"
PAESI = {"IT": "IT", "SM": "IT", "VA": "IT", "AL": "AL"}
MINIMI = {"IT": 2000, "AL": 100}          # reti IPv4 dopo l'unione: sotto, il file scaricato non è credibile
PROVE = [("127.0.0.2/32", "IT"), ("127.0.0.3/32", "AL")]


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), msg, flush=True)


def scarica(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "superavokati-geo/1.0 (+https://superavokati.ai)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def reti(testo: str) -> dict:
    per = {"IT": {4: [], 6: []}, "AL": {4: [], 6: []}}
    for riga in testo.splitlines():
        p = riga.split("|")
        if len(p) < 7 or p[1] not in PAESI or p[2] not in ("ipv4", "ipv6") or p[6] not in ("allocated", "assigned"):
            continue
        paese = PAESI[p[1]]
        if p[2] == "ipv4":
            a = ipaddress.IPv4Address(p[3])
            b = ipaddress.IPv4Address(int(a) + int(p[4]) - 1)
            per[paese][4].extend(ipaddress.summarize_address_range(a, b))
        else:
            per[paese][6].append(ipaddress.IPv6Network(f"{p[3]}/{p[4]}", strict=False))
    return {k: {v: list(ipaddress.collapse_addresses(n)) for v, n in d.items()} for k, d in per.items()}


def testo_conf(per: dict, fonte: str) -> str:
    righe = [f"# generato da /opt/sa-geo-paesi.py il {time.strftime('%Y-%m-%d %H:%M')} — {fonte}",
             "# NON modificare a mano: il prossimo aggiornamento lo riscrive"]
    righe += [f"{rete} {p};" for rete, p in PROVE]
    for paese in ("IT", "AL"):
        for v in (4, 6):
            righe += [f"{n} {paese};" for n in per[paese][v]]
    return "\n".join(righe) + "\n"


def prova(indirizzi: list) -> int:
    try:
        righe = open(DEST, encoding="utf-8").read().splitlines()
    except OSError as e:
        print("file assente:", e)
        return 1
    tab = []
    for r in righe:
        r = r.strip().rstrip(";")
        if not r or r.startswith("#"):
            continue
        rete, paese = r.split()
        tab.append((ipaddress.ip_network(rete), paese))
    for ind in indirizzi:
        ip = ipaddress.ip_address(ind)
        trovati = [(n.prefixlen, p) for n, p in tab if n.version == ip.version and ip in n]
        print(ind, "→", max(trovati)[1] if trovati else "(altro paese)")
    return 0


def main(argv: list) -> int:
    if argv[:1] == ["--prova"]:
        return prova(argv[1:])
    dati = scarica(URL)
    attesa = scarica(URL + ".md5").decode("ascii", "replace")
    impronta = hashlib.md5(dati).hexdigest()
    if impronta not in attesa:
        log(f"impronta MD5 diversa ({impronta}): file non tenuto")
        return 1
    testo = dati.decode("utf-8", "replace")
    intest = testo.splitlines()[0] if testo else ""
    per = reti(testo)
    conti = {p: (len(per[p][4]), len(per[p][6])) for p in per}
    for p, minimo in MINIMI.items():
        if conti[p][0] < minimo:
            log(f"troppo poche reti per {p}: {conti[p]} — file non tenuto")
            return 1
    nuovo = testo_conf(per, "RIPE NCC " + intest)
    vecchio = open(DEST, encoding="utf-8").read() if os.path.exists(DEST) else ""
    corpo = lambda t: "\n".join(l for l in t.splitlines() if not l.startswith("#"))  # noqa: E731
    if corpo(nuovo) == corpo(vecchio):
        log(f"nessun cambiamento (IT {conti['IT']}, AL {conti['AL']} reti v4/v6)")
        return 0
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    tmp = DEST + ".nuovo"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(nuovo)
    if vecchio:
        shutil.copy2(DEST, DEST + ".prima")
    os.replace(tmp, DEST)
    t = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if t.returncode != 0:
        if vecchio:
            os.replace(DEST + ".prima", DEST)
        else:
            os.remove(DEST)
        log("nginx -t fallito, rimesso il file di prima: " + (t.stderr or "")[-400:])
        return 1
    subprocess.run(["systemctl", "reload", "nginx"], check=False)
    log(f"aggiornato e ricaricato: IT {conti['IT']}, AL {conti['AL']} reti v4/v6")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
