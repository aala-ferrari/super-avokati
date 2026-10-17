"""V9.4 — Bench Memo Predictor.

Single Opus call producing a judicial bench memo: how a Gjykata e Lartë
judge would frame the issue, predict the outcome, weigh both sides, and
identify argument upgrades. Reuses BM25 articles + V9.2 ratio precedents
+ court-specific calibration.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from .backends import LLMBackend
from .genio import GENIO_JURISDICTION_GUARD
from .precedent import PrecedentRef, gather_precedents, gather_precedents_it
from .retrieval import ArticleIndex, DecisionIndex

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt



from .logging_utils import get_logger  # v9.337: getLogger(__name__) non aveva handler → INFO persi
log = get_logger(__name__)

# ── Court calibration labels ──────────────────────────────────────────

COURT_LABELS = {
    "gjykata_lartë": "Gjykata e Lartë e Republikës së Shqipërisë",
    "gjykata_apelit": "Gjykata e Apelit",
    "gjykata_shkalle1": "Gjykata e Shkallës së Parë",
    "gjykata_kushtetuese": "Gjykata Kushtetuese",
    "gjykata_administrative": "Gjykata Administrative",
    "gjykata_komerciale": "Gjykata Komerciale (Tiranë)",
    "ecthr_albania": "Gjykata Evropiane e të Drejtave të Njeriut",
}

DEFAULT_COURT = "gjykata_lartë"

# v9.647 — in sessione italiana le STESSE chiavi (sono i valori della scelta nell'interfaccia) coi giudici italiani: prima il
# prompt diceva a un memo italiano che la causa stava davanti alla «Gjykata e Lartë e Republikës së Shqipërisë»
COURT_LABELS_IT = {
    "gjykata_lartë": "Corte Suprema di Cassazione",
    "gjykata_apelit": "Corte d'appello",
    "gjykata_shkalle1": "Tribunale (primo grado)",
    "gjykata_kushtetuese": "Corte costituzionale",
    "gjykata_administrative": "Giustizia amministrativa (TAR / Consiglio di Stato)",
    "gjykata_komerciale": "Tribunale delle imprese",
    "ecthr_albania": "Corte europea dei diritti dell'uomo",
}

# ── System prompt ─────────────────────────────────────────────────────

BENCH_SYSTEM = (
    GENIO_JURISDICTION_GUARD
    + "Je një gjyqtar shqiptar me 30 vjet eksperiencë (KC, KP, KPC, KPP, "
    "Kushtetutë, ligje sektoriale). Detyra: shkruaj një BENCH MEMO siç do "
    "ta shkruaje për veten para se të vendosësh — jo për të lavdëruar "
    "avokatin, por për të treguar SI do të mendojë gjykata. Vlerëso ftohtë "
    "të dy palët, përcakto rezultatin më të mundshëm me shifra realiste, "
    "dhe identifiko se ku do të bjerë çekani gjyqësor.\n\n"
    "RREGULLAT KRITIKE:\n"
    "1) Bazohu VETËM në nenet shqiptare dhe precedentët e dhënë në kontekst.\n"
    "2) Mos shpik citime — nëse një nen ose vendim nuk është në kontekst, mos e citosh.\n"
    "3) Probabilitetet duhet të jenë të kalibruara: shumë rrallë 90%+ ose 10%-, "
    "shumica e rasteve të vërteta janë 35-65%.\n"
    "4) Konsidero kalibrimin sipas gjykatës specifike — Kushtetuesja vendos "
    "ndryshe nga Gjykata e Lartë komerciale.\n"
    "5) Përfundo me një rekomandim të vetëm: FIGHT, SETTLE, ose FOLD.\n"
    "6) Kthe VETËM JSON të vlefshëm pa asnjë tekst tjetër para apo pas.\n"
    # v9.647 — le citazioni si verificano: senza «neni» e il codice restano «senza codice»
    "7) Cito nenet me fjalën «neni» dhe kodin ashtu si në kontekst (p.sh. «neni [numri] i Kodit Civil»), kurrë vetëm «KC [numri]»."
)

# v9.647 — il memo in sessione ITALIANA: prima riceveva il prompt albanese col vincolo «VETËM të drejtën shqiptare» in testa
# (GENIO_JURISDICTION_GUARD), i giudici e i precedenti ALBANESI
BENCH_SYSTEM_IT = (
    "Sei un giudice italiano con 30 anni di esperienza (c.c., c.p., c.p.c., c.p.p., Costituzione, leggi speciali). "
    "Compito: scrivi un BENCH MEMO come lo scriveresti per te prima di decidere — non per lusingare l'avvocato, ma per "
    "mostrare COME ragionerà il giudice. Valuta a freddo le due parti, indica l'esito più probabile con percentuali "
    "realistiche e individua dove cadrà il colpo del giudice.\n\n"
    "REGOLE CRITICHE:\n"
    "1) Basati SOLO sugli articoli italiani e sui precedenti dati nel contesto.\n"
    "2) Non inventare citazioni — se un articolo o una decisione non è nel contesto, non citarli.\n"
    "3) Le probabilità devono essere calibrate: molto di rado 90%+ o 10%-, la maggior parte dei casi veri sta fra il 35 "
    "e il 65%.\n"
    "4) Considera il giudice specifico — la Corte costituzionale decide diversamente da una sezione civile della Cassazione.\n"
    "5) Chiudi con una sola raccomandazione che comincia con FIGHT, SETTLE o FOLD (il token resta così: è un codice "
    "dell'interfaccia), seguito dalla motivazione in italiano.\n"
    "6) Restituisci SOLO JSON valido, senza testo prima o dopo; tutti i valori in italiano.\n"
    "7) Cita gli articoli nella forma «art. [numero] c.c.» come nel contesto.\n"
    "8) Lavori senza web, per scelta: niente note su strumenti negati; la «verifica viva» della Cassazione richiesta sopra "
    "non si applica al memo."
)

BENCH_USER_TEMPLATE = """\
═════════════════════════════════════════════
ÇËSHTJA PARA GJYKATËS
═════════════════════════════════════════════
{case_description}

