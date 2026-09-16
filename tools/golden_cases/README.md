# Golden cases — valutazione dell'accuratezza legale (§37-40)

> **Benchmark Lab (16 set 2026, roadmap v3 P0)** — questi casi sono lo **STRATO 2** di
> `tools/benchmark_lab.py` (il cervello vero, via HTTP come il browser). Lo **strato 1** è
> deterministico (`tools/benchmark/layer1_auto.jsonl` generato dal corpus + `layer1_manual.jsonl`
> con sigle e REGRESSIONI: ogni errore vero trovato diventa un test per sempre) e gira in un
> minuto; lo strato 3 è il `golden_check`. Baseline strato 1 del 16 set: 851 test, GATE PASS
> (recupero AL 99,3%, IT 91,3%, stati/sigle/regressioni 100%).
>
> **Come scrivere un caso (per l'avvocato che valida)** — un file JSON per caso, campi in più
> rispetto al formato originale:
> - `question`: la domanda ESATTA come la farebbe un avvocato in chat (se manca si usa `facts`);
> - `expected_laws`: gli articoli che DEVONO essere citati (`code` = ID dell'indice, `number`);
> - `must_not_cite`: articoli che NON devono comparire (es. `kodi_penal 155` quando si parla di
>   Kodi i Punës);
> - `key_points`: espressioni regolari (case-insensitive) che la risposta deve contenere — i
>   punti giuridici decisivi («180 dit», «B1», «60 giorni|sessanta»);
> - `verdict_expect`: il senso del verdetto atteso (testo libero, per chi rilegge);
> - `validated_by`: il nome dell'avvocato che ha verificato il caso (finché è `null` è un SEME).
>
> Lancio: `docker exec super-avvocato python3 tools/benchmark_lab.py run --layer 2 --limit 3`
> (costa una domanda al cervello per caso, 3-30 min: di notte, mai in CI). Ogni giro salva le
> risposte in `data/benchmark/layer2/<run>/` e il punteggio in `layer2_history.jsonl`: punteggio =
> 45% norme attese citate + 25% punti chiave + 15% nessuna citazione vietata + 10% verdetto in
> testa + 5% lingua pura.

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
