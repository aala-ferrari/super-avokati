# -*- coding: utf-8 -*-
"""Build bm25_it.pkl from the downloaded Normattiva acts.
Writes: all_articles_it.jsonl, it_codes.json (metadata for the UI), bm25_it.pkl.
Keeps a timestamped backup of the previous index so a rollback is trivial.
"""
import json
import os, re, shutil, sys, time
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import Article
from src.retrieval import ArticleIndex

# 16 set 2026 (benchmark lab, v9.332): Normattiva marca con «((…))» il testo modificato da atti
# successivi, e nei CODICI (markup allegato-legacy) la rubrica arriva come «(Capacità giuridica).»
# o resta nel corpo dopo «Art. N.» (c.c. art. 1: rubrica VUOTA e corpo «CODICE CIVILE / Art. 1. /
# (Capacità giuridica). / La capacità…»). Misurato: 1.700+ rubriche IT che cominciano con «(»,
# 457 nel solo c.c.; «( (Maggiore età…» finiva nel badge delle citazioni e nel prompt. Qui si
# puliscono rubrica e corpo SENZA toccare i JSON scaricati (fonte grezza).
_RUB_IN_BODY = re.compile(r"^\s*(?:[A-ZÀ-Ü'’ ,.]{6,}\n+)?Art\.\s*[\dA-Za-z\-]+(?:\.\d+)?\.?\s*\n+\s*\(\(?\s*([^\n]{3,160}?)\s*\)?\)\.?\s*\n+")


# v9.383 — LA RUBRICA RIMASTA NEL CORPO. 4.848 articoli IT vivi (22 %) senza rubrica, fra cui c.c. 45, 89, 128, 158, 230-bis,
# 316 «Responsabilità genitoriale», 536 «Legittimari», 565, 581, 583, 737, c.p. 280, 635 «Danneggiamento», c.p.p. 11, 33-bis…:
# negli articoli SOSTITUITI da leggi successive Normattiva stampa la rubrica senza parentesi («Domicilio dei coniugi…».) come
# prima riga del testo, e nei decreti AKN «(Rubrica)» resta nel corpo quando manca il div della rubrica. Si sposta nella
# rubrica SOLO una prima riga corta (≤100 chr), che finisce con «.» o «)», seguita da una riga vuota e dal testo, che comincia
# con una parola piena (mai «Il/La/Chi/Se/Nei…», mai un verbo finito: una frase normativa breve resta nel corpo — c.c. 147
# non ha rubrica su Normattiva e non gliene si inventa una). Misurato su 1.078 candidate, 115 lette a mano: tutte rubriche.
_RUB_PRIMA_RIGA = re.compile(r"^\s*([^\n]{3,140}?)\s*(?:\n\s*[.;]\s*)?\n\s*\n+(?=\s*[A-ZÀ-Ü0-9(«\"])")
_RUB_STOP = {"il", "lo", "la", "i", "gli", "le", "l", "un", "uno", "una", "chi", "quando", "se", "qualora", "nei", "nel", "nella",
             "nelle", "negli", "nello", "per", "salvo", "ai", "al", "alla", "alle", "agli", "allo", "dal", "dalla", "dai", "dalle",
             "in", "con", "tra", "fra", "ogni", "ciascun", "ciascuno", "ciascuna", "è", "sono", "non", "oltre", "fuori", "fermo",
             "ferma", "restano", "resta", "sulla", "sul", "sui", "sulle", "presso", "entro", "anche", "tutti", "tutte", "nessuno",
             "questo", "questa", "tale", "tali", "detto", "detta", "a", "e", "o", "ove", "dove", "chiunque", "coloro", "colui",
             "nessun", "qualunque", "qualsiasi", "ad", "ed", "od", "sino", "fino", "dopo", "prima", "durante", "mediante",
             "decorso", "trascorso", "all", "dell", "nell", "sull", "dall"}
