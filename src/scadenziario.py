# -*- coding: utf-8 -*-
"""v9.410 — SCADENZIARIO DEL FASCICOLO: dal documento del cliente (il PDF caricato nel fascicolo) le date e i termini che
contano per l'avvocato, PROPOSTI e mai salvati da soli (l'avvocato conferma con un clic: solo allora diventano eventi del
calendario con gli avvisi per email e Telegram).

Chiesto da un avvocato albanese (29 set 2026): «inserisco il fascicolo del cliente in PDF e il cervello mi trova scadenze,
tempistiche, documenti da mandare entro una data, udienze».

Tre cose DIVERSE, e restano separate perché si verificano in modo diverso:
  1. DATE SCRITTE NEL DOCUMENTO (udienza fissata, termine con data, appuntamento, pagamento entro il …): si prendono con la
     frase esatta; la frase e la data si RITROVANO nel testo del documento (calcolo, non modello) o la proposta dice «da
     verificare»;
  2. TERMINI DATI DAL DOCUMENTO in forma relativa («memorie entro 20 giorni dalla comunicazione», «pagare entro 40 giorni dalla
     notifica»): durata e decorrenza dal testo, la DATA la calcola `deadline_engine` (festivi, sospensione feriale); se la data
     di partenza non è nel documento (di solito la notifica) la proposta la chiede all'avvocato;
  3. TERMINI DI LEGGE che il documento FA PARTIRE (sentenza notificata → appello; decreto ingiuntivo → opposizione): passano dal
     motore delle scadenze esistente (`afati.compute`: giorni dall'articolo del corpus, data dal codice), mai dalla memoria.
Il modello (tier medio, senza web: è estrazione) legge; il codice verifica e calcola. Una data che non si ritrova non si
inventa e non si spaccia per certa.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone

from . import afati as _afati
from . import deadline_engine as _de
from .logging_utils import get_logger

log = get_logger(__name__)

TESTO_MAX = 60_000                 # caratteri del documento dati al modello (un fascicolo di ~40 pagine)
MAX_INNESCHI = 3                   # termini di legge calcolati in automatico per documento (ognuno è una chiamata)

_MESI = {
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
           "novembre", "dicembre"],
    "sq": ["janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "nëntor", "dhjetor"],
}
_KIND = {"udienza": "seance", "seance": "seance", "seancë": "seance", "termine": "afat", "afat": "afat",
         "pagamento": "afat", "pagesë": "afat", "invio": "dorëzim", "deposito": "dorëzim", "dorëzim": "dorëzim",
         "appuntamento": "takim", "takim": "takim", "altro": "tjetër", "tjetër": "tjetër"}
_UNITA = {"giorni": "days", "giorno": "days", "dite": "days", "ditë": "days", "days": "days",
          "giorni_lavorativi": "business_days", "dite_pune": "business_days", "ditë_pune": "business_days",
          "business_days": "business_days", "mesi": "months", "mese": "months", "muaj": "months", "months": "months",
          "anni": "years", "anno": "years", "vite": "years", "vjet": "years", "years": "years"}


# ── verifiche deterministiche ────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.replace("­", "")
    s = re.sub(r"-\s*\n\s*", "", s)                      # «notifi-\ncazione»
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
    return re.sub(r"\s+", " ", s).strip()


def citazione_nel_testo(citazione: str, testo: str) -> bool:
    """La frase riportata c'è davvero nel documento? Uguale, o per l'80 % dei suoi pezzi da 5 parole (l'OCR sbaglia qualche
    carattere, il modello accorcia): un'invenzione non passa."""
    c, t = _norm(citazione), _norm(testo)
    if len(c) < 12:
        return False
    if c in t or c[:90] in t:
        return True
    parole = c.split()
    if len(parole) < 5:
        return False
    pezzi = [" ".join(parole[i:i + 5]) for i in range(0, len(parole) - 4, 3)]
    return sum(p in t for p in pezzi) >= max(1, round(len(pezzi) * 0.8))


