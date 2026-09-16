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
import re
from dataclasses import asdict, dataclass
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

    @property
    def citation(self) -> str:
        """Citazione nella forma della giurisdizione dell'articolo.

        I corpora italiani usano slug noti (codice_*, tu_*, disp_att_*, …):
        per quelli si cita "art. N Titolo", non "Neni N i Titolo"."""
        if _is_italian_code(self.code):
            return f"art. {self.number} {self.title_sq}"
        return f"Neni {self.number} i {self.title_sq}"

    @property
    def searchable_text(self) -> str:
        """Text to embed — heading + body + citation for recall."""
        parts = [self.citation]
        if self.heading:
            parts.append(self.heading)
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

def _hierarchy_context(text_before: str) -> tuple[str, str, str]:
    """Return the most recent (pjesa, kreu, seksioni) mentioned before this pos."""
    pjesa = kreu = seksioni = ""
    for match in HIERARCHY_RE.finditer(text_before):
        label = match.group(1).upper()
        line = match.group(0).strip()
        # Try to include the next line as the title of the section
        tail = text_before[match.end() : match.end() + 200]
        next_line = next((ln.strip() for ln in tail.splitlines() if ln.strip()), "")
        full = f"{line} — {next_line}" if next_line and not HIERARCHY_RE.match(next_line) else line
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
            if inline and (not (last_ok + 1 <= n_int <= last_ok + 3) or body_len < 40):
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
        if i > 0 and num_int > 0 and num_int < seen_max - 5:
            nxt: list[int] = []
            for k in range(i + 1, min(i + 4, len(filtered))):
                try:
                    nxt.append(int(re.sub(r"\s+", "", filtered[k].group(1)).split("/")[0]))
                except ValueError:
                    pass
            if any(v > seen_max for v in nxt):
                if nxt and nxt[0] == seen_max + 2:
                    log.info("parser: %s — Neni %s letto come %d (numero stampato male)",
                             doc.code, num_str, seen_max + 1)
                    items.append((m, str(seen_max + 1)))
                    seen_max += 1
                else:
                    log.info("parser: %s — Neni %s fuori sequenza, saltato", doc.code, num_str)
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
    for i, m in enumerate(matches):
        number = numbers[i]  # "83 / a" -> "83/a" (o il numero ricomposto)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw = text[start:end].strip()
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

        # Hierarchy from the text *before* this article
        pjesa, kreu, seksioni = _hierarchy_context(text[: m.start()])

        repealed = any(mk in (heading + " " + body).lower() for mk in REPEALED_MARKERS) \
                   and len(body) < 400  # short body + "shfuqizuar" → repealed stub

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
                last_amendment_date=doc.last_amendment_date,
            )
        )
    return articles


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
