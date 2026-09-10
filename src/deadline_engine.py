# -*- coding: utf-8 -*-
"""Motore DETERMINISTICO dei termini (afati / termini processuali).

Perché esiste (spec §13): oggi la DATA di scadenza la calcola l'LLM
(`afati.py`/`deadlines.py` → `backend.complete`). Un termine processuale
sbagliato = decadenza = malpractice. Qui la matematica è Python puro,
testabile e con i passi mostrati. **L'LLM sceglie QUALE regola si applica**
(trigger, durata, unità, feriale sì/no); **il calcolo della data lo fa questo
motore**, mai il modello.

Separazione netta:
  - identificazione della regola  → LLM (grounded sul corpus)
  - aritmetica della data         → questo modulo (deterministico)

NON contiene conclusioni giuridiche: non decide quale termine si applica a un
caso. Riceve una regola già scelta e la calcola. Assistivo: l'avvocato conferma.

I passi e gli avvisi sono BILINGUI (sq/it) perché è testo che l'avvocato legge:
LINGUA = SESSIONE (regola ferrea). La matematica è identica nelle due lingue.

Regole implementate (comuni a procedura AL e IT, salvo dove annotato):
  - `dies a quo non computatur`: nei termini a GIORNI il giorno iniziale non si
    conta — si parte dal giorno dopo (art. 155 c.p.c. IT; Neni 147 KPC AL).
  - termini a MESI/ANNI: scadono nel giorno CORRISPONDENTE del mese finale; se
    quel giorno non esiste (es. 31 gen + 1 mese) → ultimo giorno del mese.
  - `proroga`: se la scadenza cade di sabato/domenica/festivo → primo giorno
    lavorativo successivo (art. 155 c.4 c.p.c. IT; prassi AL).
  - SOSPENSIONE FERIALE ITALIANA (L. 742/1969): termini PROCESSUALI sospesi dal
    1° al 31 agosto → quei giorni non si contano. **Solo IT**; l'Albania non ha
    un equivalente → per AL il flag resta False.

Festività: fisse nazionali + Pasqua CATTOLICA (gregoriana) e, per l'Albania,
anche Pasqua ORTODOSSA (giuliana→gregoriana, calcolata). Limite dichiarato
(meglio un avviso che una data sbagliata): le feste ISLAMICHE mobili (Fitër/
Kurban Bajram) dipendono dall'avvistamento lunare (annunciate per decreto) → NON
si calcolano; in modalità giorni-lavorativi AL il motore AVVISA di verificarle.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

ONE_DAY = _dt.timedelta(days=1)


# ── parsing ────────────────────────────────────────────────────────────────
def parse_date(s) -> _dt.date:
    if isinstance(s, _dt.date):
        return s
    if not isinstance(s, str):
        raise ValueError(f"data non valida: {s!r}")
    return _dt.date.fromisoformat(s.strip()[:10])


# ── Pasqua (Gregoriana / cattolica) — Anonymous Gregorian ────────────────────
def easter_sunday(year: int) -> _dt.date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return _dt.date(year, month, day)


def orthodox_easter_sunday(year: int) -> _dt.date:
    """Pasqua ORTODOSSA (festivo ufficiale in Albania). Computus giuliano
    (Meeus) → data giuliana, poi conversione al gregoriano (+13 giorni, valido
    1900-2099). Deterministico. Verificato: 2024→5 mag, 2025→20 apr."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    julian = _dt.date(year, month, day)
    return julian + _dt.timedelta(days=13)  # giuliano → gregoriano (1900-2099)


# ── festività nazionali (fisse + Pasqua) ─────────────────────────────────────
_IT_FIXED = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}
_AL_FIXED = {(1, 1), (1, 2), (3, 14), (3, 22), (5, 1), (9, 5), (11, 28), (11, 29), (12, 8), (12, 25)}


def holidays(year: int, jurisdiction: str) -> set[_dt.date]:
    j = (jurisdiction or "AL").upper()
    fixed = _IT_FIXED if j == "IT" else _AL_FIXED
    out = {_dt.date(year, m, d) for (m, d) in fixed}
    out.add(easter_sunday(year) + ONE_DAY)  # Lunedì dell'Angelo (Pasqua cattolica)
    if j == "AL":
        # Albania osserva ANCHE la Pasqua ORTODOSSA (calendario giuliano).
        out.add(orthodox_easter_sunday(year) + ONE_DAY)
    return out


def is_holiday(d: _dt.date, jurisdiction: str) -> bool:
    return d in holidays(d.year, jurisdiction)


def is_weekend(d: _dt.date) -> bool:
    return d.weekday() >= 5


def is_business_day(d: _dt.date, jurisdiction: str) -> bool:
    return not is_weekend(d) and not is_holiday(d, jurisdiction)


