"""The Super Avvocato's legal brain — strategic reasoning over Albanian law.

Pipeline for a citizen's question (4 stages):

    1. TRIAGE (fast model)
       - rewrite the problem in neutral Albanian legal terms;
       - expand into 3–5 keyword variants for BM25;
       - identify strategic angles (deadlines, exceptions, cross-code links);
       - decide whether we can answer now or need a follow-up question.

    2. RETRIEVAL (local BM25)
       - union the top-k hits of every expansion;
       - auto-include the matching PROCEDURAL code (the hidden half of every
         case: substantive law says WHAT, procedural law says HOW and WHEN).

    3. STRATEGIC ANALYSIS (fast model) — the winning-edge layer
       - read the case + retrieved articles;
       - hunt for non-obvious details that decide real cases: hidden deadlines,
         exceptions, nullity grounds, burden-of-proof shifts, mitigating/
         aggravating circumstances, special protective regimes;
       - emit concise "critical_details" + "risk_warnings".

    4. ANSWER (main model)
       - write a 5-section answer in Albanian citing exact `Neni X` references;
       - weave the strategic insights into section 5 — the winning edge.

The brain is stateless; callers persist the conversation history they pass in.
"""
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .backends import LLMBackend, build_backend
from .config import LEGAL_DOCUMENTS, TOP_K_ARTICLES, TOP_K_DECISIONS
from .documents import format_documents_for_prompt
from .logging_utils import get_logger
from .parser import Article
from .retrieval import ArticleIndex
from .retrieval_kb import CasePrecedent, LegalKBRetriever

log = get_logger(__name__)

# ── procedural-code safety net ─────────────────────────────────────────────
# Every substantive legal area has a procedural counterpart that dictates
# deadlines, forum, evidence rules, and how the right is actually enforced.
# A citizen asking "my boss hasn't paid me" needs labor code (substance) AND
# civil procedure code (how to sue, within how long, with what evidence).
# This mapping forces retrieval to always include the matching procedural
# code — even if the triage model forgot — because that's where the
# case-winning deadline usually hides.
PROCEDURAL_MAPPING: dict[str, tuple[str, ...]] = {
    "Penal":         ("kodi_proc_penale",),
    "Civil":         ("kodi_proc_civile",),
    "Familje":       ("kodi_proc_civile",),   # family suits are tried in civil courts
    "Punë":          ("kodi_proc_civile",),   # labor disputes go to civil courts
    "Administrativ": ("kodi_proc_admin",),
    "Doganor":       ("kodi_proc_admin",),
    "Rrugor":        ("kodi_proc_admin",),
    "Zgjedhor":      ("kodi_proc_admin",),
    # Kushtetues, Detar, Ajror: no direct procedural mapping.
}


# ── prompts ────────────────────────────────────────────────────────────────

CODES_INDEX = "\n".join(
    f"  - {d.code}: {d.title_sq} ({d.area})" for d in LEGAL_DOCUMENTS
)

TRIAGE_SYSTEM = f"""Ti je asistent i një avokati strateg që ndihmon qytetarë shqiptarë me pyetje ligjore.
Detyra jote është VETËM triazhi: përgatit kërkesën, nuk përgjigjesh ligjërisht.

Kodet në dispozicion (13 gjithsej + Kushtetuta):
{CODES_INDEX}

RREGULL KRITIK për 'areas': kur rasti prek një kod material, përfshi GJITHMONË edhe kodin përkatës procedural:
  - Penal → përfshi edhe "Penal" për Kodin e Procedurës Penale (që është në të njëjtën zonë)
  - Civil, Familje, Punë → përfshi "Civil" (Kodi i Procedurës Civile mbulon edhe familjen e punën)
  - Doganor, Rrugor, Administrativ, Zgjedhor → përfshi "Administrativ"
Kjo sepse avokatët fitojnë kauzat te rregullat procedurale (afate, mjete ankimi, barra e provës), jo vetëm te ligji material.

Përgjigju vetëm me një objekt JSON me këtë strukturë EKZAKTE:
{{
  "problem_summary": "përshkrim i shkurtër neutral i problemit në shqip (1-2 fjali)",
  "areas": ["lista e 'area' që duhen kërkuar, p.sh. ['Familje', 'Civil'] — jo emrat e kodeve"],
  "search_queries": ["3-6 kërkime të shkurtra me terma të specializuar ligjorë; përfshi të paktën NJË kërkim për afatet/parashkrimin dhe NJË për përjashtimet nëse aplikohet"],
  "strategic_angles": ["2-4 kënde strategjike për t'u hulumtuar në nene, p.sh.: 'afatet e parashkrimit', 'përjashtimet për viktimat e dhunës', 'barra e provës te punëdhënësi', 'shkaqe pavlefshmërie të aktit administrativ'"],
  "needs_followup": false,
  "followup_question": "nëse needs_followup=true, një pyetje e vetme dhe konkrete në shqip për të qartësuar faktet"
}}

Vendos needs_followup=true VETËM kur mungojnë fakte kritike (p.sh. data e saktë e ngjarjes, a ka dëshmitarë, vlera e dëmit, a ka pasur akt njoftimi). Në shumicën e rasteve përpiqu të përgjigjesh pa pyetje të tjera — qytetarët shpesh janë në vështirësi dhe nuk duhen ngarkuar."""


