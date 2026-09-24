#!/usr/bin/env python3
"""v9.383 — GLI ARTICOLI «PUNTATI» PERSI DALL'INGEST ITALIANO.

Normattiva distingue «473-bis», «473-bis.1», «473-bis.2»… SOLO con `art.idSottoArticolo1` (10, 20, 30…): idArticolo e
idSottoArticolo sono gli stessi. La dedup di `normattiva_lib.article_links_all` non guardava idSottoArticolo1 e teneva
il primo link del gruppo: 286 articoli mai scaricati — gli artt. 473-bis.1-71 c.p.c. (tutto il rito per persone,
minorenni e famiglie), 380-bis.1 c.p.c., 270-bis.1 c.p., 2506.1 c.c., 9.1 L. 91/1992 (cittadinanza), 25-octies.1
d.lgs. 231/2001, 35-bis.1 d.lgs. 25/2008… Il numero stesso si leggeva male («Art. 473-bis.2» → «473-bis»).

Qui, per ogni atto: si riapre la pagina dell'atto (serve la sessione), si prendono i link che la vecchia dedup buttava
(stesso idArticolo+idSottoArticolo+gruppo, idSottoArticolo1 diverso dal primo), si scaricano SOLO quelli e si leggono con
il parser corretto. Numero = quello dell'albero («art. 473 bis.2» → «473-bis.2»), col suffisso di gruppo come fa
`assign_numbers` (gruppo principale = numero pulito; gruppo 0 = «-legge»; altro gruppo = «-allK»). Un numero che c'è già
non si tocca MAI; le parti di allegato («Allegato 1(parte 2)») restano fuori. Backup del JSON accanto.

    IT_ACTS_DIR=/var/www/apps/super-avvocato/data/processed/it_acts python3 tools/repair_dotted_it.py report
    IT_ACTS_DIR=… python3 tools/repair_dotted_it.py apply [--only codice_procedura_civile,…]
"""
import html as _html, json, os, re, sys, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from normattiva_lib import LINK_RE, Normattiva, parse_article_page, sortkey  # noqa: E402

ACTS = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))


def _norm_num(label: str) -> str:
    n = re.sub(r"^art(?:icolo)?\.?\s*", "", (label or "").strip(), flags=re.I)
    return re.sub(r"[\s\-]+", "-", n).lower().rstrip("-.")


def _atti() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(ACTS.glob("*.json")):
        if f.stem == "preleggi" or f.stem == "cedu" or f.stem.startswith("cedu_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        urn = (d.get("urn") or "").strip()
        if urn and ":" in urn and not urn.upper().startswith(("CELEX", "EUR", "3")) and "eur-lex" not in urn.lower():
            out.append((f.stem, d))
    return out


def mancanti(page: str) -> tuple[list[tuple[str, str, str]], str]:
    """I link che la vecchia dedup buttava: [(href, etichetta, gruppo)], più il gruppo principale dell'atto."""
    gruppi: dict = {}
    per_flag: Counter = Counter()
    for u, lab in LINK_RE.findall(page):
        u = _html.unescape(u); lab = lab.strip()
        if "imUpdate=true" in u or lab.lower().startswith("agg"):
            continue
        ia = re.search(r"art\.idArticolo=(\d+)", u); isa = re.search(r"art\.idSottoArticolo=(\d+)", u)
        isa1 = re.search(r"art\.idSottoArticolo1=(\d+)", u); fl = re.search(r"flagTipoArticolo=(\d+)", u)
        flag = fl.group(1) if fl else "0"
        k = (ia.group(1) if ia else lab, isa.group(1) if isa else "", flag)
        s1 = isa1.group(1) if isa1 else ""
        lst = gruppi.setdefault(k, [])
        if all(s1 != x[0] for x in lst):
            lst.append((s1, u, lab))
            per_flag[flag] += 1
    principale = per_flag.most_common(1)[0][0] if per_flag else "0"
    out = []
    for (_ia, _isa, flag), lst in gruppi.items():
        for s1, u, lab in lst[1:]:                       # il primo è quello che l'ingest aveva già preso
            out.append((u, lab, flag))
    return out, principale


def numero_corpus(label: str, flag: str, principale: str) -> str | None:
    """Il numero con cui l'articolo entra nel corpus; None per le parti di allegato («Allegato 1(parte 2)», «2 note (parte 1)»)."""
    n = _norm_num(label)
    if not re.match(r"^\d+(?:[.\-/][0-9a-z]+)*$", n):
        return None
    if flag == principale:
        return n
    return f"{n}-legge" if flag == "0" else f"{n}-all{flag}"


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    solo = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else set()
    delay = float(sys.argv[sys.argv.index("--delay") + 1]) if "--delay" in sys.argv else 0.6
    totale = scaricati = 0
    for cid, atto in _atti():
        if solo and cid not in solo:
            continue
        nm = Normattiva(delay=delay)
        try:
            page = nm.open_act(atto["urn"])
        except Exception as e:  # noqa: BLE001
            print(f"{cid:34s} ✗ pagina: {type(e).__name__}: {str(e)[:80]}", flush=True)
            continue
        persi, principale = mancanti(page)
        esistenti = {str(a.get("number")) for a in atto.get("articles") or []}
        da_fare = []
        for u, lab, flag in persi:
            n = numero_corpus(lab, flag, principale)
            if n and n not in esistenti:
                da_fare.append((u, lab, flag, n))
        time.sleep(delay)
        if not da_fare:
            continue
        totale += len(da_fare)
        print(f"{cid:34s} {len(da_fare):4d} da scaricare: {', '.join(n for *_x, n in da_fare[:10])}{' …' if len(da_fare) > 10 else ''}",
              flush=True)
        if cmd != "apply":
            continue
        nuovi, falliti = [], []
        for u, lab, flag, n in da_fare:
            try:
                a = parse_article_page(nm.fetch_article(u), fallback_number=lab)
            except Exception as e:  # noqa: BLE001
                falliti.append(f"{lab}: {type(e).__name__}"); continue
            if not a:
                falliti.append(f"{lab}: vuoto"); continue
            letto = a["number"]
            if letto != _norm_num(lab):
                print(f"    ⚠ {lab!r}: la pagina dice «{letto}» — tengo il numero dell'albero «{n}»", flush=True)
            a["number"] = n
            a["group"] = flag
            nuovi.append(a)
        if not nuovi:
            print(f"    ✗ nessun articolo letto ({len(falliti)} falliti: {falliti[:4]})", flush=True)
            continue
        f = ACTS / f"{cid}.json"
        bak = f.with_name(f"{f.name}.bak-dotted-{time.strftime('%Y%m%d-%H%M')}")
        bak.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        d = json.loads(f.read_text(encoding="utf-8"))
        gia = {str(a.get("number")) for a in d["articles"]}
        nuovi = [a for a in nuovi if a["number"] not in gia]
        d["articles"] = sorted(d["articles"] + nuovi, key=lambda a: sortkey(str(a.get("number"))))
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        try:
            os.chown(f, 1000, 1000)
        except Exception:  # noqa: BLE001
            pass
        scaricati += len(nuovi)
        es = next((a for a in nuovi if not a.get("repealed")), nuovi[0])
        print(f"    ✓ +{len(nuovi)} (falliti {len(falliti)}{': ' + '; '.join(falliti[:3]) if falliti else ''}) · "
              f"es. {es['number']}: {es.get('heading','')[:50]!r} | {es.get('body','')[:70]!r}", flush=True)
    print(f"\ntotale da scaricare {totale} · scaricati {scaricati}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
