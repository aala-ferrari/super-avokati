#!/usr/bin/env python3
"""Re-parse dei precedenti ALBANESI (Gjykata Kushtetuese + Gjykata e Lartë) — un documento alla volta, con verifica.

Perché (audit 22 set 2026): nel pickle vivo 388 sentenze GjL avevano come «ragionamento» i primi 8.000
caratteri del documento (intestazione + gradi inferiori), 225 erano inammissibilità etichettate «rrëzim»,
il dispositivo mancava; 18 dispositivi e 7 esiti della Kushtetuese erano sbagliati perché il parser cercava
le ancore senza distinguere maiuscole («për këto arsye» minuscolo nel testo spostava l'ancora).

Un solo parser a TEMPLATE per le due corti, ancore SENSIBILI alle maiuscole, ragionamento GjL dal marcatore
del Kolegji, esclusione deterministica di ciò che non è un precedente (mospranim, kthim i rekursit dal
relatore, errata, moskalim), verifica campo per campo, e caricamento uno per uno nel database dei
precedenti (JSONL = fonte di verità, pickle v2 = indice ricostruito dopo ogni documento verificato).

Modalità (percorsi pensati per il container, /app):
  probe            legge tutti i documenti dalla cache dei testi, parse+verifica, NON scrive nulla:
                   statistiche + esempi per ogni motivo di fallimento
  run              uno per uno: parse → verifica → se OK appende al JSONL e ricostruisce il pickle v2;
                   ripartibile (salta i documenti già caricati); i FAIL/EXCLUDE finiscono nei verdetti
  one <rel>        stampa il record prodotto per un documento (controllo a occhio)
  report           riassunto dei verdetti scritti da run
Variabili: RAW_DIR, TXT_CACHE, OUT_JSONL, OUT_PKL, OLD_PKL, VERDICTS, ONLY (prefisso rel), LIMIT.
"""
from __future__ import annotations

import collections
import hashlib
import html as htmlmod
import json
import os
import pickle
import re
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RAW = Path(os.environ.get("RAW_DIR", "/app/data/raw/jurisprudence"))
CACHE = Path(os.environ.get("TXT_CACHE", "/tmp/txt_cache"))
OUT_JSONL = Path(os.environ.get("OUT_JSONL", "/app/data/processed/al_decisions_v2.jsonl"))
OUT_PKL = Path(os.environ.get("OUT_PKL", "/app/data/index/bm25_decisions_v2.pkl"))
OLD_PKL = Path(os.environ.get("OLD_PKL", "/app/data/index/bm25_decisions.pkl"))
VERDICTS = Path(os.environ.get("VERDICTS", "/tmp/reparse_verdicts.jsonl"))
COURTS_AL = ("kushtetuese", "gjykata_elarte")

FIELDS = ("court_code", "court_title_sq", "court_short_sq", "year", "number", "date", "citation", "short_id",
          "objekti", "kerkues", "subjekte_interesuara", "baza_ligjore", "judges", "cited_articles", "outcome",
          "dispositif", "reasoning", "source_file", "source_url", "kind")
COURT_NAMES = {
    "kushtetuese": ("Gjykata Kushtetuese e Republikës së Shqipërisë", "Gjykata Kushtetuese"),
    "gjykata_elarte": ("Gjykata e Lartë e Republikës së Shqipërisë", "Gjykata e Lartë"),
}

# ── testo ─────────────────────────────────────────────────────────────────

def _ck(rel: str) -> Path:
    return CACHE / (hashlib.sha1(rel.encode()).hexdigest() + ".txt")


def _extract(p: Path) -> str:
    b = p.open("rb").read(8)
    try:
        if b.startswith(b"\xd0\xcf\x11\xe0"):
            r = subprocess.run(["antiword", "-m", "UTF-8.txt", "-w", "0", str(p)], capture_output=True, timeout=90)
            return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
        if b.startswith(b"PK"):
            from docx import Document
            d = Document(str(p)); parts = [x.text for x in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)
        if b.startswith(b"%PDF"):
            import pdfplumber
            with pdfplumber.open(str(p)) as pdf:
                return "\n".join((pg.extract_text() or "") for pg in pdf.pages[:200])
        raw = p.read_bytes().decode("utf-8", "replace")
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw); raw = htmlmod.unescape(raw)
        return re.sub(r"[ \t\xa0]+", " ", raw)
    except Exception:  # noqa: BLE001
        return ""


def raw_text(rel: str) -> str:
    k = _ck(rel)
    if k.exists():
        return k.read_text(encoding="utf-8")
    t = _extract(RAW / rel)
    CACHE.mkdir(exist_ok=True)
    k.write_text(t, encoding="utf-8")
    return t


def is_pdf(rel: str) -> bool:
    try:
        return (RAW / rel).open("rb").read(4) == b"%PDF"
    except Exception:  # noqa: BLE001
        return rel.lower().endswith(".pdf")


_END_PUNCT = re.compile(r"[.;:!?»”\")\]]\s*$")
_LABEL_LINE = re.compile(r"^\s*[A-ZËÇ][A-ZËÇ0-9 /\-’'.()]{2,60}:\s*$")
_SPACED_LINE = re.compile(r"^\s*(?:[A-ZËÇ]\s){2,}[A-ZËÇ]\s*:?\s*$")
_SHORT_FUNC = {"të", "e", "i", "së", "me", "nga", "për", "dhe", "në", "që", "sipas", "ose", "apo", "si", "pa", "mbi", "prej", "nën", "kur", "se", "a", "u", "ka", "do", "nuk", "të,", "e,", "i,", "dhe,"}


def normalize(text: str, pdf: bool) -> tuple[str, dict]:
    """Pulizia: intestazioni di pagina ripetute, numeri di pagina, [pic], righe spezzate dei PDF."""
    info = {"page_headers_removed": 0, "lines_joined": 0}
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").replace("\t", " ").replace("\x0c", "\n")
    text = re.sub(r"\[pic\]", "", text)
    # «Kërkues: … Faqe 2» / «Faqe 3 nga 40»: il numero di pagina rende ogni riga diversa — via il numero, poi
    # le ripetizioni si vedono
    text = re.sub(r"[ ]*\bFaqe\s+\d{1,3}(?:\s+nga\s+\d{1,3})?[ ]*$", "", text, flags=re.M)
    lines = text.split("\n")
    cnt = collections.Counter(ln.strip() for ln in lines if 6 <= len(ln.strip()) <= 140)
    rep = {ln for ln, c in cnt.items() if c >= 3 and not re.match(r"^\d+\.", ln) and not _END_PUNCT.search(ln)}
    # intestazione di pagina dei PDF della Kushtetuese («Vendim i Gjykatës Kushtetuese» / «Kërkues: …»): basta che si ripeta
    rep |= {ln for ln, c in cnt.items() if c >= 2 and re.match(r"^(?:Vendim i Gjykat[ëe]s Kushtetuese|K[ëe]rkues[ei]?(?:\s*\([^)]*\))?\s*:)", ln)}
    out = []
    for ln in lines:
        s = ln.strip()
        if s in rep:
            info["page_headers_removed"] += 1
            continue
        if re.match(r"^\d{1,3}$", s):
            continue
        out.append(ln)
    lines = out
    if pdf:
        joined = []
        for ln in lines:
            s = ln.rstrip()
            if joined and joined[-1].strip() and s.strip():
                prev = joined[-1].rstrip()
                pl = prev.strip()
                cont = s.strip()
                prev_open = (not _END_PUNCT.search(pl)) and not _LABEL_LINE.match(pl) and not _SPACED_LINE.match(pl) \
                    and not re.match(r"^[IVX]+\.?$", pl) and not pl.isupper()
                next_low = bool(re.match(r"^[a-zëç(«\"“]", cont)) or (pl.endswith(",")) or (pl.split(" ")[-1].lower() in _SHORT_FUNC)
                next_para = bool(re.match(r"^(?:\d+\.|[IVX]+\.|[a-zç]\)|-\s|•)", cont)) or _LABEL_LINE.match(cont) or _SPACED_LINE.match(cont)
                if prev_open and next_low and not next_para:
                    if pl.endswith("-") and re.match(r"^[a-zëç]", cont):
                        joined[-1] = pl[:-1] + cont
                    else:
                        joined[-1] = pl + " " + cont
                    info["lines_joined"] += 1
                    continue
            joined.append(s)
        lines = joined
    text = "\n".join(lines)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), info


