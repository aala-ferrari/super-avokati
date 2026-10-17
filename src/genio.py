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

import logging
import os

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
    # v9.648 — il web OBBLIGATORIO e illimitato («Bëj SA kërkime web të duhen… mos kurse kohën») esce: le sei menti navigavano
    # 10-17 minuti l'una (1800 s di tetto: 3 lenti in timeout) e saturavano la sottoscrizione (38 lenti «Tetramorph i zënë» su
    # 41 errori dei brief di settembre); e il blocco del caso NON conteneva un solo nene, mentre questa stessa riga chiedeva di
    # basarsi «te nenet e dhëna në kontekst». Ora i nene del corpus sono nel blocco (`web._genio_prepare`), si citano da lì e,
    # in Albania, niente web (il corpus è completo e controllato ogni giorno; la stessa scelta, misurata, del Red Team v9.645).
    # E via l'esempio concreto del Kodi Rrugor (heqja e lejes, alkool zero): il modello copia gli esempi dei prompt.
    # ⚠️ Il guard è CONDIVISO (analisi dei precedenti, corporate, ratio coach, memo del giudice AL, vigilanza): quegli strumenti
    # avevano anche loro «web obbligatorio» — il memo AL perfino con `no_web=True` (il prompt chiedeva ciò che lo strumento non
    # aveva). Qui niente sul web: il «niente web» lo aggiunge solo il Genio (`_guard`), dove le menti albanesi girano senza.
    "NENET — BAZA E ÇDO PËRGJIGJEJE. Çdo nen që citon merre nga nenet e korpusit që të jepen në kontekst (blloku «NENET E "
    "KORPUSIT» ose blloku i neneve të mjetit): numri + kodi ose ligji, fjalë për fjalë kur citon. Një nen që të duket se "
    "mungon thuaje me fjalë («duhet edhe norma për …»), PA numër. Mos cito nene nga kujtesa.\n\n"
    "SHIFRA KONKRETE — kur pyetja prek taksa, tarifa, gjoba apo çmime: jep shifrën vetëm kur del nga një nen i bllokut; "
    "përndryshe thuaj qartë «duhet verifikuar» dhe ku (VKM, tarifa zyrtare). Mos shpik kurrë një shifër.\n\n"
)


GENIO_JURISDICTION_GUARD_IT = (
    "STANDARD DEL RAGIONAMENTO — sei il miglior avvocato senior in Italia: rigoroso, acuto e scaltro. Pensa a FONDO prima di "
    "rispondere; prevedi OGNI mossa della controparte; trova le leve nascoste, le trappole procedurali e i punti deboli; non "
    "lasciare NESSUNA debolezza nella difesa. Ogni affermazione poggia su un articolo concreto o su un precedente reale — niente "
    "congetture, niente superficialità.\n\n"
    "LIMITE DI GIURISDIZIONE — CRITICO. Applichi SOLO il diritto italiano (con il diritto dell'Unione e la CEDU come li applica "
    "il giudice italiano). Nessun diritto di altri Paesi come base: un confronto solo se dichiarato come tale.\n\n"
    "ARTICOLI — LA BASE DI OGNI RISPOSTA. Nel blocco «ARTICOLI DEL CORPUS» hai il testo vigente degli articoli del caso. Ogni "
    "articolo che citi prendilo da lì: numero + atto, parola per parola quando citi. Un articolo che ti sembra mancare dillo a "
    "parole («serve anche la norma su …»), SENZA numero. Non citare articoli a memoria.\n\n"
    "WEB SOLO PER LA GIURISPRUDENZA: se serve una sentenza di Cassazione recente, al massimo 3 ricerche e 4 pagine lette; mai il "
    "PDF intero di un codice o di una legge; la sentenza con gli estremi e la fonte.\n\n"
    "CIFRE CONCRETE: una cifra solo se viene da un articolo del blocco; altrimenti «da verificare» e dove. Mai inventare.\n\n"
)


def _e_it(case_block: str) -> bool:
    return "Juridiksioni: IT" in (case_block or "")


_PA_WEB_SQ = ("PA WEB: korpusi shqiptar i neneve dhe i vendimeve është i plotë dhe kontrollohet çdo ditë me QBZ — mos kërko në "
              "internet.\n\n")
# v9.648 — la FORMA della citazione in ogni campo: misurato sul licenziamento AL, Opus 5.5 scriveva «neni 155», «neni 146/2» senza il
# codice in quasi tutti i campi (89 «senza codice» contro 77 verificate) e il verificatore non li può confermare
_FORMA_CITIMIT_SQ = ("FORMA E CITIMIT — në ÇDO fushë dhe në çdo fjali: numri i nenit BASHKË me kodin ose ligjin («neni [numri] i Kodit "
                     "të Punës», «neni [numri] i Kodit Civil», «neni [numri] i ligjit nr. …»), edhe kur e ke përmendur më sipër; kurrë "
                     "«neni [numri]» i vetëm — pa kodin verifikuesi nuk e konfirmon.\n\n")
