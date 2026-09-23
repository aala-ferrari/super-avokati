"""Parse Albanian legal PDFs into structured articles.

Each code is split on `Neni N` headers. For every article we capture:
  - number (e.g. "37", "83/a")
  - title (the single line after the `Neni` header)
  - body (full text until the next `Neni`, `KREU`, `SEKSIONI` or `PJESA` header)
  - hierarchy context (part / chapter / section it belongs to)
  - whether the article has been repealed ("Shfuqizuar")

Output: one JSON file per code in PROCESSED_DATA_PATH, plus a combined
`all_articles.jsonl` used by the indexer.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pdfplumber

from .config import LEGAL_DOCUMENTS, PROCESSED_DATA_PATH, RAW_DATA_PATH, LegalDocument
from .logging_utils import get_logger

log = get_logger(__name__)

# Matches "Neni 37", "Neni 83/a", "Neni 170/ç" or the glued form "Neni37"
# that some PDFs produce when the text-extractor drops the space.
# NOTE: we use [ \t] (not \s) inside the number group — otherwise newlines are
# consumed and page-number footers get glued to the article number, producing
# phantom articles like "Neni 1913" (really "Neni 19" + page footer "13").
ARTICLE_RE = re.compile(
    r"(?m)^[ \t]*Neni[ \t]*(\d+(?:[ \t]*/[ \t]*[a-zçëA-ZÇË0-9]+)?)[ \t]*$"
)
# «Neni 3 Parime të përgjithshme» — numero e rubrica sulla stessa riga (16 set 2026). Rubrica in
# maiuscolo, 2-90 caratteri, che NON finisce con una cifra (le voci dell'indice finiscono col
# numero di pagina); la plausibilità di sequenza si controlla in split_into_articles.
ARTICLE_INLINE_RE = re.compile(
    r"(?m)^[ \t]*Neni[ \t]*(\d+(?:[ \t]*/[ \t]*[a-zçëA-ZÇË0-9]+)?)[ \t]+([A-ZÇË][^\n]{1,89}[^\d\s])[ \t]*$"
)

# v9.362 — RUBRICA vs PRIMA FRASE. La regola V9.1 («incolla righe finché finisce una frase») era pensata per
# il Kodi Civil, che non ha rubriche; nei 40+ atti CON rubrica inghiottiva il primo paragrafo (misurato:
# 8.301 «rubriche» su 9.682 oltre 120 caratteri, corpo VUOTO negli articoli di una frase). Una riga è una
# rubrica se è corta (≤90), senza punteggiatura finale, non comincia con una cifra e non contiene un verbo
# finito; le note «(Shtuar/Ndryshuar …)» — prima della rubrica, sulla stessa riga, sulla riga dopo, anche
# spezzate su due righe — vanno in `note`. La decisione è PER ARTICOLO (Kodi i Familjes e K.Pr.C. sono misti:
# i primi articoli senza rubrica, gli altri con) e il segnale che un frammento di frase spezzata non ha è la
# RIGA DOPO: dopo una rubrica comincia con maiuscola/cifra/parentesi («Furnizimi…», «1.», «(Ndryshuar…»), dopo
# un frammento comincia in minuscolo («…në testament» / «mund të përjashtojë…»). Misurato il 21 set: KP 97 %,
# KPP 97 %, leggi ~100 %, Kodi Civil e Kushtetuta ≈ 0 (restano alla prima frase).
_RUBRIKA_NOTE_RX = re.compile(r"\((?:Shtuar|Ndryshuar|Shfuqizuar|Riformuluar|Hequr|Zëvendësuar|Ndryshohet|Shtohet)[^)]*\)?", re.I)
_RUBRIKA_VERB_RX = re.compile(
    r"\b(dënohet|dënohen|përbën|përbëjnë|konsiderohet|konsiderohen|zbatohet|zbatohen|është|janë|nuk|mund|duhet|do të|"
    r"kanë|quhet|quhen|kryhet|kryhen|lejohet|ndalohet|ka të drejtë|bëhet|bëhen|merret|merren|caktohet|caktohen|vendos|"
    r"përcakton|përcaktohet|kupton|kuptohet|njihet|detyrohet|detyrohen|paguhet|paguan|gëzon|gëzojnë|humbet|fillon|mbaron|ka|kanë)\b", re.I)
_PARAGRAF_NUM_RX = re.compile(r"^\s*(\d{1,3})[.)]\s+\S")


def _nota_ne_krye(lines: list[str]) -> tuple[str, list[str]]:
    """Le note editoriali in testa all'articolo («(Ndryshuar me ligjin…)»), anche su più righe → (note, resto)."""
    rest = list(lines)
    buf, i = "", 0
    while i < len(rest) and i < 5 and (rest[i].lstrip().startswith("(") or (buf and buf.count("(") > buf.count(")"))):
        buf = (buf + " " + rest[i]).strip(); i += 1
        if buf.count("(") <= buf.count(")") and not (i < len(rest) and rest[i].lstrip().startswith("(")):
            break
    if buf and _RUBRIKA_NOTE_RX.search(buf):
        return " ".join(buf.split()), rest[i:]
    return "", list(lines)