# ── ancore (maiuscole: solo le intestazioni vere) ─────────────────────────

LINE_VEREN = re.compile(r"^[ ]*V\s*Ë\s*R\s*E\s*(?:N|N\s*I|J\s*N\s*Ë)(?:\s+S\s*E)?\s*:?[ ]*$", re.M)
LINE_PER_KETO = re.compile(r"^[ ]*P\s*Ë\s*R\s+K\s*Ë\s*T\s*[OË]\s+A\s*R\s*S\s*Y\s*E\s*[,:.]?[ ]*$", re.M)   # anche «PËR KËTË ARSYE»
INLINE_PER_KETO = re.compile(r"P\s*Ë\s*R\s+K\s*Ë\s*T\s*[OË]\s+A\s*R\s*S\s*Y\s*E")
LINE_VENDOSI = re.compile(r"^[ ]*V\s*E\s*N\s*D\s*O\s*S\s*(?:I|Ë\s*N|A)\s*:?[ ]*$", re.M)
INLINE_VENDOSI = re.compile(r"\bV\s*E\s*N\s*D\s*O\s*S\s*(?:I|ËN|A)\b\s*:?")   # anche a fine riga senza «:» (PDF)
DISP_END = re.compile(r"^[ ]*(?:Ky vendim|Tiran[ëe],?\s+m[ëe]\b|Tiran[ëe]\s+m[ëe]\b|Kryetar|KRYETAR|Kryesues|KRYESUES|An[ëe]tar|ANËTAR|Relator|Sekretar|MENDIM|Mendim i pakic|Mendimi i pakic|MENDIMI|Gjyqtar|GJYQTAR|Nënkryetar|Z[ëe]vend[ëe]s)", re.M)
KOL_HEADING = re.compile(r"^[ ]*(?:[IVX]+\s*[.)]?\s*)?(?:V\s*L\s*E\s*R\s*Ë\s*S\s*I\s*M\s*I\s+I\s+K\s*O\s*L\s*E\s*G\s*J|Vler[ëe]simi i Kolegj)", re.M | re.I)
KOL_SENT = re.compile(r"(?:Kolegji|Kolegjet e Bashkuara|ky Kolegj|Ky Kolegj)(?:\s+(?:Civil|Penal|Administrativ|i\s+Gjykat[ëe]s\s+s[ëe]\s+Lart[ëe]|\(n[ëe] vijim Kolegji\)|,))*[^.\n]{0,90}?\b(?:vler[ëe]son|vler[ëe]sojn[ëe]|çmon|çmojn[ëe]|konstaton|konstatojn[ëe]|thekson|theksojn[ëe]|arsyeton|arsyetojn[ëe]|gjykon|gjykojn[ëe]|arrin n[ëe] p[ëe]rfundimin|arrijn[ëe] n[ëe] p[ëe]rfundimin|v[ëe]ren se|v[ëe]rejn[ëe] se)", re.I)
STOP_HEAD = re.compile(r"^[ ]*(?:GJYKATA KUSHTETUESE|GJYKATA E LART[ËE]|KOLEGJI\s+(?:PENAL|CIVIL|ADMINISTRATIV)|KOLEGJET E BASHKUARA|Gjykata Kushtetuese e Republik[ëe]s|Kolegji (?:Penal|Civil|Administrativ) i Gjykat[ëe]s|Kolegjet e Bashkuara t[ëe] Gjykat[ëe]s|pasi d[ëe]gjoi|V\s*Ë\s*R\s*E\s*N)", re.M)
RECITAL_START = re.compile(r"^[ ]*(?:\d+\.\s|[IVX]+\.\s|Gjykata e (?:Rrethit|Apelit|Shkall[ëe]s|Pos[ëa]çme)|Gjykata Administrative|Kund[ëe]r vendimit|Me vendimin|Pala |Padit[ëe]si|K[ëe]rkues[ie]\b|I pandehuri|Prokuroria|Rrethanat|RRETHANAT|Ndaj |Sipas |N[ëe] dat[ëe]n|N[ëe] shqyrtim|Nga aktet|Rezulton|Ka rezultuar|Kolegji|Gjykata Kushtetuese)", re.M)
# Etichette a inizio riga: una frase breve che finisce con «:» («PADITËS:», «Paditës:», «ME OBJEKT:», «OBJEKTI I
# PADISË:», «KËRKUESE (ANKUESE):», «Ndaj Shtetasit:», «KUNDËR SUBJEKTIT:»); è etichetta solo se contiene una delle
# parole chiave (norm_label → None altrimenti). «PERSONA TË TRETË» compare anche senza i due punti.
LABEL_RX = re.compile(r"^[ ]*([A-ZËÇ][^\n:]{0,60}?)\s*:(?!\d)|^[ ]*(PERSON(?:A|I)?\s+(?:I|T[ËE])\s+TRET[ËEA]T?)\b(?=\s+[A-ZËÇ“\"])", re.M)
_LABEL_KEYS = (
    ("KERKUES", "KERKUES"), ("PADITES", "PADITES"), ("PADITUR", "PADITUR"), ("TRET", "TRETE"), ("ANKUES", "ANKUES"),
    ("REKURSUES", "REKURSUES"), ("KALLEZUES", "KALLEZUES"), ("PANDEHUR", "PANDEHUR"), ("AKUZUAR", "AKUZUAR"),
    ("GJYKUAR", "GJYKUAR"), ("DENUAR", "DENUAR"), ("VIKTIM", "VIKTIME"), ("SUBJEKT", "SUBJEKT"), ("INTERESUAR", "INTERESUAR"),
    ("OBJEKT", "OBJEKTI"), ("KERKES", "OBJEKTI"), ("BAZALIGJORE", "BAZA"), ("BAZËLIGJORE", "BAZA"), ("KUNDER", "KUNDER"), ("NDAJ", "KUNDER"),
    ("SHTETASIT", "KUNDER"), ("PROKUROR", "PROKUROR"), ("MBROJTES", "MBROJTES"),
)