_FORMA_CITAZIONE_IT = ("FORMA DELLA CITAZIONE — in OGNI campo e in ogni frase: il numero dell'articolo INSIEME all'atto («art. [N] c.c.», "
                       "«art. [N] L. 604/1966»), anche se l'hai già nominato sopra; mai «art. [N]» da solo — senza l'atto il "
                       "verificatore non lo conferma.\n\n")


def _guard(case_block: str) -> str:
    """v9.648 — il guard della giurisdizione del FASCICOLO (prima sempre quello albanese); in Albania col «niente web»."""
    return (GENIO_JURISDICTION_GUARD_IT + _FORMA_CITAZIONE_IT) if _e_it(case_block) else (GENIO_JURISDICTION_GUARD + _PA_WEB_SQ
                                                                                           + _FORMA_CITIMIT_SQ)


def _web(case_block: str) -> dict:
    """v9.648 — in Albania le sei menti senza web (`no_web`): il corpus è completo; in Italia il web resta per la Cassazione."""
    return {} if _e_it(case_block) else {"no_web": True}


# v9.648 — la combinazione PREDEFINITA delle sei lenti, scelta sulla misura (17 ott, licenziamento orale AL e IT, codice finale):
# Opus 5.5 high sulle tre lenti che TROVANO le norme, Sonnet 5.5 high su albero, verità brutale e stile — 4/4 norme decisive,
# 0 parole dell'altra lingua, 220-246 s e 2,3-2,7 $ contro 281-314 s e 2,6-3,6 $ di Opus 5.5 su tutte; Opus 5 max (il Genio di
# prima) 791-917 s. Chiave della lente → (modello, sforzo), «*» per le altre. L'env la sostituisce: GENIO_MODEL / GENIO_EFFORT
# per tutte, GENIO_MODEL_<CHIAVE> per una.
GENIO_PREDEFINITO: dict[str, tuple[str, str]] = {
    "*": ("opus55", "high"),
    "decision_tree": ("sonnet", "high"),
    "brutal_truth": ("sonnet", "high"),
    "voice": ("sonnet", "high"),
}


def _kw_lente(key: str) -> dict:
    """v9.648 — modello e sforzo di UNA lente, dall'env (letto a ogni chiamata: la misura cambia combinazione nello stesso processo).
    `GENIO_MODEL` / `GENIO_EFFORT` per tutte, `GENIO_MODEL_<CHIAVE>` / `GENIO_EFFORT_<CHIAVE>` per una (KILL_SHOT, LEVERAGE…).
    Valori: «opus» (il senior del cervello, Opus 5 max: il comportamento di prima della v9.648), «opus55» (Opus 5.5), «fable»
    (Fable 5.1), «sonnet» (il tier medio, Sonnet 5.5 con il suo sforzo), oppure un id esplicito. Senza env = `GENIO_PREDEFINITO`."""
    from .config import FABLE_MODEL_ID
    k = (key or "").split(":")[0].upper()
    m = (os.environ.get(f"GENIO_MODEL_{k}") or os.environ.get("GENIO_MODEL") or "").strip()
    e = (os.environ.get(f"GENIO_EFFORT_{k}") or os.environ.get("GENIO_EFFORT") or "").strip()
    if not m:
        m, e_pred = GENIO_PREDEFINITO.get(k.lower(), GENIO_PREDEFINITO["*"])
        e = e or e_pred
    kw: dict = {}
    ml = m.lower()
    if ml == "sonnet":
        kw["medium"] = True
    elif ml == "fable":
        kw["model_override"] = FABLE_MODEL_ID
    elif ml in ("opus55", "opus-5-5", "opus5.5"):
        kw["model_override"] = "claude-opus-5-5"
    elif ml and ml != "opus":
        kw["model_override"] = m
    if e:
        kw["effort_override"] = e
    return kw


_SCHEMA_IT = (("(KC/KPC/Kushtetuta)", "(c.c./c.p.c./Costituzione)"), ('"art. X KC"', '"art. X c.c."'),
              ('"art. X KPC"', '"art. X c.p.c."'), ('"art. ose ligj"', '"art. X + atto"'))
_SCHEMA_AL = (('"art. X KC"', '"neni X KC"'), ('"art. X KPC"', '"neni X KPC"'), ('"art. ose ligj"', '"neni X + ligji"'))


def _adatta_schema(prompt: str, case_block: str) -> str:
    """v9.648 — i segnaposto degli schemi JSON nella forma della giurisdizione: in un fascicolo IT «art. X KC» (un codice
    albanese) spingeva le menti verso il codice sbagliato, in uno albanese «art.» al posto di «neni»."""
    for a, b in (_SCHEMA_IT if _e_it(case_block) else _SCHEMA_AL):
        prompt = prompt.replace(a, b)
    return prompt


def _direttiva_gjuhe(case_block: str) -> str:
    """Fashikull italian → brief VETËM në italisht. I sistemi delle lenti
    sono in albanese: senza questa riga la lingua d'uscita va a fortuna
    (misurato: kill-shot con corpo shqip su un caso IT, 4 set 2026)."""
    if "Juridiksioni: IT" in (case_block or ""):
        # v9.648 — solo italiano: le lenti di un fascicolo IT hanno ora il testo italiano, e una riga albanese in testa al
        # sistema tirava ancora verso l'albanese
        return (
            "LINGUA DELLA RISPOSTA — CRITICO: il fascicolo è italiano. Scrivi TUTTO solo in italiano — ogni frase, ogni "
            "elenco, ogni titolo, nessuna parola albanese.\n\n"
        )
    return ""