STRATEGIC_SYSTEM = """Ti je avokat strateg shqiptar me përvojë në sallat e gjyqit — pjesa e avokatit që FITON kauzat.
Detyra jote: nga rasti i qytetarit dhe nenet e dhëna, identifiko detajet VENDIMTARE që shumica e avokatëve i humbasin.
Pa këto detaje, një rast i sigurt humbet. Me këto detaje, një rast i humbur fitohet.

KONTROLLO çdo nen të dhënë për këto tetë kënde strategjike:

1. AFATE TË FSHEHURA — parashkrim, ankim, padi, njoftim, protestë.
   • Sa ditë/muaj/vite?
   • Nga kur fillon të numërojë? (nga dita e ngjarjes? nga njoftimi? nga dija?)
   • Çfarë e ndërpret ose e pezullon afatin?
   • Kush i duhet respektuar nga qytetari vs. nga pala tjetër?

2. PËRJASHTIME DHE KUSHTE — kërko fjalë kyçe: "përveçse", "me përjashtim", "kur", "nëse",
   "me kusht që", "vetëm", "në rastin kur". Këto klauzola janë shpesh armë të fshehta.

3. SHKAQE PAVLEFSHMËRIE — a ka detaje formale/procedurale që mund ta bëjnë veprimin
   e kundërshtar TË PAVLEFSHËM? (mungesa e njoftimit, formë e shkruar e detyruar,
   organ jokompetent, etj.)

4. BARRA E PROVËS — kush duhet të provojë çfarë?
   Në raste të punës, dhunës në familje, diskriminimit, konsumatorit, ligji e zhvendos
   shpesh barrën mbi palën e fortë (punëdhënësi, kompania). Kjo ndryshon gjithçka.

5. RRETHANA RËNDUESE / LEHTËSUESE (raste penale) — këto mund të ulin dënimin
   me vite ose ta mbyllin çështjen pa dënim (p.sh. Neni 48-51 Kodi Penal).

6. LIDHJE CROSS-CODE — a ka nen tjetër nga kod tjetër (sidomos procedural) që
   aplikohet në të njëjtin fakt dhe ndryshon rezultatin?

7. REGJIME SPECIALE MBROJTËSE — viktimë dhune në familje, i/e mitur, gjetur shtatzënë,
   punëtor, konsumator, person me aftësi të kufizuara — këta kanë mbrojtje shtesë
   që mposht rregullin e përgjithshëm.

8. DRITARE LIGJORE TË NGUSHTA — nuancë interpretimi, fjalë e vetme ("mund" vs "duhet"),
   strukturë gjuhësore që, e lexuar mirë, e kthen rastin.

FORMATI i përgjigjes — VETËM JSON, asgjë tjetër:
{
  "critical_details": [
    {
      "title": "titull i shkurtër tërheqës në shqip (5-8 fjalë)",
      "detail": "shpjegimi në 1-3 fjali në shqip. CITO nenin e saktë (p.sh. 'Neni 115/a i Kodit të Punës'). Bëj të qartë çfarë duhet bërë dhe kur."
    }
  ],
  "risk_warnings": [
    "paralajmërime të shkurtra për gabime tipike që e humbasin kauzën në këtë lloj rasti — fjali të plota në shqip"
  ]
}

RREGULLA STRIKTE:
• MAKSIMUM 5 detaje kritike dhe 3 paralajmërime.
• CILËSIA mbi sasinë — vetëm gjëra që VËRTET bëjnë diferencën në gjyq.
• Baza vetëm mbi nenet e dhëna. MOS shpik numra nenesh.
• Nëse nga nenet e dhëna nuk del asnjë detaj strategjik i veçantë, kthej liste bosh:
  {"critical_details": [], "risk_warnings": []}
• E gjithë përgjigjja NË SHQIP."""


