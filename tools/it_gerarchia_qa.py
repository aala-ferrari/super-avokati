#!/usr/bin/env python3
"""v9.383 — Controllo dei capitoli italiani raccolti da tools/it_gerarchia.py (sull'host, dopo ogni `run`).

Tre controlli, perché ognuno vede un errore che gli altri non vedono:
  contigui — lo stesso capitolo in due tratti separati di articoli = albero letto male (ha trovato le intestazioni perse
             e la «SEZIONE sopra i TITOLI» del codice dell'ambiente);
  buchi    — CAPO I, CAPO III senza CAPO II sotto lo stesso genitore: un'intestazione può mancare nell'albero stesso
             (e gli articoli di quel capo finire nel precedente). Molti buchi sono veri (capi abrogati e tolti):
             si leggono, non si correggono alla cieca;
  note     — risposte note verificate a mano sul testo dei codici (c.p.c. 414 nel rito del lavoro, c.p. 575 nei delitti
             contro la persona, c.c. 2946 nel § della prescrizione ordinaria…).

    python3 tools/it_gerarchia_qa.py [contigui|buchi|note|tutto] [--cache /root/it_ger_html]
Esce 1 se una risposta nota è sbagliata.
"""
import gzip, hashlib, json, re, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import it_gerarchia as G  # noqa: E402

NOTE = [
    ("codice_civile", "1", ["LIBRO PRIMO — DELLE PERSONE E DELLA FAMIGLIA", "TITOLO I — DELLE PERSONE FISICHE"]),
    ("codice_civile", "2043", ["LIBRO QUARTO — DELLE OBBLIGAZIONI", "TITOLO IX — DEI FATTI ILLECITI"]),
    ("codice_civile", "1453", ["CAPO XIV — Della risoluzione del contratto", "Sezione I — Della risoluzione per inadempimento"]),
    ("codice_civile", "2946", ["TITOLO V — DELLA PRESCRIZIONE E DELLA DECADENZA", "CAPO I — Della prescrizione",
                               "Sezione IV — Del termine della prescrizione", "§ 1 — Della prescrizione ordinaria"]),
    ("codice_civile", "981", ["TITOLO V — DELL'USUFRUTTO", "Sezione II — Dei diritti nascenti dall'usufrutto"]),
    ("preleggi", "12", ["Disposizioni sulla legge in generale", "CAPO II"]),
    ("codice_penale", "575", ["LIBRO SECONDO — DEI DELITTI IN PARTICOLARE", "TITOLO DODICESIMO — DEI DELITTI CONTRO LA PERSONA",
                              "CAPO I — Dei delitti contro la vita e l'incolumità individuale"]),
    ("codice_penale", "640", ["TITOLO TREDICESIMO — DEI DELITTI CONTRO IL PATRIMONIO", "CAPO II — Dei delitti contro il patrimonio mediante frode"]),
    ("codice_penale", "556", ["TITOLO UNDECIMO — DEI DELITTI CONTRO LA FAMIGLIA"]),
    ("codice_penale", "519", ["TITOLO NONO", "(CAPO ABROGATO"]),
    ("codice_procedura_civile", "163", ["LIBRO SECONDO — DEL PROCESSO DI COGNIZIONE", "CAPO I — Dell'introduzione della causa"]),
    ("codice_procedura_civile", "414", ["TITOLO IV — NORME PER LE CONTROVERSIE IN MATERIA DI LAVORO", "Sezione II — Del procedimento", "Par. 1"]),
    ("codice_procedura_civile", "433", ["TITOLO IV — NORME PER LE CONTROVERSIE IN MATERIA DI LAVORO", "Par. 2 — Delle impugnazioni"]),
    ("codice_procedura_civile", "473-bis", ["LIBRO SECONDO", "TITOLO IV-BIS", "PERSONE, MINORENNI E FAMIGLIE"]),
    ("codice_procedura_civile", "404", ["CAPO V — Dell'opposizione di terzo"]),
    ("codice_procedura_penale", "273", ["MISURE CAUTELARI", "MISURE CAUTELARI PERSONALI"]),
    ("codice_procedura_penale", "314", ["RIPARAZIONE PER L'INGIUSTA DETENZIONE"]),
    ("costituzione", "1", ["PRINCIPI FONDAMENTALI"]),
    ("costituzione", "13", ["PARTE I — DIRITTI E DOVERI DEI CITTADINI", "TITOLO I — RAPPORTI CIVILI"]),
    ("costituzione", "70", ["PARTE II — ORDINAMENTO DELLA REPUBBLICA", "TITOLO I — IL PARLAMENTO", "SEZIONE II — La formazione delle leggi"]),
    ("procedimento_amministrativo", "10-bis", ["CAPO III — PARTECIPAZIONE AL PROCEDIMENTO AMMINISTRATIVO"]),
    ("codice_ambiente", "73", ["PARTE TERZA", "SEZIONE II — TUTELA DELLE ACQUE DALL'INQUINAMENTO", "TITOLO I — PRINCIPI GENERALI E COMPETENZE"]),
    ("tuel", "149", ["PARTE II — ORDINAMENTO FINANZIARIO E CONTABILE", "TITOLO I"]),
    ("codice_strada", "186", ["TITOLO V — NORME DI COMPORTAMENTO"]),
    ("tu_bancario", "124", ["TITOLO VI", "CREDITO AI CONSUMATORI"]),
]