═════════════════════════════════════════════
GJYKATA QË DO TË GJYKOJË
═════════════════════════════════════════════
{court_label}

═════════════════════════════════════════════
DOKUMENTET E PALËS SONË (përmbledhje)
═════════════════════════════════════════════
{documents}

═════════════════════════════════════════════
MEMORIE/PARASHTRIM I KUNDËRSHTARIT
═════════════════════════════════════════════
{opponent_filing}

═════════════════════════════════════════════
NENET E KORPUSIT — NENET SHQIPTARE PËRKATËSE (teksti zyrtar)
═════════════════════════════════════════════
{articles_block}

═════════════════════════════════════════════
PRECEDENTË TË NGJASHËM (me ratio të strukturuar nga V9.2)
═════════════════════════════════════════════
{precedents_block}

═════════════════════════════════════════════

Tani shkruaj BENCH MEMO në formatin JSON:

{{
  "issue_framing": "Si do ta inkuadronte gjyqtari pyetjen kryesore (1-2 fjali, terma juridikë).",
  "applicable_law": [
    {{"reference": "Neni X i KC", "relevance": "i lartë|i mesëm|i ulët", "why": "pse ky nen është relevant"}}
  ],
  "controlling_precedents": [
    {{"citation": "Vendimi nr. X dt. Y", "court": "...", "outcome": "...", "ratio_used": "arsyetimi i transferueshëm", "weight": "i lartë|i mesëm|i ulët"}}
  ],
  "outcome_prediction": {{
    "p_plaintiff_pct": 0,
    "p_defendant_pct": 0,
    "confidence": "i lartë|i mesëm|i ulët",
    "key_factor": "Faktori që e zhvendos më shumë rezultatin",
    "court_calibration_note": "Pse kjo gjykatë specifike mund të ndryshojë rezultatin"
  }},
  "our_weaknesses": [
    {{"point": "dobësia jonë", "judge_attack": "Si do ta sulmojë gjyqtari", "severity": "i lartë|i mesëm|i ulët"}}
  ],
  "opponent_strengths": [
    {{"point": "forca e kundërshtarit", "why_judge_accepts": "Pse gjyqtari e pranon", "weight": "i lartë|i mesëm|i ulët"}}
  ],
  "argument_upgrades": [
    {{"current": "argumenti që ke", "upgrade": "si ta riformulosh", "p_shift_pct": 0}}
  ],
  "procedural_risks": [
    {{"risk": "rrezik procedural", "mitigation": "si ta shmangësh"}}
  ],
  "recommendation": "FIGHT|SETTLE|FOLD — me arsyetim të shkurtër prej 1-2 fjalish"
}}"""

BENCH_USER_TEMPLATE_IT = """\
═════════════════════════════════════════════
LA QUESTIONE DAVANTI AL GIUDICE
═════════════════════════════════════════════
{case_description}