def norm_label(s: str) -> str | None:
    k = re.sub(r"[\s.()\-’'\"“”/]+", "", s.upper().rstrip(":")).replace("Ë", "E").replace("Ç", "C")
    if len(k) > 40: return None
    if k.startswith("OBJEKT") or k.startswith("MEOBJEKT"): return "OBJEKTI"
    if k.startswith("BAZ"): return "BAZA"
    if k.startswith("PADITES"): return "PADITES"          # «PADITËSE E KUNDËRPADITUR» → paditës
    for key, name in _LABEL_KEYS:
        if key in k: return name
    return None


PRETTY_LABEL = {"KERKUES": "KËRKUES", "PADITES": "PADITËS", "PADITUR": "I PADITUR", "TRETE": "PERSON I TRETË",
                "ANKUES": "ANKUES", "REKURSUES": "REKURSUES", "KALLEZUES": "KALLËZUES", "PANDEHUR": "I PANDEHUR",
                "VIKTIME": "VIKTIMË", "INTERESUAR": "PALË E INTERESUAR", "SUBJEKT": "SUBJEKTE TË INTERESUARA",
                "KUNDER": "KUNDËR", "AKUZUAR": "AKUZUAR", "GJYKUAR": "I GJYKUAR", "DENUAR": "I DËNUAR",
                "PROKUROR": "PROKUROR", "MBROJTES": "MBROJTËS"}
PARTY_FIRST = ("KERKUES", "PADITES", "ANKUES", "REKURSUES", "KALLEZUES", "PANDEHUR", "GJYKUAR", "DENUAR", "VIKTIME")


def nz(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" :;,\t-")


def cut_value(val: str, cap: int) -> tuple[str, bool]:
    """Il valore di un'etichetta finisce alla prossima intestazione, a una riga vuota o all'inizio dei fatti."""
    m = STOP_HEAD.search(val)
    if m: val = val[:m.start()]
    m = re.search(r"\n[ ]*\n", val)
    if m and len(nz(val[:m.start()])) >= 12: val = val[:m.start()]
    nl = val.find("\n")                       # i fatti («1. …», «Gjykata e Apelit …») iniziano su una riga NUOVA
    m = RECITAL_START.search(val, nl + 1) if nl >= 0 else None
    if m and len(nz(val[:m.start()])) >= 12: val = val[:m.start()]
    v = nz(val)
    cut = len(v) > cap
    return (v[:cap].rsplit(" ", 1)[0] + " …" if cut else v), cut


ROLE_RX = re.compile(r"\b(Kryetar[ëe]?|KRYETAR[ËE]?|Kryesues[ëe]?|KRYESUES[ËE]?|An[ëe]tar[ëe]?|ANËTAR[ËE]?|Relator[ëe]?|RELATOR[ËE]?|gjyqtar[ëe]?t?|GJYQTAR[ËE]?T?|z\.|znj\.|Z\.|Znj\.)\b", re.I)


def extract_judges(text: str) -> list[str]:
    m = re.search(r"p[ëe]rb[ëe]r[ëea]\s+(?:nga|prej)\s*(?:gjyqtar[ëe]t)?\s*:?", text[:8000], re.I)
    if not m:
        return []
    block = text[m.end(): m.end() + 1500]
    block = re.sub(r"^[^\n:]{0,80}:", "", block, count=1)      # «prej anëtarëve të Gjykatës së Lartë :» → via
    stop = re.search(r"me\s+sekretar|n[ëe]\s+dat[ëe]n|Sot,?\s+m[ëe]\b|mori\s+n[ëe]\s+shqyrtim|shqyrtoi|(?-i:^[ ]*[A-ZËÇ][A-ZËÇ /]{3,}:\s)|n[ëe]\s+dhom[ëe]n|n[ëe]\s+seanc[ëe]", block, re.M | re.I)
    if stop: block = block[:stop.start()]
    names: list[str] = []
    for chunk in re.split(r"[,;\n]+|\s+-\s+|\s-|/", block):
        c = ROLE_RX.sub(" ", chunk)
        c = re.sub(r"[^A-Za-zËëÇç.\s]", " ", c)
        toks = [t for t in c.split() if len(t) >= 2 and t not in ("dhe", "e", "i", "të", "me", "nga", "prej")]
        if not (2 <= len(toks) <= 3):
            continue
        if not all(t[0].isupper() for t in toks):
            continue
        if any(t.lower() in ("gjykata", "kolegji", "republika", "shqipërisë", "kushtetuese", "lartë", "lartë,") for t in toks):
            continue
        name = " ".join(t if not t.isupper() else t.capitalize() for t in toks)
        name = re.sub(r"\.$", "", name)
        if name not in names:
            names.append(name)
    return names[:12]


# ── esito ──────────────────────────────────────────────────────────────────

GJK_VERBS = [
    ("pjesërisht", re.compile(r"pranimin?\s+(?:pjes[ëe]risht|e\s+pjes(?:sh[ëe]m|shme))|pjes[ëe]risht", re.I)),
    ("pranim", re.compile(r"\bpranimin?\b", re.I)),
    ("rrëzim", re.compile(r"\brr[ëe]zimin?\b", re.I)),
    ("pushim", re.compile(r"\bpushimin?\b", re.I)),
    ("moskompetencë", re.compile(r"moskompetenc", re.I)),
    ("shfuqizim", re.compile(r"\bshfuqizimin?\b", re.I)),
    ("deklarim", re.compile(r"\bdeklarimin?\b|\bkonstatimin?\b|\bt[ëe]\s+deklaroj[ëe]\b|\bdeklaron\b|\bt[ëe]\s+konstatoj[ëe]\b", re.I)),
    ("interpretim", re.compile(r"\binterpretimin?\b", re.I)),
    ("pezullim", re.compile(r"\bpezullimin?\b", re.I)),
    ("ERRATA", re.compile(r"\bsakt[ëe]simin?\b|\bndreqjen?\b|\bkorrigjimin?\b", re.I)),
    ("MOSKALIM", re.compile(r"\bmoskalimin?\b", re.I)),
]
GJL_VERBS = [
    ("mospranim", re.compile(r"\bmospranimin?\b", re.I)),
    ("kthim i rekursit", re.compile(r"\bkthimin?\s+e\s+rekursit\b", re.I)),
    ("ERRATA", re.compile(r"\bndreqjen?\b|\bsakt[ëe]simin?\b|\bkorrigjimin?\b", re.I)),
    ("prishje", re.compile(r"\bprishjen?\b", re.I)),
    ("lënia në fuqi", re.compile(r"\bl[ëe]nien?\s+n[ëe]\s+fuqi\b", re.I)),
    ("ndryshim", re.compile(r"\bndryshimin?\b", re.I)),
    ("pushim", re.compile(r"\bpushimin?\b", re.I)),
    ("moskompetencë", re.compile(r"nxjerrjen?\s+jasht[ëe]\s+juridiksionit|\bmoskompetenc", re.I)),
    ("kompetencë", re.compile(r"mosmarr[ëe]veshjes?\s+(?:p[ëe]r|t[ëe]|s[ëe])\s+kompetenc|gjykat[ëe]n?\s+kompetente|p[ëe]r\s+kompetenc[ëe]|konfliktin?\s+(?:e|p[ëe]r)\s+kompetenc", re.I)),
    ("pranim", re.compile(r"\bpranimin?\b", re.I)),
    ("rrëzim", re.compile(r"\brr[ëe]zimin?\b", re.I)),
    ("pezullim", re.compile(r"\bpezullimin?\b", re.I)),
    ("dërgim", re.compile(r"\bd[ëe]rgimin?\s+e\s+(?:ç[ëe]shtjes|akteve)\b", re.I)),
    ("shfuqizim", re.compile(r"\bshfuqizimin?\b", re.I)),
]


