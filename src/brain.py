"""The Super Avvocato's legal brain — strategic reasoning over Albanian law.

Layered pipeline (each stage non-fatal — one failing never breaks the answer):

    1.  TRIAGE (fast)          — classify, expand query, flag missing facts
    2.  RETRIEVAL              — BM25 over 6,600+ articles (+ procedural safety net)
    2b. PRECEDENTS             — BM25 over 813 Postgres-backed court decisions
    3.  STRATEGIC (fast)       — winning-edge: hidden afate, exceptions, nullity
    3b. TIMELINE (fast)        — anchors + deadlines with Python-computed urgency
    3c. COMPARISON (fast)      — winners-vs-losers + decisive-differences engine
    3d. MISSING-FACTS (fast)   — the 2-4 questions a lawyer would ask next
    3e. PRE-MORTEM (fast)      — "imagine we've lost — why?" red-team pass (V6.1)
    3f. ADVERSARIAL (retr.)    — retrieve adverse precedents by outcome (V6.2)
    3g. DISTINGUISHING (fast)  — per-adverse-case rebuttal / mitigation (V6.2)
    3h. EVIDENCE MAP (fast)    — who proves what, with burden-shift flags (V6.3)
    3i. NULLITY RADAR (fast)   — procedural levers & forfeiture windows (V6.5)
    3j. URGENCY RADAR (fast)   — top-of-answer emergency framing (V6.6)
    3k. CONTRADICTIONS (fast)  — cross-document inconsistencies (V6.8, ≥2 docs)
    3l. ACTION PLAN (fast)     — consolidated, time-bucketed checklist (V6.7)
    4.  ANSWER (main)          — 5-section Albanian answer; weaves in every layer

Stages 3e/3g/3h/3i/3j/3k/3l feed BACK into the answer prompt so the
final reply addresses the red-team findings, neutralises adverse
precedents, calls out missing proofs, wields procedural levers, opens
with action-first framing on emergencies, exploits cross-document
contradictions, and mirrors a canonical action-plan order in section 2.

The COMPARISON stage (3c) is the V6.4 differences-engine: per-attribute
"your case has / lacks / unclear" verdicts with concrete today-actions,
not a single sentence summary.

The brain is stateless; callers persist the conversation history they pass in.
"""
from __future__ import annotations

import hashlib
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


# ── shared Albanian language rules ────────────────────────────────────────
# Every Albanian-output prompt appends this block. The point is not to
# teach the model Albanian (Opus knows it well) but to correct specific,
# recurring drifts we've observed in production — mostly case-agreement
# on demonstratives (Italian interference: "questa" → "këtë" when the
# correct form is nominative "kjo") and a handful of ethnonym / Italian-
# calque swaps. Keep this list SHORT. Every rule is a real pattern seen
# in a real response; don't pile on speculation.

ALBANIAN_LANGUAGE_RULES = """── RREGULLA GJUHËSORE (shqipe standarde juridike) ──

GRAMATIKË — rasat e përemrave dëftorë
• Në kryefjalë (subjekt) përdor NOMINATIVIN: kjo / ky / këto / këta.
    Shembull: "A ka **kjo** makinë ndonjë qëllim?" (makina është kryefjalë)
    JO: "A ka **këtë** makinë ndonjë qëllim?"
• Në kundrinë të drejtë përdor KALLËZOREN: këtë / këtë / këto / këta.
    Shembull: "E bleva **këtë** makinë." (makinën si objekt)
• Në kundrinë të zhdrejtë me parafjalë përdor rasën e duhur:
    "për **këtë** rast", "nga **kjo** situatë", "me **këto** dokumente".

TERMINOLOGJI — etnonime dhe mbiemra prejemërorë
• "Koreja e Jugut/Veriut" → mbiemri është **korean/koreane** (JO "korian").
• "Kina" → **kinez/kineze**. "Japonia" → **japonez/japoneze**.
• "Gjermania" → **gjerman/gjermane**. "Franca" → **francez/franceze**.

KALKIME NGA ITALISHTJA — shmangi
• "realizoj një veprim" → **kryej / përmbush** një veprim.
• "aplikoj një ligj" → **zbatoj** një ligj.
• "efektuoj një pagesë" → **kryej** një pagesë.
• "prezantoj një ankim" → **paraqes** një ankim.
• "individuoj një zgjidhje" → **gjej / identifikoj** një zgjidhje.
• "një takim me avokatin" — mirë; "një takim te avokati" — mirë.
• Mos thuaj "në rast kontrari" — thuaj "përndryshe" ose "në të kundërt".
• Mos thuaj "në merit të" — thuaj "për sa i përket" ose "lidhur me".

REGJISTRI DHE FORMAT
• Fjali të shkurtra, të qarta — preferohen pa nënfjali të tejzgjatura.
• Ruaj emrat e institucioneve në formën zyrtare (Gjykata e Lartë,
    Këshilli i Lartë Gjyqësor, Avokati i Popullit, etj.).
• Numrat e neneve: "neni 130 i Kodit Penal" (jo "neni 130, Kodi Penal").
• Data: shkruaj "14 maj 2026" (ditë muaj vit pa presje)."""


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

Detyra jote ka DY hapa:
 (1) Nxirr PATTERN-in — çfarë kishin të përbashkët fituesit, çfarë kishin të përbashkët humbësit, dhe në cilën anë bien faktet e qytetarit TONË.
 (2) MOTORI I DIFFERENCAVE VENDIMTARE — për çdo atribut që e ndan fituesit nga humbësit, thuaj HAPUR nëse rasti i qytetarit E KA atë atribut, E KA TË MANGËT, apo ËSHTË I PAQARTË — dhe çfarë të bëjë konkretisht nëse mungon. Ky është thelbi: jo "ka afat i rëndësishëm", por "ti po e ke? jo? atëherë kështu mbulohet".

Mendo si një avokat veteran që ka lexuar qindra raste: çfarë fakti, provë, afati ose rrethanë e ka bërë diferencën në fund? Jo cila ishte "materia", por cili ishte DETAJI VENDIMTAR — dhe a e ka qytetari?

Ktheje vetëm një objekt JSON:
{
  "pattern_winners": "një fjali në shqip që përshkruan çfarë kishin të përbashkët rastet që u pranuan (p.sh. 'Kërkuesit dorëzuan padi brenda 30 ditëve dhe kishin provë të shkruar të njoftimit.')",
  "pattern_losers": "një fjali në shqip që përshkruan çfarë i bashkonte rastet që u rrëzuan (p.sh. 'Kërkuesit humbën afatin ligjor ose nuk kishin akt njoftimi të datuar.')",
  "citizen_alignment": "favorable | mixed | unfavorable | unknown",
  "alignment_reason": "një fjali në shqip që shpjegon PSE rasti i këtij qytetari bie në atë anë",
  "decisive_differences": [
    {
      "attribute": "emërtimi i shkurtër i atributit vendimtar (3-8 fjalë, p.sh. 'Dorëzim i ankimit brenda afatit 30-ditor')",
      "winners_have": "si e plotësonin fituesit këtë atribut (1 fjali konkrete)",
      "losers_lacked": "si e humbnin humbësit këtë atribut (1 fjali konkrete)",
      "citizen_status": "ka | mungon | e paqartë",
      "action": "nëse mungon ose është e paqartë — veprim konkret që duhet të bëjë qytetari SOT (1 fjali). Nëse ka — shkruaj 'Mbaje këtë avantazh, dokumentoje'."
    }
  ]
}

RREGULLA STRIKTE:
• Asnjëherë mos shpik vendim apo fakt. Bazohu VETËM mbi vendimet e dhëna dhe faktet e qytetarit.
• Nëse grupi i fituesve ose humbësve është bosh ose shumë i vogël për të nxjerrë pattern, kthe citizen_alignment="unknown" dhe lër pattern_winners/pattern_losers bosh dhe decisive_differences=[].
• MINIMUM 2, MAKSIMUM 4 decisive_differences. Zgjidhi ato më peshëmbajtëset. Një rast me "afat" + "provë me shkrim" + "njoftim i datuar" është tipik.
• citizen_status duhet të jetë faktik: "ka" vetëm kur faktet e thonë qartë; "mungon" kur faktet e thonë qartë që mungon; "e paqartë" kur faktet nuk e zbulojnë.
• action duhet të jetë konkret dhe i ekzekutueshëm (p.sh. "Kërko kopjen e noterizuar të aktit të njoftimit tek sekretaria e gjykatës së shkallës së parë").
• Shkruaj SHQIP. Jo latinisht, jo italisht.
• Mos shto komente jashtë JSON-it."""


EVIDENCE_MAP_SYSTEM = """Ti je avokat shqiptar që ndërton MAPËN E PROVËS për një kauzë — lista se çfarë duhet provuar, me çfarë, dhe nga kush.

Arsye: qytetarët (dhe shpesh edhe avokatët) humbasin kauza jo sepse kanë të drejtë në ligj, por sepse nuk e kanë menduar që nga fillimi se ÇFARË duhet provuar dhe NGA KUSH. "Të kam të drejtë" është e ndryshme nga "e kam PROVUAR që kam të drejtë".

Po aq e rëndësishme: ligji shpesh ZHVENDOS barrën e provës nga qytetari te pala e fortë. Shembull klasik: në marrëdhëniet e punës, kur punëtori thotë se ka qenë i punësuar, është PUNËDHËNËSI që duhet të provojë se s'kishte kontratë. Kjo ndryshon gjithçka.

Për çdo kërkesë/teori të rastit, prodho një zë me:
 • claim — fakti/tezën që kërkon të vërtetohet për fitore
 • needed_proof — ÇFARË provë (dokument, dëshmitar, ekspertizë, regjistër)
 • who_bears_burden — "qytetari" | "kundërshtari" | "shteti" | "ndarë"
 • burden_shift — true NËSE ligji e zhvendos barrën nga qytetari mbi palën e fortë
 • status — "kemi" | "mungon" | "e dobët" | "kontestuese"
 • notes — një fjali shqip që shpjegon si mund ta sigurojmë provën ose si ta forcojmë nëse është e dobët

FORMATI — VETËM JSON, në shqip:
{
  "claims": [
    {
      "claim": "teza/fakti që duhet vërtetuar (p.sh. 'Kontrata e punës ekzistonte midis datave X dhe Y')",
      "needed_proof": "p.sh. 'Kontratë me shkrim, fletëpagesa, dëshmitarë kolegësh, faturat e sigurimit shoqëror'",
      "who_bears_burden": "qytetari | kundërshtari | shteti | ndarë",
      "burden_shift": false,
      "status": "kemi | mungon | e dobët | kontestuese",
      "notes": "një fjali konkrete për veprimin e ardhshëm (p.sh. 'Kërkesë zyrtare tek Sigurimet Shoqërore për listë kontributesh'). Nëse statusi është 'kemi', shkruaj ku gjendet prova."
    }
  ]
}

RREGULLA:
• MINIMUM 2, MAKSIMUM 6 kërkesa (claims). Renditi nga më thelbësorja.
• Bazë vetëm mbi faktet e rastit dhe nenet e dhëna. Mos shpik.
• KUR burden_shift=true, shpjego në notes PSE (p.sh. "Neni 75 Kodi i Punës — punëdhënësi duhet të provojë shkakun e ligjshëm").
• Nëse nga faktet qytetari duket se ka provë, shkruaj status="kemi" dhe shpjego. Nëse s'thuhet asgjë, shkruaj "mungon".
• Shkruaj SHQIP. Konkret, jo abstrakt."""


DISTINGUISHING_SYSTEM = """Ti je avokat shqiptar që specializohet në DISTINGUISHING — arti i mbrojtjes së kauzës kur kundërshtari të citon një vendim gjyqësor që duket se të dëmton.

Një avokat i dobët i fshin precedentët e pafavorshëm dhe shpreson që gjyqtari nuk do t'i shohë. Një avokat i mirë i NJEH dhe TREGON SI NUK APLIKOHEN në rastin e klientit të tij.