# ── Perspective definitions ────────────────────────────────────────────

@dataclass
class Perspective:
    key: str
    label_sq: str
    label_it: str
    system: str
    user_template: str
    max_tokens: int = 2800
    # v9.648 — il testo ITALIANO della lente (fascicolo IT): con le istruzioni solo albanesi Opus 5 max, misurato sul licenziamento
    # orale italiano, scriveva le sei lenti IN ALBANESE (90-199 parole albanesi per lente) e Sonnet 5.5 una lente su sei
    system_it: str = ""
    user_template_it: str = ""


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
            "juridik, jo në sasi argumentimi. Mos sajo nene: merri nga "
            "blloku i neneve; një nen që mungon thuaje me fjalë, pa numër."
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
        system_it="Sei un socio senior di uno studio legale con 25 anni di esperienza. Il tuo talento più grande: vedere la VERA natura giuridica di una questione quando l'avvocato giovane vede solo la superficie. Individui riformulazioni non ovvie: un contratto diventa concorrenza sleale, un illecito diventa arricchimento senza causa, una lite civile diventa abuso di posizione dominante. Pensi alla qualità della qualificazione giuridica, non alla quantità di argomenti. Non inventare articoli: prendili dal blocco degli articoli; un articolo che manca dillo a parole, senza numero.",
        user_template_it='{case_block}\n\nIndividua fino a 3 RIFORMULAZIONI alternative di questa questione, in ordine di percorribilità. Per ciascuna: (a) il nome della tesi giuridica, (b) la base normativa (c.c./c.p.c./Costituzione), (c) perché è più forte o più debole dell\'impostazione attuale, (d) le prove necessarie che mancano.\n\nRestituisci solo JSON pulito, senza preambolo, con lo schema:\n{{\n  "current_framing": "la frase che descrive l\'impostazione attuale",\n  "alternatives": [\n    {{\n      "name": "string",\n      "rank": 1|2|3,\n      "thesis": "1-2 frasi",\n      "legal_basis": ["art. X c.c.", ...],\n      "strength_vs_current": "string",\n      "missing_evidence": ["string", ...],\n      "risk_if_chosen": "1 frase"\n    }}\n  ],\n  "verdict": "raccomandazione finale per l\'avvocato (≤ 3 frasi)"\n}}',
    ),

    Perspective(
        key="kill_shot",
        label_sq="Goditja vdekjeprurëse",
        label_it="Colpo decisivo dell'avversario",
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
        system_it="Sei l'avvocato della controparte. Spietato. Hai letto tutto il fascicolo e devi DISTRUGGERE questa causa domattina. Cerchi: contraddizioni negli atti, cavilli procedurali (termini, giurisdizione, competenza, atti nulli), debolezze probatorie, pretese non provate, esposizione fiscale, terzi non chiamati in causa. Senza pietà.",
        user_template_it='{case_block}\n\nRagiona come l\'avvocato della controparte. Individua i 3 COLPI più letali con cui distruggeresti questa causa, dal più letale al meno letale. Per ciascuno: (a) il tipo (procedurale / sostanziale / probatorio), (b) il meccanismo concreto (quale atto, quale articolo, quale termine), (c) la contromossa che il nostro avvocato deve preparare PRIMA di entrare in aula.\n\nJSON pulito:\n{{\n  "kill_shots": [\n    {{\n      "rank": 1,\n      "kind": "procedural|substantial|evidentiary",\n      "title": "string",\n      "mechanics": "2-3 frasi",\n      "legal_anchor": ["art. X c.p.c.", ...],\n      "lethality": 1-10,\n      "our_counter_prep": "2-3 frasi"\n    }}\n  ],\n  "fatal_combo_warning": "se 2 o più colpi si applicano insieme → cosa succede"\n}}',
    ),

    Perspective(
        key="leverage",
        label_sq="Levat e fshehura",
        label_it="Leve nascoste",
        system=(
            "Ti je këshilltar strategjik për avokat — sheh leva pression "
            "që juristët teknikë i injorojnë: timing (kur ngacmon, kur "
            "rri), ekspozimi reputacional, ekspozimi tatimor, kosto "
            "procesi për palën tjetër, palë të treta që mund të aktivohen "
            "(kreditorë, autoriteti tatimor, vlerësues, konkurrentë), "
            "pikat ku interesi personal i kundërshtarit kontradikton "
            "interesin e tij ligjor. Kurrë kërcënim me kallëzim penal ose me "
            "sinjalizim për të marrë pagesë a marrëveshje: është shtrëngim "
            "(neni 109/b i Kodit Penal); njoftimi se do të ndiqet rruga ligjore "
            "mbetet i lejuar."
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
        system_it="Sei il consulente strategico dell'avvocato: vedi le leve di pressione che i giuristi tecnici ignorano — il tempismo (quando muovere, quando aspettare), l'esposizione reputazionale, l'esposizione fiscale, il costo del processo per la controparte, i terzi che si possono attivare (creditori, amministrazione finanziaria, periti, concorrenti), i punti in cui l'interesse personale della controparte contraddice il suo interesse giuridico. Mai minacciare una denuncia o una segnalazione per ottenere un pagamento o un accordo: è estorsione (annunciare le vie legali resta lecito).",
        user_template_it='{case_block}\n\nIndividua fino a 3 LEVE DI PRESSIONE che l\'avvocato non ha considerato. Per ciascuna: (a) la leva, (b) perché funziona PROPRIO con questa controparte, (c) come si attiva in concreto (lettera, reclamo, segnalazione a un\'autorità, contatto con un terzo), (d) il rischio di effetto boomerang (etico, giuridico, tattico).\n\nRestituisci JSON:\n{{\n  "leverage_points": [\n    {{\n      "rank": 1,\n      "lever": "nome breve",\n      "why_it_works": "2-3 frasi specifiche per questa controparte",\n      "activation": "azione concreta",\n      "ethical_risk": "low|medium|high",\n      "backfire_risk": "1-2 frasi",\n      "legal_basis": ["art. X + atto", ...]\n    }}\n  ],\n  "do_not_use": "le leve che sembrano attraenti ma sono una trappola (1-2 frasi)"\n}}',
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
        system_it='Sei un teorico dei giochi applicato al contenzioso. Pensi per alberi decisionali probabilistici. Ogni nodo ha la nostra mossa + le risposte possibili con le loro probabilità (che sommano a 1,0) + il valore atteso in EUR. Le stime devono essere realistiche, non fantastiche.',
        user_template_it='{case_block}\n\nCostruisci l\'albero decisionale di questa questione, profondo 3 mosse.\n\nRestituisci JSON per la visualizzazione:\n{{\n  "root_label": "la situazione attuale (≤ 8 parole)",\n  "branches": [\n    {{\n      "our_move": "la nostra mossa (≤ 12 parole)",\n      "rationale": "1 frase",\n      "their_responses": [\n        {{\n          "label": "la loro risposta (≤ 10 parole)",\n          "probability": 0.0-1.0,\n          "our_counter": "la nostra contromossa (≤ 12 parole)",\n          "expected_value_eur": number,\n          "duration_months": number\n        }}\n      ]\n    }}\n  ],\n  "recommended_path": "il percorso consigliato in 3 passi (1 frase)",\n  "expected_value_total_eur": number,\n  "dominant_strategy_note": "perché questo percorso domina le alternative"\n}}\n\nLimite: 2-4 rami alla radice, ciascuno con 2-3 their_responses. Le probabilità delle their_responses di ciascun ramo devono sommare ≈ 1,0.',
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
        system_it="Sei l'avvocato che dice al cliente la verità anche quando non vuole sentirla. Onesto sul valore reale della causa, sui costi completi (avvocato + giudizio + tempo + costo emotivo), sulla distanza fra le aspettative del cliente e la realtà, sulla probabilità di vittoria e su cosa va detto ADESSO al cliente prima che il rapporto si rompa. Senza attenuazioni.",
        user_template_it='{case_block}\n\nValuta senza giri di parole. JSON:\n{{\n  "real_value_eur": {{"low": number, "likely": number, "high": number}},\n  "client_probable_expectation_eur": number,\n  "expectation_gap_severity": "low|medium|high|critical",\n  "win_probability": 0.0-1.0,\n  "total_cost_estimate_eur": {{"legal_fees": number, "court_fees": number, "time_value": number, "emotional_cost_label": "low|medium|high"}},\n  "duration_months_realistic": number,\n  "honest_recommendation": "continue|settle_now|withdraw|refer_to_specialist",\n  "what_to_tell_client_today": "la frase esatta (≤ 3 frasi) da dire al cliente al primo incontro",\n  "red_flags_for_lawyer": ["rischio specifico per l\'avvocato (mandato, parcella, reputazione)", ...]\n}}',
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
        system_it="Sei un IMITATORE dello stile di un avvocato specifico. Hai letto i suoi atti precedenti e scrivi paragrafi nuovi indistinguibili dagli originali. Imiti: la scelta delle parole, la lunghezza delle frasi, la formalità, l'uso delle citazioni, il ritmo retorico. Se mancano i campioni di stile, usa uno stile professionale italiano neutro (formale, chiaro, non enfatico).",
        user_template_it="{voice_samples_block}\n\n{case_block}\n\nScrivi i 3 paragrafi di APERTURA del prossimo atto (ricorso, atto di citazione, appello o memoria, secondo il contesto) per questa questione. Senza preambolo, solo il testo pronto da incollare nel documento. Usa lo stile dei campioni sopra.\n\nDopo i paragrafi, aggiungi una riga '---' e una breve nota '(stile imitato da: ...)' che racconta quali tratti stilistici hai imitato (formalità, lunghezza delle frasi, ecc.).",
    ),
]


