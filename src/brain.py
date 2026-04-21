"""The Super Avvocato's legal brain — strategic reasoning over Albanian law.

Layered pipeline (each stage non-fatal — one failing never breaks the answer):

    1. TRIAGE (fast)          — classify, expand query, flag missing facts
    2. RETRIEVAL              — BM25 over 6,600+ articles (+ procedural safety net)
    2b. PRECEDENTS            — BM25 over 813 Postgres-backed court decisions
    3. STRATEGIC (fast)       — winning-edge: hidden afate, exceptions, nullity
    3b. TIMELINE (fast)       — anchors + deadlines with Python-computed urgency
    3c. COMPARISON (fast)     — winners-vs-losers pattern over precedents
    3d. MISSING-FACTS (fast)  — the 2-4 questions a lawyer would ask next
    3e. PRE-MORTEM (fast)     — "imagine we've lost — why?" red-team pass
    4. ANSWER (main)          — 5-section Albanian answer; weaves in every layer

The brain is stateless; callers persist the conversation history they pass in.
"""
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime
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


TIMELINE_SYSTEM = """Ti je një analist afatesh ligjore shqiptar. Detyra jote: nga rasti i qytetarit dhe nenet e gjetura, nxirr një KRONOLOGJI të qartë të ngjarjeve të kaluara dhe një LISTË afatesh që duhen respektuar.

Afatet që humbasin janë arsyeja #1 pse avokatët humbasin kauza të fituara. Një qytetar që e di se ka 27 ditë kohë fiton kauza që e kishin humbur pa ditur.

Ndiq KËTË LOGJIKË:
1. Identifiko ANKORAT — ngjarje të kaluara që fillojnë të numërojnë afatet:
   • njoftimi i një akti administrativ → fillon 30 ditë për ankim
   • largimi nga puna → fillon 180 ditë për padi
   • shkelja e një të drejte → fillon parashkrimi (3, 5, 10 vjet, sipas rastit)
   • njoftimi i vendimit gjyqësor → fillon afati i apelit (15 ditë)
   • vdekja e trashëgimlënësit → fillon 6 muaj për pranim trashëgimie
2. Për çdo ankor, nga nenet e dhëna identifiko afatet që fillojnë dhe llogarit datën e skadencës.
3. Nëse një datë është e qartë në rastin (p.sh. qytetari tha "më datë 15 mars 2026"), përdore. Nëse është relative ("para 2 muajsh"), llogarite nga DATA E SOTME = {today}.
4. Nëse një datë nuk dihet fare, mos e shpik — lë anchor_date=null dhe due_date=null, por shtoje gjithsesi në listë me formulën (days_after + artikulli).

FORMATI — VETËM JSON, në shqip:
{{
  "anchors": [
    {{
      "event": "përshkrim i shkurtër i ngjarjes që fillon afatin (shqip, 4-10 fjalë)",
      "date": "YYYY-MM-DD ose null nëse nuk dihet",
      "source_quote": "citim i shkurtër nga teksti i qytetarit që tregon ku e morëm këtë informacion (ose \"nga dosja\" / \"nga konteksti\")"
    }}
  ],
  "deadlines": [
    {{
      "action": "Çfarë duhet bërë (shqip, foljore: p.sh. 'Depoziton ankimin administrativ')",
      "anchor_event": "cilit ankor i referohet (përdor të njëjtin tekst si te 'anchors.event')",
      "anchor_date": "YYYY-MM-DD ose null",
      "days_after": NUMBER ose null,
      "due_date": "YYYY-MM-DD ose null nëse anchor_date është null",
      "article_ref": "p.sh. 'Neni 45 i K.P.A.' — CITO vetëm nene që ke parë në kontekst"
    }}
  ]
}}

RREGULLA:
• MAKSIMUM 4 ankora dhe 6 afate. Rendit nga më urgjentja.
• CITO vetëm nene që janë në listën e dhënë. Mos shpik.
• Nëse rasti nuk ka afate të qarta, ktheje listën bosh: {{"anchors": [], "deadlines": []}}
• Datat në formatin strikt YYYY-MM-DD. Llogarit saktë (1 muaj = 30 ditë kur neni thotë "30 ditë", por 1 muaj = muaj kalendarik kur thotë "muaj").
• Mos shto komente jashtë JSON-it."""


