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

# v9.655 — LE EQUIVALENZE DI LEGGE AL↔IT, fisse dall'inizio (il glossario viaggiante comincia da qui e la prima scelta comanda).
# Prova col cervello vero (17 ott): «urdhër ekzekutimi» reso «titolo esecutivo» (è l'ORDINE di esecuzione, KPC 511; il titolo
# esecutivo è il KPC 510), «clausola penale» resa «penalitet» (il Kodi Civil dice «kusht penal», nenet 541-545), «atto notarile»
# reso «akt notarial» (in albanese «noterial»). Solo termini dove il codice di ciascun paese ha un nome preciso — niente istituzioni
# (restano col loro nome) né termini ambigui («kërkesëpadi» è citazione o ricorso a seconda del rito).
GLOSSARIO_FISSO = {
    "it": {   # dall'albanese all'italiano
        "urdhër ekzekutimi": "ordine di esecuzione",
        "titull ekzekutiv": "titolo esecutivo",
        "përmbarues gjyqësor": "ufficiale giudiziario",
        "vendim i formës së prerë": "sentenza passata in giudicato",
        "kusht penal": "clausola penale",
        "kapar": "caparra",
        "akt noterial": "atto notarile",
        "prokurë": "procura",
        "kamatvonesë": "interessi moratori",
        "shpenzime gjyqësore": "spese processuali",
        "paditës": "attore",
        "i paditur": "convenuto",
        "masë sigurimi": "misura cautelare",
        "rekurs": "ricorso per cassazione",
    },
    "sq": {   # dall'italiano all'albanese
        "ordine di esecuzione": "urdhër ekzekutimi",
        "titolo esecutivo": "titull ekzekutiv",
        "ufficiale giudiziario": "përmbarues gjyqësor",
        "passata in giudicato": "e formës së prerë",
        "clausola penale": "kusht penal",
        "caparra": "kapar",
        "atto notarile": "akt noterial",
        "rogito notarile": "akt noterial",
        "notaio": "noter",
        "procura": "prokurë",
        "interessi moratori": "kamatvonesë",
        "spese processuali": "shpenzime gjyqësore",
        "attore": "paditës",
        "convenuto": "i paditur",
        "misura cautelare": "masë sigurimi",
        "foro competente": "gjykata kompetente",
    },
}

# la sezione dei termini incerti nella lingua della SESSIONE (LINGUA = SESSIONE: era sempre albanese)
TITOLO_INCERTI = {"sq": "## ⚠️ Terma të pasigurt", "it": "## ⚠️ Termini incerti", "en": "## ⚠️ Uncertain terms"}
LINGUA_SESSIONE = {"sq": "shqip", "it": "italisht", "en": "anglisht"}


def _lingua_sessione() -> str:
    try:
        from .brain import request_jurisdiction
        return "it" if (request_jurisdiction() or "AL").upper() == "IT" else "sq"
    except Exception:  # noqa: BLE001
        return "sq"


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


def _system_rilettura(target: str, sessione: str = "sq") -> str:
    titolo = TITOLO_INCERTI.get(sessione, TITOLO_INCERTI["sq"])
    return f"""Je jurist me gjuhë amtare {LINGUA[target]} ({LINGUA_NEL_TARGET[target]}). Merr një përkthim juridik dhe LËMOJE që të tingëllojë si i shkruar drejtpërdrejt në {LINGUA_NEL_TARGET[target]} nga një jurist — jo si përkthim.

RREGULLA:
1. Kthe TEKSTIN E PLOTË të lëmuar — asnjë fjali e hequr, asnjë e shtuar, struktura dhe numërimi të paprekur.
2. Ndrequl vetëm: fraza që «tingëllojnë përkthim», terma juridikë jo idiomatikë, mospërputhje terminologjike mes pjesëve.
3. Kur të jepet TEKSTI BURIMOR, ai shërben VETËM për krahasim (mos e kthe): çdo term juridik i përkthimit duhet të japë të njëjtin institut si burimi — p.sh. një «urdhër ekzekutimi» nuk bëhet «titolo esecutivo», një «kusht penal» nuk bëhet «penalitet». Termat e glosarit të detyrueshëm mbeten ashtu siç janë:
{glossar_testo(GLOSSARIO_FISSO.get(target, {}))}
4. NË FUND, VETËM nëse ke dyshime reale, shto seksionin — titulli dhe shënimet në {LINGUA_SESSIONE.get(sessione, "shqip")} (gjuha e avokatit që e lexon):
{titolo}
- «termi» — alternativa dhe pse, me fjalë: MOS cito nene, numra ligjesh apo vendime në këtë seksion
Nëse s'ka dyshime, mos e shto fare seksionin.
5. Asnjë koment tjetër, asnjë hyrje: vetëm teksti."""


# ── orchestrazione ───────────────────────────────────────────────────────

def perkthe(backend, testo: str, target: str,
            callsite: str = "perkthim") -> dict:
    """Traduce a blocchi col glossario viaggiante, poi rilegge. Ritorna
    {markdown, cope, riletto, glossar}."""
    cope = spezza(testo)
    gloss: dict[str, str] = dict(GLOSSARIO_FISSO.get(target, {}))   # v9.655: le equivalenze di legge, fisse
    sessione = _lingua_sessione()
    tradotti: list[str] = []
    for pezzo in cope:
        out = backend.complete(
            system=_system_perkthyes(target, gloss),
            messages=[{"role": "user", "content": pezzo}],
            max_tokens=8000,
            fast=False,
            effort_override="high", raw_system=True,  # normale: la lingua la fa il modello, non il pensatoio
            callsite=callsite,
        )
        puro, nuovi = estrai_glossar(out or "")
        for k, v in nuovi.items():
            gloss.setdefault(k, v)  # la PRIMA scelta comanda: coerenza
        tradotti.append(puro.strip())
    unito = "\n\n".join(t for t in tradotti if t)

    riletto = False
    if unito and len(unito) <= MAX_RILETTURA:
        # v9.655: la rilettura vede anche il testo d'origine (prima no: non poteva accorgersi di un istituto reso male)
        _msg2 = (("TEKSTI BURIMOR (vetëm për krahasim — mos e kthe):\n" + testo[:MAX_RILETTURA]
                  + "\n\n=====\nPËRKTHIMI PËR T'U LËMUAR (ktheje të plotë):\n" + unito) if len(testo) <= MAX_RILETTURA else unito)
        out2 = backend.complete(
            system=_system_rilettura(target, sessione),
            messages=[{"role": "user", "content": _msg2}],
            max_tokens=12000,
            fast=False,
            effort_override="high", raw_system=True,
            callsite=callsite + "_rilettura",
        )
        out2 = (out2 or "").strip()
        # v9.655: se ha ripetuto le intestazioni del messaggio, si tiene solo ciò che segue; se ha restituito anche il testo
        # d'origine (troppo lungo) o lo ha «mangiato» (troppo corto), resta la prima traduzione
        _seg = "PËRKTHIMI PËR T'U LËMUAR (ktheje të plotë):"
        if _seg in out2:
            out2 = out2.split(_seg, 1)[1].strip()
        if "TEKSTI BURIMOR" in out2:
            out2 = ""
        # paracadute: se la rilettura ha «mangiato» il testo, resta la prima
        if 0.6 * len(unito) <= len(out2) <= 1.6 * len(unito) + 600:
            unito, riletto = out2, True

    return {
        "markdown": attacca_disclaimer(unito, target),
        "cope": len(cope),
        "riletto": riletto,
        "glossar": gloss,
    }