def next_business_day(d: _dt.date, jurisdiction: str) -> _dt.date:
    cur = d
    while not is_business_day(cur, jurisdiction):
        cur += ONE_DAY
    return cur


def _is_feriale_suspended(d: _dt.date, jurisdiction: str, feriale: bool) -> bool:
    return bool(feriale) and (jurisdiction or "").upper() == "IT" and d.month == 8


# ── aritmetica mesi/anni (giorno corrispondente, clamp a fine mese) ──────────
def add_months(start: _dt.date, n: int) -> _dt.date:
    m0 = start.month - 1 + n
    year = start.year + m0 // 12
    month = m0 % 12 + 1
    if month == 12:
        last = 31
    else:
        last = (_dt.date(year, month + 1, 1) - ONE_DAY).day
    return _dt.date(year, month, min(start.day, last))


def add_years(start: _dt.date, n: int) -> _dt.date:
    return add_months(start, n * 12)


# ── lingua (LINGUA = SESSIONE) ───────────────────────────────────────────────
_WD = {
    "sq": ("e hënë", "e martë", "e mërkurë", "e enjte", "e premte", "e shtunë", "e diel"),
    "it": ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"),
}
_UNITWORD = {
    "sq": {"months": "muaj", "years": "vjet"},
    "it": {"months": "mesi", "years": "anni"},
}
_MSG = {
    "sq": {
        "event": "Ngjarja (dies a quo): {d} ({wd}).",
        "monthyear": "Afat në {uw}: +{n} {uw} → dita përkatëse = {raw} (nëse dita nuk ekziston, dita e fundit e muajit).",
        "from_after": "nga dita pasuese (dies a quo nuk numërohet)",
        "from_incl": "nga dita e ngjarjes e përfshirë",
        "days": "Afat në {kind} ({note}): u numëruan {counted} ditë të vlefshme → {raw}.",
        "kind_cal": "ditë kalendarike",
        "kind_biz": "ditë pune",
        "feriale": "Pezullimi feriale IT (1–31 gusht, L. 742/1969): {n} ditë nuk u numëruan.",
        "skipped_biz": "Ditë jopune të anashkaluara në numërim: {n} (e shtunë/e diel/festa kombëtare).",
        "proroga": "Shtyrje: {raw} ({wd}{fest}) nuk është ditë pune → afati shtyhet në {final} ({wdf}).",
        "fest": " /festë",
        "w_feriale_nonit": "Pezullimi feriale u kërkua por juridiksioni nuk është IT: u shpërfill (Shqipëria nuk ka një pezullim feriale ekuivalent).",
        "w_feriale_monthyear": "Pezullimi feriale NUK zbatohet te afatet në muaj/vjet (afate materiale): u shpërfill.",
        "w_al_mobile": "AL: festat ISLAME të lëvizshme (Fitër Bajrami, Kurban Bajrami) s'janë në tabelë — data shpallet sipas hënës; verifiko nëse bien brenda periudhës (Pashkët katolike+ortodokse llogariten tashmë).",
        "w_det": "Motor determinist: avokati konfirmon RREGULLIN e zbatuar (ngjarja, afati, feriale). Llogaritja e datës verifikohet nga hapat më sipër.",
    },
    "it": {
        "event": "Evento (dies a quo): {d} ({wd}).",
        "monthyear": "Termine a {uw}: +{n} {uw} → giorno corrispondente = {raw} (se il giorno non esiste, ultimo del mese).",
        "from_after": "dal giorno successivo (dies a quo non computatur)",
        "from_incl": "dal giorno dell'evento incluso",
        "days": "Termine a {kind} ({note}): contati {counted} giorni utili → {raw}.",
        "kind_cal": "giorni solari",
        "kind_biz": "giorni lavorativi",
        "feriale": "Sospensione feriale IT (1–31 agosto, L. 742/1969): {n} giorni non contati.",
        "skipped_biz": "Giorni non lavorativi saltati nel conteggio: {n} (sabato/domenica/festivi nazionali).",
        "proroga": "Proroga: {raw} ({wd}{fest}) non è lavorativo → scadenza prorogata al {final} ({wdf}).",
        "fest": " /festivo",
        "w_feriale_nonit": "Sospensione feriale richiesta ma la giurisdizione non è IT: ignorata (l'Albania non ha una sospensione feriale equivalente).",
        "w_feriale_monthyear": "La sospensione feriale NON si applica ai termini a mesi/anni (termini sostanziali): ignorata.",
        "w_al_mobile": "AL: le festività ISLAMICHE mobili (Fitër/Kurban Bajram) non sono in tabella — la data è annunciata secondo la luna; verifica se cadono nel periodo (Pasqua cattolica+ortodossa già calcolate).",
        "w_det": "Motore deterministico: l'avvocato conferma la REGOLA applicata (trigger, durata, feriale). Il calcolo della data è verificabile dai passi qui sopra.",
    },
}