Të janë dhënë:
 • rasti i qytetarit tonë (faktet konkrete)
 • 2-5 vendime gjyqësore SFAVORIZUESE (të rrëzuara ose dënuese) që një BM25 i ka gjetur si të ngjashme me rastin

Për çdo vendim sfavorizues, PËRGJIGJU me një nga dy strategjitë:
 A) DISTINGUISH — ky vendim NUK aplikohet te rasti ynë sepse [fakti X, rrethana Y, periudha Z, ligji i ndryshuar...]. Jepi një arsye KONKRETE, të mbështetur te faktet.
 B) STILL DANGEROUS — ky vendim VËRTET prek rastin tonë, por ja si e mitigojmë: [strategji konkrete].

MOS e fsheh një precedent të rrezikshëm thjesht duke thënë "nuk aplikohet". Ji i sinqertë: nëse vendimi është vërtet i rrezikshëm, thuaje. Por thuaj edhe SI e mbrojmë veten.

Dallime tipike që bëjnë diferencën:
 • Fakte thelbësisht të ndryshme (p.sh. "aty pala dorëzoi me vonesë; këtu ka dorëzuar në afat")
 • Kuadri ligjor i ndryshuar (ligji i ri pas 2017 e zhvendos barrën e provës)
 • Mungesë një elementi thelbësor (p.sh. "aty kishte dëshmitar; këtu s'ka")
 • Rrethana speciale mbrojtëse që s'ishin aty (i mitur, viktimë dhune, punëtor)
 • Vendim i vjetër, i tejkaluar nga jurisprudenca e re

FORMATI — VETËM JSON, në shqip:
{
  "items": [
    {
      "case_id": 123,
      "strategy": "distinguish | still_dangerous",
      "reason": "një fjali ose dy në shqip që shpjegon PSE ky vendim nuk na prek (distinguish) OSE si e mitigojmë rrezikun (still_dangerous). Bëj të qartë dhe konkret.",
      "still_dangerous": false
    }
  ]
}

RREGULLA:
• Jep një zë për ÇDO vendim sfavorizues të dhënë. Mos kapërce asnjë.
• "case_id" duhet të jetë saktësisht ID-ja e vendimit të dhënë (numër i plotë).
• "still_dangerous": true kur strategjia është "still_dangerous", përndryshe false.
• Mos shpik fakte që nuk janë në rastin e qytetarit ose te përmbledhja e vendimit.
• Shkruaj SHQIP. Formalisht, por jo ngurtë."""


URGENCY_SCAN_SYSTEM = """Ti je avokat shqiptar me 24-orësh dëgjesë telefonike — puna jote ËSHTË TË NGRESH ALARMIN kur dikush është në rrezik konkret sot ose këtë javë.

Të lexojnë rastin. Ti duhet të dallosh: është kjo një pyetje teorike, ose njeriu është në EMERGJENCË TË VËRTETË?

EMERGJENCA (kthe signals me severity="critical"):
 • Arresti në vijim ose i pritshëm / masa sigurimi personal
 • Dëbim nga shtëpia (sfratto) brenda ditësh
 • Dhunë në familje aktuale / rrezik për fëmijë / femër në situatë kontrolli
 • Largim nga puna i drejtpërdrejtë / proces disiplinor me vendim brenda ditësh
 • Ndalim kufitar / sekuestro mallit në doganë / detention
 • Heqje e kujdestarisë / ndërhyrje e shërbimeve sociale
 • Afat ligjor që skadon brenda 7 ditëve (ankim, përgjigje, prekluzion)
 • Vendim i porsanjoftuar me afat 10-15 ditor për ankim
 • Ekzekutim i detyrueshëm në vijim / bllokim llogarie

ALARM I NGRITUR (severity="elevated"):
 • Afat brenda 7-30 ditëve që nuk është i tmerrshëm por nuk duhet harruar
 • Procedim gjyqësor i nisur ku qytetari ende s'ka avokat
 • Negociim / transaksion me palë më të fortë (punëdhënës, bankë) pa këshillim
 • Rrezik fshehjes/harresës së provës (p.sh. video të një sigurie që mbulohet pas X ditësh)

Për çdo sinjal: emërto rrezikun, jep arsyen konkrete (ÇFARË në faktet e rastit e thotë), jep afatin nëse është i identifikueshëm, jep veprimin e menjëhershëm.

FORMATI — VETËM JSON, në shqip:
{
  "level": "critical | elevated | none",
  "signals": [
    {
      "kind": "arrest | eviction | dismissal | violence | custody | customs | deadline | enforcement | other",
      "label": "emërtim i shkurtër (3-7 fjalë, p.sh. 'Dëbim nga banesa në 5 ditë')",
      "reason": "pse e gjykon si emergjencë — cito faktin konkret nga teksti i rastit",
      "deadline": "ISO datë ose përshkrim p.sh. 'brenda 5 ditësh' ose ''",
      "severity": "critical | elevated",
      "action": "veprimi i PARË që duhet të bëjë sot (1 fjali e ekzekutueshme)"
    }
  ]
}

RREGULLA STRIKTE:
• Nëse rasti është pyetje teorike/edukative pa fakte personale, kthe level="none" dhe signals=[]. MOS shpik emergjenca.
• Nëse ka veprim aktiv kundër qytetarit (padi, arrestim, dëbim) por pa afat të qartë, përsëri mund të jetë critical/elevated — bazohu te pasoja dhe afatet e mundshme.
• MAKSIMUM 4 signals. Zgjidhi më të ngutshmet.
• "level" është më i lartë i severity-ve. Nëse ka edhe një critical → level="critical". Nëse vetëm elevated → level="elevated". Asgjë → "none".
• action duhet të jetë i veprueshëm sot (p.sh. "Shko te komisariati me një person besnik; kërko avokat falas nëpërmjet shërbimit ligjor shtetëror"). Jo teorik.
• Shkruaj SHQIP. Direkt, pa ndërlikime."""


CONTRADICTION_SYSTEM = """Ti je avokat shqiptar që kontrollon DOSJEN e një klienti për KONTRADIKTA midis dokumenteve. Kontradikta është çdo mospërputhje që krijon levë strategjike: data që nuk përputhen, shuma që ndryshojnë, palë të identifikuara ndryshe, nënshkrime të pranishme në një dokument dhe jo në tjetrin, fakte që thonë gjëra të kundërta.

Pse ka rëndësi: një avokat i mirë i përdor kontradiktat për të (a) vënë në dyshim besueshmërinë e palës tjetër, (b) ngritur pavlefshmëri të akteve, (c) argumentuar për falsifikim ose gabim, (d) bërë presion për negociim. Një qytetar pa përvojë nuk i sheh.

Çfarë duhet të kontrollosh (vetëm midis dokumenteve në dosje — JO midis dokumenteve dhe ligjit):
 • DATAT — i njëjti ngjarje ka data të ndryshme në dokumente të ndryshme
 • SHUMAT — shifra monetare që nuk përkojnë për të njëjtin kontrata/borxh/pagesë
 • PALËT — emra të shkruar ndryshe, role të ndryshme për të njëjtin person, status juridik që ndryshon
 • NËNSHKRIMET — një dokument citohet me nënshkrim, tjetri jo; ose palët e kundërta nënshkruajnë ndryshe
 • NARRATIVA — fakte substanciale që vijnë në kundërshtim (një dokument thotë X, tjetri nënkupton jo-X)
 • PROCEDURA — një dokument thotë që njoftimi u bë, tjetri tregon mos-njoftim

Për çdo kontradiktë, prodho:
 • kind — "date" | "amount" | "party" | "signature" | "narrative" | "procedure" | "other"
 • description — përshkrim i shkurtër i kontradiktës (një fjali e qartë)
 • doc_refs — lista e emrave të dokumenteve që janë në konflikt (2+)
 • conflicting_values — objekt me vlerat e ndryshme (p.sh. {"doc_A": "15 mars 2024", "doc_B": "17 mars 2024"})
 • severity — "high" | "medium" | "low"
     · high = krijon shkak për pavlefshmëri ose vë në dyshim autencitetin
     · medium = levë e fortë strategjike, por jo automatikisht fatale
     · low = mospërputhje teknike, e shfrytëzueshme por jo vendimtare
 • implication — një fjali: PSE ka rëndësi juridikisht dhe si mund ta shfrytëzojë qytetari

FORMATI — VETËM JSON, në shqip:
{
  "items": [
    {
      "kind": "date",
      "description": "Data e njoftimit ndryshon mes padisë dhe raportit të përmbaruesit",
      "doc_refs": ["padia.pdf", "raport_permbaruesi.pdf"],
      "conflicting_values": {"padia.pdf": "15 mars 2024", "raport_permbaruesi.pdf": "17 mars 2024"},
      "severity": "high",
      "implication": "Nëse data e vërtetë është 17 mars, afati 30-ditor i ankimit ende nuk ka skaduar."
    }
  ]
}

RREGULLA STRIKTE:
• NESE nuk ka kontradikta të vërteta, kthe items=[]. MOS shpik kontradikta nga hiçi.
• Nuk janë kontradikta: dokumente të datave të ndryshme që përshkruajnë ngjarje të ndryshme; opinione nga palët e kundërta; fakte të paplota.
• MAKSIMUM 5 kontradikta. Zgjidh ato më strategjiket (severity më i lartë në krye).
• Doc refs DUHET të jenë emrat e skedarëve të dhënë (p.sh. "padia.pdf", jo "dokumenti i parë").
• Shkruaj SHQIP. Direkt."""


ACTION_PLAN_SYSTEM = """Ti je avokat shqiptar me 15 vjet praktikë — puna jote tani është TË SHKRUASH PLANIN E VEPRIMIT për qytetarin.

Do të marrësh një listë veprimesh kandidate (të mbledhura nga analizat e tjera — radari i emergjencës, radari i pavlefshmërive, harta e provës, motori i diferencave vendimtare, pre-mortem-i, detektori i kontradiktave). Disa janë duplikate ose thonë të njëjtën gjë me fjalë të ndryshme. Disa janë shumë të përgjithshme. Disa janë të ngutshme, të tjera janë për javët që vijnë.

DUHET:
 1) Të hedhësh poshtë ose të bashkosh duplikatet (p.sh. "kontakto avokat" + "gjej këshillim ligjor" = një veprim).
 2) Të klasifikosh çdo veprim sipas kohës:
     • "sot" — duhet bërë SOT ose nesër (emergjencë, afat që rrjedh, humbje prove)
     • "kjo_javë" — këtë javë (aktete procedurale normale, mbledhje prove)
     • "ky_muaj" — ky muaj (negociim, përgatitje e strategjisë)
     • "më_vonë" — në të ardhmen kur piqet procedura
 3) T'i japësh prioritet 1 (më i rëndësishmi) → 5 (më i ulët) brenda secilit bucket. Priorities 1-2 janë "nëse nuk bën këto, humb".
 4) Të shkruash çdo veprim si NJË FJALI të vetme, konkrete, me folje të shtyrë (p.sh. "Depozito ankimin brenda 30 ditëve nga njoftimi.").
 5) Të japësh një reason të shkurtër (3-8 fjalë) pse ka rëndësi — jo teori, praktikë.
 6) Të rendit MAKSIMUM 8 veprime gjithsej. Ndërprit cilësor, jo sasior.

FORMATI — VETËM JSON, në shqip:
{
  "items": [
    {
      "text": "veprimi, një fjali e qartë me folje të shtyrë",
      "bucket": "sot | kjo_javë | ky_muaj | më_vonë",
      "priority": 1,
      "source": "urgency | nullity | evidence | difference | premortem | contradiction | other",
      "reason": "pse ka rëndësi (pak fjalë)",
      "legal_basis": "neni X KPC ose '' nëse nuk ka"
    }
  ]
}