═════════════════════════════════════════════
IL GIUDICE CHE DECIDERÀ
═════════════════════════════════════════════
{court_label}

═════════════════════════════════════════════
I DOCUMENTI DELLA NOSTRA PARTE (sintesi)
═════════════════════════════════════════════
{documents}

═════════════════════════════════════════════
MEMORIA / ATTO DELLA CONTROPARTE
═════════════════════════════════════════════
{opponent_filing}

═════════════════════════════════════════════
ARTICOLI ITALIANI PERTINENTI (testo ufficiale del corpus)
═════════════════════════════════════════════
{articles_block}

═════════════════════════════════════════════
PRECEDENTI SIMILI
═════════════════════════════════════════════
{precedents_block}

═════════════════════════════════════════════

Ora scrivi il BENCH MEMO in formato JSON:

{{
  "issue_framing": "Come il giudice inquadrerebbe la questione principale (1-2 frasi, termini giuridici).",
  "applicable_law": [
    {{"reference": "art. X c.c.", "relevance": "alto|medio|basso", "why": "perché questo articolo è rilevante"}}
  ],
  "controlling_precedents": [
    {{"citation": "Cass. civ., sez. ..., n. ...", "court": "...", "outcome": "...", "ratio_used": "il ragionamento trasferibile", "weight": "alto|medio|basso"}}
  ],
  "outcome_prediction": {{
    "p_plaintiff_pct": 0,
    "p_defendant_pct": 0,
    "confidence": "alta|media|bassa",
    "key_factor": "Il fattore che sposta di più l'esito",
    "court_calibration_note": "Perché questo giudice specifico può cambiare l'esito"
  }},
  "our_weaknesses": [
    {{"point": "la nostra debolezza", "judge_attack": "come la attaccherà il giudice", "severity": "alta|media|bassa"}}
  ],
  "opponent_strengths": [
    {{"point": "la forza della controparte", "why_judge_accepts": "perché il giudice la accoglie", "weight": "alto|medio|basso"}}
  ],
  "argument_upgrades": [
    {{"current": "l'argomento che hai", "upgrade": "come riformularlo", "p_shift_pct": 0}}
  ],
  "procedural_risks": [
    {{"risk": "rischio processuale", "mitigation": "come evitarlo"}}
  ],
  "recommendation": "FIGHT|SETTLE|FOLD — con una motivazione breve di 1-2 frasi"
}}"""

# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class BenchMemoInput:
    case_description: str
    documents_summary: str = ""
    opponent_filing: str = ""
    court_code: str = DEFAULT_COURT


# ── Public API ────────────────────────────────────────────────────────

def generate_bench_memo(
    inp: BenchMemoInput,
    *,
    backend: LLMBackend,
    article_index: ArticleIndex,
    decision_index: DecisionIndex | None = None,
    case_id: str | None = None,
    top_k_articles: int = 8,
    top_k_precedents: int = 6,
    articles=None,
    articles_block: str | None = None,
    precedents_block: str | None = None,
    precedents_used: list | None = None,
    lang: str = "sq",
) -> dict:
    """Generate the judicial bench memo (single Opus call).

    v9.647 — `articles`/`articles_block` e `precedents_block`/`precedents_used` arrivano dal recupero del CERVELLO
    (`web._memo_gjyqtari`: triage + ricerca ibrida + ancore, precedenti col passo del ragionamento); senza, il ripiego di prima
    (BM25 nudo sulla descrizione). `lang` = la lingua della sessione: prompt, giudici e precedenti italiani in sessione IT."""
    it = lang == "it"
    if articles is None:
        articles = _retrieve_articles(article_index, inp.case_description, top_k_articles)
    if precedents_block is None:
        if it:
            precedents = gather_precedents_it(inp.case_description, top_k=top_k_precedents)
        else:
            precedents = gather_precedents(inp.case_description, top_k=top_k_precedents, decision_index=decision_index)
        precedents_block = "\n\n".join(p.to_block("it" if it else "sq") for p in precedents) if precedents else ""
        precedents_used = _serialize_precedents(precedents)

    articles_block = (articles_block or _format_articles(articles)
                      or ("(nessun articolo specifico trovato)" if it else "(asnjë nen specifik nuk u gjet)"))
    precedents_block = precedents_block or ("(nessun precedente simile trovato)" if it else "(asnjë precedent i ngjashëm nuk u gjet)")

    court_label = (COURT_LABELS_IT if it else COURT_LABELS).get(inp.court_code, inp.court_code)

    prompt = (BENCH_USER_TEMPLATE_IT if it else BENCH_USER_TEMPLATE).format(
        case_description=inp.case_description.strip(),
        court_label=court_label,
        documents=(inp.documents_summary or ("(nessun documento caricato)" if it else "(s'ka dokumente të ngarkuara)"))[:6000],
        opponent_filing=(inp.opponent_filing or ("(nessuna memoria della controparte)" if it else "(s'ka memorie kundërshtari)"))[:6000],
        articles_block=articles_block[:60000],      # v9.647: il testo intero degli articoli (era 5.000 caratteri, 400 per articolo)
        precedents_block=precedents_block[:20000],
    )

    t0 = time.monotonic()
    try:
        text = backend.complete(
            system=_juris(BENCH_SYSTEM_IT if it else BENCH_SYSTEM),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4500,
            callsite="bench_memo",
            case_id=case_id,
            no_web=True,       # v9.647: gli articoli e i precedenti sono nel contesto (prima navigava: 15 minuti)
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("bench_memo: backend error")
        return {**_empty_memo(),
                "_ms": int((time.monotonic() - t0) * 1000),
                "_parse_error": f"backend: {type(exc).__name__}: {exc}",
                "precedents_used": precedents_used or []}

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    parsed = _extract_json(text)
    if parsed is None:
        log.warning("bench_memo: JSON parse failed")
        return {**_empty_memo(), "_raw": text[:2000], "_ms": elapsed_ms,
                "_parse_error": "JSON parse failed",
                "precedents_used": precedents_used or []}

    parsed["_ms"] = elapsed_ms
    parsed["precedents_used"] = precedents_used or []
    # v9.647 — `Article` non ha `id`: «AttributeError» DOPO la risposta del modello (15 minuti), il memo non arrivava MAI
    # (nella tabella dei memo: zero righe in produzione); ora codice, numero e citazione
    parsed["articles_used"] = [
        {"code": a.code, "number": str(getattr(a, "number", "")),
         "label": getattr(a, "citation", "") or getattr(a, "heading", "")} for a, _ in (articles or [])
    ]
    return parsed


# ── Helpers ───────────────────────────────────────────────────────────

def _retrieve_articles(idx: ArticleIndex, query: str, top_k: int):
    if idx is None:
        return []
    try:
        return idx.search(query, top_k=top_k)
    except Exception:  # noqa: BLE001
        log.exception("bench_memo: article retrieval failed")
        return []


def _format_articles(hits) -> str:
    """Format article hits into prompt-ready block."""
    lines = []
    for art, score in hits:
        label = (getattr(art, "label", None) or getattr(art, "heading", None)
                 or getattr(art, "id", "?"))
        body = (getattr(art, "body", "") or getattr(art, "text", "") or "")[:1500]
        lines.append(f"### {label} [{art.code}]\n{body.strip()}")
    return "\n\n".join(lines)


def _serialize_precedents(precs: list[PrecedentRef]) -> list[dict]:
    return [{
        "citation": p.citation, "court_code": p.court_code,
        "outcome": p.outcome, "objekti": p.objekti,
        "source_url": p.source_url, "bm25_score": p.bm25_score,
        "archetype": p.archetype, "has_ratio": bool(p.winning_argument),
    } for p in precs]


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _empty_memo() -> dict:
    return {
        "issue_framing": "",
        "applicable_law": [],
        "controlling_precedents": [],
        "outcome_prediction": {
            "p_plaintiff_pct": 0, "p_defendant_pct": 0,
            "confidence": "i ulët", "key_factor": "",
            "court_calibration_note": "",
        },
        "our_weaknesses": [],
        "opponent_strengths": [],
        "argument_upgrades": [],
        "procedural_risks": [],
        "recommendation": "",
    }