ANSWER_SYSTEM = """Ti je Super Avokati — avokat virtual falas për qytetarët shqiptarë që nuk mund të përballojnë tarifat.
Je i ngrohtë, i qartë dhe flet gjuhën e njerëzve të thjeshtë, jo zhargon ligjor.
Por nën sipërfaqen e butë, je një avokat strateg që NUK harron asnjë detaj vendimtar.

KRITIKE: E gjithë përgjigjja jote duhet të jetë NË SHQIP.

FORMATI i përgjigjes (PESË seksione FIKSE, me këto kokëfaqe, në këtë rend):

## 1. 📜 Çfarë thotë ligji
[Shpjego ligjin në fjalë të thjeshta, duke cituar EKZAKT numrin e nenit dhe emrin e kodit.
Format: "Neni X i Kodit Y thotë që..."]

## 2. ⚖️ Të drejtat e tua
[Listo konkretisht çfarë ke të drejtë, me pika të qarta.]

## 3. 🛠️ Çfarë duhet të bësh
[Hapat praktikë: kujt t'i drejtohesh, çfarë dokumentesh të përgatisësh, si të bësh ankesë/padi,
cilat prova të mbledhësh. Numëroji hapat 1, 2, 3 kur ka sens.]

## 4. ⏰ Afatet ligjore
[Afate kritike — parashkrimi, afati i ankimit, afati i padisë. Bëj të qartë KUR fillon të numërojë afati dhe çfarë e ndërpret. Nëse afati rrezikon të kalojë, thuaje me URGJENCË.]

## 5. 🎯 Detajet që bëjnë diferencën
[KËTU është ajo që e dallon një përgjigje të zakonshme nga një avokat i vërtetë.
Këtu vendos sekretet strategjike — gjërat që shumica i humbasin:
 • Përjashtime dhe kushte specifike që mund t'i përdorësh në favorin tënd
 • Barra e provës — kush duhet të provojë çfarë (shpesh nuk është qytetari!)
 • Mundësi pavlefshmërie procedurale
 • Rrethana lehtësuese (për raste penale)
 • Regjime speciale mbrojtëse që aplikohen për rastin tënd
 • Nuanca ligjore që e kthejnë kauzën
Përdor ANALIZËN STRATEGJIKE që do të të jepet më poshtë — integroja me empati,
duke shpjeguar PSE secili detaj është i rëndësishëm për këtë qytetar konkret.
Nëse analiza strategjike është bosh, shkruaj në këtë seksion një paragraf të shkurtër
me këshillën më të rëndësishme që e ke gjetur vetë nga nenet.]

---
💙 *Ky është informacion ligjor falas. Për raste të rënda ose në gjykatë, gjithmonë konsulto një avokat të licencuar.*

RREGULLA:
- Bazo GJITHMONË përgjigjen vetëm mbi nenet e dhëna si kontekst.
- Kur cituar një nen, përdor formatin: "Neni 130 i Kodit Penal" ose "neni 50 i Kodit të Familjes".
- Nëse nenet e dhëna NUK e mbulojnë problemin, thuaje hapur: "Nga nenet që kam në dispozicion nuk gjej mbulim të drejtpërdrejtë për këtë rast. Rekomandoj..." dhe drejto te një avokat ose te ndihma juridike falas.
- Mos shpik numra nenesh. Nëse nuk je i sigurt, mos citoni.
- Ji empatik — njerëzit që pyesin shpesh janë në situata të vështira, ndonjëherë kritike.
- Seksioni 5 nuk duhet të jetë kurrë bosh — gjithmonë thuaji diçka strategjikisht të vlefshme.

CITIM I VENDIMEVE (PRECEDENT):
Kur seksioni "VENDIME RELEVANTE TË GJYKATAVE" të paraqitet më poshtë, ato janë precedent të vërtetë të indeksuar te baza jonë e të dhënave. Çdo vendim ka një shënues në formën `[[case:ID]]` (p.sh. `[[case:347]]`).
- Kur referon një vendim në përgjigje, VENDOSE menjëherë shënuesin `[[case:ID]]` pas emrit të vendimit, p.sh.: "Gjykata e Lartë, vendim nr. 123/2024 [[case:347]] ka vendosur që...".
- Shënuesi shndërrohet automatikisht në një link që e çon qytetarin te fashikulli i plotë — kështu që MOS e shkruaj si URL dhe MOS e ndrysho formatin (saktësisht `[[case:NUMER]]`).
- Cito vetëm ID-të që të janë dhënë më poshtë. Mos shpik ID-të.
- Përdori precedentët për të përforcuar argumentin te seksioni 1 (ligji), seksioni 4 (afatet, nëse vendimi qartëson një afat) ose seksioni 5 (strategjia)."""