def _varianti_data(d: date) -> list[str]:
    g, m, a = d.day, d.month, d.year
    out = {f"{g:02d}.{m:02d}.{a}", f"{g}.{m}.{a}", f"{g:02d}/{m:02d}/{a}", f"{g}/{m}/{a}", f"{g:02d}-{m:02d}-{a}",
           f"{g}-{m}-{a}", d.isoformat(), f"{g:02d}.{m:02d}.{a % 100:02d}", f"{g:02d}/{m:02d}/{a % 100:02d}"}
    for mesi in _MESI.values():
        nome = mesi[m - 1]
        out |= {f"{g} {nome} {a}", f"{g:02d} {nome} {a}", f"{g}° {nome} {a}", f"{g} {nome}"}
        if nome.endswith(("r", "t", "l", "j", "s")):      # albanese determinato: «15 shtatorit 2026»
            out.add(f"{g} {nome}it {a}")
    return sorted(out, key=len, reverse=True)


def data_nel_testo(iso: str, testo: str) -> bool:
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return False
    t = _norm(testo)
    t = re.sub(r"(\d)\s*([./-])\s*(\d)", r"\1\2\3", t)   # «15 . 09 . 2026» dell'OCR
    return any(re.search(r"(?<!\d)" + re.escape(v) + r"(?!\d)", t) for v in _varianti_data(d))


def _chiave(*parti) -> str:
    return hashlib.sha1("|".join(_norm(str(p or ""))[:80] for p in parti).encode("utf-8")).hexdigest()[:20]


# ── estrazione ───────────────────────────────────────────────────────────────

def _elenco_trigger(lang: str) -> str:
    tab = _afati.TRIGGERS_IT if lang == "it" else _afati.TRIGGERS
    return "\n".join(f"  · {k} = {v['label']}" for k, v in tab.items())


