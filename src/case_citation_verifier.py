# -*- coding: utf-8 -*-
"""Verifikuesi i vendimeve — lo scudo per le citazioni di giurisprudenza.

Il `citation_verifier` controlla i **nene**: esiste? è abrogato? è aggiornato?
Ma non guarda i **numeri di sentenza**, e li' c'era un buco misurato: in una
risposta di prova il cervello ha citato `00-2025-1760`, che non esiste in
nessun documento scaricato ne' nell'indice. Un numero di vendim inventato
arrivava in fondo senza che nessuno se ne accorgesse — e finisce in un atto.

**La differenza che conta rispetto ai nene, e che non va sbagliata.**
Per gli articoli il corpus e' completo: i 21 codici ci sono tutti, quindi
«non c'e'» vuol dire davvero «non esiste» e la parola `fake` e' onesta.
Per le sentenze **no**: nell'indice ce ne sono 1.407, mentre i tribunali
albanesi ne hanno pubblicate molte di piu'. Quindi «non lo trovo» significa
soltanto **«non posso confermarlo»**.

Dire «falsa» a una sentenza vera sarebbe grave quanto lasciar passare una
inventata: l'avvocato butterebbe un precedente buono perche' il sistema gliel'ha
marchiato male. Per questo qui gli esiti sono due soli:

  * `verified` — sta nell'indice; e si mostra anche **come e' finita**, che e'
    la cosa che l'avvocato deve sapere prima di citarla;
  * `unverified` — non e' nel nostro corpus: **va controllata a mano**.
    Mai «falsa».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# ── quali forme di citazione riconoscere ──────────────────────────────
#
# Gjykata e Larte:  «Vendimi nr. 00-2025-68 (8), datë 16.01.2025»
#                   il numero vero e' 00-ANNO-PROGRESSIVO; il numero di
#                   registro (52104-00611-00-2020) NON e' una citazione.
_GJL = re.compile(r"\b00\s*[-–]\s*(20\d{2})\s*[-–]\s*(\d{1,5})")

# Gjykata Kushtetuese: «Vendimi nr. 46, datë 11.06.2025» / «nr. 46/2025»
_KUSH = re.compile(
    r"[Vv]endim\w*\s+nr\.?\s*(\d{1,4})\s*(?:/\s*(20\d{2})|,?\s*dat[ëe]\s*"
    r"\d{1,2}[./]\d{1,2}[./](20\d{2}))", re.I)


@dataclass
class CaseCitation:
    raw: str                  # il testo trovato, es. "00-2025-68"
    court: str                # "gjykata_elarte" | "kushtetuese"
    year: str
    number: str
    status: str               # "verified" | "unverified"
    citation: str | None = None      # come la chiama l'indice
    outcome: str | None = None       # pranim / rrëzim / kthim për rishqyrtim…
    dispositif: str | None = None    # com'è finita, testuale
    objekti: str | None = None       # di cosa trattava


def _chiave(court: str, anno, numero) -> tuple[str, str, str] | None:
    """Normalizza i due formati di numero che convivono nell'indice.

    I precedenti storici hanno `number = "42"`; quelli aggiunti dagli archivi
    della Gjykata e Lartë hanno `number = "00-2025-68"`. Togliendo i non-numeri
    il secondo diventa "00202568" e nessun confronto va piu' a segno — errore
    gia' fatto una volta, che portava a considerare tutto nuovo.
    """
    n = str(numero).replace(" ", "")
    m = re.match(r"^0*0?-?(\d{4})-(\d{1,5})$", n)
    n = m.group(2) if m else re.sub(r"[^0-9]", "", n)
    y = re.sub(r"[^0-9]", "", str(anno))[:4]
    if not (n and y):
        return None
    return (court, y, n.lstrip("0") or "0")


def _mappa(index) -> dict:
    m = {}
    for d in getattr(index, "decisions", []) or []:
        k = _chiave(d.court_code, d.year, d.number)
        if k:
            m.setdefault(k, d)
    return m


def verify_cases(text: str, index) -> dict:
    """Trova le citazioni di sentenze e dice quali si possono confermare.

    Torna la stessa forma del verificatore dei nene, cosi' il client puo'
    trattarle allo stesso modo:
        {"items": [...], "stats": {"verified": n, "unverified": n, "total": n}}
    """
    if not text or index is None:
        return {"items": [], "stats": {"verified": 0, "unverified": 0, "total": 0}}

    mappa = _mappa(index)
    trovate: dict[tuple, CaseCitation] = {}

    def aggiungi(court, anno, numero, raw):
        k = _chiave(court, anno, numero)
        if not k or k in trovate:
            return
        d = mappa.get(k)
        if d is None:
            trovate[k] = CaseCitation(raw=raw, court=court, year=k[1],
                                      number=k[2], status="unverified")
            return
        trovate[k] = CaseCitation(
            raw=raw, court=court, year=k[1], number=k[2], status="verified",
            citation=d.citation, outcome=d.outcome or None,
            dispositif=(d.dispositif or "")[:300] or None,
            objekti=(d.objekti or "")[:200] or None)

    for m in _GJL.finditer(text):
        aggiungi("gjykata_elarte", m.group(1), m.group(2), m.group(0).strip())
    for m in _KUSH.finditer(text):
        anno = m.group(2) or m.group(3)
        if anno:
            aggiungi("kushtetuese", anno, m.group(1), m.group(0).strip())

    items = [asdict(c) for c in trovate.values()]
    ver = sum(1 for c in items if c["status"] == "verified")
    return {"items": items,
            "stats": {"verified": ver, "unverified": len(items) - ver,
                      "total": len(items)}}


# ── lo scudo: l'avviso viaggia col testo, non solo a schermo ──────────

_NOTA_SQ = (
    "\n\n> ⚠️ **Kujdes — vendime që nuk u konfirmuan dot.** Këto numra vendimesh "
    "nuk gjenden në bazën tonë të praktikës gjyqësore: {lista}.\n"
    "> Kjo **nuk** do të thotë se janë të pavërteta — baza jonë nuk i përmban të "
    "gjitha vendimet e botuara. Do të thotë që **duhen verifikuar një për një "
    "para se t'i citosh në një akt**.\n")

_NOTA_IT = (
    "\n\n> ⚠️ **Attenzione — sentenze che non ho potuto confermare.** Questi numeri "
    "non risultano nella nostra base di giurisprudenza: {lista}.\n"
    "> Questo **non** significa che siano inventate: la nostra base non contiene "
    "tutte le decisioni pubblicate. Significa che vanno **verificate una per una "
    "prima di citarle in un atto**.\n")


def annotate_unverified(md: str, cases: dict, *, jurisdiction: str = "AL") -> str:
    """Attacca l'avviso al testo, perche' il badge resta sullo schermo.

    Una risposta viene copiata dentro una memoria e da li' in poi il badge non
    esiste piu': il numero non confermato arriverebbe in tribunale senza un
    segno addosso. Stessa logica dello scudo dei nene.
    """
    if not md or not isinstance(cases, dict):
        return md
    da_dire = [c for c in (cases.get("items") or [])
               if c.get("status") == "unverified"]
    if not da_dire:
        return md
    lista = ", ".join("`%s`" % c["raw"] for c in da_dire[:8])
    nota = _NOTA_IT if str(jurisdiction).upper() == "IT" else _NOTA_SQ
    return md + nota.format(lista=lista)
