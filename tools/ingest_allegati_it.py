# -*- coding: utf-8 -*-
"""v9.406 — TARIFFE e TABELLE degli atti fiscali, mai entrate nel corpus (sull'HOST, come l'ingest; backup dei JSON).

Censimento del 29 set 2026 (gruppi `flagTipoArticolo` delle pagine Normattiva):
  - d.P.R. 131/1986 (imposta di registro, vigente fino al 31/12/2026): gruppo 1 = Tariffa, parte I (14 articoli: l'art. 1 ha il
    9 %, il 2 % per la prima casa con la nota II-bis, il 15 % dei terreni agricoli), 2 = Tariffa, parte II (12), 3 = Tabella (13),
    4 = Prospetto dei coefficienti — nel JSON c'era solo il testo unico (e la parte II art. 2-bis finita per errore nel testo, «2-bis»);
  - d.P.R. 633/1972 (IVA, vigente fino al 31/12/2026): Tabelle A (aliquote 4 %, 5 %, 10 %), B, C — una pagina ciascuna;
  - d.lgs. 10/2026 (testo unico IVA, dal 2027): «Tabelle», una pagina;
  - d.lgs. 123/2025 (testo unico del registro, dal 2027): Allegato 1 = la Tariffa del registro (una pagina).
Nelle tariffe le ALIQUOTE stanno in tabelle HTML che `parse_article_page` scartava: si leggono con `normattiva_lib.tabelle_in_testo`.
Le pagine uniche lunghe (50.000 caratteri) si dividono in parti («Tabella A, parte III», «Tariffa, parte I, art. 1»): una parte è
un'unità del corpus, così il recupero porta quella giusta e il modello la legge intera. Per gli atti che si abrogano dal 2027 la
versione futura va in `futuro` (come `riallinea_vigenti_it.py`).

    python3 tools/ingest_allegati_it.py apply [--only id1,id2] [--dry]
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

# gruppi numerati → unità «N-allK» (come assign_numbers) con la parte nella rubrica; pagine uniche → divise in parti
ATTI = {
    "imposta_registro": {
        "gruppi": {"1": "Tariffa, parte I — Atti soggetti a registrazione in termine fisso",
                   "2": "Tariffa, parte II — Atti soggetti a registrazione solo in caso d'uso",
                   "3": "Tabella — Atti per i quali non vi è obbligo di chiedere la registrazione"},
        "pagine": {"4": ("prospetto-dei-coefficienti", "Prospetto dei coefficienti (usufrutto, rendite e pensioni)")},
        "spuri": ["2-bis"], "futuro": True},
    "iva": {"pagine": {"1": ("tabella-a", "Tabella A"), "2": ("tabella-b", "Tabella B"), "3": ("tabella-c", "Tabella C")},
            "futuro": True},
    "tu_iva": {"pagine": {"2": ("tabella", "Tabelle")}},
    "tu_registro": {"pagine": {"2": ("tariffa", "Allegato 1 — Imposta di registro, Tariffa")}},
}

_LAT = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)"
_M_TABELLA = re.compile(r"^\s*TABELLA\s+([A-Z])\b\s*\(?\*?\)?\s*$", re.I)
_M_PARTE = re.compile(r"^\s*PARTE\s+([IVX]+)(?:\s*[-\s]?\s*(" + _LAT + r"))?\b\s*(?:\((?:\*+|\d+)\)|\*+)*\s*$", re.I)   # «PARTE III (194)»
_M_TAR_ART = re.compile(r"^\s*Tariffa\s*-\s*Parte\s+([IVX]+)\s*-\s*Articolo\s+(\d+(?:\s*-?\s*" + _LAT + r")?)\s*$", re.I)
_M_TAB_ART = re.compile(r"^\s*Tabella\s*-\s*Articolo\s+(\d+(?:\s*-?\s*" + _LAT + r")?)\s*$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "-", s.strip().lower()).replace("--", "-")


def dividi(body: str, base: str, titolo: str) -> list[dict]:
    """La pagina unica → unità: «Tabella X» / «Parte N» (tabelle IVA) o «Tariffa - Parte N - Articolo M» / «Tabella - Articolo M»
    (tariffa del testo unico del registro). Se non ci sono segni di divisione, un'unità sola."""
    righe = (body or "").split("\n")
    tagli = []                                        # (indice riga, numero, rubrica)
    lettera = base.split("-")[1] if base.startswith("tabella-") and len(base.split("-")) > 1 else ""
    for i, r in enumerate(righe):
        m = _M_TAR_ART.match(r)
        if m:
            tagli.append((i, f"tariffa-{m.group(1).lower()}-{_norm(m.group(2))}",
                          f"Tariffa, parte {m.group(1).upper()}, art. {m.group(2)}"))
            continue
        m = _M_TAB_ART.match(r)
        if m:
            tagli.append((i, f"tabella-{_norm(m.group(1))}", f"Tabella, art. {m.group(1)}"))
            continue
        m = _M_TABELLA.match(r)
        if m:
            lettera = m.group(1).lower()
            tagli.append((i, f"tabella-{lettera}", f"Tabella {m.group(1).upper()}"))
            continue
        m = _M_PARTE.match(r)
        if m and lettera:
            suf = ("-" + m.group(2).lower()) if m.group(2) else ""
            tagli.append((i, f"tabella-{lettera}-parte-{m.group(1).lower()}{suf}",
                          f"Tabella {lettera.upper()}, parte {m.group(1).upper()}{suf}"))
    if not tagli:
        return [{"number": base, "heading": titolo, "body": body.strip()}]
    out = []
    testa = "\n".join(righe[:tagli[0][0]]).strip()
    for k, (i, num, rub) in enumerate(tagli):
        fine = tagli[k + 1][0] if k + 1 < len(tagli) else len(righe)
        pezzo = "\n".join(righe[i + 1:fine]).strip()
        # il titolo della parte è la prima riga non vuota dopo il segno («Beni e servizi soggetti all'aliquota del 10 per cento»)
        prima = next((x.strip() for x in pezzo.split("\n") if x.strip()), "")
        if prima and len(prima) <= 160 and not re.match(r"^\(?\d+\)", prima):
            rub = f"{rub} — {prima.strip(' .')}"
        if len(pezzo) < (5 if ", art. " in rub else 40):   # un'intestazione vuota (la «Tabella A» prima della sua parte I)
            continue
        if num in {u["number"] for u in out}:
            num = f"{num}-{k}"
        out.append({"number": num, "heading": rub[:200], "body": pezzo})
    if testa and len(testa) > 200 and out:            # un'introduzione lunga prima della prima parte resta in testa alla prima
        out[0]["body"] = testa + "\n\n" + out[0]["body"]
    finale = []
    for u in out:
        finale.extend(_a_blocchi(u) if u["number"].startswith("tabella-") and len(u["body"]) > _MAX_BLOCCO + 2000 else [u])
    return finale


