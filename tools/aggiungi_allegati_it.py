# -*- coding: utf-8 -*-
"""v9.408 — gli ALLEGATI mai entrati nel corpus italiano (sull'HOST, come l'ingest; backup dei JSON).

`misura_allegati` (29 set 2026): 241 link «Allegato …» / «Tabella …» / gruppi numerati di allegati delle pagine Normattiva che nel
JSON non c'erano, in 31 atti — d.lgs. 81/2008 ne aveva 0 su 55 (Allegato I = le violazioni gravi che fanno sospendere l'attività,
IV = i requisiti dei luoghi di lavoro, XV = i contenuti del piano di sicurezza), la maternità 0 su 4 (Allegati A-C = i lavori
vietati alle lavoratrici madri), il codice dei contratti pubblici 42 articoli di allegati. Molti erano pagine con tabelle HTML
(`normattiva_lib.tabelle_in_testo`). Numeri come l'ingest: gruppo numerato → «N-allK»; pagina «Allegato I bis» → «allegato-i-bis»;
«Tabella C» → «tabella-c»; le pagine lunghe (oltre 9.000 caratteri) in blocchi di paragrafi («allegato-iv-2»: mai a metà di un
paragrafo), con la parte nel titolo. Gli atti e gli allegati da ESCLUDERE (moduli in bianco, specifiche tecniche senza norma) sono
elencati sotto: entra solo ciò che migliora.

    python3 tools/aggiungi_allegati_it.py apply [--only id1,id2] [--dry]
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
from riallinea_vigenti_it import _key, _num_lab, _numero_nel_json, _vigenza  # noqa: E402

SRC = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts"))
# atti le cui tabelle/allegati sono già entrati in un'altra forma (v9.390 stupefacenti, v9.406 tariffe e tabelle IVA) o sono
# corpora a sé (le preleggi dal c.c.)
GIA_FATTI = {"codice_civile", "preleggi", "iva", "tu_iva", "tu_registro", "imposta_registro", "stupefacenti"}
ESCLUSI = {"codice_nautica_diporto", "prestazione_energetica", "negoziazione_assistita"}   # specifiche tecniche e moduli
ESCLUSI_UNITA = {("codice_ambiente", "allegato-1-parte-1")}      # 112.000 caratteri di metodi di monitoraggio delle acque
_MAX = 9000


def _numero_pagina(lab: str) -> str:
    """«Allegato I bis» → «allegato-i-bis», «Allegato 3A» → «allegato-3a», «Tabella C» → «tabella-c», «Allegato 1(parte 1)» →
    «allegato-1-parte-1»."""
    t = lab.strip().lower().replace("(", " ").replace(")", " ")
    t = re.sub(r"\bart\.\s*", "art ", t)                 # «Allegato II.2-bis art. 1» → «allegato-ii.2-bis-art-1»
    t = re.sub(r"[^a-z0-9.]+", "-", t).strip("-")
    return t.replace(".-", "-").strip(".-")


_INIZIO_PUNTO = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s+\S|[A-ZÀ-Ü][A-ZÀ-Ü' ,]{8,}$|PARTE\s|CAPO\s|SEZIONE\s)")


def _blocchi(body: str) -> list[str]:
    """Blocchi di al massimo ~_MAX caratteri: si taglia fra due righe, e oltre il limite al primo punto numerato o titolo
    maiuscolo («1.2 Vie di circolazione», «PARTE II»); se non arriva entro una volta e mezza il limite, alla riga."""
    righe = body.split("\n")
    out, cur, lung = [], [], 0
    for r in righe:
        if cur and lung > _MAX and (_INIZIO_PUNTO.match(r) or not r.strip() or lung > _MAX * 1.5):
            out.append("\n".join(cur).strip()); cur, lung = [], 0
        cur.append(r)
        lung += len(r) + 1
    if cur and "\n".join(cur).strip():
        out.append("\n".join(cur).strip())
    return [b for b in out if b]


def _titolo_pagina(body: str) -> str:
    """Il titolo dell'allegato: la prima riga vera dopo «ALLEGATO IV» («REQUISITI DEI LUOGHI DI LAVORO» → «Requisiti dei luoghi di
    lavoro»), saltando la riga della sola etichetta («((Allegato B», «TABELLA»), le parentesi di modifica «((» e i rimandi fra
    parentesi anche su più righe («(Decreto legislativo 25 novembre 1996, | n. 645, allegato 2)»)."""
    aperte = 0
    for r in body.split("\n")[:16]:
        x = r.strip()
        if not x:
            continue
        if aperte > 0 or (x.startswith("(") and not x.startswith("((") and x.count("(") > x.count(")")):
            aperte += x.count("(") - x.count(")")
            continue
        if re.match(r"^\(+\s*\)*$|^\)+$", x):
            continue
        if re.match(r"(?i)^\(*\s*(?:allegat\w*|tabell\w*|prospett\w*)(?:\s+[a-z0-9ivxl.\-]{1,8})?(?:\s*[-\s](?:bis|ter|quater|quinquies))?\s*\)*\.?$", x):
            continue                                   # la sola etichetta
        if re.match(r"^\((?:art|articol|decreto|d\.)", x, re.I) and x.endswith(")"):
            continue                                   # un rimando su una riga
        x = x.strip("() ").strip()
        if len(x) < 8:
            continue
        # il titolo va a capo («Elenco dei lavori faticosi, pericolosi» | «e insalubri di cui all'art. 7»): le righe che
        # continuano in minuscolo si uniscono
        righe = body.split("\n")
        k = righe.index(r) + 1
        while k < len(righe) and len(x) < 160:
            y = righe[k].strip()
            if not y:
                k += 1
                continue
            _lett = [c for c in y if c.isalpha()]
            _maiusc = bool(_lett) and sum(c.isupper() for c in _lett) / len(_lett) >= 0.7    # «E INSALUBRI DI CUI ALL'Art. 7»
            if y[:1].islower() or (x.isupper() and _maiusc and len(y) < 80 and not re.match(r"^\d", y)):
                x = (x + " " + y.strip("() ")).strip()
                k += 1
                continue
            break
        _lx = [c for c in x if c.isalpha()]
        _su = bool(_lx) and sum(c.isupper() for c in _lx) / len(_lx) >= 0.7
        return (x.capitalize() if _su else x)[:140]
    return ""


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    oggi = date.today().isoformat()
    nm = nl.Normattiva(delay=0.6)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    urn_ok = re.compile(r"^(decreto\.legislativo|decreto\.presidente\.repubblica|decreto\.legge|legge|regio\.decreto)[:;]")
    tot = 0
    for f in sorted(SRC.glob("*.json")):
        cid = f.stem
        if (only and cid not in only) or cid in GIA_FATTI or cid in ESCLUSI:
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        urn = (j.get("urn") or "").strip()
        if not urn_ok.match(urn):
            continue
        arts = j.get("articles") or []
        nums = {str(a.get("number")).lower() for a in arts}
        try:
            links = nm.article_links_all(nm.open_act(urn + "!vig=" + oggi))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {cid}: {exc}", flush=True)
            continue
        sizes, etich = {}, {}
        for h, l, g in links:
            sizes[g] = sizes.get(g, 0) + 1
            etich.setdefault(g, []).append(l)
        main_g = max(sizes, key=lambda g: sizes[g]) if sizes else "0"
        nuovi = []
        for h, lab, g in links:
            if g == main_g or g in ("0", "-1"):
                continue
            target = _numero_nel_json(_num_lab(lab), g, sizes, etich)
            # una PAGINA d'allegato (gruppo non numerato): l'ingest la chiamava «allegato-…» come l'etichetta — qui lo stesso nome
            # normalizzato, e la pagina lunga si divide in blocchi
            pagina = (target is None or not re.match(r"^\d", target)) and bool(re.match(r"(?i)^\s*(allegat|tabell|prospett)", lab))
            if target is None and not pagina:
                continue
            if pagina:
                target = _numero_pagina(lab)
            if (cid, target) in ESCLUSI_UNITA:
                continue
            if target in nums or any(n.startswith(target + "-") for n in nums if target.startswith(("allegato", "tabella"))):
                continue
            try:
                p = nm.fetch_article(h)
            except Exception as exc:  # noqa: BLE001
                print(f"    ! {cid} {lab}: {exc}", flush=True)
                continue
            a = nl.parse_article_page(nl.tabelle_in_testo(p), fallback_number=lab) or {}
            body = (a.get("body") or "").strip()
            if len(body) < (150 if pagina else 40) or "formato grafico" in body[:400]:
                print(f"    - {cid} {lab}: senza testo leggibile ({len(body)} chr) — saltato", flush=True)
                continue
            if nl.is_repealed(a.get("heading"), body) or re.search(r"ALLEGATO\s+ABROGATO", body[:300]):
                print(f"    - {cid} {lab}: abrogato — saltato", flush=True)
                continue
            titolo = (a.get("heading") or "").strip()
            if pagina and not titolo:
                titolo = _titolo_pagina(body)
            base = {"group": g, "repealed": nl.is_repealed(titolo, body), "aggiunto": oggi, "aggiunto_da": "aggiungi_allegati_it"}
            if a.get("notes"):
                base["notes"] = a["notes"]
            pezzi = _blocchi(body) if (pagina and len(body) > _MAX + 2000) else [body]
            for k, pz in enumerate(pezzi, 1):
                num = target if len(pezzi) == 1 else f"{target}-{k}"
                rub = (lab.strip() + (f" — {titolo}" if titolo else "")) if pagina else titolo
                if len(pezzi) > 1:
                    rub = f"{rub} ({k}/{len(pezzi)})"
                nuovi.append(dict(base, number=num, heading=rub[:200], body=pz))
                nums.add(num)
        if nuovi:
            tot += len(nuovi)
            print(f"  {cid:28s} + {len(nuovi)}", flush=True)
            for u in nuovi[:60]:
                print(f"     {u['number']:34s} {len(u['body']):6d} chr · «{u['heading'][:70]}» · {u['body'][:90]!r}", flush=True)
            if not dry:
                shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}-allegati2"))
                j["articles"] = arts + nuovi
                f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"TOTALE {tot} unità{' (a secco)' if dry else ''}")


if __name__ == "__main__":
    main()