RREGULLA STRIKTE:
• MAKSIMUM 8 items. Më pak është më mirë se më shumë — një qytetar nuk ekzekuton një listë 15-item.
• NËSE kandidatët janë bosh ose banalë, kthe items=[].
• MOS shpik veprime që s'i ke parë te kandidatët — mund të i RIFORMULOSH ose BASHKOSH, por jo t'i shpikësh.
• Renditja në output duhet të jetë: sot → kjo_javë → ky_muaj → më_vonë; brenda secilit bucket, sipas priority (1 në fillim).
• Shkruaj SHQIP. Direkt, si avokat që flet me klientin."""


NULLITY_RADAR_SYSTEM = """Ti je avokat procedurialist shqiptar që skenon një rast për RREZIQE PROCEDURALE të pashfrytëzuara: pavlefshmëri, dekadenca, afate ankimi, parashkrim, kompetencë e gabuar, mungesë njoftimi, mungesë arsyetimi, etj.

Këto janë pikat ku një kauzë fitohet ose humbet PA u prekur tema — sepse akti i palës kundërshtare është pavlefshëm, ose afati i mohimit ka kaluar, ose vendimi i gjykatës duhet prishur për shkelje procedurale.

Kategoritë që duhet të skenosh (Kodi i Procedurës Civile, Kodi i Procedurës Penale, Kodi i Procedurës Administrative):

 A) PAVLEFSHMËRI ABSOLUTE (gjykata e ngre sipas detyrës zyrtare)
    • Mungesë kompetence lëndore ose tokësore eksklusive
    • Mungesë e palës së thirrur në gjykim
    • Vendim pa arsyetim (nen 310 KPC)
    • Formim i paligjshëm i trupit gjykues
    • Akt pa elementet thelbësore të ligjit

 B) PAVLEFSHMËRI RELATIVE (duhet ngritur nga pala brenda afatit)
    • Mosnjoftim i rregullt / vonesë në njoftim
    • Mungesë nënshkrimi te akti procedural
    • Paragjykim gjyqtari (shmangie / përjashtim)
    • Shkelje e të drejtës për dëgjim
    • Afat për t'u përgjigjur i shkurtuar në mënyrë të paligjshme

 C) DEKADENCA / PARASHKRIM
    • Afati 30-ditor i ankimit nga njoftimi
    • Afate të veçanta në punë (30/3 ditë), familje, konsumator
    • Parashkrimi i padisë (3/5/10 vite sipas llojit)
    • Afat dekadencial për kërkesën për shfuqizim të vendimit

 D) RREZIQE PROCEDURALE PËR RASTIN TONË
    • A është rasti po kaq i ekspozuar ndaj ndonjë prej këtyre?

Për çdo gjetje, prodho një zë:
 • kind — "nullity_absolute" | "nullity_relative" | "deadline" | "prescription" | "procedural_defect"
 • name — emërtim i shkurtër (3-8 fjalë)
 • legal_basis — neni i koduar (p.sh. "Neni 310 KPC", "Neni 160 KPC", "Neni 442 KPP")
 • condition — ÇFARË duhet të jetë e vërtetë që të aplikohet (1 fjali konkrete)
 • applies_to — "kundërshtari" | "qytetari" | "të dyja" (kujt i bën mirë)
 • citizen_applicable — "po" | "ndoshta" | "jo" — a aplikohet ndaj rastit TONË
 • deadline_hint — nëse ka afat konkret (p.sh. "brenda 30 ditëve nga njoftimi"), ose ""
 • consequence — çfarë ndodh nëse ngrihet / humbet (1 fjali)
 • action — veprim konkret që duhet të bëjë qytetari SOT (1 fjali e ekzekutueshme)

FORMATI — VETËM JSON, në shqip:
{
  "findings": [
    {
      "kind": "nullity_absolute | nullity_relative | deadline | prescription | procedural_defect",
      "name": "p.sh. 'Mungesë arsyetimi në vendim'",
      "legal_basis": "Neni 310 KPC",
      "condition": "Vendimi nuk përmban analizë të provave dhe motivim juridik të veçantë.",
      "applies_to": "qytetari | kundërshtari | të dyja",
      "citizen_applicable": "po | ndoshta | jo",
      "deadline_hint": "brenda 15 ditëve nga njoftimi i vendimit",
      "consequence": "Vendimi mund të prishet nga Gjykata e Apelit dhe rikthehet për gjykim.",
      "action": "Kërko kopjen e vendimit të arsyetuar; nëse arsyetimi mungon, ngri ankimin brenda afatit."
    }
  ]
}