_RUB_VERBI = re.compile(r"\b(?:è|sono|può|possono|deve|devono|ha|hanno|non|si|viene|vengono|era|erano|sia|siano|fosse|sarà|saranno|"
                        r"spetta|spettano|costituisce|costituiscono|comporta|provvede|provvedono|dispone|stabilisce|prevede|applica|"
                        r"applicano|determina|entra|cessa|decorre|appartiene|appartengono|abbia|abbiano|occorre|basta|vale|valgono)\b", re.I)
# non sono rubriche (misurato sul campione del v9.384): il nome di un allegato o di una tabella, il titolo dell'atto,
# una nota redazionale («COMMA ABROGATO DALLA L. COSTITUZIONALE 18 OTTOBRE 2001, N. 3»)
_RUB_NON_RUBRICA = re.compile(r"^(?:ALLEGAT|Allegat|TABELL|Tabell|TESTO UNICO|Testo unico|CONVENZIONE|CODICE|REGOLAMENTO|DECRETO|"
                              r"LEGGE|TARIFFA|PROSPETTO)|ABROGAT|SOPPRESS")
_RUB_FONTE = re.compile(r"^(.*?\S)\s*(\(\s*(?:articol[oi]|art\.|legge|decreto|d\.\s?lgs|regio)\b[^()]*\))\s*$", re.I)


# v9.384 — le altre forme della rubrica rimasta nel corpo (misurate: Roma I 29 su 29, c.c. 263, 330, 332, 337-ter, 2250…):
#   B «Libertà di scelta» + a capo + «1.  Il contratto…»        (regolamenti UE consolidati: il comma numerato sotto)
#   C «Decadenza dalla responsabilità genitoriale» + «sui figli.»  (rubrica su DUE righe, la seconda minuscola col punto)
#   D «Provvedimenti riguardo ai figli» + riga vuota + «Il figlio…» (senza punto; sotto comincia il testo, maiuscolo)
# Stessi filtri della forma A: ≤100 chr, parola piena in testa, nessun verbo finito, niente «:».
_RUB_RIGA_COMMA = re.compile(r"^\s*([^\n]{3,100}?)[ \t\xa0]*\n(?=[ \t\xa0]*(?:1\.|1\)|\(1\))[\s\xa0])")
_RUB_DUE_RIGHE = re.compile(r"^\s*([^\n]{3,90}?)[ \t\xa0]*\n[ \t\xa0]*([a-zà-ü][^\n]{0,60}?\.)[ \t\xa0]*\n\s*\n+(?=\s*[A-ZÀ-Ü0-9(«\"])")
_RUB_NUDA = re.compile(r"^\s*([^\n]{3,100}?)[ \t\xa0]*\n(?:[ \t\xa0]*\n)*(?=[ \t\xa0]*[A-ZÀ-Ü«\"])")


def _rubrica_prima_riga(body: str):
    """(rubrica, corpo) se la prima riga del corpo è la rubrica dell'articolo, altrimenti None."""
    body = body or ""
    m = _RUB_PRIMA_RIGA.match(body)
    if m:
        riga = m.group(1).strip()
        punto_sotto = bool(re.match(r"\s*\n\s*[.;]", body[m.end(1):]))     # «Reintegrazione …\n.\n\n» (c.c. 332)
        if not (riga.endswith((".", ")")) or riga.endswith("...") or punto_sotto):
            m = None
    if not m:
        m = _RUB_DUE_RIGHE.match(body)
        if m:
            riga = (m.group(1).strip() + " " + m.group(2).strip())
    if not m:
        m = _RUB_RIGA_COMMA.match(body) or _RUB_NUDA.match(body)
        if not m or re.search(r"[.;:,]$", m.group(1).strip()):
            return None
        riga = m.group(1).strip()
    fonte = ""
    f = _RUB_FONTE.match(riga)                          # «Prova del pagamento delle imposte ( articolo 14 d.lgs. 347/1990 )»
    if f and not f.group(1).startswith("("):
        riga, fonte = f.group(1), f.group(2)
    r = riga.rstrip(" .").strip()
    if r.startswith("(") and r.endswith(")") and r.count("(") == 1:
        r = r[1:-1].strip()
    r = re.sub(r"(?:\s*\(\d{1,4}\))+$", "", r).rstrip(" .").strip()   # «Legittimazione ad agire (321)(322)»: note
    if not r or len(r) > 100 or ":" in r or r.count(",") > 3 or not re.match(r"^[A-ZÀ-Ü]", r):
        return None
    w = re.sub(r"[^\wÀ-ÿ']", " ", r.split()[0]).strip().lower().rstrip("'")
    if w in _RUB_STOP or _RUB_VERBI.search(r) or _RUB_NON_RUBRICA.search(r):
        return None
    resto = body[m.end():]
    return r, ((fonte + "\n\n") if fonte else "") + resto.lstrip("\n")


