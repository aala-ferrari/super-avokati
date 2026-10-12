# -*- coding: utf-8 -*-
"""v9.633 — quante VOCI DEI PANNELLI il Giudice ha dovuto correggere, giro per giro del banco dei modelli (strato 2).

I pannelli (piano d'azione, termini e rischi, nullità, punti strategici) li scrivono le fasi junior PRIMA del senior; il Giudice, alla
fine, li elenca sotto «Panele për t'u korrigjuar» / «Pannelli da correggere». Il punteggio del banco misura solo la risposta finale:
questo conto misura la qualità dei junior (il banco del 12 ott: 25 correzioni sui 6 casi difficili di D0, fra cui «3 vjet (neni 203)»
per impugnare un licenziamento, che sono 180 giorni).

    python3 tools/conta_correzioni_pannelli.py data/benchmark/layer2/<giro> [<giro> …]
"""
import pathlib
import re
import sys

_INIZIO = re.compile(r"^\*\*(?:Panele për t.u korrigjuar|Panelet për t.u korrigjuar|Pannelli da correggere)\b", re.I)
_FINE = re.compile(r"^(?:\*\*|---|#)")


def conta(md: str) -> list[str]:
    voci, dentro = [], False
    for riga in md.splitlines():
        s = riga.strip()
        if _INIZIO.match(s):
            dentro = True
            continue
        if dentro and _FINE.match(s):
            dentro = False
        if dentro and s.startswith(("-", "•", "*")) and len(s) > 3:
            voci.append(s.lstrip("-•* ").strip())
    return voci


def main(argv):
    for giro in argv:
        d = pathlib.Path(giro)
        tot, casi = 0, 0
        print(f"\n=== {d.name} ===")
        for f in sorted(d.glob("*.md")):
            t = f.read_text(encoding="utf-8")
            if not t.strip():
                print(f"  {f.stem:42s}  (vuoto: caso interrotto)")
                continue
            v = conta(t)
            casi += 1
            tot += len(v)
            print(f"  {f.stem:42s} {len(v):2d} voci corrette")
        print(f"  TOTALE {tot} correzioni su {casi} casi" + (f" (media {tot / casi:.1f})" if casi else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