# ── data types ─────────────────────────────────────────────────────────────


@dataclass
class TriageResult:
    problem_summary: str
    areas: list[str]
    search_queries: list[str]
    strategic_angles: list[str] = field(default_factory=list)
    needs_followup: bool = False
    followup_question: str = ""


@dataclass
class StrategicInsight:
    title: str
    detail: str


@dataclass
class StrategicAnalysis:
    critical_details: list[StrategicInsight] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.critical_details and not self.risk_warnings


@dataclass
class LegalAnswer:
    kind: Literal["answer", "followup"]
    text: str                                  # the Albanian response shown to the user
    triage: TriageResult | None = None
    retrieved: list[tuple[Article, float]] = field(default_factory=list)
    # Court decisions (precedents) retrieved for this case — adds persuasive
    # weight to the answer ("the Gjykata e Lartë has already ruled X").
    # Backed by the V4 Postgres KB: each CasePrecedent carries outcome,
    # judges, articles cited, and a DB id so the answer can cite pin-to-row.
    precedents: list[tuple[CasePrecedent, float]] = field(default_factory=list)
    strategic: StrategicAnalysis | None = None
    # Claude Code session id — set by ClaudeCodeBackend after a compose call.
    # Callers (web.py, bot.py) should persist this per-citizen to maintain
    # native conversation context via `--resume`.
    session_id: str | None = None


# ── the brain ──────────────────────────────────────────────────────────────