def first_verb(disp: str, table) -> tuple[str, int]:
    best = ("", 10 ** 9)
    head = disp[:400]
    for label, rx in table:
        m = rx.search(head)
        if m and m.start() < best[1]:
            best = (label, m.start())
    return best


def classify_gjk(disp: str) -> tuple[str, str]:
    """→ (outcome, exclude_reason)"""
    lab, _ = first_verb(disp, GJK_VERBS)
    if lab == "ERRATA": return "", "errata (saktësim/ndreqje e një vendimi të mëparshëm)"
    if lab == "MOSKALIM": return "", "moskalim (vendim i Kolegjit, jo i seancës plenare)"
    if lab == "shfuqizim": return "pranim", ""          # «Shfuqizimin e nenit…» senza «Pranimin»: la kërkesa è accolta
    return lab, ""


def classify_gjl(disp: str) -> tuple[str, str, str]:
    """→ (outcome, etichetta letterale fra parentesi quadre, exclude_reason)"""
    lab, pos = first_verb(disp, GJL_VERBS)
    low = disp[:600].lower()
    if lab == "mospranim": return "", "mospranim", "mospranim (nuk vendos mbi themelin)"
    if lab == "kthim i rekursit": return "", "kthim i rekursit", "kthim i rekursit nga relatori (nuk është vendim i Kolegjit)"
    if lab == "ERRATA": return "", "ndreqje", "errata (ndreqje/saktësim i një vendimi të mëparshëm)"
    if lab == "prishje":
        rest = low[pos:pos + 500]
        if re.search(r"\bkthimin?\b|\bd[ëe]rgimin?\b|rigjykim|rishqyrtim", rest): return "kthim për rishqyrtim", "prishje + kthim", ""
        if re.search(r"\bpushimin?\b", rest): return "pushim", "prishje + pushim", ""
        if re.search(r"l[ëe]nien?\s+n[ëe]\s+fuqi", rest): return "pranim", "prishje + lënia në fuqi", ""
        if re.search(r"\brr[ëe]zimin?\b", rest): return "pranim", "prishje + rrëzim", ""
        if re.search(r"\bndryshimin?\b", rest): return "ndryshim", "prishje + ndryshim", ""
        return "pranim", "prishje", ""
    if lab == "lënia në fuqi": return "rrëzim", "lënia në fuqi", ""
    if lab == "ndryshim": return "ndryshim", "ndryshim", ""
    if lab == "pushim": return "pushim", "pushim", ""
    if lab == "moskompetencë": return "moskompetencë", "moskompetencë", ""
    if lab == "kompetencë": return "kompetencë", "kompetencë", ""
    if lab == "pranim": return "pranim", "pranim", ""
    if lab == "rrëzim": return "rrëzim", "rrëzim", ""
    if lab == "pezullim": return "pezullim", "pezullim", ""
    if lab == "dërgim":
        if re.search(r"rishqyrtim|rigjykim|vazhdimin\s+e\s+gjykimit", low[pos:pos + 400]): return "kthim për rishqyrtim", "dërgim për rishqyrtim", ""
        return "kompetencë", "dërgim për kompetencë", ""
    if lab == "shfuqizim": return "pranim", "shfuqizim", ""
    return "", "", ""


# ── numero / data ──────────────────────────────────────────────────────────

def norm_date(s: str) -> str:
    m = re.match(r"^\s*(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\s*$", s or "")
    if not m: return ""
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= d <= 31 and 1 <= mo <= 12 and 1990 <= y <= 2030): return ""
    return f"{d:02d}.{mo:02d}.{y}"


def gjk_number_date(text: str, rel: str, old: dict | None):
    warn = []
    head = text[:1500]
    m = re.search(r"Vendim\s+nr\.?\s*(\d{1,3})\s*,?\s*dat[ëe]\s*(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})", head)
    sid = re.search(r"\(\s*V\s*-\s*(\d+)\s*/\s*(\d{2,4})\s*\)", head)
    fn = re.search(r"vend_0*(\d+)_(\d{4})", rel)
    number = m.group(1) if m else (fn.group(1) if fn else (old or {}).get("number", ""))
    date = norm_date(m.group(2)) if m else ""
    if not date and old and norm_date(old.get("date", "")): date = norm_date(old["date"]); warn.append("data dal record precedente (intestazione senza data)")
    if fn and m and int(fn.group(1)) != int(m.group(1)): warn.append(f"numero intestazione {m.group(1)} ≠ nome file {fn.group(1)}")
    year = int(date[-4:]) if date else (int(fn.group(2)) if fn else int((old or {}).get("year") or 0))
    if fn and year and int(fn.group(2)) != year: warn.append(f"anno data {year} ≠ anno nome file {fn.group(2)}")
    number = str(int(number)) if str(number).isdigit() else str(number)
    short_id = f"V-{sid.group(1)}/{sid.group(2)}" if sid else ""
    return number, date, year, short_id, warn


_D = r"(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})"


def gjl_dates(text: str, disp_end: int | None = None) -> list[tuple[str, str]]:
    """Date della DECISIONE: in calce («Tiranë, më …», DOPO il dispositivo) o nella frase della seduta («sot, më
    datë … mori në shqyrtim», «në dhomë këshillimi, me datë …»). Le date dei gradi inferiori NON contano."""
    out = []
    tail = text[disp_end: disp_end + 2500] if disp_end else text[-1500:]
    for x in re.findall(r"Tiran[ëe],?\s+(?:m[ëe]\s+)?(?:dat[ëe]n?\s+)?" + _D, tail): out.append(("calce", x))
    head = text[:4500]
    for m in re.finditer(_D, head):
        before = head[max(0, m.start() - 160): m.start()]
        after = head[m.end(): m.end() + 160]
        ctx = before + " " + after
        if re.search(r"\b[Ss]ot\b[^.\n]{0,40}$", before) or re.search(r"mor[iëe]n?\s+n[ëe]\s+shqyrtim|shqyrtoi|n[ëe]\s+dhom[ëe]|k[ëe]shillimit|seanc[ëe]\s+gjyq", ctx):
            if not re.search(r"vendim\w*\s+(?:nr|me\s+nr)[^\n]{0,40}$", before, re.I):   # «vendimin nr. 94, datë …» = grado inferiore
                out.append(("seduta", m.group(1)))
    return out