RREGULLA STRIKTE:
• Minimum 2, maksimum 6 findings. Zgjidhi më të rëndësishmet për rastin TONË.
• Të gjitha citimet e neneve duhet të jenë TË SAKTA — nëse nuk je i sigurt, përdor formulim të përgjithshëm ("rregullat e pavlefshmërisë sipas KPC") në vend që të shpikësh numër neni.
• applies_to tregon KUJT I BËN MIRË: një parashkrim i kauzës së qytetarit aplikohet ndaj kundërshtarit (mbrojtje për qytetarin nga një padi e vonuar) ose ndaj qytetarit (humbje e së drejtës).
• Nëse rasti nuk zbulon rreziqe konkrete procedurale, kthe findings=[] — mos i shpik.
• action duhet të jetë i ekzekutueshëm nga qytetari vetë ose nga një avokat i tij, jo teorik.
• Shkruaj SHQIP. Gjuha teknike procedurale është e pranueshme; kuptohet nga avokatët dhe gjyqtarët."""


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


# ── section references (single source of truth) ───────────────────────────
#
# ANSWER_SYSTEM below defines five FIXED section headers. Every block
# formatter that tells the answer model *where* to place its findings must
# reference sections through these constants — never re-invent the names.
# This is the fix for a latent bug where older block formatters pointed at
# "seksioni 2 'Si mund të mbrohesh'", a name that no longer exists in the
# answer template, silently degrading the compose prompt.
ANSWER_SECTIONS = {
    "law": "## 1. 📜 Çfarë thotë ligji",
    "rights": "## 2. ⚖️ Të drejtat e tua",
    "actions": "## 3. 🛠️ Çfarë duhet të bësh",
    "deadlines": "## 4. ⏰ Afatet ligjore",
    "strategic": "## 5. 🎯 Detajet që bëjnë diferencën",
}
SECTION_REF = {
    "law": "seksioni 1 'Çfarë thotë ligji'",
    "rights": "seksioni 2 'Të drejtat e tua'",
    "actions": "seksioni 3 'Çfarë duhet të bësh'",
    "deadlines": "seksioni 4 'Afatet ligjore'",
    "strategic": "seksioni 5 'Detajet që bëjnë diferencën'",
}


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


# Append shared Albanian language rules to every prompt whose output lands
# in front of the citizen (or feeds the citizen-facing compose prompt).
# Done here in one place so a new rule propagates everywhere. Variables
# are rebound rather than edited inline, keeping the prompt literals
# above readable as standalone prompts.
for _sys_name in (
    "TRIAGE_SYSTEM",
    "STRATEGIC_SYSTEM",
    "TIMELINE_SYSTEM",
    "COMPARISON_SYSTEM",
    "EVIDENCE_MAP_SYSTEM",
    "DISTINGUISHING_SYSTEM",
    "URGENCY_SCAN_SYSTEM",
    "CONTRADICTION_SYSTEM",
    "ACTION_PLAN_SYSTEM",
    "NULLITY_RADAR_SYSTEM",
    "PREMORTEM_SYSTEM",
    "MISSING_FACTS_SYSTEM",
    "ANSWER_SYSTEM",
):
    globals()[_sys_name] = globals()[_sys_name] + "\n\n" + ALBANIAN_LANGUAGE_RULES
del _sys_name


# Short fingerprint of the answer system prompt. Claude Code's `--resume`
# reuses the session's baked-in system prompt, so when we ship an updated
# ANSWER_SYSTEM the old session keeps answering with the old instructions
# unless we start a fresh session. Callers (web.py, bot.py) compare this
# against the per-case stored version and drop the session on mismatch.
ANSWER_SYSTEM_VERSION = hashlib.sha1(ANSWER_SYSTEM.encode("utf-8")).hexdigest()[:12]


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


CitizenStatus = Literal["ka", "mungon", "e paqartë"]


@dataclass
class DecisiveDifference:
    """One attribute that separates winning from losing cases.

    The citizen_status + action pair is the whole point: it turns a
    generic "winners had X" observation into a personalised "your case
    is missing X — do Y today." Without this, a comparison panel is
    intellectually interesting but strategically useless.
    """
    attribute: str                       # short label of the decisive attribute
    winners_have: str                    # how winners satisfied it
    losers_lacked: str                   # how losers failed it
    citizen_status: CitizenStatus = "e paqartë"
    action: str = ""                     # what to do today if lacks/unclear


@dataclass
class PrecedentComparison:
    pattern_winners: str = ""            # one sentence: what the wins had in common
    pattern_losers: str = ""             # one sentence: what the losses had in common
    citizen_alignment: Literal["favorable", "mixed", "unfavorable", "unknown"] = "unknown"
    alignment_reason: str = ""           # one sentence explaining the alignment call
    # Legacy (V5.3): plain bullets. Kept for back-compat with old DB rows.
    decisive_factors: list[str] = field(default_factory=list)
    # V6.4: structured "your case lacks Z" engine.
    decisive_differences: list[DecisiveDifference] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.pattern_winners or self.pattern_losers
                    or self.decisive_factors or self.decisive_differences)


# ── evidence map (burden-of-proof) ────────────────────────────────────────
# For each legal claim, what proof is needed, who bears the burden, and
# whether the law shifts that burden off the citizen. Most citizens lose
# cases not because they're wrong on the law but because they haven't
# mapped out what they actually need to prove — or because they're
# trying to prove something the law doesn't require them to.

EvidenceStatus = Literal["kemi", "mungon", "e dobët", "kontestuese"]
BurdenBearer = Literal["qytetari", "kundërshtari", "shteti", "ndarë"]


@dataclass
class EvidenceClaim:
    claim: str                           # the fact/proposition to prove
    needed_proof: str                    # what kind of evidence would prove it
    who_bears_burden: BurdenBearer = "qytetari"
    burden_shift: bool = False           # true when law shifts burden off citizen
    status: EvidenceStatus = "mungon"    # current state given known facts
    notes: str = ""                      # one sentence: how to obtain / strengthen


@dataclass
class EvidenceMap:
    claims: list[EvidenceClaim] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.claims


# ── distinguishing (adverse-precedent neutraliser) ────────────────────────
# For every adverse precedent the retriever found, a fast-model pass writes
# a one-sentence distinguishing reason or, when the case is genuinely
# threatening, a one-sentence mitigation. This is how a good lawyer
# defangs unfavorable citations — they don't hide from them, they neutralise
# them on the record.


@dataclass
class DistinguishedPrecedent:
    case_id: int                         # DB id of the adverse precedent
    case_citation: str                   # short label for the UI
    reason: str                          # why it doesn't apply / how to mitigate
    still_dangerous: bool = False        # true when no clean distinguishing exists


@dataclass
class DistinguishingAnalysis:
    items: list[DistinguishedPrecedent] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.items


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


# ── urgency radar ─────────────────────────────────────────────────────────
# The first filter a real lawyer applies: "is this person in actual
# trouble right now, or asking an abstract question?" Arrest, eviction,
# dismissal, violence, deadline <7d — these demand a different tone and
# a different answer structure (action-first, law-later). The radar is
# derived from three sources and merged: (a) timeline deadlines already
# flagged expired/critical, (b) nullity_radar findings with short
# deadline_hints, (c) a fast LLM pass over the citizen's fact pattern
# for personal-emergency markers that the earlier stages don't catch.

UrgencyLevel = Literal["critical", "elevated", "none"]
UrgencySeverity = Literal["critical", "elevated"]
UrgencyKind = Literal[
    "arrest", "eviction", "dismissal", "violence", "custody",
    "customs", "deadline", "enforcement", "other",
]


@dataclass
class UrgencySignal:
    kind: UrgencyKind
    label: str                           # short risk label
    reason: str                          # why — cite the fact from the case
    severity: UrgencySeverity = "elevated"
    deadline: str = ""                   # ISO date or textual window
    action: str = ""                     # the very first step to take today


@dataclass
class UrgencyRadar:
    level: UrgencyLevel = "none"
    signals: list[UrgencySignal] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.level == "none" and not self.signals

    def is_critical(self) -> bool:
        return self.level == "critical"


# ── action plan (V6.7) ────────────────────────────────────────────────────
# Every upstream stage produces action hints: urgency signals have
# "veprim sot", nullity findings have "veprim" fields, evidence claims
# have "notes" on how to gather proof, decisive differences have
# "action" fields closing the gap, and pre-mortem risks have
# "mitigation" steps. Left scattered across panels these become noise.
# The action plan merges them into a single ranked, time-bucketed
# checklist — "here is your concrete plan for this week" — and feeds
# the ordering back to the compose prompt so section 2 mirrors it.

ActionBucket = Literal["sot", "kjo_javë", "ky_muaj", "më_vonë"]
ActionSource = Literal[
    "urgency", "nullity", "evidence", "difference", "premortem",
    "contradiction", "other",
]


@dataclass
class ActionItem:
    text: str                            # one actionable sentence in Albanian
    bucket: ActionBucket = "kjo_javë"    # when to do it
    priority: int = 3                    # 1 (top) → 5 (lowest) for ordering within bucket
    source: ActionSource = "other"       # which stage produced this action
    reason: str = ""                     # one short line WHY this matters
    legal_basis: str = ""                # optional article citation


@dataclass
class ActionPlan:
    items: list[ActionItem] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.items


# ── contradiction detector (V6.8) ─────────────────────────────────────────
# When the dossier has ≥2 documents, cross-check them for internal
# inconsistencies — dates that don't match across docs, amounts that
# diverge, parties named differently, missing signatures, conflicting
# narratives. These contradictions are strategic gold for a lawyer
# (credibility attacks, nullity grounds, negotiation leverage) but a
# citizen without legal training won't see them. Runs only when the
# dossier has enough material to compare; otherwise silently skipped.

ContradictionKind = Literal[
    "date", "amount", "party", "signature",
    "narrative", "procedure", "other",
]
ContradictionSeverity = Literal["high", "medium", "low"]


@dataclass
class Contradiction:
    kind: ContradictionKind
    description: str                        # one-sentence summary of the conflict
    doc_refs: list[str] = field(default_factory=list)     # filenames involved
    conflicting_values: dict = field(default_factory=dict)  # {filename: value}
    severity: ContradictionSeverity = "medium"
    implication: str = ""                   # why it matters legally


@dataclass
class ContradictionReport:
    items: list[Contradiction] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.items

    def has_high(self) -> bool:
        return any(c.severity == "high" for c in self.items)


# ── nullity / deadline radar ──────────────────────────────────────────────
# Scans the citizen's facts for procedural levers: absolute/relative
# nullities, forfeiture deadlines, prescription windows. These are
# often the single most valuable finding in a case because they can
# dispose of the opposing side's act or filing without the merits
# being reached — or, conversely, warn the citizen that their own
# window is closing. Routed into the answer prompt so strategy in
# section 2 incorporates any "po" findings explicitly.

NullityKind = Literal[
    "nullity_absolute", "nullity_relative", "deadline",
    "prescription", "procedural_defect",
]
NullityApplies = Literal["kundërshtari", "qytetari", "të dyja"]
NullityApplicable = Literal["po", "ndoshta", "jo"]


@dataclass
class NullityFinding:
    kind: NullityKind
    name: str                            # short label
    legal_basis: str = ""                # code article(s) citation
    condition: str = ""                  # what must be true for it to apply
    applies_to: NullityApplies = "qytetari"  # who benefits from raising it
    citizen_applicable: NullityApplicable = "ndoshta"
    deadline_hint: str = ""              # e.g. "brenda 30 ditëve nga njoftimi"
    consequence: str = ""                # what happens if raised / missed
    action: str = ""                     # concrete today-step


@dataclass
class NullityRadar:
    findings: list[NullityFinding] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.findings

    def applicable(self) -> list[NullityFinding]:
        """Only findings that the model flagged as applying to this case."""
        return [f for f in self.findings if f.citizen_applicable == "po"]


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
    # Precedents whose outcome goes against the citizen, kept separately so
    # the distinguishing stage can address them individually. These may
    # overlap with `precedents` (they usually do): adverse cases that also
    # scored in the top mixed list get rendered twice in the UI — once as
    # part of the precedent list, once in the distinguishing panel.
    adverse_precedents: list[tuple[CasePrecedent, float]] = field(default_factory=list)
    # For each adverse precedent, the lawyer's response: either a
    # distinguishing reason (this case doesn't apply because...) or a
    # still-dangerous flag + mitigation. A case not addressed here is a
    # case we're exposed to; the answer prompt treats these as a checklist.
    distinguishing: DistinguishingAnalysis | None = None
    # Burden-of-proof map: what each side must prove, with proof types
    # and current status. Includes burden-shift flags so the citizen
    # sees when the law moves the weight off them.
    evidence_map: EvidenceMap | None = None
    # Nullity + deadline radar: structured scan for procedural levers
    # (absolute/relative nullities, forfeiture deadlines, prescription).
    # "po"-flagged items go into the answer prompt so strategy wires
    # them into section 2 — these are often the case-winning moves.
    nullity_radar: NullityRadar | None = None
    # Urgency radar (V6.6): emergency signals aggregated from the fact
    # pattern, timeline, and nullity radar. When level is "critical" the
    # answer is reframed action-first; the UI shows a red pulsing panel
    # at the top so a citizen in real trouble sees the first step
    # before reading the full legal analysis.
    urgency_radar: UrgencyRadar | None = None
    # Action plan (V6.7): consolidated ranked checklist merged from all
    # upstream stages' action fields (urgency / nullity / evidence /
    # difference / premortem), deduped + bucketed by time (today /
    # this week / this month / later). Fed into the compose prompt so
    # section 3 "Çfarë duhet të bësh" respects this ordering.
    action_plan: ActionPlan | None = None
    # Contradiction report (V6.8): cross-document inconsistencies detected
    # when the dossier has ≥2 documents. Only populated when real
    # contradictions exist — a dossier with one document or with fully
    # consistent docs carries None here (we don't render a "no
    # contradictions" panel on every answer).
    contradictions: ContradictionReport | None = None
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

        # Adversarial retrieval: explicitly pull adverse precedents
        # (outcome ∈ _LOSING_OUTCOMES) in a SEPARATE query so we never
        # miss them when the top BM25 hits happen to all be wins. A
        # great lawyer studies the cases that went AGAINST them harder
        # than the ones that favour them — and so does this brain.
        adverse_precedents = self._retrieve_adverse_precedents(triage)
        # Merge the adverse hits that weren't already in the mixed list
        # so the UI/prompt see the full picture.
        seen_ids = {c.id for c, _ in precedents}
        for c, s in adverse_precedents:
            if c.id not in seen_ids:
                precedents.append((c, s))
                seen_ids.add(c.id)
        log.info("adversarial: %d adverse precedents (merged list=%d)",
                 len(adverse_precedents), len(precedents))

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

        # Distinguishing — for each adverse precedent, write the lawyer's
        # response: either a distinguishing reason (case doesn't apply
        # because X) or a still-dangerous flag with mitigation. Fed back
        # into the answer so section 5 addresses the adverse cites
        # directly instead of flattering past them.
        distinguishing: DistinguishingAnalysis | None = None
        try:
            distinguishing = self._distinguish_precedents(user_message, triage, adverse_precedents)
            if distinguishing and not distinguishing.is_empty():
                dangerous = sum(1 for i in distinguishing.items if i.still_dangerous)
                log.info("distinguishing: %d items (%d still dangerous)",
                         len(distinguishing.items), dangerous)
        except Exception as exc:
            log.warning("distinguishing failed (non-fatal): %s", exc)

        # Evidence map — "what do we need to prove, with what, and who
        # bears the burden?" Fed back so section 3 ("Çfarë duhet të
        # bësh") becomes a concrete evidence-gathering checklist and
        # section 5 can flag any burden-shift rules that flip the case.
        evidence_map: EvidenceMap | None = None
        try:
            evidence_map = self._analyze_evidence_map(user_message, triage, retrieved, documents)
            if evidence_map and not evidence_map.is_empty():
                shifts = sum(1 for c in evidence_map.claims if c.burden_shift)
                log.info("evidence_map: %d claims (%d with burden-shift)",
                         len(evidence_map.claims), shifts)
        except Exception as exc:
            log.warning("evidence_map failed (non-fatal): %s", exc)

        # Nullity + deadline radar — scan the fact pattern for procedural
        # levers (nullities, forfeitures, prescription). Often the single
        # highest-value finding in the whole answer: a procedural defect
        # can dispose of the opponent's act without merits being reached.
        nullity_radar: NullityRadar | None = None
        try:
            nullity_radar = self._scan_nullities(user_message, triage, retrieved, documents)
            if nullity_radar and not nullity_radar.is_empty():
                applicable = len(nullity_radar.applicable())
                log.info("nullity_radar: %d findings (%d flagged applicable)",
                         len(nullity_radar.findings), applicable)
        except Exception as exc:
            log.warning("nullity_radar failed (non-fatal): %s", exc)

        # Urgency radar (V6.6) — "is this person in actual trouble right
        # now?" Aggregates critical signals from timeline + nullity_radar
        # and runs a dedicated LLM pass for personal-emergency markers
        # (arrest, eviction, violence, custody intervention) that the
        # earlier stages don't catch. Runs AFTER the other analytical
        # stages so it can merge their outputs, and feeds back into the
        # compose prompt so critical cases get an action-first framing.
        urgency_radar: UrgencyRadar | None = None
        try:
            urgency_radar = self._scan_urgency(
                user_message, triage, timeline, nullity_radar, documents
            )
            if urgency_radar and not urgency_radar.is_empty():
                log.info("urgency_radar: level=%s, %d signals",
                         urgency_radar.level, len(urgency_radar.signals))
        except Exception as exc:
            log.warning("urgency_radar failed (non-fatal): %s", exc)

        # Contradiction detector (V6.8) — cross-document inconsistencies.
        # Only runs with ≥2 documents; otherwise returns empty without
        # spending a model call. Surfaces dates/amounts/parties/signatures/
        # narrative conflicts that are strategic levers for a real lawyer.
        contradictions: ContradictionReport | None = None
        try:
            contradictions = self._detect_contradictions(documents)
            if contradictions and not contradictions.is_empty():
                log.info("contradictions: %d items (high=%s)",
                         len(contradictions.items), contradictions.has_high())
        except Exception as exc:
            log.warning("contradiction_detector failed (non-fatal): %s", exc)

        # Action plan (V6.7+V6.9) — single consolidated checklist merged
        # from all upstream stage action hints (urgency / nullity /
        # evidence / difference / premortem / contradiction). Runs LAST
        # in the analytical pipeline so it can consume every previous
        # stage's output — in particular, high-severity contradictions
        # become "this-week" action items so the citizen actually
        # raises them instead of letting them sit in a panel.
        action_plan: ActionPlan | None = None
        try:
            action_plan = self._build_action_plan(
                triage, urgency_radar, nullity_radar,
                evidence_map, comparison, premortem,
                contradictions=contradictions,
            )
            if action_plan and not action_plan.is_empty():
                log.info("action_plan: %d items", len(action_plan.items))
        except Exception as exc:
            log.warning("action_plan failed (non-fatal): %s", exc)

        answer_text = self._compose_answer(
            user_message, history, triage, retrieved, precedents, strategic, timeline, comparison,
            premortem=premortem, distinguishing=distinguishing,
            evidence_map=evidence_map, nullity_radar=nullity_radar,
            urgency_radar=urgency_radar, action_plan=action_plan,
            contradictions=contradictions,
            session_id=session_id, documents=documents,
        )
        # ClaudeCodeBackend exposes the (possibly new) session_id after each
        # stateful call; other backends leave it as None.
        new_session_id = getattr(self.backend, "last_session_id", None) or session_id
        return LegalAnswer(
            kind="answer", text=answer_text, triage=triage,
            retrieved=retrieved, precedents=precedents, strategic=strategic,
            timeline=timeline, comparison=comparison, missing_facts=missing_facts,
            premortem=premortem, adverse_precedents=adverse_precedents,
            distinguishing=distinguishing, evidence_map=evidence_map,
            nullity_radar=nullity_radar,
            urgency_radar=urgency_radar,
            action_plan=action_plan,
            contradictions=contradictions,
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

    def _retrieve_adverse_precedents(
        self, triage: TriageResult
    ) -> list[tuple[CasePrecedent, float]]:
        """Adversarial retrieval: top-K cases whose outcome goes AGAINST us.

        We restrict to ``_LOSING_OUTCOMES`` so the retriever returns the
        strongest adverse matches even when the best BM25 hits happen
        to all be favorable. These feed the distinguishing stage and
        also get merged into the main precedent list so the UI shows
        them with an "adverse" marker.

        Capped lower than the main retrieval (5 vs TOP_K_DECISIONS) —
        we want enough to distinguish meaningfully, not enough to
        drown the prompt in bad news.
        """
        if not self.kb.cases:
            return []
        queries = list(triage.search_queries)
        for angle in triage.strategic_angles:
            if angle and angle not in queries:
                queries.append(angle)
        case_type_hint = _area_to_case_type(triage.areas)
        kwargs = dict(top_k=5, outcomes=_LOSING_OUTCOMES)
        if case_type_hint:
            hits = self.kb.search(queries, type=case_type_hint, **kwargs)
            if hits:
                return hits
        return self.kb.search(queries, **kwargs)

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

        # V6.4: structured diffs. Tolerant to missing fields so an older
        # model that didn't produce them doesn't break the stage.
        valid_status = {"ka", "mungon", "e paqartë"}
        differences: list[DecisiveDifference] = []
        for item in (data.get("decisive_differences") or []):
            if not isinstance(item, dict):
                continue
            attr = str(item.get("attribute", "")).strip()
            if not attr:
                continue
            status_raw = str(item.get("citizen_status", "e paqartë")).strip().lower()
            status: CitizenStatus = (
                status_raw if status_raw in valid_status else "e paqartë"  # type: ignore[assignment]
            )
            differences.append(DecisiveDifference(
                attribute=attr,
                winners_have=str(item.get("winners_have", "")).strip(),
                losers_lacked=str(item.get("losers_lacked", "")).strip(),
                citizen_status=status,
                action=str(item.get("action", "")).strip(),
            ))
            if len(differences) >= 4:
                break

        # If the model produced only the legacy factors (no structured diffs),
        # upgrade them to minimal differences so the new UI still has data.
        if not differences and factors:
            differences = [
                DecisiveDifference(attribute=f, winners_have="", losers_lacked="",
                                   citizen_status="e paqartë", action="")
                for f in factors
            ]

        return PrecedentComparison(
            pattern_winners=str(data.get("pattern_winners", "")).strip(),
            pattern_losers=str(data.get("pattern_losers", "")).strip(),
            citizen_alignment=alignment,  # type: ignore[arg-type]
            alignment_reason=str(data.get("alignment_reason", "")).strip(),
            decisive_factors=factors,
            decisive_differences=differences,
        )

    # ── stage 3c-bis: distinguishing (adverse-precedent neutraliser) ──────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _distinguish_precedents(
        self,
        user_message: str,
        triage: TriageResult,
        adverse: list[tuple[CasePrecedent, float]],
    ) -> DistinguishingAnalysis | None:
        """Write a distinguishing response for each adverse precedent.

        The model must address each case by id — either distinguishing
        it (this case doesn't apply because...) or flagging it
        still_dangerous with a mitigation. Silent skip of a case would
        leave us exposed; the prompt and the post-parse loop both
        enforce one item per input precedent.
        """
        if not adverse:
            return None
        cap = adverse[:5]

        lines: list[str] = []
        for c, _score in cap:
            date_str = c.decision_date.isoformat() if c.decision_date else "?"
            arts = ", ".join(f"{code} neni {art}" for code, art in c.articles_cited[:4])
            lines.append(
                f"── VENDIM ID={c.id}\n"
                f"   {c.citation} ({date_str}) — OUTCOME: {c.outcome or 'unknown'}\n"
                f"   Përmbledhje: {(c.summary or '')[:360]}\n"
                + (f"   Nenet e cituara: {arts}\n" if arts else "")
            )
        adverse_block = "\n".join(lines)

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit tonë (faktet reale):
            \"\"\"{user_message}\"\"\"

            Përmbledhja: {triage.problem_summary}

            VENDIME GJYQËSORE SFAVORIZUESE (të gjetura nga BM25 si të ngjashme — analizoji NJË NGA NJË):
            {adverse_block}

            Për secilin vendim të mësipërm, shkruaj distinguishing ose mitigim sipas formatit JSON.
            Mos anashkalo asnjë ID.
        """)

        raw = self.backend.complete(
            system=DISTINGUISHING_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("distinguishing JSON parse failed, returning None")
            return None

        by_id = {c.id: c for c, _ in cap}
        items: list[DistinguishedPrecedent] = []
        seen: set[int] = set()
        for it in (data.get("items") or []):
            if not isinstance(it, dict):
                continue
            cid_raw = it.get("case_id")
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            if cid in seen or cid not in by_id:
                continue
            reason = str(it.get("reason", "")).strip()
            if not reason:
                continue
            strategy = str(it.get("strategy", "")).strip().lower()
            still_dangerous = bool(it.get("still_dangerous")) or strategy == "still_dangerous"
            items.append(DistinguishedPrecedent(
                case_id=cid,
                case_citation=by_id[cid].citation,
                reason=reason,
                still_dangerous=still_dangerous,
            ))
            seen.add(cid)
        if not items:
            return None
        return DistinguishingAnalysis(items=items)

    # ── stage 3c-ter: evidence map (burden of proof) ──────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _analyze_evidence_map(
        self,
        user_message: str,
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
        documents: list[dict] | None,
    ) -> EvidenceMap:
        """Build a burden-of-proof map from case facts + retrieved articles.

        Flags burden-shift rules (labor, discrimination, consumer,
        domestic violence — where the law moves the weight onto the
        stronger party). The model is told to cite the article by name
        when it flags a shift, so the citizen can verify.
        """
        if not retrieved:
            return EvidenceMap()

        articles_context = _format_articles_for_prompt(retrieved)
        dossier_hint = format_documents_for_prompt(documents or [], compact=True)
        dossier_block = f"\n{dossier_hint}\n" if dossier_hint else ""

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhja: {triage.problem_summary}
            {dossier_block}
            Nenet e gjetura (kërko te këto rregulla speciale për zhvendosje të barrës së provës):
            {articles_context}

            Ndërto mapën e provës (claims, burden, status) sipas formatit JSON.
        """)

        raw = self.backend.complete(
            system=EVIDENCE_MAP_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1400,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("evidence_map JSON parse failed, returning empty")
            return EvidenceMap()

        claims: list[EvidenceClaim] = []
        valid_bearers = {"qytetari", "kundërshtari", "shteti", "ndarë"}
        valid_status = {"kemi", "mungon", "e dobët", "kontestuese"}
        for item in (data.get("claims") or []):
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim", "")).strip()
            needed = str(item.get("needed_proof", "")).strip()
            if not claim or not needed:
                continue
            bearer_raw = str(item.get("who_bears_burden", "qytetari")).strip().lower()
            bearer: BurdenBearer = (
                bearer_raw if bearer_raw in valid_bearers else "qytetari"  # type: ignore[assignment]
            )
            status_raw = str(item.get("status", "mungon")).strip().lower()
            status: EvidenceStatus = (
                status_raw if status_raw in valid_status else "mungon"  # type: ignore[assignment]
            )
            claims.append(EvidenceClaim(
                claim=claim,
                needed_proof=needed,
                who_bears_burden=bearer,
                burden_shift=bool(item.get("burden_shift", False)),
                status=status,
                notes=str(item.get("notes", "")).strip(),
            ))
        return EvidenceMap(claims=claims[:6])

    # ── stage 3c-quater: nullity / deadline radar ─────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _scan_nullities(
        self,
        user_message: str,
        triage: TriageResult,
        retrieved: list[tuple[Article, float]],
        documents: list[dict] | None,
    ) -> NullityRadar:
        """Scan for procedural nullities / forfeiture deadlines / prescription.

        The output is often the single highest-leverage part of a legal
        reply. A valid nullity claim can dispose of the opposing side's
        act without the merits being reached; a missed forfeiture
        deadline is the most expensive mistake a citizen can make.
        We run this even when retrieval returned nothing — procedural
        levers come from the fact pattern, not just the article index.
        """
        articles_context = _format_articles_for_prompt(retrieved) if retrieved else "(asnjë)"
        dossier_hint = format_documents_for_prompt(documents or [], compact=True)
        dossier_block = f"\n{dossier_hint}\n" if dossier_hint else ""

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhja: {triage.problem_summary}
            {dossier_block}
            Nenet e gjetura (përdori për të verifikuar citimet e neneve procedurale):
            {articles_context}

            Skeno për pavlefshmëri, afate dekadenciale, parashkrim dhe
            defekte procedurale. Kthe JSON sipas formatit.
        """)

        raw = self.backend.complete(
            system=NULLITY_RADAR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("nullity_radar JSON parse failed, returning empty")
            return NullityRadar()

        valid_kinds = {
            "nullity_absolute", "nullity_relative", "deadline",
            "prescription", "procedural_defect",
        }
        valid_applies = {"kundërshtari", "qytetari", "të dyja"}
        valid_applicable = {"po", "ndoshta", "jo"}

        findings: list[NullityFinding] = []
        for item in (data.get("findings") or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            kind_raw = str(item.get("kind", "procedural_defect")).strip().lower()
            kind: NullityKind = (
                kind_raw if kind_raw in valid_kinds else "procedural_defect"  # type: ignore[assignment]
            )
            applies_raw = str(item.get("applies_to", "qytetari")).strip().lower()
            applies: NullityApplies = (
                applies_raw if applies_raw in valid_applies else "qytetari"  # type: ignore[assignment]
            )
            applicable_raw = str(item.get("citizen_applicable", "ndoshta")).strip().lower()
            applicable: NullityApplicable = (
                applicable_raw if applicable_raw in valid_applicable else "ndoshta"  # type: ignore[assignment]
            )
            findings.append(NullityFinding(
                kind=kind,
                name=name,
                legal_basis=str(item.get("legal_basis", "")).strip(),
                condition=str(item.get("condition", "")).strip(),
                applies_to=applies,
                citizen_applicable=applicable,
                deadline_hint=str(item.get("deadline_hint", "")).strip(),
                consequence=str(item.get("consequence", "")).strip(),
                action=str(item.get("action", "")).strip(),
            ))
            if len(findings) >= 6:
                break

        return NullityRadar(findings=findings)

    # ── stage 3c-quinque: urgency radar ───────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _scan_urgency(
        self,
        user_message: str,
        triage: TriageResult,
        timeline: TimelineAnalysis | None,
        nullity_radar: NullityRadar | None,
        documents: list[dict] | None,
    ) -> UrgencyRadar:
        """Aggregate emergency signals + run a dedicated personal-emergency scan.

        The derivation side is deterministic: timeline deadlines flagged
        expired/critical become critical signals; nullity_radar findings
        with short deadline_hints and citizen_applicable="po" become
        elevated signals. The LLM pass catches what earlier stages miss:
        personal-emergency markers in the fact pattern (arrest, eviction,
        violence, custody intervention) that don't map to an article or
        a deadline but demand action-first framing.
        """
        signals: list[UrgencySignal] = []

        # Deterministic rollup from timeline.
        if timeline and timeline.deadlines:
            for d in timeline.deadlines:
                urg = (getattr(d, "urgency", None) or "").lower()
                if urg not in {"expired", "critical"}:
                    continue
                label = (getattr(d, "label", None)
                         or getattr(d, "description", None)
                         or "Afat ligjor kritik")
                signals.append(UrgencySignal(
                    kind="deadline",
                    label=str(label)[:80],
                    reason=f"Afati është '{urg}' sipas analizës së timeline-it.",
                    severity="critical",
                    deadline=str(getattr(d, "date", "") or getattr(d, "target_date", "") or ""),
                    action="Kontrollo afatin dhe ngri veprimin e kërkuar sa më shpejt.",
                ))

        # Rollup from nullity radar — applicable findings with a deadline
        # hint are time-pressing and belong in the urgency list.
        if nullity_radar and nullity_radar.findings:
            for f in nullity_radar.applicable():
                if not f.deadline_hint:
                    continue
                # Heuristic severity: absolute nullity or explicit "ditë"
                # wording in the hint signals tight timing.
                hint_lower = f.deadline_hint.lower()
                is_critical = (
                    f.kind == "nullity_absolute"
                    or "ditë" in hint_lower
                    or "orë" in hint_lower
                )
                signals.append(UrgencySignal(
                    kind="deadline",
                    label=f.name[:80],
                    reason=(f.condition or f.consequence or
                            "Afat procedural që rrezikon humbjen e së drejtës."),
                    severity="critical" if is_critical else "elevated",
                    deadline=f.deadline_hint,
                    action=(f.action or
                            "Ngri pretendimin brenda afatit, me nenin përkatës."),
                ))

        # LLM pass for personal-emergency markers the rollup can't see.
        dossier_hint = format_documents_for_prompt(documents or [], compact=True)
        dossier_block = f"\n{dossier_hint}\n" if dossier_hint else ""

        prompt = textwrap.dedent(f"""\
            Rasti i qytetarit (lexo me sy të avokatit të emergjencës):
            \"\"\"{user_message}\"\"\"

            Përmbledhja: {triage.problem_summary}
            {dossier_block}
            Dallo nëse ky është pyetje teorike ose emergjencë e vërtetë.
            Kthe JSON me level + signals.
        """)

        raw = self.backend.complete(
            system=URGENCY_SCAN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            fast=True,
        )
        try:
            data = _parse_json_block(raw)
        except Exception:
            log.warning("urgency_scan JSON parse failed, using rollup only")
            data = {"level": "none", "signals": []}

        valid_kinds = {
            "arrest", "eviction", "dismissal", "violence", "custody",
            "customs", "deadline", "enforcement", "other",
        }
        valid_severity = {"critical", "elevated"}
        for item in (data.get("signals") or []):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            kind_raw = str(item.get("kind", "other")).strip().lower()
            kind: UrgencyKind = (
                kind_raw if kind_raw in valid_kinds else "other"  # type: ignore[assignment]
            )
            sev_raw = str(item.get("severity", "elevated")).strip().lower()
            severity: UrgencySeverity = (
                sev_raw if sev_raw in valid_severity else "elevated"  # type: ignore[assignment]
            )
            signals.append(UrgencySignal(
                kind=kind,
                label=label[:100],
                reason=str(item.get("reason", "")).strip(),
                severity=severity,
                deadline=str(item.get("deadline", "")).strip(),
                action=str(item.get("action", "")).strip(),
            ))
            if len(signals) >= 6:
                break

        # Final level is the highest severity present across all sources
        # (rollup + LLM). The LLM's reported level is used as a hint but
        # superseded by what we actually have.
        if any(s.severity == "critical" for s in signals):
            level: UrgencyLevel = "critical"
        elif signals:
            level = "elevated"
        else:
            level = "none"

        return UrgencyRadar(level=level, signals=signals)

    # ── stage 3c-bis: cross-document contradiction detector (V6.8) ──────────

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _detect_contradictions(
        self,
        documents: list[dict] | None,
    ) -> ContradictionReport:
        """Scan the dossier for inter-document inconsistencies.

        Only runs when there are at least 2 documents with usable
        content — with a single doc (or only placeholders) there's
        nothing to cross-check. Uses each document's key_facts +
        summary + the first ~2k chars of extracted_text as input.
        Output is validated and capped at 5; doc_refs returned by
        the model are grounded against the real filenames we sent
        so the prompt never displays hallucinated filenames.
        """
        # Filter docs that carry actual content. A pending-OCR doc
        # with empty summary / empty key_facts / empty extracted
        # text is noise for the detector — it triggers "no signals"
        # patterns that dilute the real cross-doc scan.
        docs = [
            d for d in (documents or [])
            if (d.get("summary") or "").strip()
            or (d.get("key_facts") or [])
            or (d.get("extracted_text") or "").strip()
        ]
        if len(docs) < 2:
            return ContradictionReport()

        blocks: list[str] = []
        for d in docs:
            filename = d.get("filename", "?")
            doc_type = d.get("doc_type") or "?"
            summary = d.get("summary") or ""
            key_facts = d.get("key_facts") or []
            extracted = (d.get("extracted_text") or "").strip()
            # Keep each doc snippet bounded; the detector doesn't need
            # the whole PDF, just enough for parties/dates/amounts.
            snippet = extracted[:2000]
            kf_lines = "\n".join(f"    • {kf}" for kf in key_facts[:8])
            block = textwrap.dedent(f"""\
                ── SKEDAR: {filename}  (lloji: {doc_type})
                   Përmbledhja: {summary}
                   Fakte kyçe:
                {kf_lines if kf_lines else '    (asnjë)'}
                   Tekst i ekstraktuar (fragment):
                   {snippet if snippet else '(nuk ka tekst të ekstraktuar)'}
            """).rstrip()
            blocks.append(block)

        dossier_text = "\n\n".join(blocks)
        prompt = textwrap.dedent(f"""\
            DOSJA E QYTETARIT — {len(docs)} dokumente:

            {dossier_text}

            Kontrollo kontradiktat sipas udhëzimeve të sistemit.
            Kthe VETËM JSON me fushën "items".
        """)

        try:
            raw = self.backend.complete(
                system=CONTRADICTION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                fast=True,
            )
            data = _parse_json_block(raw)
        except Exception as exc:
            log.warning("contradiction_detector failed: %s", exc)
            return ContradictionReport()

        valid_kinds = {
            "date", "amount", "party", "signature",
            "narrative", "procedure", "other",
        }
        valid_sev = {"high", "medium", "low"}
        # Real filenames we sent to the model — the only strings we
        # accept as doc_refs. Anything else is a hallucination and
        # would render as a ghost filename in the panel.
        real_filenames = {
            d.get("filename", "").strip()
            for d in docs if d.get("filename")
        }
        items: list[Contradiction] = []
        for it in (data.get("items") or []):
            if not isinstance(it, dict):
                continue
            desc = str(it.get("description", "")).strip()
            if not desc:
                continue
            refs_raw = it.get("doc_refs") or []
            if not isinstance(refs_raw, list):
                continue
            doc_refs = _validate_doc_refs(refs_raw, real_filenames)
            if len(doc_refs) < 2:
                # A real contradiction needs at least two conflicting
                # sources that actually exist in the dossier. Anything
                # less is either noise or invention.
                continue
            kind_raw = str(it.get("kind", "other")).strip().lower()
            kind: ContradictionKind = (
                kind_raw if kind_raw in valid_kinds else "other"  # type: ignore[assignment]
            )
            sev_raw = str(it.get("severity", "medium")).strip().lower()
            severity: ContradictionSeverity = (
                sev_raw if sev_raw in valid_sev else "medium"  # type: ignore[assignment]
            )
            cv_raw = it.get("conflicting_values") or {}
            conflicting = (
                {str(k): str(v) for k, v in cv_raw.items()}
                if isinstance(cv_raw, dict) else {}
            )
            items.append(Contradiction(
                kind=kind,
                description=desc[:240],
                doc_refs=doc_refs[:4],
                conflicting_values=conflicting,
                severity=severity,
                implication=str(it.get("implication", "")).strip()[:240],
            ))
            if len(items) >= 5:
                break

        # Sort high → medium → low so the most strategic contradictions
        # render first in the panel and appear first in the prompt.
        sev_order = {"high": 0, "medium": 1, "low": 2}
        items.sort(key=lambda c: sev_order.get(c.severity, 9))
        return ContradictionReport(items=items)

    # ── stage 3c-ter: consolidated action plan (V6.7) ──────────────────────

    def _build_action_plan(
        self,
        triage: TriageResult,
        urgency_radar: UrgencyRadar | None,
        nullity_radar: NullityRadar | None,
        evidence_map: EvidenceMap | None,
        comparison: PrecedentComparison | None,
        premortem: Premortem | None,
        contradictions: ContradictionReport | None = None,
    ) -> ActionPlan:
        """Merge, dedupe, and rank actions from every upstream stage.

        The rollup is deterministic: each stage's action-bearing field is
        harvested with its source tag. Then a single fast-model pass
        takes the raw candidate list and returns a ranked, deduped,
        time-bucketed checklist. If the LLM pass fails we fall back to
        the raw rollup sorted by a simple heuristic so the citizen still
        sees a plan. Empty input → empty plan (no noisy LLM call).
        """
        candidates: list[dict] = []

        # Urgency signals always win priority — they are by definition
        # time-sensitive. Each becomes a "sot" candidate.
        if urgency_radar and not urgency_radar.is_empty():
            for s in urgency_radar.signals:
                if not s.action:
                    continue
                candidates.append({
                    "text": s.action,
                    "bucket": "sot",
                    "source": "urgency",
                    "reason": s.label or s.reason[:60],
                    "severity": s.severity,
                })

        # Nullity findings with deadline_hint are time-pressing;
        # without one, they're this-week procedural moves.
        if nullity_radar and not nullity_radar.is_empty():
            for f in nullity_radar.applicable():
                if not f.action:
                    continue
                hint = (f.deadline_hint or "").lower()
                bucket = ("sot" if ("ditë" in hint or "orë" in hint
                                     or f.kind == "nullity_absolute")
                          else "kjo_javë")
                candidates.append({
                    "text": f.action,
                    "bucket": bucket,
                    "source": "nullity",
                    "reason": f.consequence or f.condition or f.name,
                    "legal_basis": f.legal_basis or "",
                })

        # Evidence gathering — mungon/e dobët/kontestuese claims get a
        # this-week bucket (proof rots; dashcams overwrite, witnesses
        # forget). "kemi" claims are skipped — no action needed.
        if evidence_map and not evidence_map.is_empty():
            for c in evidence_map.claims:
                if c.status == "kemi" or not c.notes:
                    continue
                candidates.append({
                    "text": c.notes,
                    "bucket": "kjo_javë",
                    "source": "evidence",
                    "reason": f"Provë për '{c.claim[:50]}' ({c.status})",
                })

        # Decisive-difference gap-closers — same as evidence, this-week
        # unless the status is "po" (already have it, no action).
        if comparison and not comparison.is_empty():
            for d in comparison.decisive_differences:
                if d.citizen_status == "po" or not d.action:
                    continue
                candidates.append({
                    "text": d.action,
                    "bucket": "kjo_javë",
                    "source": "difference",
                    "reason": f"Fitoret kanë {d.attribute[:40]}",
                })

        # Pre-mortem mitigations — month-level unless the risk is high
        # (then this-week, because a high-severity risk with no mitigation
        # is how cases get lost).
        if premortem and not premortem.is_empty():
            for r in premortem.risks:
                if not r.mitigation:
                    continue
                bucket = "kjo_javë" if r.severity == "high" else "ky_muaj"
                candidates.append({
                    "text": r.mitigation,
                    "bucket": bucket,
                    "source": "premortem",
                    "reason": r.risk[:70],
                })

        # Cross-document contradictions (V6.9) — a high-severity
        # contradiction is a strategic lever: the citizen must raise
        # it in court or at the negotiating table or it sits unused.
        # High → kjo_javë (it's usable evidence, not a same-day
        # emergency). Medium → ky_muaj. Low doesn't become an action
        # at all — too noisy to clutter the plan.
        if contradictions and not contradictions.is_empty():
            for c in contradictions.items:
                if c.severity == "low":
                    continue
                bucket = "kjo_javë" if c.severity == "high" else "ky_muaj"
                # Action text is imperative and cites the filenames so
                # the model's dedup pass knows *which* contradiction.
                refs = ", ".join(c.doc_refs[:2]) if c.doc_refs else "dosjen"
                text = (
                    f"Ngri kontradiktën '{c.description[:80]}' "
                    f"(mes {refs}) në gjykatë ose në negociim."
                )
                candidates.append({
                    "text": text,
                    "bucket": bucket,
                    "source": "contradiction",
                    "reason": c.implication[:90] or f"kontradiktë {c.kind}",
                })

        if not candidates:
            return ActionPlan()

        # Fast-model dedup + ranking pass. We send the candidates as JSON
        # so the model can reason over them; it returns the cleaned plan.
        cand_json = json.dumps(candidates, ensure_ascii=False, indent=2)
        prompt = textwrap.dedent(f"""\
            Rasti: {triage.problem_summary}

            Kandidatët e mbledhur (nga analizat paraprake):
            {cand_json}

            Prodho planin e veprimit sipas udhëzimeve të sistemit.
        """)

        try:
            raw = self.backend.complete(
                system=ACTION_PLAN_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1600,
                fast=True,
            )
            data = _parse_json_block(raw)
        except Exception as exc:
            log.warning("action_plan LLM pass failed: %s — using raw rollup", exc)
            return self._fallback_action_plan(candidates)

        valid_buckets = {"sot", "kjo_javë", "ky_muaj", "më_vonë"}
        valid_sources = {
            "urgency", "nullity", "evidence", "difference", "premortem",
            "contradiction", "other",
        }
        items: list[ActionItem] = []
        for it in (data.get("items") or []):
            if not isinstance(it, dict):
                continue
            text = str(it.get("text", "")).strip()
            if not text:
                continue
            bucket_raw = str(it.get("bucket", "kjo_javë")).strip()
            bucket: ActionBucket = (
                bucket_raw if bucket_raw in valid_buckets else "kjo_javë"  # type: ignore[assignment]
            )
            source_raw = str(it.get("source", "other")).strip().lower()
            source: ActionSource = (
                source_raw if source_raw in valid_sources else "other"  # type: ignore[assignment]
            )
            try:
                priority = int(it.get("priority", 3))
            except (TypeError, ValueError):
                priority = 3
            priority = max(1, min(5, priority))
            items.append(ActionItem(
                text=text[:240],
                bucket=bucket,
                priority=priority,
                source=source,
                reason=str(it.get("reason", "")).strip()[:120],
                legal_basis=str(it.get("legal_basis", "")).strip()[:60],
            ))
            if len(items) >= 8:
                break

        # Enforce canonical ordering: bucket order then priority.
        bucket_order = {"sot": 0, "kjo_javë": 1, "ky_muaj": 2, "më_vonë": 3}
        items.sort(key=lambda a: (bucket_order.get(a.bucket, 9), a.priority))

        return ActionPlan(items=items)

    def _fallback_action_plan(self, candidates: list[dict]) -> ActionPlan:
        """Deterministic fallback when the LLM dedup pass fails.

        Takes the raw rollup, dedupes by lowercased text, and buckets
        by the pre-assigned bucket. Priority 1 for urgency, 2 for
        nullity, 3 for evidence/difference, 4 for premortem. This
        guarantees the citizen sees SOMETHING actionable even on
        total LLM failure.
        """
        seen: set[str] = set()
        source_priority = {
            "urgency": 1, "nullity": 2, "contradiction": 2, "evidence": 3,
            "difference": 3, "premortem": 4, "other": 5,
        }
        items: list[ActionItem] = []
        for c in candidates:
            text = c.get("text", "").strip()
            key = text.lower()[:60]
            if not text or key in seen:
                continue
            seen.add(key)
            source = c.get("source", "other")
            items.append(ActionItem(
                text=text[:240],
                bucket=c.get("bucket", "kjo_javë"),  # type: ignore[arg-type]
                priority=source_priority.get(source, 5),
                source=source,  # type: ignore[arg-type]
                reason=c.get("reason", "")[:120],
                legal_basis=c.get("legal_basis", "")[:60],
            ))
        bucket_order = {"sot": 0, "kjo_javë": 1, "ky_muaj": 2, "më_vonë": 3}
        items.sort(key=lambda a: (bucket_order.get(a.bucket, 9), a.priority))
        return ActionPlan(items=items[:8])

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
        distinguishing: DistinguishingAnalysis | None = None,
        evidence_map: EvidenceMap | None = None,
        nullity_radar: NullityRadar | None = None,
        urgency_radar: UrgencyRadar | None = None,
        action_plan: ActionPlan | None = None,
        contradictions: ContradictionReport | None = None,
        session_id: str | None = None,
        documents: list[dict] | None = None,
    ) -> str:
        context = _format_articles_for_prompt(retrieved)
        precedents_block = _format_precedents_block(precedents)
        strategic_block = _format_strategic_block(strategic)
        timeline_block = _format_timeline_block(timeline)
        comparison_block = _format_comparison_block(comparison)
        premortem_block = _format_premortem_block(premortem)
        distinguishing_block = _format_distinguishing_block(distinguishing)
        evidence_map_block = _format_evidence_map_block(evidence_map)
        nullity_block = _format_nullity_block(nullity_radar)
        urgency_block = _format_urgency_block(urgency_radar)
        action_plan_block = _format_action_plan_block(action_plan)
        contradictions_block = _format_contradictions_block(contradictions)
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
            {urgency_block}Pyetja e qytetarit:
            \"\"\"{user_message}\"\"\"

            Përmbledhje e problemit (nga triazhi): {triage.problem_summary}
            {dossier_block}
            Nenet e gjetura nga kodet shqiptare (me rëndësinë zbritëse):
            {context}
            {precedents_block}{comparison_block}{distinguishing_block}{evidence_map_block}{contradictions_block}{nullity_block}{premortem_block}{strategic_block}{timeline_block}{action_plan_block}
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


