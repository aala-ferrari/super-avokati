# Golden cases — valutazione dell'accuratezza legale (§37-40)

Questi sono i casi di riferimento con cui `tools/legal_eval.py` misura se la
piattaforma **trova la norma giusta**. A differenza di `golden_check.py` (che
verifica la *struttura* del codice), qui si misura l'**accuratezza legale reale**.

## ⚠️ Il bene prezioso sei tu (l'avvocato)

Il codice è l'impalcatura. I casi etichettati sono la verità di riferimento e
**devono essere validati da un avvocato competente**. I casi attuali sono
**SEED** (`validated_by: null`) messi da Romeo da fatti noti — servono a far
girare il motore, non sono ancora una verità professionale. Vanno:
1. riletti e corretti da un avvocato (statuti attesi, temi, precedenti contrari);
2. impostato `validated_by` col nome di chi li ha validati;
3. fatti crescere: 10-20 → 100 → 500+, distribuiti per materia (civile, penale,
   procedura, lavoro, famiglia, amministrativo, commerciale, consumatori, ecc.).

## Formato (un file JSON per caso)

```json
{
  "id": "al-parashkrim-civil-01",
  "jurisdiction": "AL",                 // AL | IT (gli ID-codice sono diversi)
  "title": "descrizione breve",
  "facts": "il racconto come lo scrive l'avvocato",
  "expected_laws": [{"code": "kodi_civil", "number": "114"}],
  "expected_issues": ["tema atteso"],   // (Tier 2)
  "expected_adverse_authority": [],     // (Tier 2) precedenti contrari attesi
  "notes": "contesto / fonte",
  "validated_by": null                  // nome dell'avvocato validante
}
```

Gli **ID-codice** devono essere quelli veri degli indici. Per elencarli:
`docker exec super-avvocato python3 tools/legal_eval.py --codes`

## Come si lancia

```bash
docker exec super-avvocato python3 tools/legal_eval.py          # Tier 1 (recall statuti)
docker exec super-avvocato python3 tools/legal_eval.py --k 12   # cambia il top-K
```

## I due livelli

- **Tier 1 (deterministico, economico)** — `STATUTE_RETRIEVAL_RECALL`: degli
  statuti attesi, quanti il retrieval fa emergere nei primi K. È un **pavimento**
  (BM25 grezzo sui fatti, senza triage/ancore/Kërkuesi che alzano il numero nel
  prodotto reale). Coglie le regressioni del retrieval e gli errori di autoraggio
  (statuto atteso abrogato o assente dall'indice).
- **Tier 2 (LLM, costoso)** — `--full`, da lanciare a mano: passa la risposta del
  cervello al citation_verifier per `CITATION_ACCURACY` /
  `HALLUCINATED_AUTHORITY_RATE` e controlla i precedenti contrari attesi. Hook
  predisposto in `legal_eval.py`.

## Regola d'oro

Un caso-seed con recall basso **non è per forza un bug del prodotto**: può essere
l'indice che non fa emergere la norma coi soli fatti (il prodotto la prende con
triage+ancore), oppure un errore nell'`expected_laws` del caso. Guardare sempre
cosa è stato recuperato prima di concludere.