_SYSTEM = {
    "it": """Sei il praticante di uno studio legale italiano che legge UN documento del fascicolo di un cliente e ne estrae
TUTTO ciò che ha una data o un termine per l'avvocato. Rispondi con UN SOLO oggetto JSON, senza testo fuori:

{"date": [{"tipo": "udienza|termine|invio|pagamento|appuntamento|altro", "titolo": "breve, in italiano",
           "data": "AAAA-MM-GG", "ora": "HH:MM o vuoto", "luogo": "ufficio/aula/autorità o vuoto",
           "cosa_fare": "l'azione concreta per l'avvocato", "citazione": "la frase ESATTA del documento con la data"}],
 "termini": [{"titolo": "…", "durata": 20, "unita": "giorni|giorni_lavorativi|mesi|anni",
              "decorrenza": "da cosa decorre, con le parole del documento (es. «dalla notificazione del presente decreto»)",
              "data_decorrenza": "AAAA-MM-GG se il documento la dice, altrimenti vuoto",
              "processuale": true, "lavoro_o_urgente": false,
              "cosa_fare": "…", "citazione": "la frase ESATTA del documento"}],
 "inneschi": [{"trigger": "una delle chiavi qui sotto",
               "data": "AAAA-MM-GG della NOTIFICA / comunicazione dell'atto se il documento la dice, altrimenti vuoto",
               "data_atto": "AAAA-MM-GG dell'atto stesso (pronuncia, pubblicazione, deposito, emissione) se c'è",
               "descrizione": "l'evento, con autorità e numero (es. «sentenza n. 1234/2026 del Tribunale di Milano, pubblicata il …»)",
               "citazione": "la frase ESATTA del documento"}]}

REGOLE:
- SOLO ciò che è scritto nel documento. Mai una data calcolata da te: «entro 20 giorni dalla notifica» va in "termini", non in
  "date". La data va riportata come AAAA-MM-GG ma deve essere quella scritta.
- "date" = date già scritte (udienza fissata, rinvio al giorno …, deposito entro il giorno …, appuntamento, pagamento entro il …).
- "termini" = durate stabilite DAL DOCUMENTO (dal giudice, dalla controparte, dal contratto, dall'ufficio).
- "inneschi" = il documento è esso stesso un evento che fa partire termini DI LEGGE (sentenza, decreto ingiuntivo, atto di
  citazione ricevuto, licenziamento, avviso di accertamento, verbale di contestazione, ordinanza, misura cautelare…). Chiavi:
{TRIGGER}
  Se nessuna chiave calza, usa "tjeter" e descrivi bene l'evento.
  ATTENZIONE: la data della sentenza o del decreto NON è la data della notifica. "data" = SOLO la data di notifica/comunicazione
  scritta nel documento (relata di notifica, PEC, «notificato il …»); la data dell'atto va in "data_atto".
- "citazione" è copiata parola per parola (massimo 300 caratteri). Se non trovi niente, liste vuote.
- Se il documento dice che un termine è già scaduto o un'udienza già tenuta, riportala comunque: lo valuta l'avvocato.""",
    "sq": """Ti je praktikanti i një studioje ligjore shqiptare që lexon NJË dokument nga dosja e një klienti dhe nxjerr
ÇDO gjë që ka një datë ose një afat për avokatin. Përgjigju me NJË objekt JSON të vetëm, pa tekst jashtë tij:

{"date": [{"tipo": "udienza|termine|invio|pagamento|appuntamento|altro", "titolo": "i shkurtër, në shqip",
           "data": "VVVV-MM-DD", "ora": "OO:MM ose bosh", "luogo": "zyra/salla/autoriteti ose bosh",
           "cosa_fare": "veprimi konkret për avokatin", "citazione": "fjalia E SAKTË e dokumentit me datën"}],
 "termini": [{"titolo": "…", "durata": 15, "unita": "dite|dite_pune|muaj|vite",
              "decorrenza": "nga çfarë nis, me fjalët e dokumentit (p.sh. «nga dita e njoftimit të vendimit»)",
              "data_decorrenza": "VVVV-MM-DD nëse dokumenti e thotë, përndryshe bosh",
              "processuale": true, "lavoro_o_urgente": false,
              "cosa_fare": "…", "citazione": "fjalia E SAKTË e dokumentit"}],
 "inneschi": [{"trigger": "një nga çelësat më poshtë",
               "data": "VVVV-MM-DD e NJOFTIMIT të aktit nëse dokumenti e thotë, përndryshe bosh",
               "data_atto": "VVVV-MM-DD e vetë aktit (shpallja, data e vendimit, lëshimi) nëse ka",
               "descrizione": "ngjarja, me autoritetin dhe numrin (p.sh. «vendimi nr. 1234 i Gjykatës së Rrethit Tiranë, datë …»)",
               "citazione": "fjalia E SAKTË e dokumentit"}]}

RREGULLA:
- VETËM ajo që është shkruar në dokument. Asnjëherë një datë e llogaritur nga ti: «brenda 15 ditëve nga njoftimi» shkon te
  "termini", jo te "date". Data shkruhet VVVV-MM-DD, por duhet të jetë ajo e shkruara.
- "date" = data tashmë të shkruara (seancë e caktuar, shtyrje në datën …, dorëzim deri më …, takim, pagesë deri më …).
- "termini" = afate të caktuara NGA DOKUMENTI (nga gjykata, pala tjetër, kontrata, zyra).
- "inneschi" = vetë dokumenti është ngjarje që nis afate LIGJORE (vendim, urdhër, padi e marrë, pushim nga puna, njoftim
  vlerësimi tatimor, procesverbal kundërvajtjeje, masë sigurimi…). Çelësat:
{TRIGGER}
  Nëse asnjë çelës nuk përshtatet, përdor "tjeter" dhe përshkruaje mirë ngjarjen.
  KUJDES: data e vendimit NUK është data e njoftimit. "data" = VETËM data e njoftimit të shkruar në dokument (fletë-njoftimi,
  «u njoftua më …»); data e vetë vendimit shkon te "data_atto".
- "citazione" kopjohet fjalë për fjalë (maksimumi 300 karaktere). Nëse s'gjen asgjë, lista bosh.
- Nëse dokumenti thotë që një afat ka kaluar ose një seancë është mbajtur, shkruaje gjithsesi: e vlerëson avokati.""",
}


def _json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    try:
        from .json_tollerante import carica as _carica   # v9.402: virgolette non protette, virgole finali, a capo crudi
        d = _carica(m.group(0))
    except Exception:  # noqa: BLE001
        return {}
    return d if isinstance(d, dict) else {}