def _kandidat_rubrike(lines: list[str]):
    """(rubrica, note, righe_del_corpo) se la prima riga (dopo le note in testa) è una rubrica plausibile, altrimenti None."""
    if not lines:
        return None
    note0, rest = _nota_ne_krye(lines)
    if not rest:
        return None
    buf, i = rest[0], 1
    # la nota può stare sulla stessa riga (anche spezzata: «…me ligjin nr.» / «9686, datë 26.2.2007)») o sulla riga dopo
    # rubrica spezzata su DUE righe («Konfiskimi i mjeteve të kryerjes së veprës penale» / «dhe produkteve të
    # veprës penale»): la continuazione è corta, minuscola, e la riga dopo di lei apre un paragrafo o una nota
    if (i < len(rest) and "(" not in buf and rest[i][:1].islower() and len(rest[i]) <= 60 and len(buf) + len(rest[i]) <= 110
            and (i + 1 >= len(rest) or rest[i + 1].lstrip()[:1].isupper() or rest[i + 1].lstrip()[:1].isdigit() or rest[i + 1].lstrip().startswith("("))
            and not rest[i].rstrip().endswith((".", ";", "!", "?"))):
        buf = buf + " " + rest[i]; i += 1
    # le note possono essere lunghe (KP 7: cinque righe di «ndryshuar shkronja …»): si incolla finché le parentesi non chiudono
    while i < len(rest) and i < 14 and (buf.count("(") > buf.count(")") or rest[i].lstrip().startswith("(")):
        buf = buf + " " + rest[i]; i += 1
        if buf.count("(") <= buf.count(")") and not (i < len(rest) and rest[i].lstrip().startswith("(")):
            break
    note = " ".join(x for x in [note0, " ".join(" ".join(m.group(0).split()) for m in _RUBRIKA_NOTE_RX.finditer(buf))] if x).strip()
    rub = " ".join(_RUBRIKA_NOTE_RX.sub("", buf).split()).strip(" -–—:;,")
    corpo = rest[i:]
    dopo = corpo[0].lstrip() if corpo else ""
    # la riga dopo: maiuscola / cifra / parentesi / virgolette = comincia un paragrafo; minuscola = la frase continua
    segue_bene = (not dopo) or dopo[0].isupper() or dopo[0].isdigit() or dopo[0] in "(«\"“"
    # frase introduttiva di un elenco («Janë të hipotekueshme» / «1. Sendet…», «Detyrimet kryesore të shitësit janë»):
    # ha un verbo E la riga dopo è una voce d'elenco → non è una rubrica
    _lista = bool(re.match(r"^(?:\d{1,3}[.)]|[a-zçë]{1,2}[).]|[-–•])\s", dopo))
    ok = (2 <= len(rub) <= 90 and rub[-1] not in ".;!?" and not re.match(r"^\d+[.)]", rub) and not rub.startswith("(")
          and segue_bene and not (_RUBRIKA_VERB_RX.search(rub) and (_lista or not corpo)))
    if not ok:
        return None
    return rub, note, corpo


