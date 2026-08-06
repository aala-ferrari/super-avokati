"""V9.0 Genio Legale — Senior Partner Briefing.

Six specialised Opus perspectives run in parallel against a single case.
Each perspective reads as a senior partner's distinct *cognitive lens*:

1. RIFRAMING — what is this case really about (legal-theory re-framing)
2. KILL_SHOT — how would the opposing counsel destroy us tomorrow
3. LEVERAGE — pressure points the lawyer hasn't seen
4. DECISION_TREE — game-tree 3 moves deep, probability-weighted
5. BRUTAL_TRUTH — honest financial + relationship reality
6. VOICE — opening paragraphs of the next filing in the lawyer's style

Design notes
────────────
- Each perspective is an independent prompt + JSON schema. One failing
  perspective never aborts the others (try/except per future).
- ThreadPoolExecutor(max_workers=6) fires all six. The Claude Code
  semaphore (3) naturally serialises into 2 batches.
- The orchestrator yields events progressively (`started`, `perspective`,
  `error`, `completed`) so the SSE endpoint can stream a live "senior
  partner thinking" UI to the browser.
- Voice mimicry: pulls up to 3 of the lawyer's prior `drafted_acts`
  (truncated) and injects them as a style anchor. Falls back to neutral
  professional Albanian if the lawyer has none.
- Citation Shield (V8.11) integrates downstream — each perspective's
  `citations` array is annotated when present. We do not gate refusal at
  the perspective level; Genio outputs *strategic* analysis, not formal
  legal opinion.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from queue import Empty, Queue

# ── Jurisdiction guard — prepended to every perspective system prompt ──
# Kept in a single place so a doctrine-boundary fix propagates to all 6
# lenses in one edit. Romeo's feedback (2026-04-27): the model was
# importing italo-francez riserva/réserve doctrine into Albanian cases —
# a serious error for a lawyer. KC shqiptar has broader testamentary
# freedom than IT/FR; foreign analogies must not become argumentation.
GENIO_JURISDICTION_GUARD = (
    "STANDARDI I ARSYETIMIT — je avokati MË I MIRË senior në Shqipëri: rigoroz, i mprehtë dhe dhelpërak. Mendo THELLË para se të përgjigjesh; parashiko ÇDO lëvizje të kundërshtarit; gjej levat e fshehura, kurthet procedurale dhe pikat e dobëta; mos lër ASNJË dobësi në mbrojtje. Çdo pohim mbështetet me nen konkret ose precedent real — asnjë hamendje, asnjë sipërfaqësi. Perfeksion strategjik, jo thjesht përgjigje.\n\n"
    "KUFI JURIDIKSIONAL — KRITIK. Ti aplikon VETËM të drejtën shqiptare. "
    "Mos importo doktrina italiane/franceze (riserva, legittima, "
    "réserve héréditaire, quotité disponible, successione necessaria) "
    "as analogji nga Kodi Civil italian/francez. Kodi Civil shqiptar "
    "lejon liri testamentare dukshëm më të gjerë: mos transplantos "
    "kuota fikse 50%/66%/75% të rezervës italo-franceze sikur të ishin "
    "parim universal. Bazohu vetëm te nenet e Kodit SHQIPTAR të dhëna "
    "në kontekst. Nëse të lind ngjasimi me institut italian/francez, "
    "NDALO — verifiko a është vërtet në nenin shqiptar që ke. Nëse "
    "jo, mos e shkruaj. Krahasimi me të drejtën e huaj lejohet vetëm "
    "kur shënohet shprehimisht si krahasim, jo si bazë vendimi.\n\n"
    "VEGLA WEB — DETYRUESHME për avokat të zgjuar. Ke akses në kërkim web "
    "(WebSearch/WebFetch). PËRDORE gjithmonë para se të mbyllësh analizën: "
    "(1) VERIFIKO nëse ligji ka NDRYSHUAR së fundmi — p.sh. ndryshimet e "
    "Kodit Rrugor 2024-2026: heqja e PËRHERSHME e lejes për kapje DY herë "
    "radhazi me alkool mbi 0.5 g/l, alkool zero për shoferët e rinj 2 vjet; "
    "(2) GJEJ precedentë / vendime PUBLIKE të gjykatave shqiptare që "
    "mbështesin ose rrezikojnë tezën; (3) lajme juridike relevante. "
    "Ji dhelpërak: gjej gjilpërën në kashtë. Bëj SA kërkime web të duhen për saktësi MAKSIMALE — mos kurse kohën. Saktësia vjen GJITHMONË para shpejtësisë: më mirë të vonohesh dhe ta gjesh të saktën, sesa shpejt e gabim. Cito GJITHMONË burimin "
    "(URL + datë). Mos u mbështet vetëm te nenet e ngarkuara — ligji mund "
    "të jetë përditësuar pas tyre.\n\n"
    "SHIFRA KONKRETE — kur pyetja prek taksa, dogana, akcizë, tarifa, gjoba apo çmime: "
    "mos u mjafto me 'kontrollo në faqe'. KËRKO shifrën zyrtare aktuale (dogana.gov.al, "
    "tatime.gov.al, qbz.gov.al, financa.gov.al), jep strukturën me numra dhe një vlerësim "
    "konkret në euro/lekë, cito URL+datë. Saktësia para shpejtësisë: më mirë vono sesa jep numër "
    "të gabuar; por mos shpik kurrë — nëse nuk e gjen, ndaj qartë 'e sigurt' nga 'duhet verifikuar te VKM'.\n\n"
)


# ── Perspective definitions ────────────────────────────────────────────

@dataclass
class Perspective:
    key: str
    label_sq: str
    label_it: str
    system: str
    user_template: str
    max_tokens: int = 2800


PERSPECTIVES: list[Perspective] = [

    Perspective(
        key="riframing",
        label_sq="Riformulim juridik",
        label_it="Riformulazione giuridica",
        system=(
            "Ti je partner senior i një studio ligjore me 25 vjet "
            "eksperiencë. Talenti yt më i madh: të shohësh natyrën E "
            "VËRTETË juridike të një çështjeje kur avokati i ri sheh "
            "vetëm sipërfaqen. Identifikon riformulime jo-të-dukshme: "
            "një kontratë e bëhet konkurrencë e pandershme, një tort "
            "bëhet pasurim i padrejtë, një çështje civile bëhet abuz "
            "i pozitës dominuese. Mendon në cilësinë e formulimit "
            "juridik, jo në sasi argumentimi. Mos sajo nene; nëse nuk "
            "je i sigurt për një referim, shkruaj 'art. N (verifiko)'."
        ),
        user_template=(
            "{case_block}\n\n"
            "Identifiko deri në 3 RIFORMULIME alternative të kësaj "
            "çështjeje, të renditura sipas viability. Për secilin: "
            "(a) emri i tezës juridike, (b) baza ligjore (KC/KPC/Kushtetuta), "
            "(c) pse është më e fortë ose më e dobët se formulimi aktual, "
            "(d) provat e nevojshme që mungojnë.\n\n"
            "Kthe vetëm JSON të pastër, pa preambël, me skemën:\n"
            "{{\n"
            '  "current_framing": "fjalia që përshkruan formulimin aktual",\n'
            '  "alternatives": [\n'
            "    {{\n"
            '      "name": "string",\n'
            '      "rank": 1|2|3,\n'
            '      "thesis": "1-2 fjali",\n'
            '      "legal_basis": ["art. X KC", ...],\n'
            '      "strength_vs_current": "string",\n'
            '      "missing_evidence": ["string", ...],\n'
            '      "risk_if_chosen": "1 fjali"\n'
            "    }}\n"
            "  ],\n"
            '  "verdict": "rekomanim final për avokatin (≤ 3 fjali)"\n'
            "}}"
        ),
    ),

    Perspective(
        key="kill_shot",
        label_sq="Goditja vdekjeprurëse",
        label_it="Kill-shot avversario",
        system=(
            "Ti je avokati i kundërshtarit. Spiteous. Ke lexuar të gjithë "
            "fashikullin dhe duhet ta SHKATËRROSH këtë padi nesër në "
            "mëngjes. Kërkon: kontradikta brenda parashtrimeve, kavile "
            "procedurale (afate, juridiksion, kompetencë, akte nule), "
            "dobësi probatore, pretendime të paprovuara, ekspozim "
            "fiskal, palë të treta që nuk janë thirrur. Pa dhembshuri."
        ),
        user_template=(
            "{case_block}\n\n"
            "Mendo si avokati i kundërshtarit. Identifiko 3 GODITJE "
            "më letale me të cilat do ta shkatërroje këtë çështje. "
            "Renditi nga më letale tek më e ulët. Për secilën: "
            "(a) lloji (procedural / substancial / probator), "
            "(b) mekanika konkrete (cili akt, cili neni, cili afat), "
            "(c) kontrasulmin që duhet të përgatisë avokati ynë "
            "PARA se të zbresë në sallë.\n\n"
            "JSON i pastër:\n"
            "{{\n"
            '  "kill_shots": [\n'
            "    {{\n"
            '      "rank": 1,\n'
            '      "kind": "procedural|substantial|evidentiary",\n'
            '      "title": "string",\n'
            '      "mechanics": "2-3 fjali",\n'
            '      "legal_anchor": ["art. X KPC", ...],\n'
            '      "lethality": 1-10,\n'
            '      "our_counter_prep": "2-3 fjali"\n'
            "    }}\n"
            "  ],\n"
            '  "fatal_combo_warning": "nëse 2+ goditje aplikohen së bashku → ç\'ndodh"\n'
            "}}"
        ),
    ),

    Perspective(
        key="leverage",
        label_sq="Levat e fshehura",
        label_it="Leverage nascosta",
        system=(
            "Ti je këshilltar strategjik për avokat — sheh leva pression "
            "që juristët teknikë i injorojnë: timing (kur ngacmon, kur "
            "rri), ekspozimi reputacional, ekspozimi tatimor, kosto "
            "procesi për palën tjetër, palë të treta që mund të aktivohen "
            "(kreditorë, autoriteti tatimor, vlerësues, konkurrentë), "
            "pikat ku interesi personal i kundërshtarit kontradikton "
            "interesin e tij ligjor."
        ),
        user_template=(
            "{case_block}\n\n"
            "Identifiko deri në 3 LEVA PRESSION që avokati nuk i ka "
            "konsideruar. Për secilën: (a) leva, (b) pse funksionon "
            "PIKËRISHT te kjo palë, (c) si aktivohet konkretisht "
            "(letër, ankim, segnalim te autoritet, kontakt me palë të "
            "tretë), (d) rreziku i backfire (etik, ligjor, taktik).\n\n"
            "Kthe JSON:\n"
            "{{\n"
            '  "leverage_points": [\n'
            "    {{\n"
            '      "rank": 1,\n'
            '      "lever": "emër i shkurtër",\n'
            '      "why_it_works": "2-3 fjali specifike për këtë palë",\n'
            '      "activation": "veprim konkret",\n'
            '      "ethical_risk": "low|medium|high",\n'
            '      "backfire_risk": "1-2 fjali",\n'
            '      "legal_basis": ["art. ose ligj", ...]\n'
            "    }}\n"
            "  ],\n"
            '  "do_not_use": "leva që duken tërheqëse por janë trap (1-2 fjali)"\n'
            "}}"
        ),
    ),

    Perspective(
        key="decision_tree",
        label_sq="Pemë vendimore (3 lëvizje)",
        label_it="Albero decisionale (3 mosse)",
        system=(
            "Ti je teorist i lojës i aplikuar në litigation. Mendon në "
            "pemë vendimore probabilistike. Çdo nyje ka mosse-ynë + "
            "përgjigje-të-mundshme me probabilitete (që mblidhen në "
            "1.0) + vlerë e pritur në EUR. Vlerësimet duhet të jenë "
            "realiste, jo fantastike."
        ),
        user_template=(
            "{case_block}\n\n"
            "Ndërto pemën vendimore për këtë çështje, 3 lëvizje thellë.\n\n"
            "Kthe JSON për UI vizualizim:\n"
            "{{\n"
            '  "root_label": "gjendja aktuale (≤ 8 fjalë)",\n'
            '  "branches": [\n'
            "    {{\n"
            '      "our_move": "lëvizja jonë (≤ 12 fjalë)",\n'
            '      "rationale": "1 fjali",\n'
            '      "their_responses": [\n'
            "        {{\n"
            '          "label": "përgjigja e tyre (≤ 10 fjalë)",\n'
            '          "probability": 0.0-1.0,\n'
            '          "our_counter": "kontra-mossa jonë (≤ 12 fjalë)",\n'
            '          "expected_value_eur": number,\n'
            '          "duration_months": number\n'
            "        }}\n"
            "      ]\n"
            "    }}\n"
            "  ],\n"
            '  "recommended_path": "rrugë e rekomanduar 3-step (1 fjali)",\n'
            '  "expected_value_total_eur": number,\n'
            '  "dominant_strategy_note": "pse kjo rrugë dominonë alternativat"\n'
            "}}\n\n"
            "Kufiri: 2-4 branches root, secila 2-3 their_responses. "
            "Probabilitetet e their_responses brenda secilës branch duhet "
            "të mblidhen ≈ 1.0."
        ),
        max_tokens=3500,
    ),

    Perspective(
        key="brutal_truth",
        label_sq="E vërteta e ashpër",
        label_it="Verità brutale",
        system=(
            "Ti je avokati që u thotë klientëve të vërtetën edhe kur ata "
            "nuk duan ta dëgjojnë. Onest mbi vlerën reale të çështjes, "
            "kostot e plota (avokati + gjyqësore + kohë + emocionale), "
            "gap-in mes pritshmërive të klientit dhe realitetit, "
            "probabilitetin e fitores, dhe ç\'duhet komunikuar TANI me "
            "klientin përpara se marrëdhënia të prishet. Pa zbutje."
        ),
        user_template=(
            "{case_block}\n\n"
            "Vlerëso pa rrethanim. JSON:\n"
            "{{\n"
            '  "real_value_eur": {{"low": number, "likely": number, "high": number}},\n'
            '  "client_probable_expectation_eur": number,\n'
            '  "expectation_gap_severity": "low|medium|high|critical",\n'
            '  "win_probability": 0.0-1.0,\n'
            '  "total_cost_estimate_eur": {{"legal_fees": number, "court_fees": number, "time_value": number, "emotional_cost_label": "low|medium|high"}},\n'
            '  "duration_months_realistic": number,\n'
            '  "honest_recommendation": "continue|settle_now|withdraw|refer_to_specialist",\n'
            '  "what_to_tell_client_today": "fjalia ekzakte (≤ 3 fjali) që duhet thënë në takimin e parë me klientin",\n'
            '  "red_flags_for_lawyer": ["rrezik specifik për avokatin (mandat, fatura, reputacion)", ...]\n'
            "}}"
        ),
    ),

    Perspective(
        key="voice",
        label_sq="Zëri i avokatit",
        label_it="La voce dell'avvocato",
        system=(
            "Ti je MIMIK i stilit të një avokati specifik. Ke lexuar "
            "akte të mëparshme të tij/saj dhe shkruan paragrafë të rinj "
            "që janë të padallueshëm nga origjinalet. Imiton: zgjedhjen "
            "e fjalëve, gjatësinë e fjalive, formalitetin, përdorimin "
            "e citimeve, ritmin retorik. Nëse mostrat e stilit "
            "mungojnë, përdor stil profesional shqiptar neutral "
            "(formal, i kthjellët, jo emfatik)."
        ),
        user_template=(
            "{voice_samples_block}\n\n"
            "{case_block}\n\n"
            "Shkruaj 3 paragrafët HAPËS të aktit të ardhshëm "
            "(kërkesë-padi, ankim ose memorie, sipas kontekstit) për "
            "këtë çështje. Pa preambël, vetëm tekst i gatshëm për t\'u "
            "ngjitur në dokument. Përdor stilin e mostrave të mësipërme.\n\n"
            "Pas paragrafëve, shto rresht me '---' dhe një shënim të "
            "shkurtër '(stil i imituar nga: ...)' që rrëfen cilat tipare "
            "stilistike imitove (formaliteti, gjatësia e fjalive, etj.)."
        ),
        max_tokens=2200,
    ),
]


# ── Output parsing ─────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Find the first complete JSON object in `text`. Best-effort."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no_json_object")
    blob = re.sub(r",(\s*[}\]])", r"\1", m.group(0))  # tolerate trailing commas
    return json.loads(blob)


# ── Voice samples gathering ────────────────────────────────────────────

def _gather_voice_samples(user_id: int, *, max_samples: int = 3,
                          chars_per_sample: int = 1500) -> str:
    """Pull up to N prior drafted_acts from the lawyer to anchor style.

    Returns a Markdown block ready to inject into the voice perspective
    prompt, or a neutral-style notice if the lawyer has no prior acts.
    """
    from . import storage
    rows: list[tuple[str, str]] = []
    try:
        with storage.db() as conn:
            for r in conn.execute(
                "SELECT act_type, draft_text FROM drafted_acts "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, max_samples * 2),  # over-pull, filter empty
            ).fetchall():
                txt = (r["draft_text"] or "").strip()
                if len(txt) < 200:
                    continue
                rows.append((r["act_type"], txt[:chars_per_sample]))
                if len(rows) >= max_samples:
                    break
    except Exception:
        pass
    if not rows:
        return ("MOSTRA STILI: avokati nuk ka akte të mëparshme në "
                "sistem. Përdor stil profesional shqiptar neutral, "
                "formal, të kthjellët. Mos shto thirrje retorike, mos "
                "përdor mbiemra teprues.")
    parts = ["MOSTRA STILI nga akte të mëparshme të AVOKATIT (imiton "
             "leximin e tyre):"]
    for i, (kind, txt) in enumerate(rows, 1):
        parts.append(f"\n--- Mostra {i} ({kind}) ---\n{txt}")
    return "\n".join(parts)


# ── Single perspective execution ──────────────────────────────────────

def run_perspective(p: Perspective, *,
                    backend, case_block: str,
                    voice_samples_block: str = "",
                    case_id: str | None = None) -> dict:
    """Execute one perspective. Returns: {
        "key": str, "label_sq": str, "label_it": str,
        "raw": str (full text response),
        "parsed": dict | None (JSON if extractable, else None),
        "kind": "json" | "text",
        "ms": int, "error": str | None
    }
    """
    user_prompt = p.user_template.format(
        case_block=case_block,
        voice_samples_block=voice_samples_block,
    )
    t0 = time.monotonic()
    err: str | None = None
    text = ""
    try:
        text = backend.complete(
            system=GENIO_JURISDICTION_GUARD + p.system,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=p.max_tokens,
            callsite=f"genio:{p.key}",
            case_id=case_id,
        )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if err:
        return {"key": p.key, "label_sq": p.label_sq, "label_it": p.label_it,
                "raw": "", "parsed": None, "kind": "error",
                "ms": elapsed_ms, "error": err}
    # Voice perspective is plain text, not JSON
    if p.key == "voice":
        return {"key": p.key, "label_sq": p.label_sq, "label_it": p.label_it,
                "raw": text, "parsed": None, "kind": "text",
                "ms": elapsed_ms, "error": None}
    parsed: dict | None = None
    parse_err: str | None = None
    try:
        parsed = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        parse_err = f"{type(e).__name__}: {e}"
    return {"key": p.key, "label_sq": p.label_sq, "label_it": p.label_it,
            "raw": text, "parsed": parsed,
            "kind": "json" if parsed is not None else "text",
            "ms": elapsed_ms,
            "error": parse_err}


# ── Orchestrator (parallel + streaming events) ─────────────────────────

def run_brief(*, backend, case_block: str, voice_samples_block: str,
              case_id: str | None = None,
              perspectives: list[Perspective] | None = None,
              ) -> Iterator[dict]:
    """Run all 6 perspectives in parallel; yield events as they complete.

    Events:
      - {"type":"started", "perspectives":[keys]}
      - {"type":"perspective", "result": {...one perspective output...}}
      - {"type":"completed", "elapsed_ms": int, "by_key": {key: result}}
    """
    plist = perspectives or PERSPECTIVES
    yield {"type": "started",
           "perspectives": [{"key": p.key,
                             "label_sq": p.label_sq,
                             "label_it": p.label_it} for p in plist]}
    t_start = time.monotonic()
    by_key: dict[str, dict] = {}
    # use a queue to avoid blocking on as_completed (executor + iter)
    q: Queue = Queue()
    def _runner(p: Perspective):
        res = run_perspective(p, backend=backend,
                              case_block=case_block,
                              voice_samples_block=voice_samples_block,
                              case_id=case_id)
        q.put(res)
    threads: list[threading.Thread] = []
    for p in plist:
        t = threading.Thread(target=_runner, args=(p,), daemon=True)
        t.start()
        threads.append(t)
    for _ in plist:
        # block until one finishes; safety timeout per slot ≤ 10 min
        try:
            res = q.get(timeout=1860)
        except Empty:
            res = {"key": "?", "kind": "error",
                   "error": "timeout_overall", "ms": 0,
                   "raw": "", "parsed": None}
        by_key[res["key"]] = res
        yield {"type": "perspective", "result": res}
    for t in threads:
        t.join(timeout=5)
    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    yield {"type": "completed", "elapsed_ms": elapsed_ms, "by_key": by_key}


# ── Convenience: build the case_block from db state ────────────────────

def build_case_block(case, *, jurisdiction: str = "AL",
                     extra_description: str = "",
                     recent_messages: list[dict] | None = None,
                     documents: list[dict] | None = None) -> str:
    """Compose the human-readable case context block for prompts."""
    parts: list[str] = []
    parts.append(f"ÇËSHTJA: {case.title}")
    parts.append(f"Juridiksioni: {jurisdiction}")
    parts.append(f"Faza: {getattr(case, 'stage', 'intake')}")
    if extra_description:
        parts.append("\nPËRSHKRIM (nga avokati):\n" + extra_description.strip())
    if documents:
        parts.append("\nDOKUMENTET KYÇE:")
        for d in documents[:8]:
            parts.append(
                f"- [{d.get('doc_type') or '?'}] {d.get('filename')} — "
                f"{(d.get('summary') or '')[:200]}"
            )
    if recent_messages:
        parts.append("\nFJALOSJA E FUNDIT (avokati ↔ Super Avvocato):")
        for m in recent_messages[-6:]:
            role = "Avokati" if m.get("role") == "user" else "AI"
            content = (m.get("content") or "")[:400]
            parts.append(f"\n{role}: {content}")
    return "\n".join(parts)
