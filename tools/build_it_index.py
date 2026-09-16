# -*- coding: utf-8 -*-
"""Build bm25_it.pkl from the downloaded Normattiva acts.
Writes: all_articles_it.jsonl, it_codes.json (metadata for the UI), bm25_it.pkl.
Keeps a timestamped backup of the previous index so a rollback is trivial.
"""
import json, re, shutil, sys, time
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
_RUB_IN_BODY = re.compile(r"^\s*(?:[A-ZÀ-Ü'’ ,.]{6,}\n+)?Art\.\s*[\dA-Za-z\-]+\.?\s*\n+\s*\(\(?\s*([^\n]{3,160}?)\s*\)?\)\.?\s*\n+")


def _pulisci(heading: str, body: str) -> tuple[str, str]:
    h, b = heading or "", body or ""
    if not h.strip():
        m = _RUB_IN_BODY.match(b)
        if m:
            h, b = m.group(1), b[m.end():]
    h = re.sub(r"\(\(|\)\)", " ", h)
    h = re.sub(r"\s+", " ", h).strip().strip(" ()").rstrip(".").strip(" ()")
    # «((13))» = numero della nota di aggiornamento, non testo normativo: nel corpus restava un
    # «13» a sé su una riga (e faceva risultare «diverso» un testo storico identico — v9.336)
    b = re.sub(r"\(\(\s*\d{1,3}\s*\)\)", " ", b)
    b = re.sub(r"\(\(\s*", "", b)
    b = re.sub(r"\s*\)\)", "", b)
    b = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", b)
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
    for cid in ordered:
        a = acts[cid]
        arts = a.get("articles") or []
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
            all_articles.append(Article(
                code=cid, title_sq=a["title"], area=a.get("area") or "",
                number=art["number"], heading=_h, body=_b,
                pjesa="", kreu="", seksioni="",
                repealed=_as_bool(art.get("repealed")), volatility="STABLE",
                last_amendment_date=_lad))
        meta.append({"code": cid, "title": a["title"], "area": a.get("area") or "",
                     "count": len(arts)})
        print(f"  {cid:34s} {len(arts):>5} art   {a['title'][:46]}")

    print(f"\nTOTALE: {len(all_articles)} articoli su {len(meta)} corpora")

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