def _paragrafet(body: str) -> list[str]:
    """I paragrafi del corpo: nuovo paragrafo a un numero in testa («1.», «2)») o dopo una riga che chiude
    una frase quando la successiva comincia con maiuscola. Interno (verifica, segmenti): mai numeri inventati."""
    out: list[list[str]] = []
    prev = ""
    for ln in (body or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        nuovo = (not out) or bool(_PARAGRAF_NUM_RX.match(ln)) or (prev[-1:] in ".;:" and ln[:1].isupper())
        if nuovo:
            out.append([ln])
        else:
            out[-1].append(ln)
        prev = ln
    return [" ".join(p) for p in out]


# Hierarchy headers (PJESA / KREU / SEKSIONI / TITULLI). Used as context.
HIERARCHY_RE = re.compile(
    r"(?m)^[ \t]*(PJESA|KREU|SEKSIONI|TITULLI|KAPITULLI)\s+([A-ZÇËÏ0-9/]+)\s*$"
)

REPEALED_MARKERS = ("shfuqizuar", "shfuqizohet")


# Slug dei corpora italiani: servono a citare "art. N" invece di "Neni N".
_IT_CODE_PREFIXES = ("codice_", "tu_", "disp_att_", "regolamento_", "reg_ue_",
                     "legge_", "imposta_", "locazioni_", "ordinamento_", "sanzioni_",
                     "bruxelles_", "roma_", "cedu", "convenzione_", "protocollo_")
# Ogni corpus italiano DEVE stare qui o sotto un prefisso: altrimenti la sua
# citazione esce «Neni N i …» dentro la sessione italiana (visto il 16 set 2026
# sui regolamenti UE e sull'antiriciclaggio). Guard: golden [76] controlla che
# tutti i codici di it_codes.json siano riconosciuti.
_IT_CODE_EXACT = frozenset({
    "costituzione", "tulps", "tuir", "tuel", "statuto_lavoratori", "sicurezza_lavoro",
    "responsabilita_enti", "responsabilita_sanitaria", "procedimento_amministrativo",
    "stupefacenti", "divorzio", "adozione", "equa_riparazione", "antiriciclaggio",
    # wave5 (16 set 2026): tributario, notarile, procedura, lavoro + EUR-Lex
    "accise", "iva", "giustizia_tributaria", "statuto_contribuente",
    "accertamento_imposte", "riscossione", "reati_tributari", "condono_edilizio",
    "immobili_da_costruire", "successioni_ue", "mediazione_civile",
    "riti_civili_semplificati", "licenziamenti_individuali", "tutele_crescenti",
    "processo_penale_minorile", "gdpr",
    # wave7 «blocco A» (16 set 2026): internazionale, cittadinanza, stranieri, lavoro,
    # procedura, famiglia, notaio, armi + trattati/regolamenti UE
    "diritto_internazionale_privato", "cittadinanza", "cittadini_ue", "protezione_internazionale",
    "contratti_lavoro", "orario_lavoro", "maternita_paternita", "pubblico_impiego",
    "negoziazione_assistita", "giudice_pace_penale", "mandato_arresto_europeo", "casellario",
    "unioni_civili", "consenso_informato_dat", "prestazione_energetica", "armi",
    "tfue", "tue", "carta_diritti_ue", "alimenti_ue", "regimi_patrimoniali_ue",
    "ingiunzione_europea", "small_claims_ue", "notifiche_ue",
    "preleggi",   # disposizioni sulla legge in generale (allegato 1 del R.D. 262/1942)
})


def _is_italian_code(code: str) -> bool:
    c = (code or "").lower()
    return c in _IT_CODE_EXACT or c.startswith(_IT_CODE_PREFIXES)


_IT_GRUPPO_RE = re.compile(r"^(.*?)-(all\d+|legge)$")


def numero_visibile_it(number: str) -> str:
    """Il numero come lo legge un giurista (v9.348, 17 set 2026). Dalla v9.327 gli atti «approvati con
    allegato» numerano PER GRUPPO: «13-ter-all3» = art. 13-ter di un ALLEGATO (c.p.a. norme di
    attuazione, allegati del codice contratti…), «1-legge» = art. 1 dell'atto di approvazione. Il
    suffisso serve all'indice (niente collisioni col testo principale) ma nel prompt, nella UI e
    nelle citazioni non deve comparire: «art. 13-ter (allegato) Codice del processo amministrativo»."""
    m = _IT_GRUPPO_RE.match(str(number or ""))
    if not m:
        return str(number)
    return f"{m.group(1)} ({'allegato' if m.group(2).startswith('all') else 'atto di approvazione'})"


SEARCH_CHAPTERS = os.environ.get("SEARCH_CHAPTERS", "1") == "1"
_CAP_PREFIX = re.compile(r"^\s*(?:KREU|KAPITULLI|SEKSIONI|TITULLI|PJESA|NËNSEKSIONI|CAPO|TITOLO|SEZIONE|LIBRO|PARTE)"
                         r"\s+[IVXLCDM0-9]+(?:[-\s]*(?:bis|ter|quater|A|B))?\s*[—–\-.:]*\s*", re.I)


@dataclass
class Article:
    """A single article extracted from a code."""

    code: str               # e.g. "kodi_penal"
    title_sq: str           # code title (Kodi Penal ...)
    area: str               # broad area (Penal, Civil, ...)
    number: str             # "37", "83/a"
    heading: str            # first line after "Neni N"
    body: str               # full article text
    pjesa: str = ""         # part
    kreu: str = ""          # chapter
    seksioni: str = ""      # section
    repealed: bool = False
    volatility: str = "STABLE"            # V7.4 — inherited from LegalDocument
    last_amendment_date: str = ""          # V7.4 — ISO date of last indexed amendment
    # v9.362 — STRUTTURA DEL NENE (21 set 2026): `heading` = la RUBRICA vera nei codici che ce l'hanno
    # («Përkrahja e autorit të krimit»), non più «rubrica + prima frase»; `note` = le note editoriali
    # «(Shtuar/Ndryshuar … me ligjin nr. …)» separate dal testo; `paragrafet` = i paragrafi del corpo
    # (numerati se lo sono nella fonte, altrimenti per ordine — MAI numeri inventati nel prompt).
    # Nei codici senza rubrica (Kodi Civil, Kushtetuta) `heading` resta la prima frase, come prima.
    note: str = ""
    paragrafet: list = field(default_factory=list)
    heading_kind: str = "fjali"           # «rubrike» = rubrica vera · «fjali» = prima frase (codici senza rubrica)

    @property
    def citation(self) -> str:
        """Citazione nella forma della giurisdizione dell'articolo.

        I corpora italiani usano slug noti (codice_*, tu_*, disp_att_*, …):
        per quelli si cita "art. N Titolo", non "Neni N i Titolo"."""
        if _is_italian_code(self.code):
            return f"art. {numero_visibile_it(self.number)} {self.title_sq}"
        return f"Neni {self.number} i {self.title_sq}"

    @property
    def searchable_text(self) -> str:
        """Text to embed — heading + body + citation for recall."""
        parts = [self.citation]
        if self.heading:
            parts.append(self.heading)
        if getattr(self, "note", ""):          # v9.362: la nota editoriale resta cercabile
            parts.append(self.note)
        # v9.373: il TITOLO DEL CAPITOLO è cercabile. Il K.Pr.P. 268 si chiama «Kushtetet e zbatimit»: che parli del
        # risarcimento per detenzione ingiusta lo dice solo «KREU V — KOMPENSIMI PËR BURGIM TË PADREJTË». Senza, una
        # domanda su quel tema non lo trovava mai. Solo il titolo, senza «KREU V —».
        if SEARCH_CHAPTERS:
            for cap in (getattr(self, "kreu", ""), getattr(self, "seksioni", "")):
                t = _CAP_PREFIX.sub("", cap or "").strip()
                if t:
                    parts.append(t)
        parts.append(self.body)
        return "\n".join(parts)


# ── PDF extraction ──────────────────────────────────────────────────────────

def extract_text_smart(pdf_path: Path, x_tolerance: float = 3.0) -> str:
    """Testo del PDF; se l'impaginazione è a DUE COLONNE (Kodi Zgjedhor, CEDU) la lettura
    intera mescola le colonne («Neni 3 3. Ligji zgjedhor nxit…» = intestazione sinistra +
    riga destra) e gli articoli spariscono (Kodi Zgjedhor: 96 su 186, 16 set 2026). Si
    estrae anche colonna per colonna (crop a metà pagina) e vince la lettura con più
    intestazioni «Neni N» pulite; a parità resta quella intera (le pagine a una colonna
    tagliate a metà danno frammenti, non più intestazioni)."""
    plain: list[str] = []
    cols: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            plain.append(page.extract_text(x_tolerance=x_tolerance) or "")
            w, h = page.width, page.height
            try:
                left = page.crop((0, 0, w / 2, h)).extract_text(x_tolerance=x_tolerance) or ""
                right = page.crop((w / 2, 0, w, h)).extract_text(x_tolerance=x_tolerance) or ""
            except Exception:  # noqa: BLE001
                left, right = "", ""
            cols.append(left + "\n" + right)
    t_plain = _clean_text("\n".join(plain))
    t_cols = _clean_text("\n".join(cols))
    n_plain = len(ARTICLE_RE.findall(t_plain))
    n_cols = len(ARTICLE_RE.findall(t_cols))
    if n_cols >= n_plain + 5 and n_cols > n_plain * 1.15:
        log.info("parser: %s letto a due colonne (%d intestazioni contro %d)", pdf_path.name, n_cols, n_plain)
        return t_cols
    return t_plain


def extract_full_text(pdf_path: Path) -> str:
    """Extract and concatenate all pages of a PDF, stripping typical footers."""
    return extract_text_smart(pdf_path)


def _clean_text(text: str) -> str:
    # Remove isolated page-number lines (1..9999 on their own line)
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$\n?", "", text)
    # Collapse runs of >2 blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ── Article splitting ───────────────────────────────────────────────────────

_NOTA_INTEST_RE = re.compile(r"^\((?:Ndryshuar|Shtuar|Shfuqizuar)\b", re.I)
_SOTTOTITOLO_RE = re.compile(r"^[A-ZÇË]\.\s+[A-ZÇË]")


def _riga_titolo(t: str) -> bool:
    """Una riga di titolo: nessuna minuscola, almeno una maiuscola, non lunghissima."""
    return bool(t) and len(t) <= 160 and re.search(r"[A-ZÇË]", t) is not None and re.search(r"[a-zëç]", t) is None


def taglia_coda_gerarchia(raw: str) -> tuple[str, str]:
    """v9.376 — Il corpo di un articolo arriva fino al «Neni» successivo, quindi l'intestazione del CAPITOLO seguente
    («KREU VI / MASAT E SIGURIMIT PASUROR / SEKSIONI I / SEKUESTROJA KONSERVATIVE» in coda al K.Pr.P. 269) finiva
    dentro l'ultimo articolo del capitolo precedente: 976 articoli. Ritorna (corpo senza la coda, coda tolta).
    Si taglia SOLO se la coda contiene un'intestazione vera (KREU/SEKSIONI/TITULLI/PJESA/KAPITULLI N) o un
    sotto-titolo «A. TITOLO»; il resto della coda può essere solo righe di titolo o note «(Ndryshuar …)»."""
    lines = (raw or "").split("\n")
    k = len(lines)
    while k > 0:
        t = lines[k - 1].strip()
        if not t or HIERARCHY_RE.match(t) or _riga_titolo(t) or _NOTA_INTEST_RE.match(t):
            k -= 1
            continue
        break
    coda = [ln.strip() for ln in lines[k:] if ln.strip()]
    if k == 0 or not coda or not any(HIERARCHY_RE.match(c) or _SOTTOTITOLO_RE.match(c) for c in coda):
        return raw, ""
    return "\n".join(lines[:k]).rstrip(), "\n".join(coda)


def _titolo_con_intestazione(line: str, tail: str) -> str:
    """«KREU X» + il titolo che segue. v9.373: il titolo va a capo nei PDF («KREU X / KËQYRJA E PERSONAVE, SENDEVE
    DHE / …») e prima se ne prendeva solo la prima riga (35 capitoli troncati a «… DHE», «… PËR TË»): si continua
    finché le righe sono in MAIUSCOLO (il titolo), mai oltre 3 righe né dentro un articolo o una nota «(Shtuar …)»."""
    righe = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    if not righe or HIERARCHY_RE.match(righe[0]) or ARTICLE_RE.match(righe[0]):
        return line
    titolo = [righe[0]]
    for ln in righe[1:3] if not re.search(r"[a-zëç]", righe[0]) else ():   # una nota «(Shfuqizuar …)» non continua
        if HIERARCHY_RE.match(ln) or ARTICLE_RE.match(ln) or not re.search(r"[A-ZËÇ]", ln) or re.search(r"[a-zëç]", ln) \
                or re.match(r"(?:PJESA|KREU|SEKSIONI|TITULLI|KAPITULLI|NËNSEKSIONI)\b", ln) \
                or re.fullmatch(r"DISPOZITA\s+T[ËE]\s+P[ËE]RGJITHSHME", ln):             # sotto-titolo, non titolo
            break
        titolo.append(ln)
    return f"{line} — {' '.join(titolo)}"[:240]


def _hierarchy_context(text_before: str) -> tuple[str, str, str]:
    """Return the most recent (pjesa, kreu, seksioni) mentioned before this pos."""
    pjesa = kreu = seksioni = ""
    for match in HIERARCHY_RE.finditer(text_before):
        label = match.group(1).upper()
        line = match.group(0).strip()
        full = _titolo_con_intestazione(line, text_before[match.end() : match.end() + 500])
        if label == "PJESA":
            pjesa = full
            kreu = seksioni = ""
        elif label in ("KREU", "KAPITULLI", "TITULLI"):
            kreu = full
            seksioni = ""
        elif label == "SEKSIONI":
            seksioni = full
    return pjesa, kreu, seksioni


def split_into_articles(text: str, doc: LegalDocument) -> list[Article]:
    """Split the full code text into Article objects."""
    raw_matches = list(ARTICLE_RE.finditer(text))
    # 16 set 2026 — «Neni N Titolo» sulla STESSA riga: il Kodi Zgjedhor perdeva così 81
    # articoli su 186 (audit_corpus). Si accetta solo se il titolo inizia in maiuscolo, non
    # finisce con un numero (le voci dell'indice finiscono col numero di pagina) e — più
    # sotto — se il numero continua la sequenza (altrimenti è prosa: «Neni 5 Kur…»).
    seen_pos = {m.start() for m in raw_matches}
    raw_matches = sorted(
        raw_matches + [m for m in ARTICLE_INLINE_RE.finditer(text) if m.start() not in seen_pos],
        key=lambda m: m.start())

    # V7.4 step 1 — filter out phantom matches. A "Neni 1913" produced by a
    # page-footer "13" glued to the real "Neni 19" has either no body or just
    # another "Neni X" header in its range. Drop those before any further
    # analysis so counter-restart detection isn't poisoned by fake maxima.
    filtered: list = []
    last_ok = 0
    for i, m in enumerate(raw_matches):
        number = re.sub(r"\s+", "", m.group(1))
        num_only = number.split("/")[0]
        end = raw_matches[i + 1].start() if i + 1 < len(raw_matches) else len(text)
        body_len = len(text[m.end():end].strip())
        inline = m.re is ARTICLE_INLINE_RE
        if num_only.isdigit():
            n_int = int(num_only)
            # Hard cap — no Albanian code exceeds ~1300 articles (Kodi Civil)
            if n_int > 2000:
                continue
            # Implausible + empty body → page-footer collision artifact. 16 set 2026: SOLO se
            # il numero è anche fuori sequenza — l'art. 587 c.c. («Dorëzania duhet të bëhet
            # me shkresë.», 36 caratteri) è vero e in sequenza, e veniva buttato.
            if n_int > 500 and body_len < 40 and not (last_ok + 1 <= n_int <= last_ok + 3):
                continue
            # titolo in riga: solo se continua la sequenza (last_ok+1 … last_ok+3) e ha un
            # corpo (le voci dell'INDICE sono intestazioni una dietro l'altra senza testo)
            # («Neni 1 Objekti…» in riga si accetta sempre: è l'inizio del testo, anche dopo
            # un preambolo che ha già alzato last_ok — ligji 9901/2008 su QBZ)
            if inline and ((not (last_ok + 1 <= n_int <= last_ok + 3) and n_int != 1) or body_len < 40):
                continue
            last_ok = max(last_ok, n_int)
        elif inline:
            continue
        filtered.append(m)

    # V7.4 step 2 — some official PDFs (especially for ligji_*) bundle the
    # main law with implementing acts (VKM, UDHËZIM) that each start their
    # own Neni 1. Detect a counter restart (a number far below the running
    # max) and drop everything past that point.
    # 16 set 2026: un SOLO numero stampato male non è un riavvio — la VKM 651/2017
    # (dispozitat doganore) ha «Neni 29» al posto di «Neni 129» e perdeva 600 articoli.
    # Se subito dopo la numerazione principale continua, il numero fuori posto si
    # ricompone (se il successivo è seen_max+2) o si salta; si tronca solo se il
    # riavvio è confermato dai numeri seguenti.
    items: list = []          # (match, numero definitivo)
    seen_max = 0
    stop = False
    for i, m in enumerate(filtered):
        if stop:
            break
        num_str = re.sub(r"\s+", "", m.group(1))
        try:
            num_int = int(num_str.split("/")[0])
        except ValueError:
            num_int = 0
        nxt: list[int] = []
        for k in range(i + 1, min(i + 4, len(filtered))):
            try:
                nxt.append(int(re.sub(r"\s+", "", filtered[k].group(1)).split("/")[0]))
            except ValueError:
                pass
        # 16 set 2026 — NOTA A PIÈ DI PAGINA incollata al numero: nei consolidati QBZ le
        # modifiche stanno in note e il richiamo si attacca al numero («Neni 1¹» → «Neni 11»,
        # «Neni 5²» → «Neni 52»). Segnale: salto in avanti (>15) mentre i numeri seguenti
        # continuano la sequenza vecchia; il numero vero è il prefisso che continua la
        # sequenza (seen_max+1). Senza questa regola ligji 9901/2008 partiva da «Neni 11».
        if ((num_int > seen_max + 15 or (not items and num_int > 1)) and "/" not in num_str
                and nxt and seen_max + 1 <= nxt[0] <= seen_max + 3):
            want = str(seen_max + 1)
            if num_str.startswith(want) and len(num_str) > len(want):
                log.info("parser: %s — Neni %s letto come %s (nota a piè di pagina incollata)",
                         doc.code, num_str, want)
                num_str, num_int = want, int(want)
        if i > 0 and num_int > 0 and num_int < seen_max - 5:
            if any(v > seen_max for v in nxt):
                if nxt and nxt[0] == seen_max + 2:
                    log.info("parser: %s — Neni %s letto come %d (numero stampato male)",
                             doc.code, num_str, seen_max + 1)
                    items.append((m, str(seen_max + 1)))
                    seen_max += 1
                else:
                    log.info("parser: %s — Neni %s fuori sequenza, saltato", doc.code, num_str)
                continue
            # 16 set 2026: se la sequenza raccolta finora è minuscola (≤3 articoli) non è il
            # testo ma un preambolo/atto modificante in testa al PDF (ligji 9901/2008 su QBZ
            # apre con un «Neni 11» e poi riparte da 1: restava UN articolo su 234) →
            # si butta il preambolo e si riparte dalla sequenza nuova
            if len(items) <= 3:
                log.info("parser: %s — preambolo di %d articoli scartato, si riparte da Neni %s",
                         doc.code, len(items), num_str)
                items = []
                seen_max = num_int
                items.append((m, num_str))
                continue
            log.info(
                "parser: truncating %s at Neni %s — counter dropped from %d",
                doc.code, num_str, seen_max,
            )
            stop = True
            break
        if num_int > seen_max:
            seen_max = num_int
        items.append((m, num_str))
    matches = [m for m, _ in items]
    numbers = [n for _, n in items]

    articles: list[Article] = []
    # v9.362 — la rubrica si decide PER ARTICOLO (`doc.rubrika_mode = "jo"` la spegne per un documento)
    rubrika_mode = (getattr(doc, "rubrika_mode", "") or "") != "jo"
    for i, m in enumerate(matches):
        number = numbers[i]  # "83 / a" -> "83/a" (o il numero ricomposto)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw = text[start:end].strip()
        raw, _coda = taglia_coda_gerarchia(raw)      # v9.376: l'intestazione del capitolo SEGUENTE non è dell'articolo
        if m.re is ARTICLE_INLINE_RE:          # la rubrica stava sulla riga di «Neni N»
            raw = m.group(2).strip() + "\n" + raw

        # Heading = the FIRST COMPLETE SENTENCE after "Neni N", body = rest.
        # The Albanian PDFs hard-wrap mid-sentence ("Trashëgimlënësi edhe pa
        # caktuar trashëgimtarë në testament\nmund të përjashtojë nga...");
        # the old parser took only line[0], producing tronche headings that
        # poisoned BM25 retrieval and led the model to drift on
        # successioni-testamentari analyses (V9.0.3 doctrine bug). We now
        # glue lines until a sentence terminator is reached.
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        heading = ""
        body = ""
        if lines:
            buf = lines[0]
            consumed = 1
            # Sentence is complete if it ends with `.`, `:`, `!`, `?` AND
            # is at least 25 chars (so we don't stop on "p.sh." abbreviation
            # at the very start). Cap at 8 lines to never swallow whole body.
            def _is_complete(s: str) -> bool:
                return len(s) >= 25 and s[-1] in ".:!?"
            while consumed < len(lines) and consumed < 8 and not _is_complete(buf):
                buf = buf + " " + lines[consumed]
                consumed += 1
            heading = buf
            body = "\n".join(lines[consumed:]).strip()
        # v9.362 — la «prima frase» (heading_v/body_v) resta il metro per abrogazione e date (invariante
        # rispetto a v9.330); i campi mostrati e cercati diventano rubrica / note / corpo intero
        heading_v, body_v = heading, body
        note, paragrafet, heading_kind = "", [], "fjali"
        if lines:
            cand = _kandidat_rubrike(lines) if rubrika_mode else None
            if cand is not None:
                heading, note, _rest = cand
                body = "\n".join(_rest).strip()
                heading_kind = "rubrike"
            else:
                note, _rest = _nota_ne_krye(lines)
                if note and _rest:
                    buf2, consumed2 = _rest[0], 1
                    while consumed2 < len(_rest) and consumed2 < 8 and not _is_complete(buf2):
                        buf2 = buf2 + " " + _rest[consumed2]; consumed2 += 1
                    heading, body = buf2, "\n".join(_rest[consumed2:]).strip()
            paragrafet = _paragrafet(body if body else heading)

        # Hierarchy from the text *before* this article
        pjesa, kreu, seksioni = _hierarchy_context(text[: m.start()])

        repealed = is_repealed_stub(heading_v, body_v)
        # v9.334 (roadmap v3 P3b): la data dell'ultima modifica PER ARTICOLO dalle note editoriali
        # dei consolidati QBZ «(Ndryshuar … me ligjin nr. 48/2012, datë 26.4.2012)» — 1.665 note nel
        # corpus; prima il campo era quello (vuoto) del documento intero
        try:
            from .temporal import ultima_modifica as _um
            _lad = _um(_NoteView(heading_v, body_v)) or getattr(doc, "last_amendment_date", "")
        except Exception:  # noqa: BLE001
            _lad = getattr(doc, "last_amendment_date", "")

        articles.append(
            Article(
                code=doc.code,
                title_sq=doc.title_sq,
                area=doc.area,
                number=number,
                heading=heading,
                body=body,
                pjesa=pjesa,
                kreu=kreu,
                seksioni=seksioni,
                repealed=repealed,
                volatility=doc.volatility,
                last_amendment_date=_lad,
                note=note,
                paragrafet=paragrafet,
                heading_kind=heading_kind,
            )
        )
    articles.extend(_group_repeal_stubs(text, items, articles, doc))
    return articles


# 16 set 2026 — QUANDO un articolo è uno STUB abrogato. La regola vecchia («shfuqizuar» ovunque
# nel testo e corpo < 400 chr) marcava abrogati ~120 articoli VIVI del corpus AL — la stessa classe
# del difetto italiano dei 433 «abrogati»: l'articolo «Shfuqizime» in coda a ogni legge («Me
# hyrjen në fuqi… shfuqizohet ligji nr. …», è un VERBO), gli articoli con la nota «(Shfuqizuar
# pika 3 me ligjin …)» (abrogato un pezzo, l'articolo vive), gli articoli che hanno in coda un
# marcatore a gruppo «(Shfuqizuar nenet 80-83 …)» riferito ad ALTRI articoli. `search()` li
# saltava e il verificatore diceva «abrogato» a chi li citava. Ora è stub SOLO se, tolte le
# note fra parentesi e le righe di capo/titolo, non resta contenuto vivo oltre la rubrica — e il
# marcatore è il participio «Shfuqizuar» NUDO (non «i/e/të shfuqizuar» in prosa) o «Shfuqizohet.»
# da solo. `tools/recompute_repealed_al.py` ricalcola il flag sul jsonl senza riscaricare.
_STUB_MARK_RE = re.compile(r"(?<![\wë])(?<!\bi )(?<!\be )(?<!\btë )shfuqizuar\b", re.I)
_STUB_ALONE_RE = re.compile(r"^\W*(?:i |e |të )?(?:shfuqizohe[tn]|shfuqizuar)\W*$", re.I)
_EDIT_NOTE_RE = re.compile(r"\([^()]*\)")
_UNIT_LINE_RE = re.compile(r"^(?:KREU|KAPITULLI|TITULLI|PJESA|SEKSIONI|NËNSEKSIONI|NENSEKSIONI)\b", re.I)


class _NoteView:
    """Vista minima (heading/body) per leggere le note editoriali prima che l'Article esista."""
    __slots__ = ("heading", "body")

    def __init__(self, heading: str, body: str):
        self.heading, self.body = heading or "", body or ""


# solo l'articolo INTERO: «(Shfuqizuar me ligjin …)», mai «(Shfuqizuar fjalë/pika/shkronja … me ligjin …)» (una parte)
_STUB_TITOLO_NOTA_RE = re.compile(r"^[^().;]{3,100}\(\s*Shfuqizuar\s+(?:me|nga)\s+(?:ligjin|vendimin|VKM)\b[^)]*\)\s*[.;]?\s*$", re.I)


def is_repealed_stub(heading: str, body: str) -> bool:
    heading, body = heading or "", body or ""
    if len(body) >= 400:
        return False
    # v9.376 — «Vendimi interpretues (Shfuqizuar me ligjin nr. 99/2016, datë 6.10.2016).» senza corpo (GjK 8577/2000
    # neni 79): il punto dopo la nota lo faceva passare per una frase viva. Solo titolo + nota di abrogazione = stub.
    if not body.strip() and _STUB_TITOLO_NOTA_RE.match(" ".join(heading.split())):
        return True
    txt = heading + "\n" + body
    if (not _STUB_MARK_RE.search(txt) and not _STUB_ALONE_RE.match(txt.strip())
            and not _STUB_ALONE_RE.match(body.strip())):    # «Titulli» + corpo «Shfuqizohet.»
        return False
    plain = _EDIT_NOTE_RE.sub(" ", txt)
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _UNIT_LINE_RE.match(ln) and not (ln.isupper() and len(ln) < 80)]
    head, rest = (lines[0] if lines else ""), lines[1:]
    m = _STUB_MARK_RE.search(head)          # «Titolo Shfuqizuar me ligjin nr. …» (rubrica incollata)
    if m:
        head = head[: m.start()]
    # la rubrica incollata può contenere la PRIMA FRASE dell'articolo («Fusha e zbatimit Dispozitat
    # e këtij ligji zbatohen … .»): una frase compiuta o un titolo lunghissimo = contenuto vivo
    if not _STUB_ALONE_RE.match(head) and (re.search(r"[.;!?](?:\s|$)", head.strip()) or len(head) > 120):
        return False
    live = re.sub(r"\s+", " ", " ".join(rest)).strip()
    m2 = _STUB_MARK_RE.search(live)
    if m2 and m2.start() < 3:               # corpo = «Shfuqizuar me ligjin nr. …»
        live = ""
    if live and _STUB_ALONE_RE.match(live):  # corpo = «Shfuqizohet.»
        live = ""
    return not live and len(head) < 200