class SuperAvvocato:
    def __init__(
        self,
        index: ArticleIndex | None = None,
        kb: LegalKBRetriever | None = None,
        backend: LLMBackend | None = None,
    ):
        self.backend = backend or build_backend()
        self.index = index or ArticleIndex.load()
        # Legal KB (Postgres) is optional — if the DB is unreachable the
        # brain still works on articles alone. We don't want an outage of
        # the precedent store to take down the citizen-facing answer flow.
        if kb is not None:
            self.kb = kb
        else:
            try:
                self.kb = LegalKBRetriever.load()
            except Exception as exc:  # noqa: BLE001
                log.warning("legalkb unavailable (%s) — running without precedents", exc)
                self.kb = LegalKBRetriever([], None)  # type: ignore[arg-type]
        log.info(
            "SuperAvvocato ready — backend=%s, %d articles, %d precedents",
            self.backend.name,
            len(self.index.articles),
            len(self.kb.cases),
        )

    # ── public entrypoint ──────────────────────────────────────────────────

    def answer(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        session_id: str | None = None,
        documents: list[dict] | None = None,
    ) -> LegalAnswer:
        """Process one user message and return either a follow-up or a full answer.

        `session_id`, when provided, is passed to the compose stage so the
        backend (Claude Code) can use `--resume` for native conversation
        continuity. The returned LegalAnswer carries the updated session_id.

        `documents`, when provided, is the case's dossier — a list of dicts
        with keys `filename`, `doc_type`, `summary`, `key_facts`,
        `extracted_text`. The brain folds this into BOTH the triage prompt
        (so retrieval queries account for the real facts of the case) and
        the answer prompt (so the final reasoning cites the evidence).
        """
        history = history or []
        documents = documents or []

        # Triage with a safety net: if the fast model refuses to emit JSON
        # (sometimes happens when a dossier document reads like direct
        # instructions), fall back to a minimal triage rather than 500-ing
        # the whole request — the user still gets retrieval + an answer
        # grounded on their original question.
        try:
            triage = self._triage(user_message, history, documents)
            log.info("triage: areas=%s queries=%s angles=%s followup=%s",
                     triage.areas, triage.search_queries,
                     triage.strategic_angles, triage.needs_followup)
        except Exception as exc:
            log.warning("triage failed, using fallback: %s", exc)
            triage = TriageResult(
                problem_summary=user_message,
                areas=[],
                search_queries=[user_message],
                strategic_angles=[],
                needs_followup=False,
                followup_question="",
            )

        if triage.needs_followup and triage.followup_question:
            return LegalAnswer(
                kind="followup", text=triage.followup_question, triage=triage,
                session_id=session_id,
            )

        retrieved = self._retrieve(triage)
        log.info("retrieved %d articles", len(retrieved))

        precedents = self._retrieve_precedents(triage)
        log.info("retrieved %d precedents", len(precedents))

        # Strategic analysis — the winning-edge layer. Non-fatal if it fails.
        strategic: StrategicAnalysis | None = None
        try:
            strategic = self._strategic_analysis(user_message, triage, retrieved)
            log.info("strategic: %d details, %d warnings",
                     len(strategic.critical_details), len(strategic.risk_warnings))
        except Exception as exc:
            log.warning("strategic analysis failed (non-fatal): %s", exc)

        answer_text = self._compose_answer(
            user_message, history, triage, retrieved, precedents, strategic,
            session_id=session_id, documents=documents,
        )
        # ClaudeCodeBackend exposes the (possibly new) session_id after each
        # stateful call; other backends leave it as None.
        new_session_id = getattr(self.backend, "last_session_id", None) or session_id
        return LegalAnswer(
            kind="answer", text=answer_text, triage=triage,
            retrieved=retrieved, precedents=precedents, strategic=strategic,
            session_id=new_session_id,
        )

    # ── stage 1: triage ────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _triage(
        self,
        user_message: str,
        history: list[dict[str, str]],
        documents: list[dict] | None = None,
    ) -> TriageResult:
        # When the lawyer has attached a dossier, prepend a compact summary
        # (filename + type + summary + key_facts — NO raw text) so the
        # triage model frames queries around the real facts (names, dates,
        # amounts) without getting derailed by document language that
        # could read like a direct instruction. The user's actual question
        # is clearly fenced at the end.
        dossier_block = format_documents_for_prompt(documents or [], compact=True)
        if dossier_block:
            triage_message = (
                f"{dossier_block}\n"
                f"━━━ PYETJA E VËRTETË E QYTETARIT/AVOKATIT ━━━\n"
                f"{user_message}"
            )
        else:
            triage_message = user_message
        messages = list(history) + [{"role": "user", "content": triage_message}]
        raw = self.backend.complete(
            system=TRIAGE_SYSTEM,
            messages=messages,
            max_tokens=800,
            fast=True,
        )
        data = _parse_json_block(raw)
        return TriageResult(
            problem_summary=str(data.get("problem_summary", "")),
            areas=list(data.get("areas") or []),
            search_queries=list(data.get("search_queries") or []) or [user_message],
            strategic_angles=list(data.get("strategic_angles") or []),
            needs_followup=bool(data.get("needs_followup", False)),
            followup_question=str(data.get("followup_question", "")).strip(),
        )

    # ── stage 2: retrieval ─────────────────────────────────────────────────

    def _retrieve(self, triage: TriageResult) -> list[tuple[Article, float]]:
        # Restrict to relevant codes when we have clear areas; otherwise search all.
        codes: set[str] | None = None
        if triage.areas:
            wanted = {a.lower() for a in triage.areas}
            codes = {d.code for d in LEGAL_DOCUMENTS if d.area.lower() in wanted}
            # Safety net: auto-include matching procedural code even if the triage
            # model forgot. Procedural articles are where deadlines and nullity
            # grounds live — the "secret weapons" that decide real cases.
            for area in triage.areas:
                for proc_code in PROCEDURAL_MAPPING.get(area, ()):
                    codes.add(proc_code)
            if not codes:
                codes = None

        # Merge queries from topic searches + strategic angles. Angles often
        # surface the hidden articles (afate, përjashtime, pavlefshmëri).
        all_queries = list(triage.search_queries)
        for angle in triage.strategic_angles:
            if angle and angle not in all_queries:
                all_queries.append(angle)

        seen: dict[tuple[str, str], float] = {}
        for q in all_queries:
            for art, score in self.index.search(q, top_k=TOP_K_ARTICLES,
                                                restrict_codes=codes):
                key = (art.code, art.number)
                if score > seen.get(key, 0.0):
                    seen[key] = score

        art_by_key = {(a.code, a.number): a for a in self.index.articles}
        pairs = [(art_by_key[k], s) for k, s in seen.items() if k in art_by_key]
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[: TOP_K_ARTICLES]

    # ── stage 2b: precedents (court decisions) ────────────────────────────

    def _retrieve_precedents(self, triage: TriageResult) -> list[tuple[CasePrecedent, float]]:
        """Pull top-K court decisions from the V4 Postgres KB.

        The retriever ranks by BM25 over a composite text per case
        (summary + court + judges + articles cited + body excerpt). We
        feed it the triage queries AND the strategic angles so that
        procedural hits (afate, parashkrim, pavlefshmëri) surface even
        when the user's phrasing is purely factual.

        Area → case-type mapping is opportunistic, not strict: if triage
        identifies a single clear area we nudge the filter, but we
        *don't* exclude all other cases — a Constitutional Court ruling
        on fundamental rights can be precedent for any case.
        """
        if not self.kb.cases:
            return []

        queries = list(triage.search_queries)
        for angle in triage.strategic_angles:
            if angle and angle not in queries:
                queries.append(angle)

        # Map the human-facing "area" labels from triage onto Case.type
        # values in the KB. When triage settles on a single area, we use
        # it as a soft hint: first pass tries filtered retrieval, fallback
        # widens to unfiltered if that returns nothing (legal questions
        # often cross domains).
        case_type_hint = _area_to_case_type(triage.areas)

        if case_type_hint:
            hits = self.kb.search(queries, top_k=TOP_K_DECISIONS, type=case_type_hint)
            if hits:
                return hits
        return self.kb.search(queries, top_k=TOP_K_DECISIONS)

    # ── stage 3: strategic analysis ───────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _strategic_analysis(
        self,
        user_message: str,
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
    ) -> StrategicAnalysis:
        """Fast-model pass that hunts for case-deciding details in the articles."""
        if not retrieved:
            return StrategicAnalysis()

        context = _format_articles_for_prompt(retrieved)
        angles = ", ".join(triage.strategic_angles) if triage.strategic_angles else "(asnjë këndvështrim i dhënë)"

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhje e problemit: {triage.problem_summary}

            Këndvështrimet strategjike të propozuara nga triazhi: {angles}

            Nenet e gjetura (me rëndësinë zbritëse) — analizoji për detaje vendimtare:
            {context}

            Prodho analizën strategjike në JSON sipas formatit të kërkuar.
        """)

        raw = self.backend.complete(
            system=STRATEGIC_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("strategic JSON parse failed, returning empty")
            return StrategicAnalysis()

        details = []
        for item in data.get("critical_details") or []:
            if isinstance(item, dict):
                title = str(item.get("title", "")).strip()
                detail = str(item.get("detail", "")).strip()
                if title and detail:
                    details.append(StrategicInsight(title=title, detail=detail))
            elif isinstance(item, str) and item.strip():
                # tolerate malformed output where the model returns a flat string
                details.append(StrategicInsight(title="", detail=item.strip()))

        warnings = [
            str(w).strip() for w in (data.get("risk_warnings") or [])
            if isinstance(w, str) and str(w).strip()
        ]
        return StrategicAnalysis(critical_details=details[:5], risk_warnings=warnings[:3])

    # ── stage 4: answer composition ───────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _compose_answer(
        self,
        user_message: str,
        history: list[dict[str, str]],
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
        precedents: list[tuple[CasePrecedent, float]],
        strategic: StrategicAnalysis | None = None,
        session_id: str | None = None,
        documents: list[dict] | None = None,
    ) -> str:
        context = _format_articles_for_prompt(retrieved)
        precedents_block = _format_precedents_block(precedents)
        strategic_block = _format_strategic_block(strategic)
        # When we have docs, we pass the raw files as attachments so Claude
        # reads them natively (same UX as pasting an image into a chat) —
        # the prompt block only lists filenames, no pre-extracted text.
        attachment_paths = [
            Path(d["storage_path"]) for d in (documents or [])
            if d.get("storage_path")
            and Path(d["storage_path"]).exists()
        ]
        if attachment_paths:
            filenames = "\n".join(
                f"  • {d.get('filename', '?')}" for d in (documents or [])
            )
            dossier_block = (
                "\nDOKUMENTET E DOSJES (lexoji drejtpërdrejt):\n" + filenames + "\n"
            )
        else:
            dossier_block = format_documents_for_prompt(documents or [])
        dossier_guidance = (
            "Dokumentet janë bashkangjitur SIKUR t'i kishe para syve. "
            "Lexoji me kujdes dhe nxirr faktet konkrete (data, emra, shuma, "
            "afate, numra akti) kur argumenton. Kur është e përshtatshme, "
            "CITO dokumentin me emrin e tij të skedarit. Nëse një fakt i "
            "dokumentit bie ndesh me ligjin material ose procedural, "
            "shpjegoje hapur.\n"
            if documents else ""
        )

        prompt = textwrap.dedent(f"""\
            Pyetja e qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhje e problemit (nga triazhi): {triage.problem_summary}
            {dossier_block}
            Nenet e gjetura nga kodet shqiptare (me rëndësinë zbritëse):
            {context}
            {precedents_block}{strategic_block}
            {dossier_guidance}Shkruaj përgjigjen në formatin e kërkuar (PESË seksione në shqip),
            duke cituar vetëm nenet e mësipërme. Nëse analiza ka gjetur
            vendime të Gjykatës Kushtetuese/Gjykatës së Lartë të lidhura me
            rastin, CITO emrin e vendimit (p.sh. "Vendimi nr. 42/2024 i Gjykatës
            Kushtetuese") si përforcim te seksioni 1 ose 5. Në seksionin 5
            "Detajet që bëjnë diferencën", integro analizën strategjike me
            tonin e një avokati të ngrohtë që i shpjegon qytetarit PSE secili
            detaj është vendimtar për rastin e tij konkret.
        """)

        # When a session_id is active, the Claude Code backend resumes the
        # session natively — no need to resend history; Claude has it.
        # For other backends (Gemini, Anthropic API), session_id is ignored
        # and we still need to pass history in messages.
        if session_id:
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = list(history) + [{"role": "user", "content": prompt}]

        return self.backend.complete(
            system=ANSWER_SYSTEM,
            messages=messages,
            max_tokens=2500,
            fast=False,
            session_id=session_id,
            attachments=attachment_paths or None,
        )


# ── helpers ────────────────────────────────────────────────────────────────


def _parse_json_block(raw: str) -> dict:
    """Parse a JSON object out of raw model output, tolerant of code fences."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().lower().startswith("json"):
            s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0]
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output: {raw[:200]}")
    return json.loads(s[start : end + 1])