def _mappa(cid: str) -> dict:
    f = G.OUT / f"{cid}.json"
    if not f.exists():
        return {}
    return {tuple(k.split("|", 1)): tuple(v) for k, v in json.loads(f.read_text(encoding="utf-8"))["map"].items()}


def contigui() -> int:
    tot = 0
    for f in sorted(G.OUT.glob("*.json")):
        m = _mappa(f.stem)
        per_g = defaultdict(list)
        for (g, n), v in m.items():
            per_g[g].append((G.ordina(n), n, v))
        for g, items in per_g.items():
            items.sort()
            runs, last = defaultdict(list), None
            for _o, n, v in items:
                if v != last:
                    runs[v].append(n)
                last = v
            for v, starts in runs.items():
                if any(v) and len(starts) > 1:
                    tot += 1
                    print(f"  {f.stem}: NON CONTIGUO g{g} {' | '.join(x for x in v if x)[:140]} — riprende agli artt. {starts[:6]}")
    print(f"contigui: {tot} segnalazioni")
    return 0


def buchi(cache: Path) -> int:
    rom = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

    def _r(s):
        t, p = 0, 0
        for ch in reversed(s.upper()):
            v = rom.get(ch, 0); t = t - v if v < p else t + v; p = max(p, v)
        return t
    parole = {"PRIM": 1, "SECOND": 2, "TERZ": 3, "QUART": 4, "QUINT": 5, "SEST": 6, "SETTIM": 7, "OTTAV": 8, "NON": 9,
              "DECIM": 10, "UNDECIM": 11, "UNDICESIM": 11, "DODICESIM": 12, "TREDICESIM": 13, "QUATTORDICESIM": 14, "UNIC": 1}

    def _val(et):
        m = re.match(r"^\S+\s+(.*)$", et.strip())
        if not m:
            return None
        o = m.group(1).upper()
        if re.search(r"[\s\-](?:BIS|TER|QUATER|QUINQUIES|SEXIES|SEPTIES|OCTIES)\b|\.\d|^\d+-|^[IVXL]+\.", o):
            return None
        if re.match(r"^\d+", o):
            return int(re.match(r"^\d+", o).group(0))
        if re.fullmatch(r"[IVXL]+", o):
            return _r(o)
        return next((v for k, v in parole.items() if o.startswith(k)), None)
    orig = G._applica
    visti = defaultdict(list)

    def spia(pila, e, primo):
        nuova = orig(pila, e, primo)
        if e["tipo"] in ("PARTE", "LIBRO", "TITOLO", "CAPO", "SEZIONE", "§"):
            v = _val(e["etichetta"])
            if v is not None:
                visti[(tuple(x["testo"][:60] for x in nuova[:-1]), e["tipo"])].append((v, e["etichetta"]))
        return nuova
    G._applica = spia
    tot = 0
    try:
        for cid, atto in G._atti():
            if cid == "preleggi":
                continue
            cf = cache / (hashlib.sha1(atto["urn"].encode()).hexdigest()[:16] + ".html.gz")
            if not cf.exists():
                continue
            visti.clear()
            G.albero(gzip.decompress(cf.read_bytes()).decode("utf-8"), atto.get("title") or "")
            for (gen, tipo), vs in visti.items():
                attesi = 1
                for v, et in vs:
                    if v > attesi:
                        tot += 1
                        print(f"  {cid:30s} {tipo:8s} manca prima di «{et}» (atteso {attesi}) · sotto: {' > '.join(gen)[-110:]}")
                    attesi = max(attesi, v + 1)
    finally:
        G._applica = orig
    print(f"buchi: {tot} (da leggere: capi abrogati e tolti dall'albero sono buchi veri)")
    return 0


def note() -> int:
    ok = bad = 0
    for cid, num, attesi in NOTE:
        m = _mappa(cid)
        atto = json.loads((G.ACTS / f"{cid}.json").read_text(encoding="utf-8"))
        art = next((a for a in atto["articles"] if a["number"] == num), None)
        v = G.voce(G.prepara(m), num, (art or {}).get("group")) if m else None
        tutto = " | ".join(v) if v else "(nessuna voce)"
        manca = [x for x in attesi if x.lower() not in tutto.lower()]
        if manca:
            bad += 1; print(f"  ✗ {cid} {num}: mancano {manca}\n       ha: {tutto[:300]}")
        else:
            ok += 1
    print(f"note: {ok}/{ok + bad} giuste")
    return 1 if bad else 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "tutto"
    cache = Path(sys.argv[sys.argv.index("--cache") + 1]) if "--cache" in sys.argv else Path("/root/it_ger_html")
    rc = 0
    if cmd in ("contigui", "tutto"):
        contigui()
    if cmd in ("buchi", "tutto"):
        buchi(cache)
    if cmd in ("note", "tutto"):
        rc = note()
    return rc


if __name__ == "__main__":
    sys.exit(main())