# 16 set 2026 — ABROGAZIONI A GRUPPO nei consolidati QBZ. Il K.Pr.C. dice «(Shfuqizuar titulli IV,
# nenet 400 – 441, me ligjin nr. 122/2013)» e NON stampa i 42 articoli: nel corpus restavano
# BUCHI e chi citava il neni 420 riceveva «nen fantazmë» (inventato) invece di «shfuqizuar».
# Qui ogni numero mancante coperto da un marcatore diventa uno stub `repealed=True` con la
# legge abrogante nel corpo: il verificatore lo trova in `_build_lookup_all` e dice «abrogato»,
# `search()` lo salta come gli altri abrogati. Solo numeri ASSENTI e dentro 1..max: un
# articolo presente non viene mai toccato.
_GROUP_REPEAL_RE = re.compile(r"\([^()]{0,60}?[Ss]hfuqizu\w*[^()]{0,240}\)")
_REPEAL_RANGE_RE = re.compile(r"nen(?:et|i|ve|in)\s+(\d+)\s*(?:[–\-—]|deri(?:\s+(?:në|te|tek))?)\s*(\d+)", re.I)
_REPEAL_LIST_RE = re.compile(r"nenet\s+((?:\d+\s*(?:,|dhe)\s*)+\d+)", re.I)
_REPEAL_UNIT_RE = re.compile(r"\b(?:kreu|kapitulli|titulli|seksioni|nënseksioni|pjesa)\b", re.I)
_REPEAL_PARTIAL_RE = re.compile(r"paragraf|pik[aëe]|fjal|shkronj|germ|togfjal|fjali", re.I)
_REPEAL_LAW_RE = re.compile(r"me\s+(?:ligjin|vendimin|aktin|dekretin)[^;)]*", re.I)