def gjl_number_date(text: str, rel: str, old: dict | None, disp_end: int | None = None):
    warn = []
    head = text[:3500]
    kb = bool(re.search(r"KOLEGJET\s+E\s+BASHKUARA|Kolegj(?:i|e)t\s+e\s+Bashkuara", head))
    m = re.search(r"Nr\.?\s*(00\s*[-–]\s*20\d\d\s*[-–]\s*\d{1,5})\s*(?:i\s+)?Vendimi", head)
    number = ""
    if m: number = re.sub(r"\s+", "", m.group(1)).replace("–", "-")
    fn = re.search(r"(00-20\d\d-\d{1,5})", rel.replace("–", "-"))
    if number and fn and fn.group(1) != re.sub(r"^00-(20\d\d)-0*(\d+)$", lambda x: f"00-{x.group(1)}-{int(x.group(2))}", number):
        warn.append(f"numero intestazione {number} ≠ nome file {fn.group(1)}")
    if not number and fn: number = fn.group(1); warn.append("numero dal nome del file (non trovato nell'intestazione)")
    dates = [(src, norm_date(x)) for src, x in gjl_dates(text, disp_end)]
    dates = [(s, d) for s, d in dates if d]
    ny = re.match(r"^(?:00|KB)-(20\d\d)-", number)
    date = ""
    if ny:   # fra calce e seduta vince quella che concorda con l'anno del numero (i refusi di anno esistono: «Tiranë, më 03.02.2020» su un vendim 00-2021-160)
        for s, d in dates:
            if d[-4:] == ny.group(1): date = d; break
    if not date and dates: date = dates[0][1]
    if not number and kb:
        mk = re.search(r"Nr\.?\s*(\d{1,4})\s*(?:i\s+)?Vendimi", head)
        if mk and date: number = f"KB-{date[-4:]}-{int(mk.group(1))}"; warn.append("vendim unifikues (Kolegjet e Bashkuara): numero KB-anno-n")
    if not number:
        m2 = re.search(r"Vendimi?\s+(?:Unifikues\s+)?nr\.?\s*(\d{1,5})\s*[,]?\s*dat[ëe]\s*(\d{1,2}\.\d{1,2}\.\d{4})", head, re.I)
        if m2:
            y = m2.group(2)[-4:]; number = f"00-{y}-{m2.group(1)}"; warn.append("numero ricostruito da «Vendimi nr. N, datë»")
    if not number and old and old.get("number"):
        number = str(old["number"]).replace(" ", ""); warn.append("numero dal record precedente")
    mm = re.match(r"^(00|KB)-(20\d\d)-0*(\d+)$", number)
    if mm: number = f"{mm.group(1)}-{mm.group(2)}-{int(mm.group(3))}"
    if not date and old and norm_date(old.get("date", "")): date = norm_date(old["date"]); warn.append("data dal record precedente")
    year = int(mm.group(2)) if mm else (int(date[-4:]) if date else 0)
    if date and year and int(date[-4:]) != year: warn.append(f"anno della data {date[-4:]} ≠ anno del numero {year}")
    return number, date, year, "", warn


# ── nene citati ────────────────────────────────────────────────────────────

def cited_articles_for(objekti: str, baza: str, reasoning: str, dispositif: str, article_index) -> tuple[list[str], str]:
    """«code:number» via citation_verifier (verificati/abrogati), poi i numeri nudi; max 60. Ritorna (lista, avviso)."""
    cited: list[str] = []; warn = ""
    if article_index is not None and (objekti or baza or reasoning):
        try:
            from src.citation_verifier import verify_text
            res = verify_text((objekti + "\n" + baza + "\n" + reasoning + "\n" + dispositif)[:120_000], article_index)
            seen = set()
            for ct in (res.get("citations") or res.get("items") or []):
                code = getattr(ct, "code", None) if not isinstance(ct, dict) else ct.get("code")
                num = getattr(ct, "number", None) if not isinstance(ct, dict) else ct.get("number")
                st = getattr(ct, "status", "") if not isinstance(ct, dict) else ct.get("status", "")
                if not num: continue
                key = f"{code}:{num}" if code and st in ("verified", "repealed", "stale", "verified_stale") else str(num)
                if key not in seen:
                    seen.add(key); cited.append(key)
        except Exception as exc:  # noqa: BLE001
            warn = f"citazioni: verificatore non disponibile ({exc})"
    if not cited:
        for m in re.finditer(r"\bnen(?:i|it|in|e|eve|et)?\s+(\d+(?:\s*/\s*[a-zçë0-9]+)?)", objekti + " " + baza + " " + reasoning, re.I):
            k = re.sub(r"\s+", "", m.group(1))
            if k not in cited: cited.append(k)
    # i «code:number» prima: sono quelli che legano il vendim ai nene recuperati
    cited = sorted(cited[:80], key=lambda s: 0 if ":" in s else 1)[:60]
    return cited, warn


# ── parser ─────────────────────────────────────────────────────────────────