def _wd(d: _dt.date, lang: str) -> str:
    return _WD.get(lang, _WD["sq"])[d.weekday()]


# ── risultato strutturato ────────────────────────────────────────────────────
@dataclass
class DeadlineResult:
    trigger_date: _dt.date
    duration: int
    unit: str
    jurisdiction: str
    feriale_applied: bool
    raw_deadline: _dt.date
    deadline: _dt.date
    rolled: bool
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    legal_basis: str = ""

    def to_dict(self) -> dict:
        return {
            "trigger_date": self.trigger_date.isoformat(),
            "duration": self.duration, "unit": self.unit,
            "jurisdiction": self.jurisdiction, "feriale_applied": self.feriale_applied,
            "raw_deadline": self.raw_deadline.isoformat(),
            "deadline": self.deadline.isoformat(), "rolled": self.rolled,
            "steps": list(self.steps), "warnings": list(self.warnings),
            "legal_basis": self.legal_basis,
        }


_VALID_UNITS = ("days", "business_days", "months", "years")


def compute_deadline(
    trigger_date,
    duration: int,
    unit: str,
    *,
    jurisdiction: str = "AL",
    feriale: bool = False,
    roll_on_holiday: bool = True,
    count_from_day_after: bool = True,
    legal_basis: str = "",
    lang: str = "sq",
) -> DeadlineResult:
    """Calcola la scadenza in modo DETERMINISTICO. I parametri (trigger, durata,
    unità, feriale) sono scelti dall'LLM/avvocato — il motore fa solo l'aritmetica."""
    td = parse_date(trigger_date)
    if not isinstance(duration, int) or duration < 0:
        raise ValueError(f"durata non valida: {duration!r}")
    if unit not in _VALID_UNITS:
        raise ValueError(f"unità non valida: {unit!r} (attese: {_VALID_UNITS})")
    if lang not in _MSG:
        lang = "sq"
    M = _MSG[lang]

    j = (jurisdiction or "AL").upper()
    steps: list[str] = []
    warnings: list[str] = []
    feriale_effective = bool(feriale) and j == "IT"
    if feriale and j != "IT":
        warnings.append(M["w_feriale_nonit"])

    steps.append(M["event"].format(d=td.isoformat(), wd=_wd(td, lang)))

    if unit in ("months", "years"):
        raw = add_months(td, duration if unit == "months" else duration * 12)
        uw = _UNITWORD[lang]["months" if unit == "months" else "years"]
        steps.append(M["monthyear"].format(uw=uw, n=duration, raw=raw.isoformat()))
        if feriale_effective:
            warnings.append(M["w_feriale_monthyear"])
            feriale_effective = False
    else:
        business = unit == "business_days"
        remaining = duration
        cur = td if count_from_day_after else td - ONE_DAY
        counted = skipped_feriale = skipped_nonbiz = 0
        guard = 0
        while remaining > 0:
            guard += 1
            if guard > 400000:
                raise RuntimeError("day-walk non converge (durata anomala)")
            cur += ONE_DAY
            if _is_feriale_suspended(cur, j, feriale_effective):
                skipped_feriale += 1
                continue
            if business and not is_business_day(cur, j):
                skipped_nonbiz += 1
                continue
            counted += 1
            remaining -= 1
        raw = cur
        note = M["from_after"] if count_from_day_after else M["from_incl"]
        kind = M["kind_biz"] if business else M["kind_cal"]
        steps.append(M["days"].format(kind=kind, note=note, counted=counted, raw=raw.isoformat()))
        if skipped_feriale:
            steps.append(M["feriale"].format(n=skipped_feriale))
        if business and skipped_nonbiz:
            steps.append(M["skipped_biz"].format(n=skipped_nonbiz))
        if business and j == "AL":
            warnings.append(M["w_al_mobile"])

    rolled = False
    final = raw
    if roll_on_holiday and not is_business_day(raw, j):
        final = next_business_day(raw, j)
        rolled = True
        fest = M["fest"] if is_holiday(raw, j) else ""
        steps.append(M["proroga"].format(raw=raw.isoformat(), wd=_wd(raw, lang),
                                         fest=fest, final=final.isoformat(), wdf=_wd(final, lang)))

    warnings.append(M["w_det"])

    return DeadlineResult(
        trigger_date=td, duration=duration, unit=unit, jurisdiction=j,
        feriale_applied=feriale_effective, raw_deadline=raw, deadline=final,
        rolled=rolled, steps=steps, warnings=warnings, legal_basis=legal_basis or "",
    )