# Una parte di tabella lunga (la parte III della Tabella A IVA: 27.000 caratteri) si divide in blocchi di VOCI NUMERATE, mai a metà
# di una voce: il modello legge 12.000 caratteri per articolo in chat e 3.500 negli strumenti PRO, e la voce giusta (n. 127-quaterdecies,
# i lavori di recupero edilizio) sta in fondo
_MAX_BLOCCO = 6000
_VOCE = re.compile(r"^\s*(\d+(?:-[a-z]+)?)\)\s")


def _a_blocchi(u: dict) -> list[dict]:
    righe = u["body"].split("\n")
    blocchi, cur, primo, ultimo = [], [], None, None
    for r in righe:
        mv = _VOCE.match(r)
        if mv and cur and sum(len(x) + 1 for x in cur) >= _MAX_BLOCCO and primo is not None:
            blocchi.append((primo, ultimo, cur))
            cur, primo = [], None
        if mv:
            primo = primo or mv.group(1)
            ultimo = mv.group(1)
        cur.append(r)
    if cur:
        blocchi.append((primo, ultimo, cur))
    if len(blocchi) <= 1:
        return [u]
    out = []
    for primo, ultimo, rr in blocchi:
        if primo is None:
            continue
        out.append(dict(u, number=f"{u['number']}-nn-{primo}-{ultimo}", heading=f"{u['heading']} (nn. {primo}–{ultimo})"[:200],
                        body="\n".join(rr).strip()))
    return out or [u]