def _pulisci(heading: str, body: str) -> tuple[str, str]:
    h, b = heading or "", body or ""
    if not h.strip():
        m = _RUB_IN_BODY.match(b)
        if m:
            h, b = m.group(1), b[m.end():]
    h = re.sub(r"\(\(|\)\)", " ", h)
    h = re.sub(r"\s+", " ", h).strip().strip(" ()").rstrip(".").strip(" ()")
    # v9.384 — TFUE/TUE: la «rubrica» è la nota di corrispondenza «(ex articolo 234 del TCE)», non un titolo: va in testa al
    # testo (ai giuristi serve la vecchia numerazione) e la rubrica resta vuota, come nel trattato
    if re.fullmatch(r"ex\s+articol[oi]\b.*", h, re.I):
        b, h = "(" + h + ")\n" + b, ""
    # «((13))» = numero della nota di aggiornamento, non testo normativo: nel corpus restava un
    # «13» a sé su una riga (e faceva risultare «diverso» un testo storico identico — v9.336)
    b = re.sub(r"\(\(\s*\d{1,3}\s*\)\)", " ", b)
    b = re.sub(r"\(\(\s*", "", b)
    b = re.sub(r"\s*\)\)", "", b)
    b = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", b)
    # v9.384 — «… della presente Convenzione. TITOLO I DIRITTI E LIBERTÀ»: l'intestazione del titolo SEGUENTE incollata in
    # coda all'articolo (CEDU artt. 1, 18, 51; nel corpus IT non succede altrove — misurato): non è testo dell'articolo
    b = re.sub(r"(?<=[.;:])\s+(?:PARTE|TITOLO|CAPO|SEZIONE|SOTTOSEZIONE)\s+(?:[IVXLC]+|\d+)\b(?:\s+[A-ZÀ-Ü’'«»,\-]+)+\s*$", "", b)
    if not h.strip():                                   # dopo la pulizia dei «((…))»: «(( (Competenza …).» c.p.p. 11
        rp = _rubrica_prima_riga(b.strip())
        if rp:
            h, b = rp
    return h, b.strip()

SRC = Path("/app/data/processed/it_acts")
JSONL = Path("/app/data/processed/all_articles_it.jsonl")
CODES_META = Path("/app/data/processed/it_codes.json")
INDEX = Path("/app/data/index/bm25_it.pkl")