COMPARISON_SYSTEM = """Ti je avokat strateg shqiptar që analizon precedent.
Të janë dhënë dy grupe vendimesh gjyqësore të ngjashme me rastin e qytetarit:
 • vendime ku kërkesa u PRANUA (fituesit)
 • vendime ku kërkesa u RRËZUA (humbësit)

Detyra jote: nxirr PATTERN-in — çfarë kishin të përbashkët fituesit, çfarë kishin të përbashkët humbësit, dhe në cilën anë bien faktet e qytetarit TONE.

Mendo si një avokat veteran që ka lexuar qindra raste: çfarë fakti, provë, afati ose rrethanë e ka bërë diferencën në fund? Jo cila ishte "materia", por cili ishte DETAJ VENDIMTAR.

Ktheje vetëm një objekt JSON:
{
  "pattern_winners": "një fjali në shqip që përshkruan çfarë kishin të përbashkët rastet që u pranuan (p.sh. 'Kërkuesit dorëzuan padi brenda 30 ditëve dhe kishin provë të shkruar të njoftimit.')",
  "pattern_losers": "një fjali në shqip që përshkruan çfarë i bashkonte rastet që u rrëzuan (p.sh. 'Kërkuesit humbën afatin ligjor ose nuk kishin akt njoftimi të datuar.')",
  "citizen_alignment": "favorable | mixed | unfavorable | unknown",
  "alignment_reason": "një fjali në shqip që shpjegon PSE rasti i këtij qytetari bie në atë anë",
  "decisive_factors": [
    "2-4 faktorë të shkurtër (6-14 fjalë secili) që historikisht bëjnë diferencën në raste si ky — këta faktorë duhet të jenë konkretë dhe të verifikueshëm (p.sh. 'A u dorëzua ankimi brenda 30 ditëve nga njoftimi?'), jo abstraktë"
  ]
}

RREGULLA STRIKTE:
• Asnjëherë mos shpik vendim apo fakt. Bazohu VETËM mbi vendimet e dhëna dhe faktet e qytetarit.
• Nëse grupi i fituesve ose humbësve është bosh ose shumë i vogël për të nxjerrë pattern, kthe citizen_alignment="unknown" dhe lër pattern_winners/pattern_losers bosh.
• MAKSIMUM 4 decisive_factors. Përzgjidhi ato më peshëmbajtësit.
• Shkruaj SHQIP. Jo latinisht, jo italisht.
• Mos shto komente jashtë JSON-it."""


PREMORTEM_SYSTEM = """Ti je avokat strateg shqiptar — pjesa CINIKE dhe paranoide e vetes tënde, ajo që shpëton kauzat sepse i sheh rreziqet PARA se të ndodhin.

Detyra jote: PARA se Super Avokati të japë përgjigjen përfundimtare, ti duhet të shkruash 3-5 ARSYE TË FORTA pse ky rast mund të HUMBET. Jo dobësi gjenerike, por skenarë konkretë ku avokati kundërshtar ose gjyqtari e rrëzon kauzën.

Kjo është teknika "pre-mortem": imagjinon që kauza tashmë ka humbur dhe shkon prapa për të zbuluar pse. Fiton më shumë kauza kush e di ku mund të humbasë se kush e di ku mund të fitojë.

FOKUSET e duhura (jo të gjitha aplikohen në çdo rast):
 1. AFATI I HUMBUR — parashkrim, ankim, padi, protestë: a ka kaluar ose po afrohet?
 2. PROVA E MANGËT — çfarë nuk mund të vërtetohet me çfarë qytetari ka?
 3. BARRA E PROVËS KUNDËR — në çfarë momenti barra bie mbi qytetarin dhe ai nuk mund ta mbajë?
 4. FORMA E CENUAR — akti ynë a ka formë, firmë, njoftim, kompetencë, kohë të duhura?
 5. PRECEDENTI I PAPËRSHTATSHËM — a ka vendime që shkojnë kundër tezës sonë dhe si mund t'i përdorë kundërshtari?
 6. FAKTI KOHPROMETUES — a ka diçka në rrëfimin e qytetarit që mund të kthehet kundër tij?
 7. INTERPRETIMI ALTERNATIV — si e lexon nenin kundërshtari, dhe a është leximi i tij i mundshëm?
 8. GABIMI PROCEDURAL — një hap i lënë pas dore (njoftim palëve, pagesa e taksës, komunikim me organin) që mund ta mbyllë rastin pa e diskutuar fondin.

FORMATI — VETËM JSON, në shqip:
{
  "risks": [
    {
      "risk": "formulim i qartë dhe konkret i arsyes pse kauza mund të humbet (1-2 fjali, cito nenin ose detajin faktik)",
      "mitigation": "çfarë mund të bëjë qytetari ose avokati PARA gjyqit për ta neutralizuar këtë rrezik (1 fjali konkrete)",
      "severity": "high | medium | low"
    }
  ]
}

RREGULLA STRIKTE:
• MINIMUM 3, MAKSIMUM 5 rreziqe. Renditi nga më i rrezikshmi.
• Secila "risk" duhet të jetë KONKRETE për këtë rast (jo "mund të humbet afati" në abstrakt, por "afati i 30 ditëve për ankim ndaj aktit të datës X ka kaluar").
• Baza vetëm mbi faktet e qytetarit + nenet e dhëna. Mos shpik.
• Nëse nga faktet dhe nenet nuk del asnjë rrezik i vërtetë, kthe: {"risks": []} — por kjo duhet të jetë e rrallë. Thuajse çdo rast ka së paku 2-3 dobësi reale.
• severity="high" për rreziqe që e humbasin vërtet kauzën; "medium" për pengesa të kalueshme; "low" për bezdi procedurale.
• Shkruaj SHQIP."""


