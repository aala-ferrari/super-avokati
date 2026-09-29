# -*- coding: utf-8 -*-
"""v9.405 — L'ART. 1 VERO dei codici e testi unici approvati con decreto (sull'HOST, come l'ingest; backup dei JSON).

Sulla pagina Normattiva di un d.P.R. / d.lgs. che approva un codice o un testo unico, il decreto di approvazione («Art. 01 — È
approvato l'unito testo unico…») ha `art.flagTipoArticolo=-1` e gli STESSI idArticolo/idSottoArticolo dell'art. 1 del testo. Il
lettore dei link non riconosceva il segno meno: i due link avevano la stessa chiave e l'art. 1 vero veniva scartato. Nel corpus:
c.p.p. («art. 1 c.p.p.» usciva INESISTENTE: è «Giurisdizione penale»), d.P.R. 309/1990, accise, imposta di registro (al posto
dell'art. 1 c'era «01» = l'approvazione), TUEL e beni culturali (l'«art. 1» era l'approvazione: il «residuo accettato» del v9.327
era questo difetto). Qui, atto per atto: si scarica l'art. 1 vero (testo di OGGI con «!vig=» e, se diversa, la versione futura
in `futuro` come fa riallinea_vigenti_it.py) e l'approvazione diventa «1-legge» (come negli altri atti approvati con allegato).

    python3 tools/repair_art1_it.py apply [--only id1,id2] [--dry]
"""
import json
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402
from riallinea_vigenti_it import _vigenza, _versione  # noqa: E402

SRC = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts"))
ATTI = ("codice_procedura_penale", "stupefacenti", "accise", "imposta_registro", "tuel", "codice_beni_culturali")
_APPROVA = re.compile(r"(?:è|sono)\s+approvat|approvazione\s+del", re.I)


def _links_art1(links):
    """I link candidati all'art. 1 del TESTO (gruppo più grande, idArticolo=1, non il decreto «-1»). Nel TUEL sono DUE, nello
    stesso gruppo e con la stessa etichetta «1» (differiscono in idSottoArticolo1): il primo è l'approvazione."""
    sizes = {}
    for _h, _l, f in links:
        sizes[f] = sizes.get(f, 0) + 1
    main = max(sizes, key=lambda g: sizes[g]) if sizes else "0"
    return [h for h, l, f in links
            if f == main and re.search(r"art\.idArticolo=1(?:&|$)", h)
            and re.sub(r"(?i)^\s*art(?:icolo)?\.?\s*", "", l).strip() in ("1", "1.")]


def _art1_vero(nm, candidati):
    """(href, pagina, articolo) del primo candidato che NON è l'approvazione."""
    for h in candidati:
        p = nm.fetch_article(h)
        a = nl.parse_article_page(p, fallback_number="1")
        if a and not _APPROVA.search((a.get("body") or "")[:200]):
            return h, p, a
    return None, None, None


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    oggi = date.today().isoformat()
    nm = nl.Normattiva(delay=0.6)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for cid in ATTI:
        if only and cid not in only:
            continue
        f = SRC / f"{cid}.json"
        j = json.loads(f.read_text(encoding="utf-8"))
        arts = j.get("articles") or []
        try:
            cand_fut = _links_art1(nm.article_links_all(nm.open_act(j["urn"])))
            cand_oggi = _links_art1(nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + oggi)))
            h_oggi, p_oggi, a = _art1_vero(nm, cand_oggi)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {cid}: {type(exc).__name__} {str(exc)[:100]}", flush=True)
            continue
        if not a:
            print(f"  ! {cid}: nessuna pagina dell'art. 1 che non sia l'approvazione — saltato", flush=True)
            continue
        # la versione futura dello STESSO articolo (stessa chiave, versione diversa)
        _k = lambda h: re.sub(r"art\.versione=\d+&?", "", h.split("?")[-1])
        h_fut = next((h for h in cand_fut if _k(h) == _k(h_oggi)), None)
        nuovo = {"number": "1", "heading": a.get("heading") or "", "body": a.get("body") or "",
                 "repealed": nl.is_repealed(a.get("heading"), a.get("body")), "art1_riparato": oggi}
        if a.get("notes"):
            nuovo["notes"] = a["notes"]
        if h_fut and _versione(h_fut) != _versione(h_oggi):
            p_fut = nm.fetch_article(h_fut)
            af = nl.parse_article_page(p_fut, fallback_number="1") or {}
            dal_fut, _ = _vigenza(p_fut)
            _d, al_oggi = _vigenza(p_oggi)
            nuovo["futuro"] = {"dal": dal_fut, "heading": af.get("heading") or "", "body": af.get("body") or "",
                               "repealed": nl.is_repealed(af.get("heading"), af.get("body"))}
            nuovo["vigente_fino"] = al_oggi
            nuovo["riallineato"] = oggi
        vecchi = [x for x in arts if str(x.get("number")) in ("1", "01") and _APPROVA.search((x.get("body") or "")[:200])]
        altri = [x for x in arts if not (str(x.get("number")) in ("1", "01") and _APPROVA.search((x.get("body") or "")[:200]))]
        if any(str(x.get("number")) == "1" for x in altri):
            print(f"  ! {cid}: c'è già un art. 1 che non è l'approvazione — saltato", flush=True)
            continue
        app = [dict(x, number="1-legge") for x in vecchi[:1]]
        j["articles"] = app + [nuovo] + altri
        print(f"  {cid:26s} art. 1 «{nuovo['heading'][:50]}» {len(nuovo['body'])} chr"
              + (f" · futuro dal {nuovo['futuro']['dal']}" if nuovo.get("futuro") else "")
              + f" · approvazione → 1-legge ({len(app)})", flush=True)
        if not dry:
            shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}-art1"))
            f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