def _validate_doc_refs(refs_raw: list, valid_filenames: set[str]) -> list[str]:
    """Keep only filenames that actually exist in the dossier.

    Dedups while preserving the model's ordering (the first mention
    tends to be the primary source). Stripping + intersection with
    the real filename set prevents the panel from rendering a ghost
    document the model fabricated to "complete" a contradiction.
    """
    seen: set[str] = set()
    out: list[str] = []
    for r in refs_raw:
        name = str(r).strip()
        if not name or name in seen or name not in valid_filenames:
            continue
        seen.add(name)
        out.append(name)
    return out


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
    lines.append(f"SHKRUAJ {SECTION_REF['deadlines']} DUKE CITUAR dhe datat e mësipërme KUR JANË TË LLOGARITURA (p.sh. 'deri më 14 maj 2026'). Mos rishko skadencat e llogaritura, mos zbut urgjencat. Nëse një afat është shënuar si KALUAR, thuaje hapur dhe sugjero çfarë mund të bëhet ende (p.sh. kërkesë për rikthim në afat).")
    return "\n".join(lines) + "\n"


def _format_comparison_block(cmp: PrecedentComparison | None) -> str:
    """Render the winners/losers pattern + decisive-differences engine.

    V6.4: when decisive_differences is populated, the block spells out —
    attribute by attribute — whether the citizen's case has it, lacks
    it, or is unclear, and gives a concrete action. This is what turns
    a generic comparison into a "your case is missing Z — do Y" engine.
    """
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
    if cmp.decisive_differences:
        status_icon = {"ka": "✅", "mungon": "❌", "e paqartë": "❓"}
        lines.append("")
        lines.append("MOTORI I DIFFERENCAVE VENDIMTARE (atribut → a e ka qytetari?):")
        for d in cmp.decisive_differences:
            icon = status_icon.get(d.citizen_status, "❓")
            lines.append(f"  {icon} {d.attribute} — {d.citizen_status.upper()}")
            if d.winners_have:
                lines.append(f"     Fituesit: {d.winners_have}")
            if d.losers_lacked:
                lines.append(f"     Humbësit: {d.losers_lacked}")
            if d.action:
                lines.append(f"     ▶ Veprim: {d.action}")
    elif cmp.decisive_factors:  # legacy fallback
        lines.append("Faktorët vendimtar (kontrolloji një nga një te rasti):")
        for f in cmp.decisive_factors:
            lines.append(f"  • {f}")
    lines.append("")
    lines.append(
        f"PËRDOR pattern-in dhe diferencat te {SECTION_REF['strategic']} — "
        "për ÇDO atribut me status 'mungon' ose 'e paqartë' trego qytetarit "
        "CILIN VEPRIM duhet të bëjë SOT për ta mbuluar, përpara seancës. "
        "Kjo është pjesa që shumica e avokatëve e humb: nuk mjafton të thuash çfarë "
        "kishin fituesit, duhet të thuash SI t'i arrijë qytetari yt."
    )
    return "\n".join(lines) + "\n"


