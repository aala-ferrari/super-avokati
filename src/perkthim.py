# -*- coding: utf-8 -*-
"""Përkthim ligjor — traduzione giuridica SQ↔IT↔EN dentro la piattaforma.

Perché esiste: un avvocato che incolla l'atto di un cliente su Google
Translate lo sta mandando a un terzo. Qui il documento resta in casa
(stesso DPA del cervello) e la traduzione è GIURIDICA: terminologia
coerente, struttura conservata, niente «miglioramenti» creativi.

Ricetta approvata dal titolare (4 set 2026):
- Opus con effort NORMALE (non max): l'effort compra ragionamento, la
  taglia del modello compra lingua — e per il registro giuridico albanese
  serve il modello grande, non il pensatoio profondo;
- GLOSSARIO VIAGGIANTE: i documenti lunghi si spezzano, e ogni pezzo
  riceve le scelte terminologiche già fatte nei pezzi prima — così
  «masë sigurimi» non cambia veste a pagina 14;
- RILETTURA finale da giurista madrelingua della lingua d'arrivo, che
  leviga il suono e segnala a parte i termini incerti;
- DISCLAIMER sempre: përkthim pune, jo i betuar — mai spacciarsi per
  traduzione giurata (in Albania è un mestiere protetto).

Il testo arriva già estratto (il canale allegati esistente passa PDF e
foto da /api/extract-text, OCR compreso): qui si traduce solo testo.
"""
from __future__ import annotations

import re

# oltre questa soglia un pezzo viaggia da solo (circa 2-3 pagine)
MAX_COPE = 7000
# oltre questa soglia la rilettura integrale costerebbe quanto una seconda
# traduzione: si salta e lo si DICE (mai fingere di aver riletto)
MAX_RILETTURA = 40_000

LINGUA = {"sq": "shqip", "it": "italisht", "en": "anglisht"}
LINGUA_NEL_TARGET = {"sq": "shqip", "it": "italiano", "en": "English"}

DISCLAIMER = {
    "sq": "⚠️ *Përkthim pune nga Super Avokati — nuk zëvendëson përkthyesin e betuar.*",
    "it": "⚠️ *Traduzione di lavoro di Super Avokati — non sostituisce il traduttore giurato.*",
    "en": "⚠️ *Working translation by Super Avokati — not a substitute for a sworn translator.*",
}

_SEGNA_GLOSSAR = "---GLOSSAR---"


# ── funzioni pure (le sorvegliano i golden) ──────────────────────────────

def spezza(testo: str, max_cope: int = MAX_COPE) -> list[str]:
    """Spezza ai confini di paragrafo, conservando ESATTAMENTE i separatori:
    l'invariante è ``"".join(spezza(t)) == t`` — nessun carattere si perde
    né si inventa per strada."""
    if len(testo) <= max_cope:
        return [testo] if testo else []
    # paragrafi CON il loro separatore attaccato (split che cattura)
    grezzi = re.split(r"(\n\s*\n)", testo)
    atomi: list[str] = []
    for i in range(0, len(grezzi), 2):
        pezzo = grezzi[i] + (grezzi[i + 1] if i + 1 < len(grezzi) else "")
        if not pezzo:
            continue
        # paragrafo-mostro: si spezza a righe, e in extremis a fette secche
        while len(pezzo) > max_cope:
            taglio = pezzo.rfind("\n", 1, max_cope)
            if taglio < 1:
                taglio = max_cope
            atomi.append(pezzo[:taglio])
            pezzo = pezzo[taglio:]
        if pezzo:
            atomi.append(pezzo)
    # impacchetta greedy
    cope: list[str] = []
    corrente = ""
    for a in atomi:
        if corrente and len(corrente) + len(a) > max_cope:
            cope.append(corrente)
            corrente = a
        else:
            corrente += a
    if corrente:
        cope.append(corrente)
    return cope


def estrai_glossar(risposta: str) -> tuple[str, dict[str, str]]:
    """Separa la coda ---GLOSSAR--- (se c'è) dal testo tradotto.
    Righe attese: «termine burimor = përkthimi». Robusto all'assenza."""
    pos = risposta.rfind(_SEGNA_GLOSSAR)
    if pos < 0:
        return risposta, {}
    testo = risposta[:pos].rstrip()
    gloss: dict[str, str] = {}
    for riga in risposta[pos + len(_SEGNA_GLOSSAR):].splitlines():
        riga = riga.strip().strip("-•").strip()
        if "=" not in riga:
            continue
        k, _, v = riga.partition("=")
        k, v = k.strip(), v.strip()
        if k and v and len(k) < 120 and len(v) < 120:
            gloss[k] = v
    return testo, gloss