def _group_repeal_stubs(text: str, items: list, articles: list, doc) -> list:
    present = {str(a.number) for a in articles}
    ints = [int(str(a.number).split("/")[0]) for a in articles if str(a.number).split("/")[0].isdigit()]
    if not ints:
        return []
    mx = max(ints)
    pos_nums = sorted((m.start(), int(str(n).split("/")[0])) for m, n in items if str(n).split("/")[0].isdigit())
    stubs = []
    for mk in _GROUP_REPEAL_RE.finditer(text):
        s = re.sub(r"\s+", " ", mk.group(0)).strip()
        nums: set[int] = set()
        # si guarda SOLO ciò che segue «shfuqizu…» fino al «;» (un marcatore può dire anche
        # «ndryshuar nenet 5-7; shfuqizuar nenet 80-83»: i 5-7 non sono abrogati)
        for seg in re.split(r"[Ss]hfuqizu\w*", s)[1:]:
            seg = seg.split(";")[0]
            for a, b in _REPEAL_RANGE_RE.findall(seg):
                a, b = int(a), int(b)
                if 0 < a <= b <= a + 200:
                    nums.update(range(a, b + 1))
            for lst in _REPEAL_LIST_RE.findall(seg):
                nums.update(int(x) for x in re.findall(r"\d+", lst))
            if not nums and _REPEAL_UNIT_RE.search(seg) and not _REPEAL_PARTIAL_RE.search(seg):
                # «(shfuqizuar kreu me ligjin …)» senza numeri: l'unità intera è il buco fra
                # l'articolo prima e quello dopo il marcatore (ligji 8308/1998, kreu 54-63)
                prev = max((n for p, n in pos_nums if p < mk.start()), default=None)
                nxt = min((n for p, n in pos_nums if p > mk.start()), default=None)
                if prev is not None and nxt is not None and prev + 1 < nxt <= prev + 60:
                    nums.update(range(prev + 1, nxt))
        if not nums:
            continue
        law = _REPEAL_LAW_RE.search(s)
        ref = re.sub(r"\s+", " ", law.group(0)).strip(" ;,.") if law else ""
        pjesa, kreu, seksioni = _hierarchy_context(text[: mk.start()])
        for n in sorted(nums):
            if n < 1 or n > mx or str(n) in present:
                continue
            present.add(str(n))
            stubs.append(Article(
                code=doc.code, title_sq=doc.title_sq, area=doc.area, number=str(n),
                heading="(Shfuqizuar)",
                body=f"Shfuqizuar {ref}. Nuk figuron në tekstin e konsoliduar: {s.strip('()')}".replace("  ", " "),
                pjesa=pjesa, kreu=kreu, seksioni=seksioni, repealed=True,
                volatility=doc.volatility, last_amendment_date=doc.last_amendment_date))
    if stubs:
        log.info("parser: %s — %d nene shfuqizuar a gruppo aggiunti come stub (%s…)",
                 doc.code, len(stubs), ", ".join(a.number for a in stubs[:6]))
    return stubs


