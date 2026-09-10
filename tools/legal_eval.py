# -*- coding: utf-8 -*-
"""Evaluation framework legale (spec §37-40) — misura l'ACCURATEZZA REALE, non
il «verde strutturale» del golden_check.

Il golden_check verifica la struttura del codice; questo misura se la
piattaforma TROVA la norma giusta. La verità di riferimento (golden cases) deve
essere validata da un AVVOCATO: il codice qui è l'impalcatura + le metriche; i
casi etichettati sono il bene prezioso, da far crescere (10-20 → 100 → 500+).

TIER 1 (deterministico, economico, senza LLM) — eseguibile spesso:
  STATUTE_RETRIEVAL_RECALL = frazione degli statuti ATTESI che il retrieval
  (BM25) fa emergere nei primi K. È un PAVIMENTO: la pipeline reale fa meglio
  (triage + ancore + Kërkuesi), ma questo numero è deterministico e coglie le
  regressioni del retrieval. Segnala anche gli statuti attesi ABROGATI o ASSENTI
  dall'indice (errore di AUTORAGGIO del caso, non del prodotto).

TIER 2 (LLM, costoso) — `--full`, da lanciare a mano, non in CI:
  richiede il cervello; misura CITATION_ACCURACY / HALLUCINATED_AUTHORITY_RATE
  passando la risposta al citation_verifier. Hook predisposto, vedi in fondo.

Uso:
  docker exec super-avvocato python3 tools/legal_eval.py            # Tier 1 su tutti i casi
  docker exec super-avvocato python3 tools/legal_eval.py --codes    # elenca gli ID-codice degli indici
  docker exec super-avvocato python3 tools/legal_eval.py --k 12     # top-K del retrieval (default 12)

Formato di un golden case — tools/golden_cases/*.json:
  {
    "id": "al-parashkrim-civil-01",
    "jurisdiction": "AL",                      // AL | IT
    "title": "…",
    "facts": "racconto del caso come lo scrive l'avvocato",
    "expected_laws": [{"code": "kodi_civil", "number": "114"}],
    "expected_issues": ["…"],                  // (Tier 2) temi attesi
    "expected_adverse_authority": [],          // (Tier 2) precedenti contrari attesi
    "notes": "SEED — da validare da avvocato",
    "validated_by": null                       // nome dell'avvocato che l'ha validato
  }
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.retrieval import ArticleIndex, INDEX_FILE  # noqa: E402

# i golden case vivono SOTTO tools/ (il Dockerfile COPIA tools/, non tests/ →
# devono stare qui per essere dentro l'immagine e leggibili a runtime).
CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_cases")


def _load_indexes():
    al = ArticleIndex.load()
    it = None
    it_path = INDEX_FILE.parent / "bm25_it.pkl"
    if it_path.exists():
        try:
            it = ArticleIndex.load(it_path)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] indice IT non caricato: {e}")
    return al, it


def _code_ids(idx) -> set:
    return {str(getattr(a, "code", "")) for a in getattr(idx, "articles", [])}


def list_codes():
    al, it = _load_indexes()
    print("=== ID-codice AL (%d articoli) ===" % len(getattr(al, "articles", [])))
    for c in sorted(_code_ids(al)):
        print("  ", c)
    if it is not None:
        print("\n=== ID-codice IT (%d articoli) ===" % len(getattr(it, "articles", [])))
        for c in sorted(_code_ids(it)):
            print("  ", c)


def load_cases() -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(CASES_DIR, "*.json"))):
        try:
            out.append(json.load(open(p, encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] caso illeggibile {os.path.basename(p)}: {e}")
    return out


def _norm(code, number) -> tuple:
    return (str(code or "").strip().lower(), str(number or "").strip())


def eval_tier1(cases: list[dict], *, k: int = 12) -> dict:
    al, it = _load_indexes()
    al_codes, it_codes = _code_ids(al), (_code_ids(it) if it else set())
    recalls = []
    print("=" * 70)
    for c in cases:
        juris = (c.get("jurisdiction") or "AL").upper()
        idx = it if (juris == "IT" and it is not None) else al
        idx_codes = it_codes if (juris == "IT" and it is not None) else al_codes
        expected = [_norm(x.get("code"), x.get("number")) for x in (c.get("expected_laws") or [])]
        if not expected:
            print(f"• {c.get('id','?')}: nessun expected_laws — salto")
            continue
        # Query = i TERMINI GIURIDICI del tema (proxy di ciò che triage/Kërkuesi
        # producono), con fallback ai fatti. Misura la qualità dell'INDICE dato
        # un buon termine di ricerca; i casi che mancano comunque (es. Neni 114,
        # zero sovrapposizione lessicale) indicano dove servono le ANCORE.
        query = " ".join(c.get("expected_issues") or []).strip() or (c.get("facts") or "")
        hits = idx.search(query, top_k=max(k, 20))
        retrieved = {_norm(getattr(a, "code", ""), getattr(a, "number", "")) for a, _ in hits[:k]}
        found = [e for e in expected if e in retrieved]
        # diagnostica: lo statuto atteso esiste nell'indice? è abrogato?
        missing_from_index = [e for e in expected if e[0] not in idx_codes]
        recall = len(found) / len(expected)
        recalls.append(recall)
        status = "✓" if recall == 1.0 else ("~" if recall > 0 else "✗")
        print(f"{status} [{juris}] {c.get('id','?')} — recall {recall:.0%} "
              f"({len(found)}/{len(expected)})  {c.get('title','')}")
        for e in expected:
            mark = "✓ trovato" if e in retrieved else ("⚠ NON nell'indice (caso da correggere?)" if e in missing_from_index else "✗ non recuperato")
            print(f"      {e[0]} {e[1]}: {mark}")
    macro = (sum(recalls) / len(recalls)) if recalls else 0.0
    print("=" * 70)
    print(f"STATUTE_RETRIEVAL_RECALL (macro, top-{k}, query = termini del tema ≈ triage): {macro:.1%}")
    print(f"Casi valutati: {len(recalls)}")
    print("\nNOTA: la query usa i termini giuridici del tema (proxy del triage/Kërkuesi),")
    print("quindi misura la qualità dell'INDICE dato un buon termine. Un caso che manca")
    print("comunque (zero sovrapposizione lessicale, es. Neni 114) indica dove servono le")
    print("ANCORE — non un bug. I casi-seed vanno VALIDATI da un avvocato e fatti crescere.")
    print("Tier 2 (citazioni/allucinazioni, col cervello) = --full.")
    return {"macro_recall": macro, "n": len(recalls)}


def main(argv):
    if "--codes" in argv:
        list_codes()
        return 0
    if "--full" in argv:
        print("Tier 2 (LLM) non ancora implementato: richiede il cervello + citation_verifier")
        print("sulla risposta reale. Hook predisposto — da lanciare a mano, non in CI.")
        return 0
    k = 12
    if "--k" in argv:
        try:
            k = int(argv[argv.index("--k") + 1])
        except (ValueError, IndexError):
            pass
    cases = load_cases()
    if not cases:
        print(f"Nessun golden case in {CASES_DIR}. Aggiungine (vedi README).")
        return 0
    eval_tier1(cases, k=k)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