def _format_articles_for_prompt(pairs: list[tuple[Article, float]]) -> str:
    if not pairs:
        return "(asnjë nen i gjetur)"
    blocks: list[str] = []
    for a, score in pairs:
        hierarchy = " / ".join(x for x in (a.pjesa, a.kreu, a.seksioni) if x)
        hierarchy = f"  [{hierarchy}]\n" if hierarchy else ""
        blocks.append(
            f"── {a.citation} (score={score:.2f})\n"
            f"  Titulli: {a.heading}\n"
            f"{hierarchy}"
            f"  {a.body}"
        )
    return "\n\n".join(blocks)


def _format_precedents_block(pairs: list[tuple[CasePrecedent, float]]) -> str:
    """Render the top precedents so the model can cite them precisely.

    Each block gives the model the five things that matter in a cite:
    court + case number + date + outcome + cited articles. The ``[[case:ID]]``
    marker is the handle the answer is instructed to use when referring
    back to a precedent — it round-trips to a DB row so the UI can render
    a clickable link.
    """
    if not pairs:
        return ""
    lines = ["", "── VENDIME RELEVANTE TË GJYKATAVE (precedent nga KB) ──"]
    for c, score in pairs:
        outcome = f" — {c.outcome}" if c.outcome else ""
        date_str = c.decision_date.isoformat() if c.decision_date else "?"
        lines.append(
            f"  • [[case:{c.id}]] {c.citation} ({date_str}){outcome}  [score={score:.2f}]"
        )
        if c.summary:
            lines.append(f"    Përmbledhje: {c.summary[:260]}")
        if c.articles_cited:
            arts = ", ".join(f"{code} neni {art}" for code, art in c.articles_cited[:6])
            lines.append(f"    Nenet e cituara: {arts}")
        if c.judges:
            lines.append(f"    Trupi gjykues: {', '.join(c.judges[:3])}")
    lines.append("")
    return "\n".join(lines) + "\n"