# ── Orchestration ───────────────────────────────────────────────────────────

def parse_one(doc: LegalDocument) -> list[Article]:
    pdf_path = RAW_DATA_PATH / doc.local_pdf
    if not pdf_path.exists():
        log.warning("skip %s — file not found: %s", doc.code, pdf_path)
        return []

    log.info("parsing %s ...", doc.code)
    text = extract_full_text(pdf_path)
    articles = split_into_articles(text, doc)
    log.info("  → %d articles extracted from %s", len(articles), doc.code)
    return articles


def parse_all() -> dict[str, list[Article]]:
    PROCESSED_DATA_PATH.mkdir(parents=True, exist_ok=True)
    all_articles: dict[str, list[Article]] = {}
    combined_path = PROCESSED_DATA_PATH / "all_articles.jsonl"
    with combined_path.open("w", encoding="utf-8") as combined:
        for doc in LEGAL_DOCUMENTS:
            articles = parse_one(doc)
            all_articles[doc.code] = articles

            # per-code JSON for debugging / inspection
            (PROCESSED_DATA_PATH / f"{doc.code}.json").write_text(
                json.dumps([asdict(a) for a in articles], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for a in articles:
                combined.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    log.info("combined articles written to %s", combined_path)
    return all_articles


def print_summary(results: dict[str, list[Article]]) -> None:
    print("\n" + "=" * 60)
    print(f"{'Code':<22}{'Articles':>10}{'Repealed':>12}{'Avg body':>12}")
    print("-" * 60)
    total = 0
    for code, articles in results.items():
        total += len(articles)
        if not articles:
            print(f"{code:<22}{'0':>10}{'-':>12}{'-':>12}")
            continue
        repealed = sum(1 for a in articles if a.repealed)
        avg_body = int(sum(len(a.body) for a in articles) / len(articles))
        print(f"{code:<22}{len(articles):>10}{repealed:>12}{avg_body:>12}")
    print("-" * 60)
    print(f"{'TOTAL':<22}{total:>10}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    results = parse_all()
    print_summary(results)