# ── Output parsing ─────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Find the first complete JSON object in `text`. Best-effort."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no_json_object")
    blob = re.sub(r",(\s*[}\]])", r"\1", m.group(0))  # tolerate trailing commas
    from .json_tollerante import carica as _carica       # v9.402: virgolette interne / a capo crudi
    return _carica(blob)


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
    try:
        from .documents import _lingua_sessione
        it = _lingua_sessione() == "it"
    except Exception:  # noqa: BLE001
        it = False
    if not rows:
        if it:
            return ("CAMPIONI DI STILE: l'avvocato non ha atti precedenti nel sistema. Usa uno stile professionale italiano neutro, "
                    "formale, chiaro. Niente domande retoriche, niente aggettivi superflui.")
        return ("MOSTRA STILI: avokati nuk ka akte të mëparshme në "
                "sistem. Përdor stil profesional shqiptar neutral, "
                "formal, të kthjellët. Mos shto thirrje retorike, mos "
                "përdor mbiemra teprues.")
    parts = ["CAMPIONI DI STILE dagli atti precedenti dell'AVVOCATO (imitane la lettura):" if it else
             "MOSTRA STILI nga akte të mëparshme të AVOKATIT (imiton leximin e tyre):"]
    for i, (kind, txt) in enumerate(rows, 1):
        parts.append(f"\n--- {'Campione' if it else 'Mostra'} {i} ({kind}) ---\n{txt}")
    return "\n".join(parts)