def _abrogato(a: dict) -> bool:
    h, b = a.get("heading") or "", a.get("body") or ""
    return nl.is_repealed(h, b) or (len(b) < 400 and bool(re.search(r"ABROGAT", b)))


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    oggi = date.today().isoformat()
    nm = nl.Normattiva(delay=0.6)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for cid, cfg in ATTI.items():
        if only and cid not in only:
            continue
        f = SRC / f"{cid}.json"
        j = json.loads(f.read_text(encoding="utf-8"))
        arts = j.get("articles") or []
        nums = {str(a.get("number")).lower() for a in arts}
        try:
            cur_links = nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + oggi))
            fut_links = nm.article_links_all(nm.open_act(j["urn"])) if cfg.get("futuro") else []
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {cid}: {exc}", flush=True)
            continue
        fut_by_key = {_key(h): h for h, _l, _g in fut_links}
        sizes, etich = {}, {}
        for h, l, g in cur_links:
            sizes[g] = sizes.get(g, 0) + 1
            etich.setdefault(g, []).append(l)
        nuovi = []

        def _futuro(h_oggi):
            hf = fut_by_key.get(_key(h_oggi))
            if not hf:
                return None
            pf = nm.fetch_article(hf)
            af = nl.parse_article_page(nl.tabelle_in_testo(pf), fallback_number="x") or {}
            dal, _ = _vigenza(pf)
            if not dal or dal <= oggi:
                return None
            return {"dal": dal, "heading": af.get("heading") or "", "body": af.get("body") or "", "repealed": _abrogato(af)}

        for h, lab, g in cur_links:
            if g in (cfg.get("gruppi") or {}):
                target = _numero_nel_json(_num_lab(lab), g, sizes, etich)
                if not target or target in nums:
                    continue
                p = nm.fetch_article(h)
                a = nl.parse_article_page(nl.tabelle_in_testo(p), fallback_number=lab) or {}
                if not a.get("body"):
                    print(f"    ? {cid} {lab} (gruppo {g}): pagina senza testo", flush=True)
                    continue
                corpo = re.sub(r"^\s*(?:TARIFFA|TABELLA)\s*\n+\s*(?:PARTE\s+\w+\s*\n+)?[^\n]*\n+\s*Art\.\s*\d+[^\n]*\n+", "",
                               a["body"], count=1)      # l'intestazione della parte si sposta nella rubrica
                _rub = a.get("heading") or ""
                if len(corpo.strip(" .)(\n")) < 5 and len(_rub) > 20:
                    # la voce della tariffa è TUTTA fra doppie parentesi («((Locazioni ed affitti di immobili … nell'anno))») e il
                    # parser l'aveva presa per rubrica: è il testo
                    corpo, _rub = re.sub(r"\s*\n\s*", " ", _rub).strip(" ()") + ".", ""
                # l'OGGETTO della voce nella rubrica («1. Locazione e affitti di beni immobili:»): senza, tutte le voci di una parte
                # avevano la stessa rubrica e la ricerca non distingueva la locazione dalla compravendita
                _ogg = re.sub(r"^\s*\d+\.\s*", "", next((x.strip() for x in corpo.split("\n") if x.strip()), ""))
                _ogg = re.split(r"\s+—\s+|[:;]", _ogg)[0].strip(" .")[:110]
                u = {"number": target, "group": g,
                     "heading": cfg["gruppi"][g] + ((" — " + _rub) if _rub else (" — " + _ogg if len(_ogg) > 8 else "")),
                     "body": corpo.strip(), "repealed": _abrogato({"heading": a.get("heading"), "body": corpo}),
                     "aggiunto": oggi, "aggiunto_da": "ingest_allegati_it"}
                if a.get("notes"):
                    u["notes"] = a["notes"]
                fu = _futuro(h) if cfg.get("futuro") else None
                if fu:
                    _d, al = _vigenza(p)
                    u["futuro"], u["vigente_fino"], u["riallineato"] = fu, al, oggi
                nuovi.append(u)
            elif g in (cfg.get("pagine") or {}):
                base, titolo = cfg["pagine"][g]
                p = nm.fetch_article(h)
                a = nl.parse_article_page(nl.tabelle_in_testo(p), fallback_number=lab) or {}
                if not a.get("body") or "formato grafico" in (a.get("body") or "")[:300]:
                    print(f"    ? {cid} {lab}: pagina senza testo leggibile (immagine) — saltata", flush=True)
                    continue
                fu = _futuro(h) if cfg.get("futuro") else None
                _d, al = _vigenza(p)
                for u in dividi(a["body"], base, titolo):
                    if u["number"] in nums:
                        continue
                    u.update({"group": g, "repealed": _abrogato(u), "aggiunto": oggi, "aggiunto_da": "ingest_allegati_it"})
                    if fu:
                        u["futuro"], u["vigente_fino"], u["riallineato"] = dict(fu), al, oggi
                    nuovi.append(u)
        spuri = [a for a in arts if str(a.get("number")) in (cfg.get("spuri") or [])
                 and not a.get("riallineato")]           # mai un articolo che il riallineamento ha toccato (è vero)
        print(f"  {cid:18s} + {len(nuovi)} unità · spuri tolti {[a['number'] for a in spuri]}", flush=True)
        for u in nuovi:
            fu = u.get("futuro") or {}
            print(f"     {u['number']:34s} {len(u['body']):6d} chr · «{u['heading'][:90]}»"
                  + (f" · futuro dal {fu.get('dal')} ({'abrogato' if fu.get('repealed') else 'cambia'})" if fu else ""), flush=True)
        if dry or not (nuovi or spuri):
            continue
        shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}-allegati"))
        j["articles"] = [a for a in arts if a not in spuri] + nuovi
        f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