def parse(court: str, rel: str, text: str, old: dict | None, article_index=None) -> tuple[dict | None, dict]:
    v = {"status": "OK", "reasons": [], "warnings": [], "checks": {}}
    text, ninfo = normalize(text, is_pdf(rel))
    if ninfo["page_headers_removed"]: v["warnings"].append(f"intestazioni di pagina rimosse: {ninfo['page_headers_removed']}")
    if len(text) < 800:
        if old and len(old.get("reasoning") or "") > 500 and (old.get("dispositif") or "").startswith("["):
            # documento non leggibile (es. .doc che antiword rifiuta): si conserva il record già verificato il 29 ago,
            # dichiarandolo — non è una ri-verifica
            rec = {k: old.get(k) for k in FIELDS}; rec["source_file"] = rel; rec["kind"] = "decision"
            v["warnings"].append("documento illeggibile: conservato il record precedente (NON riverificato dal documento)")
            v["checks"]["carried_over"] = True
            return rec, v
        v["status"] = "FAIL"; v["reasons"].append(f"testo illeggibile ({len(text)} chr)"); return None, v
    sq = len(re.findall(r"\b(dhe|të|së|nga|për|gjykata|nenit|neni)\b", text[:6000]))
    en = len(re.findall(r"\b(the|of|and|court|applicant)\b", text[:6000]))
    if en > sq:
        v["status"] = "FAIL"; v["reasons"].append("testo non in albanese"); return None, v

    # ancore
    veren = LINE_VEREN.search(text)
    per_ketos = list(LINE_PER_KETO.finditer(text)) or list(INLINE_PER_KETO.finditer(text))
    vendosis = list(LINE_VENDOSI.finditer(text)) or list(INLINE_VENDOSI.finditer(text))
    pk = None
    for cand in reversed(per_ketos):
        if any(cand.end() <= vd.start() <= cand.end() + 1500 for vd in vendosis):
            pk = cand; break
    if pk is None and per_ketos: pk = per_ketos[-1]
    vd = None
    if pk is not None:
        after = [x for x in vendosis if x.start() >= pk.end()]
        vd = after[0] if after else None
    if vd is None and vendosis:
        vd = vendosis[-1]; v["warnings"].append("VENDOSI senza «PËR KËTO ARSYE» davanti")
    if vd is None:
        v["status"] = "FAIL"; v["reasons"].append("dispositivo non trovato (nessun VENDOSI maiuscolo)"); return None, v

    # dispositivo
    seg = text[vd.end(): vd.end() + 4000]
    m = DISP_END.search(seg)
    if m and m.start() > 5: seg = seg[:m.start()]
    dispositif = nz(seg)
    if len(dispositif) > 3000: dispositif = dispositif[:3000].rsplit(" ", 1)[0] + " …"; v["warnings"].append("dispositivo tagliato a 3000 chr")

    # numero / data
    if court == "kushtetuese":
        number, date, year, short_id, w = gjk_number_date(text, rel, old)
    else:
        number, date, year, short_id, w = gjl_number_date(text, rel, old, vd.end())
    v["warnings"] += w
    if not number: v["status"] = "FAIL"; v["reasons"].append("numero non trovato")
    if not date: v["status"] = "FAIL"; v["reasons"].append("data non trovata")
    if not year: v["status"] = "FAIL"; v["reasons"].append("anno non determinato")

    # esito / esclusioni
    if court == "kushtetuese":
        outcome, excl = classify_gjk(dispositif); label = ""
    else:
        outcome, label, excl = classify_gjl(dispositif)
    if excl:
        v["status"] = "EXCLUDE"; v["reasons"].append(excl)
    elif not outcome:
        v["status"] = "FAIL"; v["reasons"].append(f"esito non riconosciuto: «{dispositif[:120]}»")

    # intestazione: parti, oggetto, base legale
    limit = veren.start() if veren else min(len(text), 6000)
    labs = []
    for m in LABEL_RX.finditer(text, 0, limit + 400):
        name = norm_label(m.group(1) or m.group(2) or "")
        if name: labs.append((m.start(), m.end(), name))
    fields: dict[str, str] = {}
    for i, (s, e, name) in enumerate(labs):
        end = labs[i + 1][0] if i + 1 < len(labs) else min(len(text), e + 3000)
        val, cut = cut_value(text[e:end], 2000 if name == "OBJEKTI" else 1500 if name == "BAZA" else 700)
        if cut: v["warnings"].append(f"{name} tagliato")
        if name not in fields and val: fields[name] = val
    objekti = fields.get("OBJEKTI", "") or (("Akuzuar: " + fields["AKUZUAR"]) if fields.get("AKUZUAR") else "")
    baza = fields.get("BAZA", "")
    kerkues = ""
    for k in PARTY_FIRST:
        if fields.get(k): kerkues = fields[k]; break
    others = []
    for k, val in fields.items():
        if k in ("OBJEKTI", "BAZA") or not val: continue
        if k == "AKUZUAR" and objekti.startswith("Akuzuar: "): continue
        if kerkues and val == kerkues: continue
        others.append(f"{PRETTY_LABEL.get(k, k)}: {val}")
    subjekte = nz(" | ".join(others))[:800]
    judges = extract_judges(text)
    kolegji = ""
    if court == "gjykata_elarte":
        mk = re.search(r"KOLEGJI\s+(PENAL|CIVIL|ADMINISTRATIV)|KOLEGJET\s+E\s+BASHKUARA|Kolegji\s+(Penal|Civil|Administrativ)\s+i\s+Gjykat", text[:3000])
        if mk:
            kolegji = "Kolegjet e Bashkuara" if "BASHKUARA" in mk.group(0).upper() else "Kolegji " + (mk.group(1) or mk.group(2)).capitalize()

    # ragionamento
    reasoning = ""
    if court == "kushtetuese":
        if veren and pk is not None and pk.start() > veren.end():
            reasoning = text[veren.end(): pk.start()].strip()
        elif veren:
            reasoning = text[veren.end(): vd.start()].strip(); v["warnings"].append("ragionamento fino al VENDOSI (manca PËR KËTO ARSYE)")
        else:
            v["status"] = "FAIL" if v["status"] != "EXCLUDE" else v["status"]; v["reasons"].append("manca l'intestazione VËREN")
    else:
        start_min = veren.end() if veren else (labs[-1][1] if labs else 0)
        end = pk.start() if pk is not None else vd.start()
        cand = [m for m in KOL_HEADING.finditer(text) if start_min <= m.start() < end]
        start = None
        if cand: start = cand[0].start(); v["checks"]["kolegji_marker"] = "heading"
        else:
            cand = [m for m in KOL_SENT.finditer(text) if start_min <= m.start() < end]
            if cand: start = cand[0].start(); v["checks"]["kolegji_marker"] = "sentence"
        if start is None:
            if v["status"] != "EXCLUDE":
                v["status"] = "FAIL"; v["reasons"].append("marcatore del Kolegji non trovato (ragionamento = gradi inferiori)")
        else:
            reasoning = text[start:end].strip()
            if len(reasoning) < 0.12 * len(text) and len(reasoning) < 1500:
                v["warnings"].append(f"ragionamento del Kolegji corto ({len(reasoning)} chr su {len(text)})")
    reasoning = re.sub(r"\n{2,}", "\n", reasoning)
    if len(reasoning) > 200_000: reasoning = reasoning[:200_000]; v["warnings"].append("ragionamento tagliato a 200k")

    # verifiche di contenuto
    c = v["checks"]
    c["objekti"] = len(objekti) >= 8
    c["dispositif"] = len(dispositif) >= 10
    c["reasoning"] = len(reasoning) >= 500
    c["parties"] = bool(kerkues or subjekte)
    c["judges"] = len(judges) >= (5 if court == "kushtetuese" else 3)
    c["baza"] = bool(baza)
    c["disp_verb_first"] = bool(re.match(r"^\s*(?:\d+[.)]\s*|-\s*|•\s*)?[A-ZËÇ]", dispositif))
    c["disp_no_header"] = not re.search(r"KËRKUES|OBJEKTI|BAZA LIGJORE", dispositif)
    c["objekti_no_header"] = not re.search(r"BAZA LIGJORE|KËRKUES|SUBJEKT|KOLEGJI|pasi dëgjoi", objekti)
    c["reasoning_no_dispositif"] = not (INLINE_VENDOSI.search(reasoning) and INLINE_PER_KETO.search(reasoning))
    c["reasoning_not_header"] = not any(norm_label(m.group(1) or m.group(2) or "") in ("KERKUES", "OBJEKTI", "BAZA", "PADITES") for m in LABEL_RX.finditer(reasoning[:600]))
    c["mospranim_leak"] = ("mospranim" not in dispositif.lower()) or (court == "kushtetuese")
    if v["status"] == "OK":
        for key, ok in c.items():
            if ok is True or ok in ("heading", "sentence"): continue
            if key in ("objekti", "dispositif", "reasoning", "disp_no_header", "reasoning_no_dispositif", "reasoning_not_header", "mospranim_leak", "objekti_no_header"):
                v["status"] = "FAIL"; v["reasons"].append(f"verifica fallita: {key}")
            else:
                v["warnings"].append(f"verifica debole: {key}")
    if old:
        if old.get("outcome") and outcome and old["outcome"] != outcome: v["checks"]["old_outcome"] = old["outcome"]
        if old.get("date") and date and norm_date(old["date"]) != date: v["warnings"].append(f"data diversa dal record precedente ({old['date']} → {date})")

    # citazioni con codice (stesso verificatore della produzione) — anche dall'OBJEKTI: nei penali è lì l'accusa
    # («neni 291 i Kodit Penal»), il legame più utile fra un vendim e un nene
    cited, cw = cited_articles_for(objekti, baza, reasoning, dispositif, article_index)
    if cw: v["warnings"].append(cw)

    title, short = COURT_NAMES[court]
    if old and old.get("court_title_sq"): title = old["court_title_sq"]
    if old and old.get("court_short_sq"): short = old["court_short_sq"]
    if court == "kushtetuese":
        citation = f"Vendimi nr. {number}/{year} i Gjykatës Kushtetuese"
        disp_out = dispositif
    elif str(number).startswith("KB-"):
        citation = f"Vendimi Unifikues nr. {number.split('-')[2]}/{year} i Kolegjeve të Bashkuara të Gjykatës së Lartë"
        disp_out = f"[{label}] {dispositif}" if label else dispositif
    else:
        citation = f"Vendimi nr. {number} i Gjykatës së Lartë" + (f" ({kolegji})" if kolegji else "")
        disp_out = f"[{label}] {dispositif}" if label else dispositif
    rec = {
        "court_code": court, "court_title_sq": title, "court_short_sq": short, "year": int(year or 0),
        "number": number, "date": date, "citation": citation, "short_id": short_id,
        "objekti": objekti, "kerkues": kerkues, "subjekte_interesuara": subjekte, "baza_ligjore": baza,
        "judges": judges, "cited_articles": cited, "outcome": outcome, "dispositif": disp_out,
        "reasoning": reasoning, "source_file": rel, "source_url": (old or {}).get("source_url", "") or "",
        "kind": "decision",
    }
    v["kolegji"] = kolegji; v["label"] = label
    return rec, v