# ── Quanto della macchina puo' prendersi il Genio ──────────────────────
#
# Il semaforo globale delle chiamate al modello (backends) e' 6. Se il Genio
# ne lancia 6 in parallelo li prende TUTTI, e per la durata del giro nessun
# altro avvocato riesce a far partire niente: misurato, 7 minuti di media e
# fino a 33 nel caso peggiore.
#
# Quattro invece di sei lascia due slot sempre liberi per le domande normali.
# Le sei lenti si fanno tutte lo stesso — cambia quante corrono insieme, non
# quante ne corrono — e il giro dura un po' di piu' in cambio di un sistema
# che non si ferma mai per nessuno.
MENTI_PARALLELE = int(os.environ.get("GENIO_PARALLEL", "4"))

# Un Genio alla volta in tutto il sistema. Due giri insieme raddoppierebbero
# il blocco senza far finire prima nessuno dei due: il secondo si accoda, e
# con la notifica di fine lavoro l'attesa non pesa a nessuno.
_genio_sem = threading.Semaphore(int(os.environ.get("GENIO_CONCURRENT", "1")))


# ── Single perspective execution ──────────────────────────────────────

def run_perspective(p: Perspective, *,
                    backend, case_block: str,
                    voice_samples_block: str = "",
                    case_id: str | None = None,
                    attachments: list | None = None) -> dict:
    """Execute one perspective. Returns: {
        "key": str, "label_sq": str, "label_it": str,
        "raw": str (full text response),
        "parsed": dict | None (JSON if extractable, else None),
        "kind": "json" | "text",
        "ms": int, "error": str | None
    }
    """
    _sys, _ut = _testi_lente(p, case_block)
    user_prompt = _adatta_schema(_ut.format(
        case_block=case_block,
        voice_samples_block=voice_samples_block,
    ), case_block)
    t0 = time.monotonic()
    err: str | None = None
    text = ""
    try:
        text = backend.complete(
            system=_direttiva_gjuhe(case_block) + _guard(case_block) + _sys,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=p.max_tokens,
            callsite=f"genio:{p.key}",
            case_id=case_id,
            attachments=attachments or None,
            **_web(case_block),
            **_kw_lente(p.key),
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


# ── Il secondo cervello ────────────────────────────────────────────────

from .logging_utils import get_logger  # v9.337: getLogger(__name__) non aveva handler → INFO persi
log = get_logger(__name__)

from .config import FABLE_MODEL_ID as FABLE_MODEL  # v9.393: nome esplicito (l'alias «fable» dipende dalla versione del CLI)

# Le lenti che devono TROVARE qualcosa. Le altre tre — l'albero delle
# decisioni, la verita' scomoda, la voce — producono comunque un contenuto
# utile anche quando la risposta e' «poco»: non ha senso ritentarle.
LENTI_DA_RITENTARE = ("kill_shot", "leverage", "riframing")


def _a_mani_vuote(res: dict) -> bool:
    """La lente non ha trovato niente di utilizzabile?

    Non basta guardare se c'e' del testo: un modello scrive sempre qualcosa.
    Si guarda se le liste che contano sono vuote — nessun kill shot, nessuna
    leva, nessuna riformulazione — o se il JSON non e' nemmeno uscito.
    """
    if res.get("kind") == "error":
        return True
    parsed = res.get("parsed")
    if not isinstance(parsed, dict):
        # niente JSON: se il testo e' comunque sostanzioso lo teniamo
        return len((res.get("raw") or "").strip()) < 400
    for chiave in ("kill_shots", "leverage_points", "leva", "reframings", "alternatives",
                   "alternative_theories", "points", "items"):
        v = parsed.get(chiave)
        if isinstance(v, list) and v:
            return False
    # nessuna delle liste attese e' popolata: si guarda se almeno c'e' sostanza
    testo = " ".join(str(v) for v in parsed.values() if isinstance(v, str))
    return len(testo.strip()) < 200


SPRONE_FABLE = (
    "\n\n━━━ KUJDES ━━━\n"
    "Një mendje tjetër e ka parë tashmë këtë rast me këtë pyetje dhe "
    "NUK gjeti asgjë të përdorshme. Kjo NUK do të thotë që nuk ka asgjë: "
    "do të thotë që nuk u pa nga ai kënd.\n"
    "Mos e përsërit rrugën e tij. Kërko aty ku nuk shikohet zakonisht: "
    "afate procedurale të harruara, pavlefshmëri formale, mospërputhje midis "
    "dokumenteve, kompetenca, legjitimiteti i palëve, prova të marra në mënyrë "
    "të papranueshme, kontradikta në qëndrimin e kundërshtarit.\n"
    "Nëse edhe pas kësaj vërtet nuk ka asgjë, thuaje qartë — një përgjigje "
    "boshe e ndershme vlen më shumë se një e trilluar."
)


SPRONE_FABLE_IT = (
    "\n\n━━━ ATTENZIONE ━━━\n"
    "Un'altra mente ha già esaminato questo caso con questa domanda e NON ha trovato nulla di utilizzabile. Questo NON vuol dire che "
    "non ci sia niente: vuol dire che non è stato visto da quell'angolo.\n"
    "Non ripetere la sua strada. Cerca dove di solito non si guarda: termini processuali dimenticati, nullità formali, discordanze "
    "fra i documenti, competenza, legittimazione delle parti, prove acquisite in modo inutilizzabile, contraddizioni nella posizione "
    "della controparte.\n"
    "Se anche così davvero non c'è niente, dillo chiaramente — una risposta vuota onesta vale più di una inventata."
)


def _testi_lente(p, case_block: str) -> tuple[str, str]:
    """v9.648 — (system, user_template) della lente nella lingua del fascicolo: in un fascicolo IT il testo italiano, se c'è."""
    if _e_it(case_block) and getattr(p, "system_it", "") and getattr(p, "user_template_it", ""):
        return p.system_it, p.user_template_it
    return p.system, p.user_template


def _seconda_mente(key: str) -> dict:
    """v9.648 — la seconda mente è l'ALTRA: Fable se la lente gira su Opus (come prima), Opus 5 max se gira già su Fable."""
    if (_kw_lente(key).get("model_override") or "") == FABLE_MODEL:
        return {"effort_override": "max"}
    return {"model_override": FABLE_MODEL}


def ritenta_con_fable(res: dict, p: Perspective, *, backend,
                      case_block: str, voice_samples_block: str = "",
                      case_id: str | None = None,
                      attachments: list | None = None) -> dict | None:
    """Rifa' una lente con Fable. Torna None se non c'era motivo di rifarla.

    Il risultato di Opus non viene toccato: questo si affianca, marcato con la
    mente che l'ha prodotto, cosi' l'avvocato sa sempre chi ha detto cosa.
    """
    if p.key not in LENTI_DA_RITENTARE or not _a_mani_vuote(res):
        return None
    _sys, _ut = _testi_lente(p, case_block)
    prompt = _adatta_schema(_ut.format(
        case_block=case_block,
        voice_samples_block=voice_samples_block,
    ), case_block) + (SPRONE_FABLE_IT if _e_it(case_block) else SPRONE_FABLE)
    t0 = time.monotonic()
    try:
        text = backend.complete(
            system=_direttiva_gjuhe(case_block) + _guard(case_block) + _sys,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=p.max_tokens,
            callsite=f"genio:{p.key}:fable",
            case_id=case_id,
            attachments=attachments or None,
            **_seconda_mente(p.key),
            **_web(case_block),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("genio: secondo cervello fallito su %s: %s", p.key, e)
        return None
    parsed = None
    try:
        parsed = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        pass
    fuori = {
        "key": p.key + ":fable",
        "label_sq": p.label_sq + " — mendja e dytë",
        "label_it": p.label_it + " — seconda mente",
        "raw": text, "parsed": parsed,
        "kind": "json" if parsed is not None else "text",
        "ms": int((time.monotonic() - t0) * 1000),
        "error": None,
        "second_brain": True,
    }
    # Se anche Fable torna a mani vuote, non si mostra niente: due risposte
    # vuote una sotto l'altra sono rumore, non trasparenza.
    if _a_mani_vuote(fuori):
        return None
    return fuori


# ── Orchestrator (parallel + streaming events) ─────────────────────────

def run_brief(*, backend, case_block: str, voice_samples_block: str,
              case_id: str | None = None,
              perspectives: list[Perspective] | None = None,
              attachments: list | None = None,
              ) -> Iterator[dict]:
    """Un Genio alla volta, con il semaforo restituito in ogni caso.

    Involucro sottile: tutta la logica resta in `_run_brief`. Serve solo a
    garantire che il semaforo torni libero anche se il giro salta o se chi
    ascolta se ne va a meta'.
    """
    _genio_sem.acquire()
    try:
        yield from _run_brief(
            backend=backend, case_block=case_block,
            voice_samples_block=voice_samples_block, case_id=case_id,
            perspectives=perspectives, attachments=attachments,
        )
    finally:
        _genio_sem.release()


def _run_brief(*, backend, case_block: str, voice_samples_block: str,
              case_id: str | None = None,
              perspectives: list[Perspective] | None = None,
              attachments: list | None = None,
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
    # Chi ha chiesto, catturato prima di lanciare le menti: ognuna gira in
    # un thread suo e senza questo il lavoro piu' pesante del prodotto
    # resterebbe senza padrone nel registro dei consumi.
    try:
        from .brain import request_user_id as _chi, set_request_user as _arma
        _utente_genio = _chi()
    except Exception:  # noqa: BLE001
        _utente_genio, _arma = None, None

    def _runner(p: Perspective):
        if _arma:
            try:
                _arma(_utente_genio)
            except Exception:  # noqa: BLE001
                pass
        res = run_perspective(p, backend=backend,
                              case_block=case_block,
                              voice_samples_block=voice_samples_block,
                              case_id=case_id,
                              attachments=attachments)
        q.put(res)
    # Un cancello prima del lancio: le menti partono a ondate di
    # MENTI_PARALLELE invece che tutte insieme, cosi' il semaforo globale non
    # viene svuotato e le domande normali degli altri avvocati continuano a
    # passare.
    cancello = threading.Semaphore(max(1, MENTI_PARALLELE))
    _runner_vero = _runner

    def _runner(p: Perspective):  # noqa: F811
        with cancello:
            _runner_vero(p)

    threads: list[threading.Thread] = []
    # v9.648 — la giurisdizione del fascicolo anche nei thread delle lenti: senza, il backend accodava a ogni lente di un
    # fascicolo IT «[GJUHA E PËRGJIGJES: VETËM SHQIP…]» (l'ultima riga del messaggio: Opus 5 max ci ha scritto una lente)
    from .brain import porta_contesto as _ctx
    for p in plist:
        t = threading.Thread(target=_ctx(_runner), args=(p,), daemon=True)
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
        # Se la lente e' tornata a mani vuote, la stessa domanda va alla mente
        # piu' scaltra. Solo per le tre lenti che devono trovare qualcosa, e
        # solo quando la prima non ha trovato: se Opus ha visto, Fable non
        # parte e non costa niente.
        p_orig = next((x for x in plist if x.key == res.get("key")), None)
        if p_orig is not None:
            try:
                bis = ritenta_con_fable(
                    res, p_orig, backend=backend, case_block=case_block,
                    voice_samples_block=voice_samples_block,
                    case_id=case_id, attachments=attachments)
            except Exception:  # noqa: BLE001
                bis = None
            if bis:
                by_key[bis["key"]] = bis
                yield {"type": "perspective", "result": bis}
    for t in threads:
        t.join(timeout=5)
    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    yield {"type": "completed", "elapsed_ms": elapsed_ms, "by_key": by_key}


# ── Convenience: build the case_block from db state ────────────────────

# Quanto testo di documenti entra nel contesto, in tutto. È un tetto
# complessivo e non per file di proposito: un contratto da quarantamila
# caratteri, con un tetto per file, si mangerebbe lo spazio degli altri sette.
# v9.446: era 24.000 e il PRIMO documento se lo prendeva tutto (dall'inizio): le sei menti vedevano le prime ~16 pagine del
# fascicolo e mai gli atti più recenti (in fondo), e i documenti dopo il primo nessun testo. Ora il posto si divide fra i documenti
# (i corti interi, ai lunghi il resto in parti uguali) e del documento lungo entrano inizio E fine. `GENIO_BUDGET_DOCUMENTI`.
import os as _os_g  # noqa: E402
BUDGET_DOCUMENTI = int(_os_g.environ.get("GENIO_BUDGET_DOCUMENTI", "48000"))


def _quote_documenti(lunghezze: list[int], budget: int) -> list[int]:
    """Il budget diviso «ad acqua»: chi ha meno della sua parte prende tutto, il resto si ridivide fra gli altri."""
    quote = [0] * len(lunghezze)
    restanti = [i for i, n in enumerate(lunghezze) if n > 0]
    rimasto = budget
    while restanti and rimasto > 0:
        parte = rimasto // len(restanti)
        piccoli = [i for i in restanti if lunghezze[i] - quote[i] <= parte]
        if not piccoli:
            for i in restanti:
                quote[i] += parte
            break
        for i in piccoli:
            rimasto -= lunghezze[i] - quote[i]
            quote[i] = lunghezze[i]
        restanti = [i for i in restanti if i not in piccoli]
    return quote


def _blocco_documenti(documents: list[dict]) -> list[str]:
    """I documenti come li leggerebbe un socio anziano: per intero finché c'è spazio; i lunghi con inizio e fine (v9.446).

    Prima qui arrivavano duecento caratteri di riassunto per file. Sei menti
    che ragionano sette minuti ciascuna su due righe di sommario sono sei menti
    sprecate.
    """
    from .documents import _budget_clip, _lingua_sessione
    it = _lingua_sessione() == "it"
    fuori: list[str] = ["\nDOCUMENTI DEL FASCICOLO:" if it else "\nDOKUMENTET E FASHIKULLIT:"]
    testi = [(d.get("extracted_text") or "").strip() for d in documents]
    quote = _quote_documenti([len(t) for t in testi], BUDGET_DOCUMENTI)
    for d, testo, quota in zip(documents, testi, quote):
        nome = d.get("filename") or "?"
        fuori.append(f"\n── {nome} [{d.get('doc_type') or '?'}] ──")
        sunto = (d.get("summary") or "").strip()
        if sunto:
            fuori.append(("Riassunto: " if it else "Përmbledhje: ") + sunto[:400])
        # un documento che sta nella sua quota entra INTERO (anche di poche righe: la prova [223] ha trovato un avviso di una riga
        # lasciato fuori); uno più lungo con inizio e fine, se la quota è ragionevole
        if testo and (quota >= len(testo) or quota > 300):
            fuori.append(("Testo:\n" if it else "Përmbajtja:\n") + (testo if quota >= len(testo) else _budget_clip(testo, quota)))
        elif d.get("allegato"):
            # niente testo estratto: il file viaggia come allegato vero
            fuori.append("(file allegato — guardalo direttamente)" if it else "(skedar i bashkangjitur — shihe drejtpërdrejt)")
        elif not sunto:
            fuori.append("(nessun testo estratto)" if it else "(pa tekst të nxjerrë)")
    return fuori


def _blocco_precedente(briefs: list[dict] | None) -> list[str]:
    """Cosa aveva concluso il Genio la volta scorsa su questo stesso caso.

    Senza questo, il secondo giro riparte da zero: rianalizza gli stessi fatti
    e riscopre le stesse cose, per quaranta minuti di modello. Con questo
    diventa un aggiornamento — «questo dicevamo, cosa è cambiato» — che è
    esattamente il modo in cui un socio anziano riprende un caso in mano.
    """
    if not briefs:
        return []
    ultimo = briefs[0]
    per_lente = ultimo.get("by_key") or {}
    if not isinstance(per_lente, dict) or not per_lente:
        return []
    quando = (ultimo.get("completed_at") or ultimo.get("started_at") or "")[:10]
    from .documents import _lingua_sessione
    it = _lingua_sessione() == "it"
    fuori = ([
        f"\n━━━ GENIO PRECEDENTE ({quando}) ━━━",
        "Questo caso è già stato analizzato. Sotto ci sono le conclusioni di allora.",
        "NON RIPETERLE: parti da lì, di' cosa è CAMBIATO con i fatti nuovi, cosa regge, cosa cade e cosa non era stato visto.",
    ] if it else [
        f"\n━━━ GJENIO I MËPARSHËM ({quando}) ━━━",
        "Ky rast është analizuar tashmë. Më poshtë janë përfundimet e atëhershme.",
        "MOS I PËRSËRIT: nis prej tyre, thuaj çfarë ka NDRYSHUAR me faktet e reja, "
        "çfarë qëndron, çfarë bie, dhe çfarë nuk ishte parë.",
    ])
    for chiave, ris in per_lente.items():
        grezzo = (ris or {}).get("raw") or ""
        if not grezzo.strip():
            continue
        fuori.append(f"\n[{chiave}] {grezzo.strip()[:700]}")
    fuori.append("\n━━━ FINE DEL GENIO PRECEDENTE ━━━" if it else "\n━━━ FUND I GJENIOS SË MËPARSHME ━━━")
    return fuori


def build_case_block(case, *, jurisdiction: str = "AL",
                     extra_description: str = "",
                     recent_messages: list[dict] | None = None,
                     documents: list[dict] | None = None,
                     previous_briefs: list[dict] | None = None,
                     articles_block: str = "") -> str:
    """Compose the human-readable case context block for prompts.

    v9.648: + `articles_block` — i nene del corpus del caso (il recupero del cervello, `web._genio_prepare`), che prima mancavano
    del tutto: le sei menti citavano a memoria o dal web. Etichette nella lingua del fascicolo; i messaggi del filo fino a 1.500
    caratteri (la testa della risposta del cervello è il verdetto: a 400 restava fuori)."""
    it = (jurisdiction or "AL").upper() == "IT"
    parts: list[str] = []
    parts.append(f"{'CASO' if it else 'ÇËSHTJA'}: {case.title}")
    parts.append(f"Juridiksioni: {jurisdiction}")
    parts.append(f"{'Fase' if it else 'Faza'}: {getattr(case, 'stage', 'intake')}")
    if extra_description:
        parts.append(("\nDESCRIZIONE (dall'avvocato):\n" if it else "\nPËRSHKRIM (nga avokati):\n") + extra_description.strip())
    if documents:
        parts.extend(_blocco_documenti(documents))
    if recent_messages:
        parts.append("\nULTIMI MESSAGGI (avvocato ↔ Super Avokati):" if it else "\nFJALOSJA E FUNDIT (avokati ↔ Super Avokati):")
        for m in recent_messages[-6:]:
            role = ("Avvocato" if it else "Avokati") if m.get("role") == "user" else "Super Avokati"
            content = (m.get("content") or "")[:1500]
            parts.append(f"\n{role}: {content}")
    if articles_block:
        parts.append(("\nARTICOLI DEL CORPUS (testo vigente — cita solo da qui):\n" if it else
                      "\nNENET E KORPUSIT (teksti zyrtar — cito vetëm prej këtu):\n") + articles_block.strip())
    parts.extend(_blocco_precedente(previous_briefs))
    return "\n".join(parts)
