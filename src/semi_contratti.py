"""v9.645 — i SEMI dei contratti: le norme che le clausole tipiche chiamano in causa, lette dal TESTO del contratto.

Audit del 17 ott 2026 (sessione AL, contratto di locazione inventato con penale di 50 €/giorno, recesso vietato al conduttore,
risoluzione libera del locatore con 7 giorni, deposito «che non si restituisce in nessun caso», esonero totale da responsabilità,
arbitro nominato dal locatore): il Red Team e la revisione del contratto lavoravano SENZA articoli del corpus — il Red Team ha
letto il Codice civile e la legge sull'arbitrato dal web per 23 minuti (1,5 milioni di token di contesto, la legge 52/2023 da
un PDF di un'università russa, il neni 28 della legge sui consumatori da una versione del 2008: oggi è un'altra norma), la
revisione citava solo i tre articoli scritti nel suo prompt. Il recupero del cervello (triage + ricerca) su un contratto
intero ne porta 12-19 per sei istituti diversi e misurato ne trovava 4 su 10 decisivi (fuori KC 807 sull'esonero del
locatore, 686 sulle condizioni generali, 602 sulla caparra, 655, la legge sui consumatori): qui, per ogni clausola
riconosciuta nel testo, gli articoli che la governano — verificati uno per uno sugli indici (golden [446]).
Solo per gli strumenti che leggono un CONTRATTO (Red Team, revisione): i fatti di una causa non passano di qui.
"""
from __future__ import annotations

import re

# (regex sul testo minuscolo, articoli) — l'ordine è quello in cui entrano nel blocco
_AL: list[tuple[str, tuple[tuple[str, str], ...]]] = [
    # le condizioni generali predisposte da una parte (e il dubbio contro chi le ha scritte): l'ossatura di ogni revisione
    (r".", (("kodi_civil", "686"), ("kodi_civil", "688"))),
    # la locazione: obblighi del locatore, vizi, esonero dalla responsabilità per i vizi (nullo se taciuti in mala fede o se
    # impediscono il godimento), restituzione, fine e rinnovo
    (r"\bqir(?:a|aja|ajë|asë|anë|ane|e)\b|qiradhën|qiramarr",
     (("kodi_civil", "802"), ("kodi_civil", "806"), ("kodi_civil", "807"), ("kodi_civil", "814"), ("kodi_civil", "820"))),
    # la clausola penale e la sua riduzione da parte del giudice
    (r"penalitet|kusht\w* penal|për çdo ditë vones",
     (("kodi_civil", "541"), ("kodi_civil", "544"), ("kodi_civil", "545"))),
    # caparra / deposito (i sostantivi: «depozitoi», «depozitohet» sono il deposito di un atto)
    (r"\bkapar|\bdepozit(?:a|ë|ën|ës)\b", (("kodi_civil", "601"), ("kodi_civil", "602"))),
    # una somma trattenuta «in ogni caso»: l'arricchimento senza causa
    (r"nuk (?:do të )?(?:kthehet|rimbursohet)", (("kodi_civil", "655"),)),
    # l'esonero dalla responsabilità contrattuale
    (r"nuk (?:mban|ka) (?:asnjë )?përgjegjësi|nuk përgjigjet|përjashtohet nga (?:çdo )?përgjegjësi|pa asnjë përgjegjësi",
     (("kodi_civil", "479"),)),
    # la clausola arbitrale: accordo, forma (con il consumatore: separata e firmata), azione davanti al giudice, l'arbitro
    # indipendente e imparziale
    (r"\barbit(?:ër|er|ri|rit|rat|rash|razh)",
     (("ligji_arbitrazhi", "8"), ("ligji_arbitrazhi", "9"), ("ligji_arbitrazhi", "12"), ("ligji_arbitrazhi", "13"))),
    # la clausola sul foro
    (r"gjykat\w* kompetente|juridiksion|kompetenc\w* tokësore", (("kodi_proc_civile", "52"),)),
]

# il consumatore: detto esplicitamente, o una società che dà un'abitazione o vende un bene di consumo a una persona
_AL_KONSUMATOR = r"konsumator"
_AL_TREGTAR = r"sh\.?\s?p\.?\s?k|sh\.?\s?a\.?\b|shoqëri"
_AL_BANIM = r"\bbanim|apartament|shtëpi"

_IT: list[tuple[str, tuple[tuple[str, str], ...]]] = [
    (r".", (("codice_civile", "1341"), ("codice_civile", "1342"))),
    (r"\blocazion|\blocator|\bconduttor|\bcanone\b",
     (("codice_civile", "1575"), ("codice_civile", "1578"), ("codice_civile", "1579"), ("codice_civile", "1590"))),
    (r"\bpenal[ei]\b", (("codice_civile", "1382"), ("codice_civile", "1384"))),
    (r"non rispond\w*|esoner\w*|nessuna responsabilit|esclus\w* (?:ogni|qualsiasi) responsabilit",
     (("codice_civile", "1229"),)),
    (r"\brecede|\brecesso|in qualsiasi momento|risolvere il contratto", (("codice_civile", "1373"),)),
    (r"\barbitr", (("codice_procedura_civile", "806"), ("codice_procedura_civile", "808"),
                   ("codice_procedura_civile", "809"), ("codice_procedura_civile", "810"))),
    (r"\bforo\b|tribunale competente", (("codice_procedura_civile", "28"), ("codice_procedura_civile", "29"))),
]
_IT_LOCAZIONE = r"\blocazion|\blocator|\bconduttor"
_IT_ABITATIVO = r"abitativ|abitazion|appartament"
_IT_DEPOSITO = r"deposito cauzional|cauzion"
_IT_CONSUMATORE = r"consumator"
_IT_IMPRESA = r"s\.?\s?r\.?\s?l\.?|s\.?\s?p\.?\s?a\.?|società"

MAX_SEMI = 20


def semi(testo: str, lingua: str = "sq") -> list[tuple[str, str]]:
    """Gli articoli (codice, numero) che le clausole del contratto chiamano in causa, nell'ordine, senza doppioni."""
    t = " " + " ".join((testo or "").lower().split()) + " "
    out: list[tuple[str, str]] = []

    def _add(chiavi):
        for k in chiavi:
            if k not in out:
                out.append(k)

    # le condizioni generali (prima regola, sempre) e SUBITO il consumatore: con tutte le clausole riconosciute i semi superano il
    # tetto, e le norme sulle clausole abusive non devono essere le prime a cadere
    if (lingua or "sq") == "it":
        _add(_IT[0][1])
        if re.search(_IT_CONSUMATORE, t) or (re.search(_IT_IMPRESA, t) and re.search(_IT_ABITATIVO, t)):
            _add((("codice_consumo", "33"), ("codice_consumo", "36")))
        for rx, chiavi in _IT[1:]:
            if re.search(rx, t):
                _add(chiavi)
        if re.search(_IT_LOCAZIONE, t) and re.search(_IT_ABITATIVO, t):
            _add((("locazioni_abitative", "2"), ("locazioni_abitative", "13")))
        if re.search(_IT_LOCAZIONE, t) and re.search(_IT_DEPOSITO, t):
            _add((("locazioni_immobili_urbani", "11"),))
    else:
        _add(_AL[0][1])
        if re.search(_AL_KONSUMATOR, t) or (re.search(_AL_TREGTAR, t) and re.search(_AL_BANIM, t)):
            _add((("ligji_konsumatoret", "27"),))
        for rx, chiavi in _AL[1:]:
            if re.search(rx, t):
                _add(chiavi)
    return out[:MAX_SEMI]