# ── store ──────────────────────────────────────────────────────────────────

def norm_key(court: str, year, number: str) -> tuple:
    n = str(number or "").replace(" ", "")
    m = re.match(r"^0*0?-?(\d{4})-0*(\d+)$", n)
    n = m.group(2) if m else re.sub(r"[^0-9]", "", n).lstrip("0")
    return (court, int(year or 0), n)


class OldRecords(dict):
    """Record del pickle vivo: per file sorgente normalizzato, e per chiave (corte, anno, numero) — i 146 documenti
    riscaricati dall'archivio hanno un nome nuovo («2024/00-2024-1129.docx») e il vecchio record va ritrovato dal numero."""

    def __init__(self):
        super().__init__(); self.by_key = {}

    def get(self, rel, default=None):
        d = dict.get(self, rel)
        if d is not None: return d
        court = rel.split("/")[0]
        m = re.search(r"(00-20\d\d-\d{1,5})", rel.replace("–", "-"))
        if court == "gjykata_elarte" and m:
            return self.by_key.get(norm_key(court, int(m.group(1)[3:7]), m.group(1)), default)
        m = re.search(r"vend_0*(\d+)_(\d{4})", rel)
        if court == "kushtetuese" and m:
            return self.by_key.get(norm_key(court, int(m.group(2)), m.group(1)), default)
        return default


def old_records() -> tuple[OldRecords, list]:
    """Record del pickle vivo, per file sorgente normalizzato; + la lista CEDU da conservare."""
    with OLD_PKL.open("rb") as fh:
        decs = pickle.load(fh)["decisions"]
    by_src = OldRecords()
    echr = []
    for d in decs:
        d = dict(d)
        if d.get("court_code") == "ecthr_albania":
            echr.append(d); continue
        s = (d.get("source_file") or "").replace("\\", "/")
        i = s.find("jurisprudence/")
        by_src[s[i + len("jurisprudence/"):] if i >= 0 else s] = d
        by_src.by_key.setdefault(norm_key(d.get("court_code"), d.get("year"), d.get("number")), d)
    return by_src, echr


def documents() -> list[tuple[str, str]]:
    out = []
    only = os.environ.get("ONLY", "")
    for court in COURTS_AL:
        base = RAW / court
        if not base.exists(): continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or "_cache" in p.parts or p.name.startswith("_index"): continue
            if p.suffix.lower() not in (".pdf", ".docx", ".doc", ".rtf", ".html", ".htm", ".txt"): continue
            rel = str(p.relative_to(RAW))
            if only and not rel.startswith(only): continue
            out.append((court, rel))
    lim = int(os.environ.get("LIMIT", "0") or 0)
    return out[:lim] if lim else out


def _article_index():
    try:
        from src.retrieval import ArticleIndex
        return ArticleIndex.load()
    except Exception as exc:  # noqa: BLE001
        print("indice articoli non disponibile:", exc)
        return None


def cmd_probe():
    by_src, _ = old_records()
    aidx = _article_index()
    docs = documents()
    stats = collections.Counter(); reasons = collections.Counter(); warns = collections.Counter()
    ex = collections.defaultdict(list); t0 = time.time()
    out = Path(os.environ.get("PROBE_OUT", "/tmp/probe_verdicts.jsonl")).open("w", encoding="utf-8")
    for n, (court, rel) in enumerate(docs, 1):
        rec, v = parse(court, rel, raw_text(rel), by_src.get(rel), aidx)
        stats[(court, v["status"])] += 1
        for r in v["reasons"]: reasons[(court, r.split(":")[0][:60])] += 1; ex[(court, r.split(":")[0][:60])].append(rel)
        for w in v["warnings"]: warns[(court, w.split(":")[0].split("(")[0][:50])] += 1
        out.write(json.dumps({"rel": rel, "court": court, "status": v["status"], "reasons": v["reasons"], "warnings": v["warnings"],
                              "checks": v["checks"], "outcome": (rec or {}).get("outcome"), "label": v.get("label"),
                              "number": (rec or {}).get("number"), "date": (rec or {}).get("date"),
                              "len_reasoning": len((rec or {}).get("reasoning") or ""), "n_judges": len((rec or {}).get("judges") or []),
                              "n_cited": len((rec or {}).get("cited_articles") or ""), "disp": ((rec or {}).get("dispositif") or "")[:160]}, ensure_ascii=False) + "\n")
        if n % 100 == 0: print(f"  … {n}/{len(docs)} ({int(time.time() - t0)} s)", flush=True)
    out.close()
    print("\nSTATO per corte:")
    for k, c in sorted(stats.items()): print(f"  {c:4d}  {k[0]:16s} {k[1]}")
    print("\nMOTIVI (FAIL/EXCLUDE):")
    for k, c in reasons.most_common(): print(f"  {c:4d}  {k[0]:16s} {k[1]}   es. {ex[k][:3]}")
    print("\nAVVISI:")
    for k, c in warns.most_common(40): print(f"  {c:4d}  {k[0]:16s} {k[1]}")


def cmd_one(rel: str):
    court = rel.split("/")[0]
    by_src, _ = old_records()
    rec, v = parse(court, rel, raw_text(rel), by_src.get(rel), _article_index())
    print(json.dumps(v, ensure_ascii=False, indent=1))
    if rec:
        for k in FIELDS:
            val = rec[k]
            if isinstance(val, str) and len(val) > 700: val = val[:700] + f" … [{len(rec[k])} chr]"
            print(f"{k:22s}: {val!r}")