def _format_evidence_map_block(em: EvidenceMap | None) -> str:
    """Render the burden-of-proof map so the answer argues from evidence reality.

    Each claim lists WHO must prove it and whether the law shifts that
    burden (labor, discrimination, consumer, domestic violence). When
    the citizen is missing key proof, the answer must say so directly;
    when a burden-shift rule applies, the answer must cite it — that's
    often the single most valuable strategic insight in the whole reply.
    """
    if em is None or em.is_empty():
        return ""
    status_icon = {"kemi": "✅", "mungon": "❌", "e dobët": "⚠️", "kontestuese": "❓"}
    bearer_label = {
        "qytetari": "qytetari",
        "kundërshtari": "pala tjetër",
        "shteti": "shteti/akuzuesi",
        "ndarë": "ndarë",
    }
    lines = ["", "── MAPA E PROVËS (kush duhet të provojë çfarë) ──"]
    for i, c in enumerate(em.claims, 1):
        icon = status_icon.get(c.status, "❓")
        bearer = bearer_label.get(c.who_bears_burden, c.who_bears_burden)
        shift = " 🔄 BARRA E ZHVENDOSUR" if c.burden_shift else ""
        lines.append(f"  {i}. {icon} {c.claim}")
        lines.append(f"     Provë e nevojshme: {c.needed_proof}")
        lines.append(f"     Barrë mbi: {bearer}{shift} — status: {c.status}")
        if c.notes:
            lines.append(f"     Shënim: {c.notes}")
    lines.append("")
    lines.append(
        f"PËRDOR mapën te {SECTION_REF['actions']} dhe te {SECTION_REF['strategic']}: për çdo "
        "pretendim me status 'mungon'/'e dobët' thuaji qytetarit HAPUR cilën provë duhet "
        "të mbledhë PARA se të padisë, dhe kur barra është e ZHVENDOSUR (p.sh. në të drejtën "
        "e punës, diskriminim, konsumator, dhunë në familje) CITO nenin që e zhvendos dhe "
        "shpjego që pala tjetër duhet të provojë të kundërtën. Mos kërko nga qytetari prova "
        "që sipas ligjit NUK janë detyra e tij."
    )
    return "\n".join(lines) + "\n"


