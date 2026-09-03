#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[B] Harvester Corte Costituzionale da Consulta OnLine (giurcost.org).

**Perché giurcost e non il sito ufficiale**: la Consulta ufficiale serve un
CAPTCHA Radware agli IP datacenter (misurato); giurcost.org è l'archivio
accademico storicamente aperto, completo dal 1956, con URL prevedibili:

    /decisioni/{anno}/{numero:04d}{s|o}-{aa}.html     (s=sentenza, o=ordinanza)

**Miss-detection** (misurato): un numero inesistente risponde HTTP 200 con
una pagina-404 «soft» (~20KB, marcatore '404'/'non trovat'). Ci si ferma
dopo MAX_MISS numeri consecutivi mancanti per tipo.

**La regola di copertura — il cuore del design**: il verificatore timbrerà
✓/⚠ SOLO per gli anni che questo harvester ha CHIUSO (meta-file). Un anno a
metà marchierebbe ⚠ decisioni vere non ancora scaricate — e da noi «non lo
trovo ≠ è falso» è legge. L'anno corrente resta aperto finché non passa.

**Strato 2 incluso**: si salva anche il TESTO ripulito, così il futuro
indice BM25 dei precedenti IT sarà un index-build, non un re-harvest.

Solo stdlib (gira sull'host come la pipeline Normattiva). Uso:
    ingest_it_giurcost.py --da 2024 --a 2026
    ingest_it_giurcost.py --anno 2023 --chiudi
"""
import argparse
import html as _html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import UTC, datetime

BASE = "https://giurcost.org/decisioni"
OUT = "/var/www/apps/super-avvocato/data/processed/it_decisions.jsonl"
META = "/var/www/apps/super-avvocato/data/processed/it_decisions_meta.json"
UA = ("SuperAvokati-ingest/1.0 (archivio verificazione citazioni; "
      "contatto: info@aala.global)")
MAX_MISS = 15
PAUSA = 0.6

_TIPI_RE = {"sentenza": "SENTENZA", "ordinanza": "ORDINANZA"}


def e_vendim(corpo: str, tipo: str, n: int) -> bool:
    """Vera decisione ⇔ la pagina nomina il PROPRIO numero.

    La soft-404 di giurcost e' la shell del sito: contiene il numero solo
    nel commento dell'URL («<!-- decisioni, 2024, 3200s-24 -->»), mai nella
    forma canonica «SENTENZA N. 3200». Un marcatore testuale ('404') si e'
    gia' dimostrato cieco sotto urllib: questo criterio e' strutturale.
    """
    return re.search(
        rf"{_TIPI_RE[tipo]}\s+N\.?\s*{n}\b", corpo or "", re.I) is not None
_DATA = re.compile(r"Depositata in Cancelleria il\s+(\d{1,2}\s+\w+\s+\d{4})")
_TAG = re.compile(r"<script.*?</script>|<style.*?</style>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPAZI = re.compile(r"[ \t\r\f\v]+")


def log(m: str) -> None:
    print(f"{datetime.now().strftime('%F %T')} {m}", flush=True)


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        log(f"  ! rete {url}: {exc}")
        time.sleep(3)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return None


def pulisci(raw: str) -> str:
    t = _TAG.sub(" ", raw)
    t = _TAGS.sub(" ", t)
    t = _html.unescape(t)
    t = _SPAZI.sub(" ", t)
    righe = [r.strip() for r in t.split("\n")]
    return "\n".join(r for r in righe if r)[:60_000]


def carica_visti() -> set:
    visti = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for riga in f:
                try:
                    d = json.loads(riga)
                    visti.add((d["court"], d["type"], d["number"], d["year"]))
                except Exception:  # noqa: BLE001
                    pass
    return visti


def carica_meta() -> dict:
    if os.path.exists(META):
        try:
            return json.load(open(META, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"CCost": {"complete_years": []}}


def salva_meta(m: dict) -> None:
    m["updated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(m, open(META, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)


def anno_harvest(anno: int, visti: set, out) -> tuple[int, bool]:
    """Ritorna (nuovi, completato_senza_errori_rete)."""
    aa = f"{anno % 100:02d}"
    nuovi, rete_ok = 0, True
    for tipo, t in (("sentenza", "s"), ("ordinanza", "o")):
        miss = 0
        n = 0
        while miss < MAX_MISS:
            n += 1
            chiave = ("CCost", tipo, n, anno)
            if chiave in visti:
                miss = 0
                continue
            url = f"{BASE}/{anno}/{n:04d}{t}-{aa}.html"
            corpo = fetch(url)
            time.sleep(PAUSA)
            if corpo is None:
                rete_ok = False
                break
            if not e_vendim(corpo, tipo, n):
                miss += 1
                continue
            miss = 0
            md = _DATA.search(corpo)
            out.write(json.dumps({
                "juris": "IT", "court": "CCost", "type": tipo,
                "number": n, "year": anno,
                "date": md.group(1) if md else None,
                "url": url, "text": pulisci(corpo),
            }, ensure_ascii=False) + "\n")
            out.flush()
            visti.add(chiave)
            nuovi += 1
            if nuovi % 50 == 0:
                log(f"  {anno}: {nuovi} nuove…")
    return nuovi, rete_ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--da", type=int)
    ap.add_argument("--a", type=int)
    ap.add_argument("--anno", type=int)
    ap.add_argument("--chiudi", action="store_true",
                    help="marca l'anno come COMPLETO nel meta (abilita il "
                         "verificatore su quell'anno)")
    args = ap.parse_args()
    anni = ([args.anno] if args.anno
            else list(range(args.da, args.a + 1)) if args.da and args.a
            else [datetime.now().year])

    visti = carica_visti()
    meta = carica_meta()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    anno_corrente = datetime.now().year
    with open(OUT, "a", encoding="utf-8") as out:
        for anno in anni:
            log(f"anno {anno}…")
            nuovi, rete_ok = anno_harvest(anno, visti, out)
            log(f"anno {anno}: +{nuovi} decisioni")
            # ⚠️ COMPLETO solo se: rete pulita, e (anno passato o --chiudi).
            # L'anno corrente resta aperto: nuove decisioni arrivano ancora.
            if rete_ok and (anno < anno_corrente or args.chiudi):
                cy = set(meta.setdefault("CCost", {})
                             .setdefault("complete_years", []))
                cy.add(anno)
                meta["CCost"]["complete_years"] = sorted(cy)
                salva_meta(meta)
                log(f"anno {anno}: CHIUSO (il verificatore ora lo timbra)")
    tot = len(visti)
    log(f"fine — totale in archivio: {tot}")


if __name__ == "__main__":
    main()