def glossar_testo(gloss: dict[str, str]) -> str:
    if not gloss:
        return "(ende bosh)"
    return "\n".join(f"- {k} = {v}" for k, v in list(gloss.items())[:60])


def attacca_disclaimer(testo: str, target: str) -> str:
    return testo.rstrip() + "\n\n" + DISCLAIMER.get(target, DISCLAIMER["sq"])


# ── prompt ───────────────────────────────────────────────────────────────

def _system_perkthyes(target: str, gloss: dict[str, str]) -> str:
    return f"""Je përkthyes juridik profesionist. Përkthe tekstin e dhënë në {LINGUA[target]} ({LINGUA_NEL_TARGET[target]}).

RREGULLA TË HEKURTA:
1. Gjuha e burimit njihet vetë — mos e pyet përdoruesin.
2. Përkthe GJITHÇKA, pa përmbledhur, pa shtuar, pa «përmirësuar» përmbajtjen: as koment, as opinion, as hyrje — vetëm përkthimi.
3. Ruaj strukturën: numërimin e neneve/pikave, titujt, listat, tabelat, theksimet markdown — si në origjinal.
4. Terminologji juridike E QËNDRUESHME: një term ligjor = një përkthim i vetëm në gjithë dokumentin. Përdor detyrimisht glosarin e mëposhtëm për termat tashmë të vendosur.
5. Emrat e njerëzve, vendeve, institucioneve dhe numrat NUK përkthehen — transkriptohen saktë.
6. Përkthimi duhet të TINGËLLOJË natyrshëm në {LINGUA_NEL_TARGET[target]} juridik — jo fjalë-për-fjalë robotik; kuptimi para gërmës, por pa u larguar nga teksti.

GLOSARI I DERITANISHËM (respektoje):
{glossar_testo(gloss)}

NË FUND — pas përkthimit, në rresht të ri, shto bllokun (deri 15 terma kyç që zgjodhe në KËTË pjesë, të rinj ose të konfirmuar):
{_SEGNA_GLOSSAR}
termi burimor = përkthimi i zgjedhur

Pas bllokut mos shkruaj ASGJË tjetër."""


def _system_rilettura(target: str) -> str:
    return f"""Je jurist me gjuhë amtare {LINGUA[target]} ({LINGUA_NEL_TARGET[target]}). Merr një përkthim juridik dhe LËMOJE që të tingëllojë si i shkruar drejtpërdrejt në {LINGUA_NEL_TARGET[target]} nga një jurist — jo si përkthim.

RREGULLA:
1. Kthe TEKSTIN E PLOTË të lëmuar — asnjë fjali e hequr, asnjë e shtuar, struktura dhe numërimi të paprekur.
2. Ndrequl vetëm: fraza që «tingëllojnë përkthim», terma juridikë jo idiomatikë, mospërputhje terminologjike mes pjesëve.
3. NË FUND, VETËM nëse ke dyshime reale, shto seksionin:
## ⚠️ Terma të pasigurt
- «termi» — alternativa dhe pse
Nëse s'ka dyshime, mos e shto fare seksionin.
4. Asnjë koment tjetër, asnjë hyrje: vetëm teksti."""


# ── orchestrazione ───────────────────────────────────────────────────────

def perkthe(backend, testo: str, target: str,
            callsite: str = "perkthim") -> dict:
    """Traduce a blocchi col glossario viaggiante, poi rilegge. Ritorna
    {markdown, cope, riletto, glossar}."""
    cope = spezza(testo)
    gloss: dict[str, str] = {}
    tradotti: list[str] = []
    for pezzo in cope:
        out = backend.complete(
            system=_system_perkthyes(target, gloss),
            messages=[{"role": "user", "content": pezzo}],
            max_tokens=8000,
            fast=False,
            effort_override="high",  # normale: la lingua la fa il modello, non il pensatoio
            callsite=callsite,
        )
        puro, nuovi = estrai_glossar(out or "")
        for k, v in nuovi.items():
            gloss.setdefault(k, v)  # la PRIMA scelta comanda: coerenza
        tradotti.append(puro.strip())
    unito = "\n\n".join(t for t in tradotti if t)

    riletto = False
    if unito and len(unito) <= MAX_RILETTURA:
        out2 = backend.complete(
            system=_system_rilettura(target),
            messages=[{"role": "user", "content": unito}],
            max_tokens=12000,
            fast=False,
            effort_override="high",
            callsite=callsite + "_rilettura",
        )
        out2 = (out2 or "").strip()
        # paracadute: se la rilettura ha «mangiato» il testo, resta la prima
        if len(out2) >= 0.6 * len(unito):
            unito, riletto = out2, True

    return {
        "markdown": attacca_disclaimer(unito, target),
        "cope": len(cope),
        "riletto": riletto,
        "glossar": gloss,
    }