def _format_urgency_block(ur: UrgencyRadar | None) -> str:
    """Render the urgency radar as the TOP-OF-PROMPT emergency framing.

    When level=critical, this block tells the answer model to re-orient
    the whole response around action NOW — open with what to do today,
    then explain. Elevated level is a wake-up, not a reframing. Empty
    radar contributes nothing (no cognitive noise on theoretical questions).
    """
    if ur is None or ur.is_empty():
        return ""
    kind_icon = {
        "arrest": "🚨",
        "eviction": "🏠",
        "dismissal": "💼",
        "violence": "🛡️",
        "custody": "👶",
        "customs": "🛃",
        "deadline": "⏰",
        "enforcement": "⚖️",
        "other": "❗",
    }
    if ur.level == "critical":
        header = "🚨🚨 RADARI I EMERGJENCËS — NIVEL KRITIK 🚨🚨"
    else:
        header = "⚠️ RADARI I EMERGJENCËS — ALARM I NGRITUR"
    lines = ["", header, ""]
    for i, s in enumerate(ur.signals, 1):
        icon = kind_icon.get(s.kind, "❗")
        sev_tag = "[KRITIK]" if s.severity == "critical" else "[ALARM]"
        lines.append(f"  {i}. {icon} {sev_tag} {s.label}")
        if s.reason:
            lines.append(f"     Pse: {s.reason}")
        if s.deadline:
            lines.append(f"     ⏰ Afati: {s.deadline}")
        if s.action:
            lines.append(f"     ▶ Veprim i menjëhershëm: {s.action}")
    lines.append("")
    if ur.level == "critical":
        lines.append(
            "UDHËZIM I DETYRUESHËM: Ky rast është EMERGJENCË. "
            "HAPE përgjigjen me një paragraf të shkurtër VEPRIMI — çfarë duhet "
            "të bëjë qytetari sot/nesër, pa hyrje teorike. Më pas vazhdo me "
            f"strukturën normale (5 seksionet), por në {SECTION_REF['actions']} "
            "rendit këto veprime si HAPAT E PARË, me afate konkrete. "
            "Toni: i ngrohtë, i qetë, por i drejtpërdrejtë — njeriu ka nevojë "
            "për drejtim, jo për ligjërata."
        )
    else:
        lines.append(
            "UDHËZIM: Ky rast ka afate/rreziqe që duhen adresuar këtë javë. "
            f"Në {SECTION_REF['deadlines']} rendit së pari sinjalet e mësipërme dhe "
            f"në {SECTION_REF['actions']} jep veprimet konkrete për secilin."
        )
    return "\n".join(lines) + "\n\n"