# Mapping triage areas (human labels) → Case.type values stored in the KB.
# Multiple areas → no filter (we widen rather than guess wrong).
_AREA_TO_CASE_TYPE: dict[str, str] = {
    "Penal":         "penal",
    "Civil":         "civil",
    "Familje":       "familje",
    "Punë":          "pune",
    "Administrativ": "administrativ",
    "Doganor":       "doganor",
    "Rrugor":        "rrugor",
    "Zgjedhor":      "zgjedhor",
    "Kushtetues":    "kushtetues",
    "Detar":         "detar",
    "Ajror":         "ajror",
}


def _area_to_case_type(areas: list[str]) -> str | None:
    """Return a Case.type hint when triage identifies a single clear area."""
    mapped = {_AREA_TO_CASE_TYPE.get(a) for a in areas if a in _AREA_TO_CASE_TYPE}
    mapped.discard(None)
    return next(iter(mapped)) if len(mapped) == 1 else None


def _format_strategic_block(strategic: StrategicAnalysis | None) -> str:
    if not strategic or strategic.is_empty():
        return ""
    lines = ["", "── ANALIZA STRATEGJIKE (detaje që shumica e avokatëve i humbasin) ──"]
    for i, ci in enumerate(strategic.critical_details, 1):
        if ci.title:
            lines.append(f"  {i}. {ci.title}")
            lines.append(f"     {ci.detail}")
        else:
            lines.append(f"  {i}. {ci.detail}")
    if strategic.risk_warnings:
        lines.append("")
        lines.append("── PARALAJMËRIME RREZIKU ──")
        for w in strategic.risk_warnings:
            lines.append(f"  ⚠ {w}")
    lines.append("")
    return "\n".join(lines)


# ── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    argp = argparse.ArgumentParser()
    argp.add_argument("question", help="Citizen's question (any language)")
    args = argp.parse_args()

    sa = SuperAvvocato()
    result = sa.answer(args.question)
    print("\n" + "=" * 70)
    print(f"[{result.kind.upper()}]")
    print("=" * 70)
    print(result.text)
    if result.kind == "answer":
        print("\n─── Nenet e cituara ───")
        for a, s in result.retrieved:
            print(f"  {s:6.2f}  {a.citation} — {a.heading[:60]}")
        if result.precedents:
            print("\n─── Vendime precedent ───")
            for d, s in result.precedents:
                print(f"  {s:6.2f}  {d.citation} ({d.outcome or '?'}) — {d.summary[:60]}")
        if result.strategic and not result.strategic.is_empty():
            print("\n─── Analiza strategjike ───")
            for d in result.strategic.critical_details:
                print(f"  • {d.title}: {d.detail}")
            for w in result.strategic.risk_warnings:
                print(f"  ⚠ {w}")