# display order: fundamentals first, then by area
ORDER = ["costituzione", "codice_civile", "preleggi", "disp_att_cc", "codice_procedura_civile",
         "codice_penale", "codice_procedura_penale", "disp_att_cpp",
         "codice_strada", "regolamento_strada", "codice_consumo", "codice_crisi_impresa",
         "ordinamento_polizia", "tulps", "statuto_lavoratori", "sicurezza_lavoro",
         "tu_bancario", "tu_finanza", "codice_proprieta_industriale", "codice_terzo_settore",
         "codice_assicurazioni", "responsabilita_enti", "procedimento_amministrativo",
         "codice_processo_amministrativo", "codice_amministrazione_digitale",
         "tu_documentazione_amministrativa", "codice_contratti_pubblici",
         "sanzioni_amministrative", "tu_spese_giustizia", "codice_privacy",
         "codice_ambiente", "tu_edilizia", "tu_immigrazione", "codice_antimafia",
         "tuir", "codice_beni_culturali", "codice_navigazione", "stupefacenti",
         "ordinamento_penitenziario", "codice_pari_opportunita", "codice_protezione_civile",
         "divorzio", "adozione", "equa_riparazione", "antiriciclaggio",
         # wave5 (16 set 2026) — dogana/tributario, notarile, procedura, lavoro, altro
         "codice_doganale_nazionale", "codice_doganale_ue", "reg_ue_2015_2446", "reg_ue_2015_2447",
         "accise", "iva", "imposta_registro", "imposta_successioni", "sanzioni_tributarie",
         "giustizia_tributaria", "statuto_contribuente", "accertamento_imposte", "riscossione",
         "reati_tributari", "legge_notarile", "legge_52_1985", "condono_edilizio",
         "immobili_da_costruire", "successioni_ue", "locazioni_abitative", "locazioni_immobili_urbani",
         "mediazione_civile", "riti_civili_semplificati", "bruxelles_i_bis", "roma_i", "roma_ii",
         "bruxelles_ii_ter", "ordinamento_forense", "licenziamenti_individuali", "tutele_crescenti",
         "responsabilita_sanitaria", "regolamento_immigrazione", "tuel", "processo_penale_minorile",
         "codice_nautica_diporto", "gdpr",
         # wave6 (16 set 2026) — testi unici della riforma fiscale (sostituiscono gli atti abrogati)
         "tu_sanzioni_tributarie", "tu_riscossione", "tu_registro", "tu_iva", "tu_accertamento",
         # wave7 «blocco A» (16 set 2026)
         "diritto_internazionale_privato", "cittadinanza", "regolamento_cittadinanza", "cittadini_ue",
         "protezione_internazionale", "contratti_lavoro", "orario_lavoro", "maternita_paternita",
         "legge_biagi", "pubblico_impiego", "negoziazione_assistita", "giudice_pace_penale",
         "mandato_arresto_europeo", "casellario", "unioni_civili", "consenso_informato_dat",
         "regolamento_notarile", "prestazione_energetica", "legge_urbanistica", "armi",
         "regolamento_penitenziario",
         "tfue", "tue", "carta_diritti_ue", "codice_frontiere_schengen", "reg_ue_2018_1806",
         "codice_visti", "roma_iii", "alimenti_ue", "regimi_patrimoniali_ue", "ingiunzione_europea",
         "small_claims_ue", "notifiche_ue",
         # wave8 «blocco B»: trattati
         "convenzione_it_al_fisco", "protocollo_it_al_migranti", "cedu", "cedu_protocollo_1",
         "cedu_protocollo_4", "cedu_protocollo_6", "cedu_protocollo_7", "cedu_protocollo_12",
         "cedu_protocollo_13", "cedu_protocollo_16"]


def _as_bool(v) -> bool:
    # La prima ingestione EUR-Lex (16 set 2026) scriveva str(bool): bool("False")
    # e' True -> 1.342 articoli UE «abrogati» e invisibili al BM25 (search() li
    # salta). Qui una stringa vale solo se dice davvero «true».
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "si", "sì")
    return bool(v)


GER = Path("/app/data/processed/it_gerarchia")


def _gerarchia(cid: str):
    """v9.383 — Libro / Titolo / Capo / Sezione di ogni articolo, raccolti dall'albero di Normattiva da tools/it_gerarchia.py
    (una mappa per atto). Ritorna l'indice pronto per `it_gerarchia.voce` (stessa regola del controllo di copertura), o None."""
    f = GER / f"{cid}.json"
    if not f.exists():
        return None
    try:
        m = json.loads(f.read_text(encoding="utf-8")).get("map") or {}
    except Exception:  # noqa: BLE001
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from it_gerarchia import prepara
    return prepara({tuple(k.split("|", 1)): v for k, v in m.items()})


