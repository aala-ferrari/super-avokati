#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[E] Watcher quotidiano delle decisioni albanesi — sentinella, non ingest.

⚠️ **REGOLA SACRA (memoria di progetto)**: nel corpus dei precedenti entra
solo cio' che MIGLIORA — mai auto-ingest. Questo script quindi NON tocca
l'indice: scopre le novita', le mette in staging, e AVVISA per la curatela.

v1 copre la **Gjykata Kushtetuese** (gjykatakushtetuese.gov.al, pagina
«Njoftime mbi vendimarrjen» — misurata: 200, ~360KB). La Gjykata e Larte
e' una SPA Angular con API non pubblica documentata: TODO onesto, i probe
sono annotati in fondo.

Diff per URL contro lo stato in /var/lib/decisions-watch/; le novita' si
salvano in data/staging_decisions/<data>/ e parte UNA email (Resend, canale
rodato) con titoli e link.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime

FONTE = "https://www.gjykatakushtetuese.gov.al/njoftime-mbi-vendimarrjen/"
STATO_DIR = "/var/lib/decisions-watch"
STAGING = "/var/www/apps/super-avvocato/data/staging_decisions"
ENV_AALA = "/var/www/apps/aala/.env.local"
FROM = "Super Avokati <njoftim@aala.global>"
TO = "info@aala.global"
UA = "SuperAvokati-watch/1.0 (kurim precedentesh; info@aala.global)"

_LINK = re.compile(
    r'<a[^>]+href="(https://www\.gjykatakushtetuese\.gov\.al/[^"]+)"[^>]*>'
    r'\s*([^<]{10,160})', re.I)
_SKARTA = ("njoftime-mbi-vendimarrjen", "/shpallje", "/kontakt", "/rreth",
           "facebook", "twitter", "#")


def ora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        print(f"{ora()} ⚠️ fetch {url}: {exc}")
        return None


def manda(oggetto: str, corpo: str) -> bool:
    key = ""
    try:
        for r in open(ENV_AALA, encoding="utf-8"):
            if r.startswith("RESEND_API_KEY="):
                key = r.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    if not key:
        print(f"{ora()} ⚠️ RESEND_API_KEY assente")
        return False
    carico = json.dumps({"from": FROM, "to": [TO], "subject": oggetto,
                         "html": corpo}, ensure_ascii=False)
    r = subprocess.run(
        ["curl", "-s", "-m", "20", "-X", "POST",
         "https://api.resend.com/emails",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json", "--data-binary", "@-"],
        input=carico, capture_output=True, text=True, timeout=40)
    return '"id"' in (r.stdout or "")


def main() -> None:
    os.makedirs(STATO_DIR, exist_ok=True)
    stato_f = os.path.join(STATO_DIR, "gjk.json")
    visti: set = set()
    if os.path.exists(stato_f):
        try:
            visti = set(json.load(open(stato_f, encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass

    corpo = fetch(FONTE)
    if corpo is None:
        sys.exit(1)
    trovati = []
    for url, titolo in _LINK.findall(corpo):
        if any(s in url for s in _SKARTA):
            continue
        titolo = re.sub(r"\s+", " ", titolo).strip()
        if url not in visti:
            trovati.append((url, titolo))

    prima_volta = not visti
    if not trovati:
        print(f"{ora()} GJK: asnjë vendim i ri")
        return

    oggi = datetime.now().strftime("%Y-%m-%d")
    dest = os.path.join(STAGING, oggi)
    os.makedirs(dest, exist_ok=True)
    for i, (url, titolo) in enumerate(trovati[:20], 1):
        pagina = fetch(url)
        if pagina:
            nome = re.sub(r"[^a-zA-Z0-9]+", "_", url.rstrip("/").split("/")[-1])[:80]
            open(os.path.join(dest, f"{nome}.html"), "w",
                 encoding="utf-8").write(pagina)
        visti.add(url)
    json.dump(sorted(visti), open(stato_f, "w", encoding="utf-8"))

    if prima_volta:
        # il primo giro censisce l'esistente: niente valanga di email
        print(f"{ora()} GJK: primo censimento — {len(trovati)} voci "
              f"registrate senza avviso")
        return
    righe = "".join(f'<li><a href="{u}">{t}</a></li>'
                    for u, t in trovati[:20])
    ok = manda(f"🏛️ GJK: {len(trovati)} vendime/njoftime të reja — për kurim",
               f"<p>Në staging ({dest}) dhe gati për shqyrtim — "
               f"<b>asgjë nuk hyn vetë në korpus</b> (rregulli i shenjtë: "
               f"vetëm çfarë e përmirëson trurin).</p><ul>{righe}</ul>")
    print(f"{ora()} GJK: {len(trovati)} të reja · staging {dest} · "
          f"email {'✅' if ok else '❌'}")


# TODO Gjykata e Lartë: app.gjykataelarte.gov.al è una SPA Angular; le rotte
# /api/vendime e simili rispondono 404 con la shell (misurato 3 set 2026).
# Serve sniffing del bundle JS per l'endpoint reale — candidato v2.

if __name__ == "__main__":
    main()