def estrai(backend, testo: str, nome_file: str, lang: str, oggi: str) -> dict:
    t = testo or ""
    if len(t) > TESTO_MAX:
        t = t[:TESTO_MAX] + ("\n[… il resto del documento è stato tagliato …]" if lang == "it"
                             else "\n[… pjesa tjetër e dokumentit u shkurtua …]")
    system = _SYSTEM[lang].replace("{TRIGGER}", _elenco_trigger(lang))
    prompt = ((f"DATA DI OGGI: {oggi}\nDOCUMENTO: {nome_file}\n\n\"\"\"\n{t}\n\"\"\"\n\nEstrai il JSON.")
              if lang == "it" else
              (f"DATA E SOTME: {oggi}\nDOKUMENTI: {nome_file}\n\n\"\"\"\n{t}\n\"\"\"\n\nNxirr JSON-in."))
    raw = backend.complete(system=system, messages=[{"role": "user", "content": prompt}], max_tokens=4000,
                           medium=True, no_web=True, callsite="scadenziario")
    return _json(raw)


# ── dal JSON alle proposte (verificate) ─────────────────────────────────────

def _iso(s) -> str:
    s = str(s or "").strip()[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return ""


def _ora(s) -> str:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(s or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 else ""


def calcola_regola(regola: dict, data_partenza: str, jurisdiction: str, lang: str) -> dict:
    """Termine dato dal documento («entro 20 giorni dalla notifica») + la data di partenza → data (motore deterministico)."""
    feriale = (jurisdiction == "IT" and bool(regola.get("processuale")) and not bool(regola.get("lavoro_o_urgente")))
    r = _de.compute_deadline(data_partenza, int(regola["durata"]), regola["unita"], jurisdiction=jurisdiction,
                             feriale=feriale, legal_basis=str(regola.get("decorrenza") or ""), lang=lang)
    passi = [s for s in r.steps] + ["⚠ " + w for w in r.warnings]
    if jurisdiction == "IT":
        passi.append(("sospensione feriale (1-31 agosto) applicata: termine processuale — verifica che la materia non ne sia "
                      "esclusa (lavoro, cautelare, urgenze)") if feriale else
                     "sospensione feriale NON applicata (termine non processuale o materia esclusa): verifica")
    return {"data": r.deadline.isoformat(), "passi": passi}


def proposte_da_estrazione(est: dict, testo: str, *, lang: str, jurisdiction: str, oggi: str) -> tuple[list[dict], list[dict]]:
    """(proposte pronte, inneschi da calcolare) — tutto verificato sul testo del documento."""
    out, inneschi = [], []
    L = lang
    for it in (est.get("date") or [])[:40]:
        if not isinstance(it, dict):
            continue
        d, cit = _iso(it.get("data")), str(it.get("citazione") or "")[:400]
        titolo = str(it.get("titolo") or "").strip()[:160]
        if not d or not titolo:
            continue
        c_ok, d_ok = citazione_nel_testo(cit, testo), data_nel_testo(d, testo)
        note = []
        if not c_ok:
            note.append("frase non ritrovata nel documento: verifica" if L == "it" else "fjalia nuk u gjet në dokument: verifikoje")
        if not d_ok:
            note.append("data non ritrovata così nel documento: verifica" if L == "it"
                        else "data nuk u gjet kështu në dokument: verifikoje")
        if d < oggi:
            note.append("data già passata" if L == "it" else "data ka kaluar")
        out.append({"tipo": "data", "kind": _KIND.get(str(it.get("tipo") or "").lower(), "tjetër"), "titolo": titolo,
                    "data": d, "ora": _ora(it.get("ora")), "luogo": str(it.get("luogo") or "")[:160],
                    "cosa_fare": str(it.get("cosa_fare") or "")[:400], "origine": "documento", "citazione": cit,
                    "verificato": c_ok and d_ok, "nota": " · ".join(note),
                    "chiave": _chiave("data", d, titolo)})
    for it in (est.get("termini") or [])[:20]:
        if not isinstance(it, dict):
            continue
        try:
            durata = int(it.get("durata"))
        except (TypeError, ValueError):
            continue
        unita = _UNITA.get(str(it.get("unita") or "").strip().lower())
        titolo = str(it.get("titolo") or "").strip()[:160]
        cit = str(it.get("citazione") or "")[:400]
        if not unita or not titolo or not (0 < durata <= 3650):
            continue
        regola = {"durata": durata, "unita": unita, "decorrenza": str(it.get("decorrenza") or "")[:200],
                  "processuale": bool(it.get("processuale")), "lavoro_o_urgente": bool(it.get("lavoro_o_urgente"))}
        c_ok = citazione_nel_testo(cit, testo)
        durata_ok = bool(re.search(r"(?<!\d)" + str(durata) + r"(?!\d)", _norm(cit))) or _durata_in_lettere(durata, cit)
        dp = _iso(it.get("data_decorrenza"))
        note = []
        if not c_ok:
            note.append("frase non ritrovata nel documento: verifica" if L == "it" else "fjalia nuk u gjet në dokument: verifikoje")
        if not durata_ok:
            note.append("durata non ritrovata nella frase: verifica" if L == "it" else "kohëzgjatja nuk u gjet në fjali: verifikoje")
        base = {"kind": "afat", "titolo": titolo, "cosa_fare": str(it.get("cosa_fare") or "")[:400], "origine": "documento",
                "citazione": cit, "regola_json": json.dumps(regola, ensure_ascii=False)}
        if dp and data_nel_testo(dp, testo):
            try:
                calc = calcola_regola(regola, dp, jurisdiction, L)
            except Exception as exc:  # noqa: BLE001
                log.warning("scadenziario: calcolo del termine fallito (%s): %s", titolo, exc)
                calc = None
            if calc:
                out.append(dict(base, tipo="data", data=calc["data"], verificato=c_ok and durata_ok,
                                base=regola["decorrenza"], nota=" · ".join(note + calc["passi"]),
                                chiave=_chiave("regola", titolo, durata, dp)))
                continue
        note.insert(0, ("serve la data da cui decorre (" + regola["decorrenza"] + ")") if L == "it"
                    else ("duhet data nga e cila nis (" + regola["decorrenza"] + ")"))
        out.append(dict(base, tipo="regola", data="", verificato=c_ok and durata_ok, base=regola["decorrenza"],
                        nota=" · ".join(note), chiave=_chiave("regola", titolo, durata, regola["decorrenza"])))
    tab = _afati.TRIGGERS_IT if L == "it" else _afati.TRIGGERS
    for it in (est.get("inneschi") or [])[:6]:
        if not isinstance(it, dict):
            continue
        trig = str(it.get("trigger") or "").strip()
        if trig not in tab:
            trig = "tjeter"
        d, cit = _iso(it.get("data")), str(it.get("citazione") or "")[:400]
        da = _iso(it.get("data_atto"))
        da = da if (da and data_nel_testo(da, testo)) else ""
        d = d if (d and data_nel_testo(d, testo)) else ""
        # la data dell'atto passata per «notifica» è l'errore da non fare (sentenza del 10/9 → «appello entro il 25/9»): per i
        # trigger che decorrono dalla NOTIFICA una data uguale a quella dell'atto non basta, serve quella della notifica
        if trig in _TRIGGER_DA_NOTIFICA and d and d == da:
            d = ""
        desc = str(it.get("descrizione") or "").strip()[:300] or tab[trig]["label"]
        if da:
            desc = (desc + (" — atto del " if L == "it" else " — akti i datës ") + _data_umana(da, L))[:340]
        inneschi.append({"trigger": trig, "data": d, "data_atto": da, "descrizione": desc,
                         "citazione": cit, "verificato": citazione_nel_testo(cit, testo),
                         "chiave": _chiave("innesco", trig, desc[:80])})
    return out, inneschi


# una base che il motore stesso dichiara non trovata negli articoli dati non è una base verificata
_BASE_INCERTA = re.compile(r"(?i)non tra gli articoli|da confermar|da verificar|nuk (?:është|eshte) (?:midis|ndër)|për t'u verifikuar|verifiko")

# i trigger il cui nome dice «notifica» (afati.TRIGGERS / TRIGGERS_IT): la data giusta è quella in cui l'atto arriva
_TRIGGER_DA_NOTIFICA = {"vendim_penal", "vendim_civil"}

_NUMERI_PAROLE = {"it": {5: "cinque", 10: "dieci", 15: "quindici", 20: "venti", 30: "trenta", 40: "quaranta",
                         45: "quarantacinque", 60: "sessanta", 90: "novanta", 120: "centoventi", 180: "centottanta"},
                  "sq": {5: "pesë", 10: "dhjetë", 15: "pesëmbëdhjetë", 20: "njëzet", 30: "tridhjetë", 45: "dyzet e pesë",
                         60: "gjashtëdhjetë", 90: "nëntëdhjetë", 180: "njëqind e tetëdhjetë"}}


def _durata_in_lettere(n: int, cit: str) -> bool:
    c = _norm(cit)
    return any(v.get(n) and v[n] in c for v in _NUMERI_PAROLE.values())


def termini_di_legge(backend, index, innesco: dict, *, jurisdiction: str, lang: str, data: str) -> list[dict]:
    """L'evento del documento + la sua data → i termini DI LEGGE dal motore esistente (articoli del corpus, data dal codice)."""
    fatti = innesco.get("descrizione") or ""
    if innesco.get("notifica_ignota"):
        fatti += ("\nData della NOTIFICA: sconosciuta — per i termini che decorrono dalla notifica NON dare la riga AFAT "
                  "(descrivili solo nella tabella)." if lang == "it" else
                  "\nData e NJOFTIMIT: e panjohur — për afatet që nisin nga njoftimi MOS jep rreshtin AFAT "
                  "(përshkruaji vetëm në tabelë).")
    r = _afati.compute(backend, index, trigger=innesco["trigger"], event_date=_data_umana(data, lang),
                       facts=fatti, jurisdiction=jurisdiction)
    out = []
    for a in (r.get("afatet") or []):
        d = _iso(a.get("date"))
        if not d:
            continue
        passi = a.get("passi") or []
        out.append({"tipo": "data", "kind": "afat", "titolo": str(a.get("title") or "")[:160], "data": d,
                    "origine": "legge", "citazione": innesco.get("descrizione") or "", "base": a.get("baza") or "",
                    "cosa_fare": "", "verificato": bool(a.get("baza")) and not _BASE_INCERTA.search(a.get("baza") or ""),
                    "nota": " · ".join(passi)[:1500],
                    "chiave": _chiave("legge", d, a.get("title"))})
    return out


def _data_umana(iso: str, lang: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%d.%m.%Y")


def oggi_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def analizza_documento(backend, index, doc, *, jurisdiction: str) -> tuple[list[dict], list[dict]]:
    """Un documento → (proposte, inneschi). I termini di legge con la data nel documento si calcolano subito (al massimo
    MAX_INNESCHI); gli altri restano «innesco» e l'avvocato dà la data (di solito la notifica) con un clic."""
    lang = "it" if (jurisdiction or "AL").upper() == "IT" else "sq"
    testo = getattr(doc, "extracted_text", "") or ""
    if len(testo.strip()) < 40:
        return [], []
    oggi = oggi_iso()
    est = estrai(backend, testo, getattr(doc, "filename", "") or "documento", lang, oggi)
    proposte, inneschi = proposte_da_estrazione(est, testo, lang=lang, jurisdiction=(jurisdiction or "AL").upper(), oggi=oggi)
    calcolati = 0
    for inn in inneschi:
        if not inn["data"] and inn.get("data_atto") and inn["trigger"] not in _TRIGGER_DA_NOTIFICA:
            inn["data"], inn["notifica_ignota"] = inn["data_atto"], True     # arresto, contratto, decreto dalla pronuncia…
        if inn["data"] and calcolati < MAX_INNESCHI:
            try:
                proposte += termini_di_legge(backend, index, inn, jurisdiction=(jurisdiction or "AL").upper(), lang=lang,
                                             data=inn["data"])
                inn["calcolato"] = True
                calcolati += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("scadenziario: termini di legge falliti (%s): %s", inn.get("trigger"), exc)
    return proposte, inneschi
