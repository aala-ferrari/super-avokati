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

TESTO_MAX = 60_000                 # caratteri per chiamata al modello (~40 pagine)
# v9.427: un fascicolo più lungo si legge A PEZZI (prima si tagliava a 60.000 caratteri e i termini delle pagine in fondo
# — gli atti più recenti — non esistevano): pezzi sovrapposti, tagliati a un cambio pagina o paragrafo, al massimo PEZZI_MAX
# chiamate; oltre, il resto non letto si dice nel log e nell'analisi.
PEZZI_MAX = 6
SOVRAPPOSIZIONE = 1_500
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


def _numero_it(n: int) -> list[str]:
    """1-99 in lettere (italiano), con le forme accettate: «ventitré»/«ventitre», «ventuno», «ventotto»."""
    u = ["", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove"]
    teen = ["dieci", "undici", "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove"]
    dec = ["", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta"]
    if n < 10:
        return [u[n]]
    if n < 20:
        return [teen[n - 10]]
    t, k = divmod(n, 10)
    if k == 0:
        return [dec[t]]
    base = dec[t][:-1] if k in (1, 8) else dec[t]
    return [base + "tré", base + "tre"] if k == 3 else [base + u[k]]


def _numero_sq(n: int) -> list[str]:
    u = ["", "një", "dy", "tre", "katër", "pesë", "gjashtë", "shtatë", "tetë", "nëntë"]
    if n < 10:
        return [u[n]]
    if n == 10:
        return ["dhjetë"]
    if n < 20:
        return [u[n - 10] + "mbëdhjetë"]
    t, k = divmod(n, 10)
    dec = {2: "njëzet", 3: "tridhjetë", 4: "dyzet", 5: "pesëdhjetë", 6: "gjashtëdhjetë", 7: "shtatëdhjetë", 8: "tetëdhjetë",
           9: "nëntëdhjetë"}[t]
    return [dec] if k == 0 else [f"{dec} e {u[k]}"]


def _date_in_lettere(d: date) -> set[str]:
    """v9.431 — «venti novembre duemilaventisei», «primo dicembre 2026», «njëzet nëntor dy mijë e njëzet e gjashtë»: le
    ordinanze scrivono spesso la data in lettere, e senza questo la data giusta restava «da verificare»."""
    out: set[str] = set()
    anno = d.year % 100
    it_gg = (["primo"] if d.day == 1 else []) + _numero_it(d.day)
    it_aa = ["duemila" + x for x in (_numero_it(anno) if anno else [""])] + [str(d.year)]
    sq_gg = _numero_sq(d.day)
    sq_aa = [f"dy mijë e {x}" for x in _numero_sq(anno)] + ([f"dymijë e {x}" for x in _numero_sq(anno)]) + [str(d.year)]
    for g in it_gg:
        for a in it_aa:
            out.add(f"{g} {_MESI['it'][d.month - 1]} {a}")
    for a in it_aa[:-1]:
        out.add(f"{d.day} {_MESI['it'][d.month - 1]} {a}")
    for g in sq_gg:
        for a in sq_aa:
            out.add(f"{g} {_MESI['sq'][d.month - 1]} {a}")
    return out


def _varianti_data(d: date) -> list[str]:
    g, m, a = d.day, d.month, d.year
    out = {f"{g:02d}.{m:02d}.{a}", f"{g}.{m}.{a}", f"{g:02d}/{m:02d}/{a}", f"{g}/{m}/{a}", f"{g:02d}-{m:02d}-{a}",
           f"{g}-{m}-{a}", d.isoformat(), f"{g:02d}.{m:02d}.{a % 100:02d}", f"{g:02d}/{m:02d}/{a % 100:02d}"}
    for mesi in _MESI.values():
        nome = mesi[m - 1]
        out |= {f"{g} {nome} {a}", f"{g:02d} {nome} {a}", f"{g}° {nome} {a}", f"{g} {nome}"}
        if nome.endswith(("r", "t", "l", "j", "s")):      # albanese determinato: «15 shtatorit 2026»
            out |= {f"{g} {nome}it {a}", f"{g} {nome}it"}
    out |= _date_in_lettere(d)
    return sorted(out, key=len, reverse=True)


def data_nel_testo(iso: str, testo: str) -> bool:
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return False
    t = _norm(testo)
    t = re.sub(r"(\d)\s*([./-])\s*(\d)", r"\1\2\3", t)   # «15 . 09 . 2026» dell'OCR
    # v9.431: confini di PAROLA per le forme con le lettere («sei novembre» sta dentro «ventisei novembre», «duemilaventi»
    # dentro «duemilaventisei»): un giorno sbagliato non deve risultare verificato
    def _rx(v: str) -> str:
        pre = r"(?<!\w)" if v[0].isalpha() else r"(?<!\d)"
        # «20 novembre» senza anno vale solo se DOPO non c'è un anno («20 novembre 2027» non verifica il 2026)
        post = r"(?!\w)(?!\s*(?:\d{4}|duemila|dy mijë|dymijë))" if v[-1].isalpha() else r"(?!\d)"
        return pre + re.escape(v) + post
    return any(re.search(_rx(v), t) for v in _varianti_data(d))


# parole che stanno in quasi ogni titolo di scadenza: non dicono QUALE scadenza è («termine per memorie» ≠ «termine per note»)
_PAROLE_GENERICHE = {"termin", "scaden", "deposi", "udienz", "giorni", "contro", "presso", "tribun", "giudic", "causa",
                     "afati", "afatit", "afate", "seanca", "seancë", "seance", "gjykat", "dorëzi", "depozi", "kundër", "ditëve",
                     "dosjes", "vendim", "vendimi",
                     # articoli e preposizioni (la prova dei doppioni: «Deposito DELLE memorie» ≠ «Deposito DELLE note»)
                     "delle", "della", "dello", "degli", "dalla", "dalle", "dallo", "dagli", "nella", "nelle", "nello",
                     "negli", "sulla", "sulle", "sullo", "sugli", "entro", "prima", "presso", "verso", "oltre", "quale",
                     "quali", "quest", "sensi", "ovvero", "oppure", "ësht", "është", "sipas", "lidhur", "brenda", "përpar",
                     "pranë", "palës", "datës", "ditën", "lidhj"}


def _parole_titolo(t: str) -> set:
    return {w[:6] for w in re.findall(r"[a-zà-ÿëç]{5,}", _norm(t))} - _PAROLE_GENERICHE


def stesso_evento(a: dict, b: dict) -> bool:
    """v9.439 — due proposte (o una proposta e un evento) parlano della STESSA scadenza? Lo stesso fascicolo porta la stessa
    udienza in più documenti (citazione, ordinanza, verbale) con titoli diversi. Prudenza: un doppione mostrato costa un clic,
    una scadenza diversa nascosta costa la causa — per le udienze bastano giorno e ora (o l'ora mancante in una delle due); per
    termini e depositi lo stesso giorno NON basta: servono DUE parole specifiche in comune nel titolo («opposizione» + «decreto»),
    fuori da quelle che stanno in ogni titolo («termine», «afati», «deposito») e dagli articoli — «pagare la somma ingiunta» e
    «opporsi al decreto ingiuntivo» cadono lo stesso giorno e sono due azioni: restano due."""
    if not a.get("data") or a.get("data") != b.get("data") or a.get("kind") != b.get("kind"):
        return False
    oa, ob = (a.get("ora") or "")[:5], (b.get("ora") or "")[:5]
    if oa and ob and oa != ob:
        return False
    if a.get("kind") == "seance":
        return True
    ta, tb = _norm(a.get("titolo") or ""), _norm(b.get("titolo") or "")
    return ta == tb or len(_parole_titolo(ta) & _parole_titolo(tb)) >= 2


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
           "cosa_fare": "l'azione concreta per l'avvocato", "citazione": "la frase ESATTA del documento con la data",
           "rinvio_da": "AAAA-MM-GG dell'udienza che questa SOSTITUISCE (rinvio), se il documento la dice, altrimenti vuoto"}],
 "termini": [{"titolo": "…", "durata": 20, "unita": "giorni|giorni_lavorativi|mesi|anni",
              "decorrenza": "da cosa decorre, con le parole del documento (es. «dalla notificazione del presente decreto»)",
              "data_decorrenza": "AAAA-MM-GG se il documento la dice, altrimenti vuoto",
              "processuale": true, "lavoro_o_urgente": false, "a_ritroso": false,
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
  Se l'udienza è un RINVIO di un'udienza precedente («rinvia l'udienza del … al …»), la data vecchia va in "rinvio_da".
  Anche la SCADENZA o la fine di un contratto, di una garanzia, di un permesso, di un mandato («fino al …», «con scadenza il …»):
  è una data per l'avvocato (rinnovo, disdetta, restituzione).
- "termini" = durate stabilite DAL DOCUMENTO (dal giudice, dalla controparte, dal contratto, dall'ufficio).
  "a_ritroso": true quando il termine si conta ALL'INDIETRO da una data («almeno N giorni prima dell'udienza», «N giorni prima
  della scadenza del contratto»): allora "data_decorrenza" è la data di RIFERIMENTO (l'udienza, la scadenza) se è scritta.
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
           "cosa_fare": "veprimi konkret për avokatin", "citazione": "fjalia E SAKTË e dokumentit me datën",
           "rinvio_da": "VVVV-MM-DD e seancës që kjo ZËVENDËSON (shtyrje), nëse dokumenti e thotë, përndryshe bosh"}],
 "termini": [{"titolo": "…", "durata": 15, "unita": "dite|dite_pune|muaj|vite",
              "decorrenza": "nga çfarë nis, me fjalët e dokumentit (p.sh. «nga dita e njoftimit të vendimit»)",
              "data_decorrenza": "VVVV-MM-DD nëse dokumenti e thotë, përndryshe bosh",
              "processuale": true, "lavoro_o_urgente": false, "a_ritroso": false,
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
  Nëse seanca është SHTYRJE e një seance të mëparshme («seanca e datës … shtyhet për datën …»), data e vjetër shkon te "rinvio_da".
  Edhe PËRFUNDIMI ose skadimi i një kontrate, garancie, leje, mandati («deri më …», «me afat deri më …»): është një datë për
  avokatin (rinovim, njoftim për mosrinovim, kthim).
- "termini" = afate të caktuara NGA DOKUMENTI (nga gjykata, pala tjetër, kontrata, zyra).
  "a_ritroso": true kur afati llogaritet PRAPA nga një datë («të paktën N ditë para seancës», «N ditë para përfundimit të
  kontratës»): atëherë "data_decorrenza" është data e REFERIMIT (seanca, përfundimi) nëse është e shkruar.
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


def pezzi_del_testo(testo: str, massimo: int = TESTO_MAX, sovrapp: int = SOVRAPPOSIZIONE,
                    limite: int = PEZZI_MAX) -> tuple[list[str], int]:
    """(pezzi, caratteri NON letti). Ogni taglio cade sull'ultimo cambio di pagina («── Faqja/Pagina N»), altrimenti
    sull'ultimo paragrafo, nella seconda metà del pezzo; il pezzo dopo riparte `sovrapp` caratteri prima (una scadenza a
    cavallo del taglio resta intera in uno dei due)."""
    t = testo or ""
    pezzi, i = [], 0
    while i < len(t) and len(pezzi) < limite:
        fine = min(len(t), i + massimo)
        if fine < len(t):
            finestra = t[i + massimo // 2:fine]
            m = [x.start() for x in re.finditer(r"\n── (?:Faqja|Pagina) \d+", finestra)]
            k = m[-1] if m else finestra.rfind("\n\n")
            if k > 0:
                fine = i + massimo // 2 + k
        pezzi.append(t[i:fine])
        if fine >= len(t):
            return pezzi, 0
        i = max(fine - sovrapp, i + 1)
    return pezzi, max(0, len(t) - i)


def estrai_tutto(backend, testo: str, nome_file: str, lang: str, oggi: str) -> dict:
    """L'estrazione su TUTTO il documento, a pezzi; le liste unite (i doppioni fra pezzi sovrapposti li toglie la chiave
    della proposta, e prima ancora qui per data+frase)."""
    pezzi, resto = pezzi_del_testo(testo)
    if len(pezzi) <= 1 and not resto:
        return estrai(backend, testo, nome_file, lang, oggi)
    unito: dict = {"date": [], "termini": [], "inneschi": []}
    visti: set = set()
    for n, p in enumerate(pezzi, 1):
        est = estrai(backend, p, f"{nome_file} ({n}/{len(pezzi)})", lang, oggi)
        for k in unito:
            for it in (est.get(k) or []):
                if not isinstance(it, dict):
                    continue
                firma = (k, str(it.get("data") or ""), _norm(str(it.get("citazione") or ""))[:80])
                if firma in visti:
                    continue
                visti.add(firma)
                unito[k].append(it)
    if resto:
        log.warning("scadenziario: %s letto in %d pezzi, %d caratteri finali NON letti", nome_file, len(pezzi), resto)
    unito["non_letti"] = resto
    return unito


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


_RITROSO = {
    "it": re.compile(r"(?:\d+|[a-zà-ù]+)\s+(?:giorni|giorno|mesi|mese|anni|anno)\s+(?:liberi\s+|lavorativi\s+|interi\s+)?"
                     r"(?:prima|antecedent\w*|anterior\w*)\b"),
    "sq": re.compile(r"(?:\d+|[a-zëç]+)\s+(?:ditë|dite|muaj|vjet|vite)(?:\s+pune)?\s+(?:para|përpara|perpara)\b"),
}


def a_ritroso_nel_testo(cit: str) -> bool | None:
    """v9.431 — la frase dice «N giorni PRIMA di …» / «N ditë PARA …»? True/False se la frase contiene la durata con un verso
    riconoscibile, None se non lo dice. «prima udienza» (= la prima) non conta: serve la forma «numero + unità + prima»."""
    c = _norm(cit)
    if not c:
        return None
    if any(rx.search(c) for rx in _RITROSO.values()):
        return True
    if re.search(r"\b(?:dalla|dal|dall'|decorrent\w*|successiv\w*|dopo)\b|\bnga (?:dita|data|njoftimi|marrja|e nesërmja)\b"
                 r"|\bpas\b", c):
        return False
    return None


def _calcola_a_ritroso(regola: dict, riferimento: str, jurisdiction: str, lang: str) -> dict:
    """«Almeno N giorni PRIMA dell'udienza del …»: la data di riferimento meno N; se cade di sabato, domenica o festivo si
    ANTICIPA al giorno lavorativo precedente (un giorno prima è sempre in tempo: la scelta prudente); in Italia, per un termine
    processuale non escluso, i giorni di agosto nel mezzo non si contano (sospensione feriale anche a ritroso) — anticipando."""
    from datetime import timedelta
    it = lang == "it"
    j = (jurisdiction or "AL").upper()
    ref = date.fromisoformat(riferimento)
    n, u = int(regola["durata"]), regola["unita"]
    if u == "days":
        d = ref - timedelta(days=n)
    elif u == "months":
        d = _de.add_months(ref, -n)
    elif u == "years":
        d = _de.add_months(ref, -12 * n)
    else:                                          # giorni lavorativi, all'indietro
        d, k = ref, 0
        while k < n:
            d -= timedelta(days=1)
            if _de.is_business_day(d, j):
                k += 1
    wd = lambda x: _de._wd(x, lang)
    parola = {"days": ("giorni", "ditë"), "business_days": ("giorni lavorativi", "ditë pune"), "months": ("mesi", "muaj"),
              "years": ("anni", "vjet")}[u][0 if it else 1]
    passi = [(f"termine A RITROSO: {n} {parola} PRIMA del {ref.isoformat()} ({wd(ref)}) → {d.isoformat()} ({wd(d)})" if it else
              f"afat PRAPA: {n} {parola} PARA datës {ref.isoformat()} ({wd(ref)}) → {d.isoformat()} ({wd(d)})")]
    feriale = (j == "IT" and bool(regola.get("processuale")) and not bool(regola.get("lavoro_o_urgente")) and u == "days")
    if feriale:
        contati: set = set()
        while True:
            agosto = {x for x in (d + timedelta(days=i) for i in range((ref - d).days)) if x.month == 8} - contati
            if not agosto:
                break
            contati |= agosto
            d -= timedelta(days=len(agosto))
        if contati:
            passi.append(f"sospensione feriale: {len(contati)} giorni di agosto nel mezzo non si contano → anticipato al "
                         f"{d.isoformat()} ({wd(d)})")
    while not _de.is_business_day(d, j):
        d -= timedelta(days=1)
        passi.append((f"cade in un giorno non lavorativo: anticipato al {d.isoformat()} ({wd(d)}) — la scelta prudente" if it else
                      f"bie në ditë jo pune: sillet përpara në {d.isoformat()} ({wd(d)}) — zgjedhja e kujdesshme"))
    passi.append(("⚠ computo a ritroso: verifica se il termine è a giorni «liberi» (escluso anche il giorno di riferimento); la data "
                  "indicata è quella prudente" if it else
                  "⚠ llogaritje prapa: verifiko nëse afati është me ditë «të lira»; data e dhënë është ajo e kujdesshme"))
    return {"data": d.isoformat(), "passi": passi}


def calcola_regola(regola: dict, data_partenza: str, jurisdiction: str, lang: str) -> dict:
    """Termine dato dal documento («entro 20 giorni dalla notifica») + la data di partenza → data (motore deterministico).
    v9.431: con `a_ritroso` la data di partenza è quella di RIFERIMENTO e il termine si conta all'indietro."""
    if regola.get("a_ritroso"):
        return _calcola_a_ritroso(regola, data_partenza, jurisdiction, lang)
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
    for it in (est.get("date") or [])[:120]:
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
        # v9.440: un RINVIO vale solo se la data vecchia è scritta nel documento e viene prima della nuova
        rd = _iso(it.get("rinvio_da"))
        rd = rd if (rd and rd != d and rd < d and data_nel_testo(rd, testo)) else ""
        out.append({"tipo": "data", "kind": _KIND.get(str(it.get("tipo") or "").lower(), "tjetër"), "titolo": titolo,
                    "data": d, "ora": _ora(it.get("ora")), "luogo": str(it.get("luogo") or "")[:160],
                    "cosa_fare": str(it.get("cosa_fare") or "")[:400], "origine": "documento", "citazione": cit,
                    "verificato": c_ok and d_ok, "nota": " · ".join(note), "rinvio_da": rd,
                    "chiave": _chiave("data", d, titolo)})
    for it in (est.get("termini") or [])[:60]:
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
        # v9.431: il VERSO del termine si controlla sul testo («N giorni PRIMA dell'udienza» si conta all'indietro): la frase
        # vince sul modello; se la frase non dice niente vale il modello, ma la proposta resta da verificare
        indietro_testo = a_ritroso_nel_testo(cit)
        indietro = indietro_testo if indietro_testo is not None else bool(it.get("a_ritroso"))
        verso_ok = indietro_testo is not None or not bool(it.get("a_ritroso"))
        regola = {"durata": durata, "unita": unita, "decorrenza": str(it.get("decorrenza") or "")[:200],
                  "processuale": bool(it.get("processuale")), "lavoro_o_urgente": bool(it.get("lavoro_o_urgente")),
                  "a_ritroso": indietro}
        c_ok = citazione_nel_testo(cit, testo)
        durata_ok = (bool(re.search(r"(?<!\d)" + str(durata) + r"(?!\d)", _norm(cit))) or _durata_in_lettere(durata, cit)) and verso_ok
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
    for it in (est.get("inneschi") or [])[:12]:
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
        if not passi:                                   # v9.434: la riga vecchia «AFAT | titolo | data» = data del modello
            passi = [("data NON calcolata dal motore deterministico: verificala" if lang == "it" else
                      "data e PA llogaritur nga motori determinist: verifikoje")]
        out.append({"tipo": "data", "kind": "afat", "titolo": str(a.get("title") or "")[:160], "data": d,
                    "origine": "legge", "citazione": innesco.get("descrizione") or "", "base": a.get("baza") or "",
                    "cosa_fare": "", "verificato": (bool(a.get("baza")) and bool(a.get("passi"))
                                                    and not _BASE_INCERTA.search(a.get("baza") or "")),
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
    est = estrai_tutto(backend, testo, getattr(doc, "filename", "") or "documento", lang, oggi)
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