def main():
    files = sorted(SRC.glob("*.json"))
    if not files:
        print("nessun atto scaricato — esco")
        return 1
    acts = {}
    for f in files:
        try:
            acts[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! {f.name} illeggibile: {e}")
    ordered = [c for c in ORDER if c in acts] + [c for c in sorted(acts) if c not in ORDER]

    all_articles, meta = [], []
    notes_map: dict = {}          # code -> number -> [note] (per src/temporal.py: storia + transitori)
    ger_ok = ger_tot = 0
    for cid in ordered:
        a = acts[cid]
        arts = a.get("articles") or []
        _ger = _gerarchia(cid)
        if not arts:
            print(f"  ! {cid}: 0 articoli — escluso")
            continue
        for art in arts:
            _h, _b = _pulisci(art.get("heading") or "", art.get("body") or "")
            # P3b-IT (16 set 2026): la data dell'ultima modifica per articolo dalle note di
            # aggiornamento Normattiva (vedi normattiva_lib.parse_notes), quando l'atto le ha
            _notes = [n for n in (art.get("notes") or []) if isinstance(n, dict)]
            _lad = max((n.get("date") or "" for n in _notes), default="")
            if _notes:
                notes_map.setdefault(cid, {})[str(art["number"])] = [
                    {"n": n.get("n"), "date": n.get("date") or "", "acts": [x.get("label") for x in (n.get("acts") or [])][:3],
                     "text": (n.get("text") or "")[:600]} for n in _notes[:6]]
            _gv = ["", "", ""]
            if _ger is not None:
                from it_gerarchia import voce as _ger_voce
                _gv = _ger_voce(_ger, art["number"], art.get("group")) or ["", "", ""]
            ger_tot += 1; ger_ok += 1 if any(_gv) else 0
            all_articles.append(Article(
                code=cid, title_sq=a["title"], area=a.get("area") or "",
                number=art["number"], heading=_h, body=_b,
                pjesa=_gv[0], kreu=_gv[1], seksioni=_gv[2],
                repealed=_as_bool(art.get("repealed")), volatility="STABLE",
                last_amendment_date=_lad))
        meta.append({"code": cid, "title": a["title"], "area": a.get("area") or "",
                     "count": len(arts)})
        print(f"  {cid:34s} {len(arts):>5} art   {a['title'][:46]}")

    print(f"\nTOTALE: {len(all_articles)} articoli su {len(meta)} corpora · con capitolo (Titolo/Capo/Sezione): {ger_ok}/{ger_tot}")
    # v9.383 — indice di PROVA: IT_INDEX_OUT=/percorso scrive SOLO il pickle lì (niente jsonl, meta, note: la produzione non si tocca)
    _test_out = os.environ.get("IT_INDEX_OUT", "").strip()
    if _test_out:
        ArticleIndex.build(all_articles, lang="it").save(Path(_test_out))
        print(f"indice di PROVA scritto in {_test_out} (produzione intatta)")
        return 0

    # backup previous index before overwriting
    if INDEX.exists():
        bak = INDEX.with_suffix(f".pkl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(INDEX, bak)
        print(f"backup indice precedente -> {bak.name}")

    with JSONL.open("w", encoding="utf-8") as fh:
        for a in all_articles:
            fh.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    CODES_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    NOTES = CODES_META.parent / "it_notes.json"
    NOTES.write_text(json.dumps(notes_map, ensure_ascii=False), encoding="utf-8")
    n_notes = sum(len(v) for v in notes_map.values())
    ArticleIndex.build(all_articles, lang="it").save(INDEX)
    print(f"scritto: {JSONL.name}, {CODES_META.name}, {INDEX.name}, {NOTES.name} ({n_notes} articoli con note)")

    # sanity: reload and spot-check
    idx = ArticleIndex.load(INDEX)
    print(f"reload OK: {len(idx.articles)} articoli, lang={getattr(idx, 'lang', '?')}")
    by = {(a.code, a.number): a for a in idx.articles}
    checks = [("codice_civile", "2043"), ("codice_penale", "575"),
              ("codice_procedura_civile", "163"), ("codice_procedura_penale", "273"),
              ("costituzione", "21"), ("codice_strada", "186"), ("codice_strada", "142"),
              ("codice_consumo", "33"), ("codice_crisi_impresa", "2"),
              ("statuto_lavoratori", "18"), ("codice_privacy", "1")]
    for code, n in checks:
        a = by.get((code, n))
        print(f"  {code} art.{n}: " + (f"{(a.heading or a.body[:44])[:50]!r}" if a else "MANCANTE"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