def cmd_run():
    from src.jurisprudence_parser import Decision
    from src.retrieval import DecisionIndex
    by_src, echr = old_records()
    aidx = _article_index()
    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    loaded: dict[str, dict] = {}
    if OUT_JSONL.exists():
        for line in OUT_JSONL.open(encoding="utf-8"):
            d = json.loads(line); loaded[d["source_file"]] = d
    keys = {norm_key(d["court_code"], d["year"], d["number"]) for d in loaded.values()}
    by_key = {norm_key(d["court_code"], d["year"], d["number"]): d for d in loaded.values()}
    decisions = [Decision(**{k: d.get(k) for k in FIELDS if k != "kind"}) for d in echr]
    decisions += [Decision(**{k: d[k] for k in FIELDS if k != "kind"}) for d in loaded.values()]
    print(f"ripresa: {len(loaded)} già caricati, {len(echr)} CEDU conservati")
    docs = documents(); t0 = time.time(); n_ok = n_ex = n_fail = 0
    vlog = VERDICTS.open("a", encoding="utf-8")
    for n, (court, rel) in enumerate(docs, 1):
        if rel in loaded: continue
        rec, v = parse(court, rel, raw_text(rel), by_src.get(rel), aidx)
        if v["status"] == "OK":
            k = norm_key(rec["court_code"], rec["year"], rec["number"])
            if k in keys:
                prev = by_key.get(k) or {}
                fn = re.search(r"(00-20\d\d-\d{1,5})", rel.replace("–", "-"))
                same = nz(prev.get("objekti", ""))[:80] == nz(rec["objekti"])[:80] and prev.get("date") == rec["date"]
                if not same and fn and rec["court_code"] == "gjykata_elarte" and norm_key("gjykata_elarte", int(fn.group(1)[3:7]), fn.group(1)) not in keys:
                    # refuso nell'intestazione (es. «Nr. 00-2020-18» su un vendim del 2021 che nell'archivio è 00-2021-18):
                    # è un'ALTRA decisione — si tiene, col numero del file, dichiarandolo
                    v["warnings"].append(f"numero dell'intestazione {rec['number']} già usato da un altro vendim: usato il numero del file {fn.group(1)}")
                    rec["number"] = fn.group(1); rec["year"] = int(fn.group(1)[3:7])
                    rec["citation"] = f"Vendimi nr. {rec['number']} i Gjykatës së Lartë" + (f" ({v.get('kolegji')})" if v.get("kolegji") else "")
                    k = norm_key(rec["court_code"], rec["year"], rec["number"])
                else:
                    v["status"] = "EXCLUDE"; v["reasons"].append(f"duplicato di {k[2]}/{k[1]} già caricato" + ("" if same else " (testo diverso: da controllare)"))
        vlog.write(json.dumps({"rel": rel, "court": court, "status": v["status"], "reasons": v["reasons"], "warnings": v["warnings"],
                               "checks": v["checks"], "outcome": (rec or {}).get("outcome"), "label": v.get("label"), "ts": time.strftime("%H:%M:%S")}, ensure_ascii=False) + "\n"); vlog.flush()
        if v["status"] != "OK":
            if v["status"] == "EXCLUDE": n_ex += 1
            else: n_fail += 1
            print(f"[{n}/{len(docs)}] {v['status']:7s} {rel} — {'; '.join(v['reasons'])[:140]}", flush=True)
            continue
        # caricamento: prima la riga nel JSONL (fonte di verità), poi l'indice ricostruito
        line = dict(rec); line["_meta"] = {"warnings": v["warnings"], "checks": v["checks"], "kolegji": v.get("kolegji"), "label": v.get("label"), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with OUT_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        loaded[rel] = rec; keys.add(norm_key(rec["court_code"], rec["year"], rec["number"])); by_key[norm_key(rec["court_code"], rec["year"], rec["number"])] = rec
        decisions.append(Decision(**{k: rec[k] for k in FIELDS if k != "kind"}))
        DecisionIndex.build(decisions).save(OUT_PKL)
        n_ok += 1
        print(f"[{n}/{len(docs)}] OK      {rel} → nr {rec['number']} ({rec['date']}) {rec['outcome']}; giudici {len(rec['judges'])}, nene {len(rec['cited_articles'])}, ragionamento {len(rec['reasoning'])} chr"
              + (f"; avvisi: {'; '.join(v['warnings'])[:120]}" if v["warnings"] else ""), flush=True)
    vlog.close()
    print(f"\nfatto in {int(time.time() - t0)} s: OK {n_ok}, esclusi {n_ex}, falliti {n_fail}; totale nel database: {len(loaded)} AL + {len(echr)} CEDU = {len(decisions)}")


CEDU_JSONL = Path(os.environ.get("CEDU_JSONL", "/app/data/processed/cedu_decisions_v2.jsonl"))


def _decisions_from_store():
    """I record AL del JSONL + la CEDU: dal suo JSONL (reparse_cedu.py, dal 23 set) se esiste, altrimenti dal pickle vivo."""
    from src.jurisprudence_parser import Decision
    rows = [json.loads(l) for l in OUT_JSONL.open(encoding="utf-8")] if OUT_JSONL.exists() else []
    if CEDU_JSONL.exists():
        echr = [json.loads(l) for l in CEDU_JSONL.open(encoding="utf-8")]
    else:
        _, echr = old_records()
    decisions = [Decision(**{k: d.get(k) for k in FIELDS if k != "kind"}) for d in echr]
    decisions += [Decision(**{k: d[k] for k in FIELDS if k != "kind"}) for d in rows]
    return decisions, rows


def cmd_rebuild():
    """Ricostruisce il pickle v2 dal JSONL (+ CEDU conservata): dopo un `recite`, o dopo un cambio del tokenizer."""
    from src.retrieval import DecisionIndex
    decisions, rows = _decisions_from_store()
    DecisionIndex.build(decisions).save(OUT_PKL)
    print(f"pickle ricostruito: {len(rows)} AL + {len(decisions) - len(rows)} CEDU = {len(decisions)} → {OUT_PKL}")


def cmd_recite():
    """Ricalcola i nene citati di OGNI record AL (objekti + baza + ragionamento + dispositivo) e riscrive il JSONL
    (backup accanto), poi ricostruisce il pickle."""
    aidx = _article_index()
    rows = [json.loads(l) for l in OUT_JSONL.open(encoding="utf-8")]
    bak = OUT_JSONL.with_suffix(OUT_JSONL.suffix + ".bak-recite-" + time.strftime("%Y%m%d-%H%M%S"))
    bak.write_text(OUT_JSONL.read_text(encoding="utf-8"), encoding="utf-8")
    changed = 0
    for r in rows:
        new, _w = cited_articles_for(r.get("objekti") or "", r.get("baza_ligjore") or "", r.get("reasoning") or "", r.get("dispositif") or "", aidx)
        if new != r.get("cited_articles"):
            changed += 1; r["cited_articles"] = new
    with OUT_JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"nene citati ricalcolati: {changed}/{len(rows)} record cambiati (backup {bak.name})")
    cmd_rebuild()


def cmd_report():
    rows = [json.loads(l) for l in VERDICTS.open(encoding="utf-8")] if VERDICTS.exists() else []
    st = collections.Counter((r["court"], r["status"]) for r in rows)
    print("verdetti:", dict(st))
    rs = collections.Counter((r["court"], x.split(":")[0][:60]) for r in rows for x in r["reasons"])
    for k, c in rs.most_common(): print(f"  {c:4d}  {k}")
    n = sum(1 for _ in OUT_JSONL.open(encoding="utf-8")) if OUT_JSONL.exists() else 0
    print("record nel JSONL:", n)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe": cmd_probe()
    elif cmd == "run": cmd_run()
    elif cmd == "one": cmd_one(sys.argv[2])
    elif cmd == "report": cmd_report()
    elif cmd == "rebuild": cmd_rebuild()
    elif cmd == "recite": cmd_recite()
    else: raise SystemExit(__doc__)