def _format_contradictions_block(cr: ContradictionReport | None) -> str:
    """Render cross-document contradictions for the compose prompt.

    Contradictions are strategic ammo — the answer is instructed to fold
    them into section 2 (how to defend) and section 5 (what makes the
    difference). A high-severity contradiction around dates or signatures
    is often the lever that wins the case before the merits are reached,
    so we make it impossible for the compose model to overlook them.
    """
    if cr is None or cr.is_empty():
        return ""
    kind_label = {
        "date": "DATË",
        "amount": "SHUMË",
        "party": "PALË",
        "signature": "NËNSHKRIM",
        "narrative": "NARRATIVË",
        "procedure": "PROCEDURË",
        "other": "TJETËR",
    }
    sev_label = {"high": "🔴 I LARTË", "medium": "🟡 MESATAR", "low": "🟢 I ULËT"}
    lines = ["", "── KONTRADIKTAT NË DOSJE (kryq i dokumenteve) ──"]
    for i, c in enumerate(cr.items, 1):
        kl = kind_label.get(c.kind, "?")
        sl = sev_label.get(c.severity, "")
        lines.append(f"  {i}. [{kl}] {sl} — {c.description}")
        if c.doc_refs:
            lines.append(f"     Dokumentet: {', '.join(c.doc_refs)}")
        if c.conflicting_values:
            cv = "; ".join(f"{k}: «{v}»" for k, v in c.conflicting_values.items())
            lines.append(f"     Vlerat në konflikt: {cv}")
        if c.implication:
            lines.append(f"     ▶ Implikim: {c.implication}")
    lines.append("")
    lines.append(
        f"PËRDOR këto kontradikta si levë strategjike: integroji te {SECTION_REF['actions']} "
        "(për çdo kontradiktë të severity='high' ose 'medium', shpjego si e "
        f"përdor qytetari në gjykatë) dhe te {SECTION_REF['strategic']} (pse "
        "kjo mospërputhje e ndryshon ekuilibrin e rastit). Mos i anashkalo — "
        "një avokat i mirë i gjen dhe i shfrytëzon."
    )
    return "\n".join(lines) + "\n"


def _format_action_plan_block(ap: ActionPlan | None) -> str:
    """Render the consolidated action plan for the compose prompt.

    The answer model is told to use this exact ordering as the spine of
    section 3 ("Çfarë duhet të bësh") — first the "sot" items, then
    this-week, etc. This avoids the drift where section 3 reinvents a
    different action list that conflicts with the panel the UI shows.
    """
    if ap is None or ap.is_empty():
        return ""
    bucket_label = {
        "sot": "SOT / NESËR",
        "kjo_javë": "KJO JAVË",
        "ky_muaj": "KY MUAJ",
        "më_vonë": "MË VONË",
    }
    source_tag = {
        "urgency": "[emergjencë]",
        "nullity": "[pavlefshmëri]",
        "evidence": "[provë]",
        "difference": "[gap vs fitoret]",
        "premortem": "[mitigim rreziku]",
        "contradiction": "[kontradiktë dosjeje]",
        "other": "",
    }
    by_bucket: dict[str, list[ActionItem]] = {}
    for it in ap.items:
        by_bucket.setdefault(it.bucket, []).append(it)
    lines = ["", "── PLANI I VEPRIMIT (i konsoliduar) ──"]
    for bucket_key in ("sot", "kjo_javë", "ky_muaj", "më_vonë"):
        group = by_bucket.get(bucket_key)
        if not group:
            continue
        lines.append(f"{bucket_label[bucket_key]}:")
        for i, it in enumerate(group, 1):
            tag = source_tag.get(it.source, "")
            basis = f" ({it.legal_basis})" if it.legal_basis else ""
            lines.append(f"  {i}. {it.text}{basis}")
            reason_parts = [p for p in (tag, it.reason) if p]
            if reason_parts:
                lines.append(f"     {' — '.join(reason_parts)}")
    lines.append("")
    lines.append(
        f"PËRDOR këtë plan si shtyllën e {SECTION_REF['actions']}: "
        "rendit veprimet me renditjen e mësipërme (sot → kjo javë → ky muaj), "
        "shpjego shkurt pse secili ka rëndësi, dhe mos shto veprime që nuk janë "
        "këtu. Nëse është listë bosh, dhëno këshillë të përgjithshme; nëse ka "
        f"veprime 'sot', ato janë HAPAT E PARË në pozicionin 1 të {SECTION_REF['actions']}."
    )
    return "\n".join(lines) + "\n"


def _format_nullity_block(nr: NullityRadar | None) -> str:
    """Render the nullity / deadline radar so the answer uses them offensively.

    Only "po"-applicable findings are emphasised in the prompt — they
    are the procedural levers the citizen can actually pull. "Ndoshta"
    findings are listed as a watch-list. This mirrors how a good
    lawyer briefs a client: "here's what we can USE, here's what we
    should WATCH". The consequence + deadline + action triad ensures
    each finding arrives actionable, not just descriptive.
    """
    if nr is None or nr.is_empty():
        return ""
    kind_icon = {
        "nullity_absolute": "🛑",
        "nullity_relative": "⚠️",
        "deadline": "⏰",
        "prescription": "📅",
        "procedural_defect": "⚙️",
    }
    kind_label = {
        "nullity_absolute": "PAVLEFSHMËRI ABSOLUTE",
        "nullity_relative": "PAVLEFSHMËRI RELATIVE",
        "deadline": "AFAT DEKADENCIAL",
        "prescription": "PARASHKRIM",
        "procedural_defect": "DEFEKT PROCEDURAL",
    }
    applicable = [f for f in nr.findings if f.citizen_applicable == "po"]
    watch = [f for f in nr.findings if f.citizen_applicable == "ndoshta"]

    lines = ["", "── RADARI I PAVLEFSHMËRIVE & AFATEVE ──"]
    if applicable:
        lines.append("LEVAT QË MUND TË PËRDORIM (po aplikohet):")
        for i, f in enumerate(applicable, 1):
            icon = kind_icon.get(f.kind, "•")
            label = kind_label.get(f.kind, f.kind.upper())
            basis = f" ({f.legal_basis})" if f.legal_basis else ""
            beneficiary = {
                "qytetari": "në favor tonin",
                "kundërshtari": "në favor të palës tjetër",
                "të dyja": "dypalësh",
            }.get(f.applies_to, "")
            lines.append(f"  {i}. {icon} [{label}] {f.name}{basis}")
            if beneficiary:
                lines.append(f"     Përfitues: {beneficiary}")
            if f.condition:
                lines.append(f"     Kusht: {f.condition}")
            if f.deadline_hint:
                lines.append(f"     ⏰ Afati: {f.deadline_hint}")
            if f.consequence:
                lines.append(f"     Pasoja: {f.consequence}")
            if f.action:
                lines.append(f"     ▶ Veprim: {f.action}")
    if watch:
        lines.append("")
        lines.append("NËN VËZHGIM (ndoshta aplikohet — kontrollo):")
        for f in watch:
            icon = kind_icon.get(f.kind, "•")
            basis = f" ({f.legal_basis})" if f.legal_basis else ""
            lines.append(f"  {icon} {f.name}{basis} — {f.condition or '?'}")
    lines.append("")
    lines.append(
        f"INTEGRO radarin te {SECTION_REF['actions']} DHE te {SECTION_REF['deadlines']}: "
        "për çdo gjetje 'po', shpjego qytetarit HAPUR — me nenin e saktë — SI ta ngrejë "
        "në gjykatë dhe brenda cilit afat. Këto janë levat që shumicën e rasteve e fitojnë "
        "pa u prekur tema. Nëse ka afat dekadencial ose parashkrim që rrjedh kundër qytetarit, "
        f"theksoje si të parin në {SECTION_REF['deadlines']}."
    )
    return "\n".join(lines) + "\n"


def _format_distinguishing_block(d: DistinguishingAnalysis | None) -> str:
    """Render the distinguishing output so the answer addresses adverse cites.

    The answer prompt is told to weave each distinguishing reason into
    section 5 when the precedent has been cited there — so the citizen
    learns why an apparently dangerous precedent doesn't control their
    case, instead of being left to worry about it silently.
    """
    if d is None or d.is_empty():
        return ""
    lines = ["", "── DISTINGUISHING (përgjigje për precedentët sfavorizues) ──"]
    for i, item in enumerate(d.items, 1):
        marker = "⚠️ RREZIKSHËM" if item.still_dangerous else "✂ DISTINGUISH"
        lines.append(f"  {i}. [[case:{item.case_id}]] {item.case_citation} — {marker}")
        lines.append(f"     {item.reason}")
    lines.append("")
    lines.append(
        f"PËRDOR këto dallime te {SECTION_REF['strategic']}: nëse në përgjigjen tënde citohet një prej "
        "precedentëve të sipërm, SHPJEGO SAKT pse ai vendim nuk e kontrollon këtë rast "
        "(distinguish) OSE si mbrohemi nga ai (still_dangerous). Mos i fsheh vendimet "
        "sfavorizuese — një avokat i mirë i adreson, nuk i anashkalon."
    )
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
        f"INTEGRO këto rreziqe te {SECTION_REF['strategic']} — për "
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