MISSING_FACTS_SYSTEM = """Ti je avokat strateg shqiptar që bën intervistën e parë me një qytetar në zyrë.
Qytetari të ka shpjeguar rastin e tij. Përgjigja ligjore është dhënë tashmë me faktet që ke.
Detyra jote: identifiko 2-4 FAKTE QË NUK DIHEN por që, nëse ishin të njohura, do ndryshonin ose forconin PLOTËSISHT përgjigjen.

Këto NUK janë pyetje kuriozitetesh. Janë pyetjet që një avokat veteran bën para se të hyjë në gjyq: ato që e kthejnë kauzën.

Shembuj të pyetjeve të mira:
 • "A u dorëzua akti me vulë dhe firmë të organit përkatës?" (ndryshon mundësitë për pavlefshmëri)
 • "A u njoftuat me shkrim apo vetëm gojarisht?" (fillon ose jo afati i ankimit)
 • "A keni prova të shkruara të punësimit (kontratë, rroga)?" (zhvendos barrën e provës mbi punëdhënësin)
 • "A ishte fëmija i mitur në momentin e ngjarjes?" (aktivizohet mbrojtja speciale)

Shembuj të pyetjeve të KËQIJA (mos i bëj):
 • "Si u ndjetë?" (jo ligjërisht i rëndësishëm)
 • "Çfarë doni të bëni?" (kjo është përgjigjja, jo një fakt)
 • "A keni nevojë për avokat?" (jo një fakt që ndryshon analizën)

FORMATI — VETËM JSON, në shqip:
{
  "facts": [
    {
      "question": "pyetje e shkurtër dhe e qartë (10-20 fjalë) që një qytetar pa njohuri ligjore e kupton",
      "why_it_matters": "një fjali shqip që shpjegon PSE kjo pyetje ndryshon analizën (cito nenin nëse mundesh)",
      "impact_if_yes": "një fjali shqip: çfarë do të thonte kjo për rastin nëse përgjigjja është PO",
      "impact_if_no": "një fjali shqip: çfarë do të thonte kjo për rastin nëse përgjigjja është JO"
    }
  ]
}

RREGULLA:
• MAKSIMUM 4 fakte. Më mirë 2 të forta se 4 të dobëta.
• Renditi nga më i rëndësishmi (ai që e ndryshon më shumë përgjigjen).
• Mos përsërit fakte që qytetari i ka thënë tashmë — lexo tekstin me kujdes.
• Nëse qytetari tashmë i ka dhënë të gjitha faktet kritike, kthe: {"facts": []}
• Shkruaj SHQIP."""


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


# ── timeline ──────────────────────────────────────────────────────────────
# Urgency buckets are computed deterministically from (due_date - today) so
# the colour a citizen sees never depends on what the LLM felt like saying.
UrgencyLevel = Literal["expired", "critical", "warning", "info", "unknown"]


@dataclass
class TimelineAnchor:
    """A past event that starts one or more legal deadlines running."""
    event: str
    date: str | None                # ISO YYYY-MM-DD, or None when unknown
    source_quote: str = ""


@dataclass
class TimelineDeadline:
    """A future (or missed) cutoff the citizen must act by."""
    action: str
    anchor_event: str               # cross-ref to TimelineAnchor.event
    anchor_date: str | None
    days_after: int | None          # days from anchor to due_date
    due_date: str | None            # ISO YYYY-MM-DD
    article_ref: str = ""
    urgency: UrgencyLevel = "unknown"
    days_remaining: int | None = None  # signed: negative = expired


@dataclass
class TimelineAnalysis:
    anchors: list[TimelineAnchor] = field(default_factory=list)
    deadlines: list[TimelineDeadline] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.anchors and not self.deadlines


