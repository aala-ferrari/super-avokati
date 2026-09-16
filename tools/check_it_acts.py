# -*- coding: utf-8 -*-
"""Dopo OGNI ingest del corpus italiano: quali atti sono legge morta?

Normattiva risponde anche per un atto abrogato — ogni articolo torna con il testo
«((ARTICOLO/PROVVEDIMENTO ABROGATO DAL D.LGS. … N. …))». Il 16 set 2026 la wave5
aveva preso cosi' DPR 602/1973 (135/135 abrogati dal D.Lgs 33/2025), IVA 633/72,
registro, successioni, sanzioni e reati tributari, DPR 600/73: la riforma fiscale
li aveva sostituiti con i testi unici. Questo controllo stampa, per ogni atto,
articoli / abrogati / con testo «ABROGATO» e il successore piu' citato: un atto con
la maggioranza abrogata va AFFIANCATO dal successore (l'atto vecchio resta, marcato
abrogato, cosi' il verificatore dice «superato» a chi lo cita).

    python3 tools/check_it_acts.py [dir]            # default: /app/data/processed/it_acts
    IT_ACTS_DIR=/var/www/apps/super-avvocato/data/processed/it_acts python3 tools/check_it_acts.py
Exit 1 se almeno un atto e' per la maggioranza abrogato e nessun atto del corpus
dichiara nel titolo il suo successore (numero/anno del decreto abrogante).
"""
import json, os, re, sys
from collections import Counter
from pathlib import Path

D = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
_ABRO = re.compile(r"ABROGAT[OA] DAL (D\.?\s*LGS\.?|D\.?P\.?R\.?|L\.|LEGGE|D\.?L\.)\s*([^,)]*?)\s*,?\s*N\.?\s*(\d+)", re.I)


# atti «per la maggioranza abrogati» che NON hanno un successore da aggiungere: il decreto
# abrogante ha tolto articoli senza sostituirli con un testo unico proprio
_OK_DEAD = {
    "codice_privacy": "D.Lgs 101/2018 ha adeguato il codice al GDPR (gdpr e' nel corpus): il resto e' vigente",
    "condono_edilizio": "L. 47/1985: le parti abrogate vivono nel TU edilizia DPR 380/2001 (tu_edilizia nel corpus)",
}


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes", "si", "sì")


def main() -> int:
    files = sorted(D.glob("*.json"))
    if not files:
        print(f"nessun atto in {D}")
        return 2
    titles = " ".join(json.loads(f.read_text(encoding="utf-8")).get("title", "") for f in files).lower()
    bad = []
    print(f"{'atto':28s} {'art':>5} {'abrog':>5} {'testo':>5}  successore piu' citato")
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        arts = d.get("articles") or []
        if not arts:
            continue
        rep = sum(1 for a in arts if _truthy(a.get("repealed")))
        succ = Counter()
        abro = 0
        for a in arts:
            m = _ABRO.search((a.get("body") or "")[:300])
            if m:
                abro += 1
                year = re.search(r"(\d{4})", m.group(2))
                succ[f"{m.group(1).upper().replace(' ', '')} {m.group(3)}/{year.group(1) if year else '?'}"] += 1
        top = succ.most_common(1)[0] if succ else None
        flag = ""
        if abro > len(arts) // 2 or rep == len(arts):
            flag = "  <-- LEGGE MORTA"
            if f.stem in _OK_DEAD:
                flag += f" (ok: {_OK_DEAD[f.stem]})"
            elif top:
                num, year = top[0].split()[-1].split("/")
                if f"{num}/{year}" not in titles:
                    flag += f" — manca il successore {top[0]} nel corpus"
                    bad.append(f.stem)
                else:
                    flag += f" — successore {top[0]} presente"
        print(f"{f.stem:28s} {len(arts):>5} {rep:>5} {abro:>5}  {top[0] + ' (' + str(top[1]) + ')' if top else '-'}{flag}")
    if bad:
        print("\nATTI DA AFFIANCARE COL SUCCESSORE:", ", ".join(bad))
        return 1
    print("\nOK: ogni atto per la maggioranza abrogato ha il successore nel corpus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