def _urgency_from_days(days_remaining: int | None) -> UrgencyLevel:
    """Bucket a day-delta into the colour we show the citizen.

    Thresholds are conservative on purpose: a week is 'critical' because
    anyone who needs an advokat typically needs a few days to reach one,
    draft, and file. A month is 'warning' because paperwork drifts.
    """
    if days_remaining is None:
        return "unknown"
    if days_remaining < 0:
        return "expired"
    if days_remaining <= 7:
        return "critical"
    if days_remaining <= 30:
        return "warning"
    return "info"


# ── precedent comparison ──────────────────────────────────────────────────
# "What the cases that won had, and what the cases that lost had" — the
# pattern recognition layer. A lawyer's intuition made explicit.

# Winners / losers from the claimant's perspective. ECtHR and constitutional
# cases lean "accepted = pro-rights", so they get mapped the same way.
# "unknown/other/settled" stay out of the comparison — too noisy.
_WINNING_OUTCOMES = {"accepted", "partially_accepted", "acquitted", "modified"}
_LOSING_OUTCOMES = {"rejected", "dismissed", "convicted"}


@dataclass
class PrecedentComparison:
    pattern_winners: str = ""            # one sentence: what the wins had in common
    pattern_losers: str = ""             # one sentence: what the losses had in common
    citizen_alignment: Literal["favorable", "mixed", "unfavorable", "unknown"] = "unknown"
    alignment_reason: str = ""           # one sentence explaining the alignment call
    decisive_factors: list[str] = field(default_factory=list)  # 2-4 bullets

    def is_empty(self) -> bool:
        return not (self.pattern_winners or self.pattern_losers
                    or self.decisive_factors)


# ── pre-mortem ────────────────────────────────────────────────────────────
# "Imagine the case has already lost — why?" A red-team stage the brain
# runs against ITSELF before composing the final answer. The identified
# risks are fed back into the answer prompt so the lawyer's recommendations
# address the weaknesses head-on instead of glossing over them.

PremortemSeverity = Literal["high", "medium", "low"]


@dataclass
class PremortemRisk:
    risk: str                            # concrete reason this case could be lost
    mitigation: str = ""                 # one sentence of what to do about it
    severity: PremortemSeverity = "medium"


@dataclass
class Premortem:
    risks: list[PremortemRisk] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.risks


# ── missing-facts detector ────────────────────────────────────────────────
# "The 3 questions a real lawyer would ask before answering." Different from
# triage's needs_followup (which blocks the answer): this augments the answer
# with follow-ups the citizen can click to drill deeper.


@dataclass
class MissingFact:
    question: str                        # the question to ask, in Albanian
    why_it_matters: str                  # 1 sentence — legal reason it changes things
    impact_if_yes: str = ""              # 1 sentence — what the answer looks like if yes
    impact_if_no: str = ""               # 1 sentence — what the answer looks like if no


@dataclass
class MissingFactsAnalysis:
    facts: list[MissingFact] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.facts


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
    # Timeline of past anchors + future deadlines with urgency badges. The
    # answer weaves the dates into section 4 ("Afatet"); the UI also shows
    # the structured list as a colour-coded widget.
    timeline: TimelineAnalysis | None = None
    # Precedent pattern analysis: what the winning cases had in common vs
    # the losing ones, and which side the citizen's facts align with.
    comparison: PrecedentComparison | None = None
    # "The 3 questions a lawyer would ask before answering." Augments —
    # doesn't block — the answer, giving the citizen pointers to drill
    # deeper where their original framing was ambiguous.
    missing_facts: MissingFactsAnalysis | None = None
    # Red-team pre-mortem: 3-5 reasons the case could be LOST, generated
    # before the answer is composed. Fed back into the answer prompt so
    # the final strategy addresses these risks head-on instead of bluffing.
    premortem: Premortem | None = None
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

        # Timeline — anchors (past events that start deadlines running) +
        # future cutoffs with urgency badges. Runs after retrieval so the
        # extractor can cite real article numbers. Non-fatal: timeline loss
        # must not block the primary answer.
        timeline: TimelineAnalysis | None = None
        try:
            timeline = self._analyze_timeline(user_message, triage, retrieved, documents)
            log.info("timeline: %d anchors, %d deadlines",
                     len(timeline.anchors), len(timeline.deadlines))
        except Exception as exc:
            log.warning("timeline analysis failed (non-fatal): %s", exc)

        # Precedent comparison — only worth doing when we have signal on
        # both sides (≥1 winning + ≥1 losing outcome). A one-sided set
        # produces a pattern the LLM has to invent the other side of.
        comparison: PrecedentComparison | None = None
        try:
            comparison = self._compare_precedents(user_message, triage, precedents)
            if comparison and not comparison.is_empty():
                log.info("comparison: alignment=%s, %d factors",
                         comparison.citizen_alignment, len(comparison.decisive_factors))
        except Exception as exc:
            log.warning("comparison analysis failed (non-fatal): %s", exc)

        # Missing-facts — "the 3 questions a lawyer would ask next." Runs
        # independently; not fed into the answer prompt (it's post-hoc
        # guidance that augments the answer, not a premise for it).
        missing_facts: MissingFactsAnalysis | None = None
        try:
            missing_facts = self._detect_missing_facts(user_message, triage, retrieved, documents)
            if missing_facts and not missing_facts.is_empty():
                log.info("missing_facts: %d questions", len(missing_facts.facts))
        except Exception as exc:
            log.warning("missing-facts detector failed (non-fatal): %s", exc)

        # Pre-mortem — "imagine the case is already lost; why?" This MUST
        # run before compose because its output is fed back into the answer
        # prompt. Forces the final reasoning to address identified weaknesses
        # head-on instead of walking past them.
        premortem: Premortem | None = None
        try:
            premortem = self._premortem(user_message, triage, retrieved, precedents, documents)
            if premortem and not premortem.is_empty():
                log.info("premortem: %d risks (severities=%s)",
                         len(premortem.risks),
                         [r.severity for r in premortem.risks])
        except Exception as exc:
            log.warning("premortem failed (non-fatal): %s", exc)

        answer_text = self._compose_answer(
            user_message, history, triage, retrieved, precedents, strategic, timeline, comparison,
            premortem=premortem, session_id=session_id, documents=documents,
        )
        # ClaudeCodeBackend exposes the (possibly new) session_id after each
        # stateful call; other backends leave it as None.
        new_session_id = getattr(self.backend, "last_session_id", None) or session_id
        return LegalAnswer(
            kind="answer", text=answer_text, triage=triage,
            retrieved=retrieved, precedents=precedents, strategic=strategic,
            timeline=timeline, comparison=comparison, missing_facts=missing_facts,
            premortem=premortem, session_id=new_session_id,
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

    # ── stage 3b: timeline & deadlines ────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _analyze_timeline(
        self,
        user_message: str,
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
        documents: list[dict] | None,
    ) -> TimelineAnalysis:
        """Extract past anchors + future deadlines from the case facts.

        The LLM proposes dates and day-counts; Python then derives urgency
        from (due_date - today) so the colour the citizen sees is not at
        the mercy of the model's arithmetic. Dropping a deadline here is
        better than inventing one — the answer still renders, just without
        a timeline widget.
        """
        if not retrieved:
            return TimelineAnalysis()

        articles_context = _format_articles_for_prompt(retrieved)
        dossier_hint = format_documents_for_prompt(documents or [], compact=True)
        dossier_block = f"\n{dossier_hint}\n" if dossier_hint else ""

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhje: {triage.problem_summary}
            {dossier_block}
            Nenet e gjetura (kërko afate, parashkrime, momente njoftimi, tenues ankimi):
            {articles_context}

            Nxirr kronologjinë sipas formatit JSON. DATA E SOTME = {date.today().isoformat()}.
        """)

        raw = self.backend.complete(
            system=TIMELINE_SYSTEM.format(today=date.today().isoformat()),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("timeline JSON parse failed, returning empty")
            return TimelineAnalysis()

        anchors: list[TimelineAnchor] = []
        for item in (data.get("anchors") or []):
            if not isinstance(item, dict):
                continue
            event = str(item.get("event", "")).strip()
            if not event:
                continue
            anchors.append(TimelineAnchor(
                event=event,
                date=_normalise_iso_date(item.get("date")),
                source_quote=str(item.get("source_quote", "")).strip(),
            ))

        deadlines: list[TimelineDeadline] = []
        today = date.today()
        for item in (data.get("deadlines") or []):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).strip()
            if not action:
                continue
            due_date_str = _normalise_iso_date(item.get("due_date"))
            days_remaining: int | None = None
            if due_date_str:
                try:
                    days_remaining = (datetime.strptime(due_date_str, "%Y-%m-%d").date() - today).days
                except ValueError:
                    due_date_str = None
            deadlines.append(TimelineDeadline(
                action=action,
                anchor_event=str(item.get("anchor_event", "")).strip(),
                anchor_date=_normalise_iso_date(item.get("anchor_date")),
                days_after=_coerce_int(item.get("days_after")),
                due_date=due_date_str,
                article_ref=str(item.get("article_ref", "")).strip(),
                urgency=_urgency_from_days(days_remaining),
                days_remaining=days_remaining,
            ))

        # Sort deadlines: expired first (so the citizen sees what they've
        # already missed), then by days_remaining ascending. Unknown dates
        # fall to the bottom — they're informational.
        def _sort_key(d: TimelineDeadline) -> tuple[int, int]:
            bucket = {"expired": 0, "critical": 1, "warning": 2, "info": 3, "unknown": 4}
            return (bucket[d.urgency], d.days_remaining if d.days_remaining is not None else 10_000)
        deadlines.sort(key=_sort_key)

        return TimelineAnalysis(anchors=anchors[:4], deadlines=deadlines[:6])

    # ── stage 3c: precedent comparison (winners vs losers pattern) ─────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _compare_precedents(
        self,
        user_message: str,
        triage: TriageResult,
        precedents: list[tuple[CasePrecedent, float]],
    ) -> PrecedentComparison | None:
        """Split precedents by outcome and ask the fast model for the pattern.

        We only run when there's at least one winning AND one losing outcome
        in the set — anything less forces the model to fabricate one side,
        and the comparison then becomes noise instead of signal.
        """
        winners = [c for c, _ in precedents if (c.outcome or "") in _WINNING_OUTCOMES]
        losers = [c for c, _ in precedents if (c.outcome or "") in _LOSING_OUTCOMES]
        if not winners or not losers:
            return None

        def _render_set(label: str, cases: list[CasePrecedent]) -> str:
            lines = [f"── {label} ({len(cases)}) ──"]
            for c in cases[:4]:  # cap: prompt budget
                arts = ", ".join(f"{code} n.{art}" for code, art in c.articles_cited[:4])
                lines.append(f"  • {c.citation} — {c.outcome}")
                if c.summary:
                    lines.append(f"    Përmbledhje: {c.summary[:260]}")
                if arts:
                    lines.append(f"    Nenet: {arts}")
            return "\n".join(lines)

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit (faktet reale që duhen krahasuar):
            \"\"\"{user_message}\"\"\"

            Përmbledhje e rastit: {triage.problem_summary}

            {_render_set("FITUESIT — vendime ku kërkesa u pranua", winners)}

            {_render_set("HUMBËSIT — vendime ku kërkesa u rrëzua", losers)}

            Analizoje dhe kthe JSON-in sipas formatit.
        """)

        raw = self.backend.complete(
            system=COMPARISON_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("comparison JSON parse failed, returning None")
            return None

        alignment = str(data.get("citizen_alignment", "unknown")).strip().lower()
        if alignment not in {"favorable", "mixed", "unfavorable", "unknown"}:
            alignment = "unknown"

        factors = [
            str(x).strip() for x in (data.get("decisive_factors") or [])
            if isinstance(x, str) and str(x).strip()
        ][:4]

        return PrecedentComparison(
            pattern_winners=str(data.get("pattern_winners", "")).strip(),
            pattern_losers=str(data.get("pattern_losers", "")).strip(),
            citizen_alignment=alignment,  # type: ignore[arg-type]
            alignment_reason=str(data.get("alignment_reason", "")).strip(),
            decisive_factors=factors,
        )

    # ── stage 3d: missing-facts detector ──────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _detect_missing_facts(
        self,
        user_message: str,
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
        documents: list[dict] | None,
    ) -> MissingFactsAnalysis:
        """Identify 2-4 unknown facts that would meaningfully change the answer.

        We feed the retrieved articles in so the detector can surface
        facts that pivot around a specific clause (e.g. "was the notice
        in writing?" when retrieved articles require written notice for
        a deadline to start).
        """
        if not retrieved:
            return MissingFactsAnalysis()

        articles_context = _format_articles_for_prompt(retrieved)
        dossier_hint = format_documents_for_prompt(documents or [], compact=True)
        dossier_block = f"\n{dossier_hint}\n" if dossier_hint else ""

        prompt = textwrap.dedent(f"""\
            Pyetja e qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhja e rastit: {triage.problem_summary}
            {dossier_block}
            Nenet e gjetura (përdori për të ditur cilat fakte pivotojnë te cili nen):
            {articles_context}

            Nxirr faktet që mungojnë sipas formatit JSON.
        """)

        raw = self.backend.complete(
            system=MISSING_FACTS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("missing-facts JSON parse failed, returning empty")
            return MissingFactsAnalysis()

        facts: list[MissingFact] = []
        for item in (data.get("facts") or []):
            if not isinstance(item, dict):
                continue
            q = str(item.get("question", "")).strip()
            why = str(item.get("why_it_matters", "")).strip()
            if not q or not why:
                continue
            facts.append(MissingFact(
                question=q,
                why_it_matters=why,
                impact_if_yes=str(item.get("impact_if_yes", "")).strip(),
                impact_if_no=str(item.get("impact_if_no", "")).strip(),
            ))
        return MissingFactsAnalysis(facts=facts[:4])

    # ── stage 3e: pre-mortem (red-team) ───────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _premortem(
        self,
        user_message: str,
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
        precedents: list[tuple[CasePrecedent, float]],
        documents: list[dict] | None,
    ) -> Premortem:
        """Write 3-5 reasons the case could be lost, BEFORE composing the answer.

        The premortem is fed back into the answer prompt so the final
        recommendations address the identified weaknesses head-on. This
        is the ``imagine the case is already lost — why?`` technique:
        a cynical red-team pass that forces the model to stop flattering
        the citizen's tesi.
        """
        if not retrieved:
            return Premortem()

        articles_context = _format_articles_for_prompt(retrieved)
        dossier_hint = format_documents_for_prompt(documents or [], compact=True)
        dossier_block = f"\n{dossier_hint}\n" if dossier_hint else ""
        precedent_hint = ""
        if precedents:
            lines = ["Precedent relevant (për të ditur si ka vendosur gjykata më parë):"]
            for c, _ in precedents[:5]:
                out = f" — {c.outcome}" if c.outcome else ""
                lines.append(f"  • {c.citation}{out}")
            precedent_hint = "\n" + "\n".join(lines) + "\n"

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhja: {triage.problem_summary}
            {dossier_block}{precedent_hint}
            Nenet e gjetura (kërko dobësi konkrete mbi ligjin material dhe procedural):
            {articles_context}

            Shkruaj pre-mortem — 3-5 arsye se pse kjo kauzë mund të humbet — në JSON.
        """)

        raw = self.backend.complete(
            system=PREMORTEM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1100,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("premortem JSON parse failed, returning empty")
            return Premortem()

        risks: list[PremortemRisk] = []
        for item in (data.get("risks") or []):
            if not isinstance(item, dict):
                continue
            r = str(item.get("risk", "")).strip()
            if not r:
                continue
            sev_raw = str(item.get("severity", "medium")).strip().lower()
            sev: PremortemSeverity = (
                sev_raw if sev_raw in ("high", "medium", "low") else "medium"  # type: ignore[assignment]
            )
            risks.append(PremortemRisk(
                risk=r,
                mitigation=str(item.get("mitigation", "")).strip(),
                severity=sev,
            ))
        # Sort by severity so the answer prompt sees the biggest risks first.
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        risks.sort(key=lambda x: sev_rank.get(x.severity, 1))
        return Premortem(risks=risks[:5])

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
        timeline: TimelineAnalysis | None = None,
        comparison: PrecedentComparison | None = None,
        premortem: Premortem | None = None,
        session_id: str | None = None,
        documents: list[dict] | None = None,
    ) -> str:
        context = _format_articles_for_prompt(retrieved)
        precedents_block = _format_precedents_block(precedents)
        strategic_block = _format_strategic_block(strategic)
        timeline_block = _format_timeline_block(timeline)
        comparison_block = _format_comparison_block(comparison)
        premortem_block = _format_premortem_block(premortem)
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
            {precedents_block}{comparison_block}{premortem_block}{strategic_block}{timeline_block}
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


def _normalise_iso_date(v) -> str | None:
    """Accept YYYY-MM-DD strings, reject everything else (incl. None/''/'null').

    The LLM sometimes emits 'null' as a string or free-form dates like
    '15 mars 2026'. We only trust strict ISO — anything else is treated as
    'unknown' so the downstream urgency computation doesn't pretend.
    """
    if not v or not isinstance(v, str):
        return None
    s = v.strip()
    if s.lower() in {"", "null", "none", "n/a"}:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _coerce_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _format_timeline_block(timeline: TimelineAnalysis | None) -> str:
    """Render the timeline so the answer model can weave dates into section 4.

    We include the urgency badge text so the LLM can faithfully echo it
    ('URGJENT — 3 ditë') rather than inventing a softer rewording of a
    critical deadline. Ordering is preserved (expired/critical first).
    """
    if not timeline or timeline.is_empty():
        return ""
    lines = ["", "── KRONOLOGJIA DHE AFATET (ANKORA + SKADENCA) ──"]
    if timeline.anchors:
        lines.append("Ankorat (ngjarje të kaluara që fillojnë afatet):")
        for a in timeline.anchors:
            d = a.date or "?"
            lines.append(f"  • [{d}] {a.event}")
    if timeline.deadlines:
        lines.append("Afatet që duhen respektuar:")
        for d in timeline.deadlines:
            if d.due_date:
                if d.days_remaining is not None and d.days_remaining < 0:
                    tag = f"⛔ KALUAR ({-d.days_remaining} ditë më parë)"
                elif d.urgency == "critical":
                    tag = f"🚨 URGJENT ({d.days_remaining} ditë)"
                elif d.urgency == "warning":
                    tag = f"⚠️  ({d.days_remaining} ditë)"
                else:
                    tag = f"({d.days_remaining} ditë)"
                when = f"deri më {d.due_date} {tag}"
            elif d.days_after is not None:
                when = f"brenda {d.days_after} ditësh nga '{d.anchor_event or '?'}'"
            else:
                when = "afat i lidhur me një ngjarje që nuk dihet"
            ref = f" [{d.article_ref}]" if d.article_ref else ""
            lines.append(f"  • {d.action} — {when}{ref}")
    lines.append("")
    lines.append("SHKRUAJ seksionin 4 'Afatet ligjore' DUKE CITUAR dhe datat e mësipërme KUR JANË TË LLOGARITURA (p.sh. 'deri më 14 maj 2026'). Mos rishko skadencat e llogaritura, mos zbut urgjencat. Nëse një afat është shënuar si KALUAR, thuaje hapur dhe sugjero çfarë mund të bëhet ende (p.sh. kërkesë për rikthim në afat).")
    return "\n".join(lines) + "\n"


def _format_comparison_block(cmp: PrecedentComparison | None) -> str:
    """Render the winners/losers pattern so the answer can cite it honestly."""
    if cmp is None or cmp.is_empty():
        return ""
    lines = ["", "── PATTERN I PRECEDENTËVE (fituesit vs humbësit) ──"]
    if cmp.pattern_winners:
        lines.append(f"✅ Çfarë kishin të përbashkët fituesit: {cmp.pattern_winners}")
    if cmp.pattern_losers:
        lines.append(f"❌ Çfarë i bashkonte humbësit: {cmp.pattern_losers}")
    alignment_label = {
        "favorable":   "RASTI I QYTETARIT BIE NË ANËN E FITUESVE",
        "mixed":       "RASTI ËSHTË I PËRZIER — kërkon rritje prove",
        "unfavorable": "RASTI BIE NË ANËN E HUMBËSVE — strategji mbrojtëse",
        "unknown":     "POZICIONIMI I RASTIT NUK ËSHTË I QARTË",
    }.get(cmp.citizen_alignment, "POZICIONIMI I RASTIT NUK ËSHTË I QARTË")
    lines.append(f"→ {alignment_label}")
    if cmp.alignment_reason:
        lines.append(f"  Arsye: {cmp.alignment_reason}")
    if cmp.decisive_factors:
        lines.append("Faktorët vendimtar (kontrolloji një nga një te rasti):")
        for f in cmp.decisive_factors:
            lines.append(f"  • {f}")
    lines.append("")
    lines.append("PËRDOR këtë pattern te seksioni 5 'Detajet që bëjnë diferencën' — shpjego qytetarit nëse rasti i tij bie në anën e fituesve apo humbësve DHE pse. Integroje natyrshëm, jo me kopjim direkt.")
    return "\n".join(lines) + "\n"


def _format_premortem_block(pm: Premortem | None) -> str:
    """Render the pre-mortem risks so the answer directly addresses them.

    The prompt tells the answer model to treat each risk as a weakness
    it must mitigate inside section 5 — not glance past. That's what
    separates this from the strategic-analysis block, which surfaces
    winning details: pre-mortem surfaces *losing* details.
    """
    if pm is None or pm.is_empty():
        return ""
    sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines = ["", "── PRE-MORTEM (arsye pse kauza mund të HUMBET) ──"]
    for i, r in enumerate(pm.risks, 1):
        icon = sev_icon.get(r.severity, "🟡")
        lines.append(f"  {i}. {icon} {r.risk}")
        if r.mitigation:
            lines.append(f"     Mitigim: {r.mitigation}")
    lines.append("")
    lines.append(
        "INTEGRO këto rreziqe te seksioni 5 'Detajet që bëjnë diferencën' — për "
        "secilin rrezik high/medium, shpjego qytetarit hapur PSE kauza mund të "
        "humbet nga ajo anë DHE jepi mitigjimin konkret. Mos i fsheh. Qytetari "
        "ka më shumë rrespekt për avokatin që i thotë të vërtetën sesa për atë "
        "që i jep shpresa të rreme. Mos harro të tregosh edhe PIKA TË FORTA — "
        "pre-mortem nuk do të thotë pesimizëm, por onestitet strategjik."
    )
    return "\n".join(lines) + "\n"


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
