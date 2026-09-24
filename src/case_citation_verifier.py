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
import re as _re
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


# v9.388 — un «vendim nr. N, datë …» di un ALTRO organo (appello, tribunale, Consiglio dei ministri, registri) non è
# della Kushtetuese: misurato sulle risposte salvate, 1842/2026 (Tribunale di Tirana), 39/2019 e 10/2023 (Appello),
# 1143/2020 (VKM), 837/2013 (registro delle OJF)
_ALTRA_CORTE = re.compile(r"Gjykat(?:a|ës|ën)\s+(?:e|së)\s+(?:Apelit|Rrethit|Shkallës|Posaçme|Lartë)|Gjykat(?:a|ës|ën)\s+Administrative|"
                          r"\bApelit\b|\bRrethit\b|\bVKM\b|Këshillit\s+të\s+Ministrave|\bKLGJ\b|\bKPA\b|\bKPK\b|\bKQZ\b|"
                          r"regjistr|Kuvendit|Prokuroris", re.I)


@dataclass
class CaseCitation:
    raw: str                  # il testo trovato, es. "00-2025-68"
    court: str                # "gjykata_elarte" | "kushtetuese"
    year: str
    number: str
    status: str               # "verified" | "unverified" | "quashed"
    citation: str | None = None      # come la chiama l'indice
    outcome: str | None = None       # pranim / rrëzim / kthim për rishqyrtim…
    dispositif: str | None = None    # com'è finita, testuale
    objekti: str | None = None       # di cosa trattava
    # v9.339 (grafo delle sentenze): annullata dalla Gjykata Kushtetuese («kushtetuese|2016|71»),
    # forza (citata da N decisioni, unificatrice)
    quashed_by: str | None = None
    cited_by: int = 0
    unifying: bool = False


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


# ── ITALIA — Corte costituzionale (v1: unica corte coperta) ──────────
# «Corte cost. n. 100/2024» · «C. cost., sent. n. 5/2019» ·
# «Corte costituzionale, ordinanza n. 12 del 2021»
_IT_CCOST = _re.compile(
    r"\b[Cc](?:orte)?\.?\s*[Cc]ost(?:ituzionale)?\.?\s*,?\s*"
    r"(?:sent(?:enza)?\.?|ord(?:inanza)?\.?)?\s*,?\s*"
    r"n\.?\s*(\d{1,4})\s*(?:/\s*|\s+del\s+)(\d{4})")


def verify_cases_it(text: str) -> dict:
    """Verifica le citazioni ITALIANE contro l'indice locale (giurcost).

    ⚠️ LA REGOLA DI COPERTURA: si giudica solo un (corte, anno) che
    l'harvester ha CHIUSO. Anno non coperto → la citazione non entra
    nemmeno negli items: «non lo trovo ≠ è falso», e un buco nostro non
    deve mai sporcare un estremo vero. Cassazione (v9.385): archivio
    ufficiale via `cassazione.verifica`, coperta dal 2009 — prima del 2009
    o archivio muto → intoccata, come prima.
    """
    from .it_case_index import anno_coperto, esiste
    items, visti = [], set()
    for m in _IT_CCOST.finditer(text or ""):
        numero, anno = int(m.group(1)), int(m.group(2))
        chiave = ("CCost", numero, anno)
        if chiave in visti:
            continue
        visti.add(chiave)
        if not anno_coperto("CCost", anno):
            continue                      # buco nostro, non suo
        items.append({
            "raw": m.group(0), "court": "CCost",
            "number": numero, "year": anno,
            "status": "verified" if esiste("CCost", numero, anno)
                      else "unverified",
        })
    # v9.385 — la CASSAZIONE sull'archivio UFFICIALE della Corte (src/cassazione.py): metadati di tutti i
    # provvedimenti dal 2009, testo integrale degli ultimi 5 anni. Esiti verified / mismatch (estremi diversi) /
    # unverified; fuori copertura o archivio che non risponde → nessun esito (stessa regola della Consulta).
    try:
        from . import cassazione as _cass
        items += _cass.verifica(text or "").get("items") or []
    except Exception:  # noqa: BLE001
        pass
    ver = sum(1 for i in items if i["status"] == "verified")
    mis = sum(1 for i in items if i["status"] == "mismatch")
    return {"items": items,
            "stats": {"total": len(items), "verified": ver,
                      "unverified": len(items) - ver, "mismatch": mis}}


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
    try:
        from . import case_graph as _cg
        _annullati = _cg.annullati_gjl()          # «00-AAAA-N» → vendim Kushtetuese che l'ha annullato
    except Exception:  # noqa: BLE001
        _cg, _annullati = None, {}

    def aggiungi(court, anno, numero, raw):
        k = _chiave(court, anno, numero)
        if not k or k in trovate:
            return
        d = mappa.get(k)
        # v9.339 — un vendim della Gjykata e Lartë ANNULLATO dalla Kushtetuese (dispositivo
        # «Shfuqizimin … të vendimit nr. 00-…») si segnala anche se non è nel nostro corpus:
        # citarlo come precedente è portare in aula una sentenza che non esiste più
        q = _annullati.get(f"00-{k[1]}-{k[2]}") if court == "gjykata_elarte" else None
        if d is None:
            # v9.388 — non è nel corpus dei precedenti, ma può ESISTERE nell'archivio ufficiale della Gjykata e Lartë
            # (le esclusioni per regola: mospranim, kthim i rekursit, errata, procedurali). Misurato: 5 «non confermate»
            # su 6 esistevano — 00-2021-756 è un mospranim citato come precedente. Solo in positivo: se l'archivio non
            # l'ha, resta «unverified» come prima.
            arch = None
            if court == "gjykata_elarte" and not q:
                try:
                    from . import arkiva_gjl as _ag
                    arch = _ag.info(k[1], k[2])
                except Exception:  # noqa: BLE001
                    arch = None
            if arch:
                trovate[k] = CaseCitation(raw=raw, court=court, year=k[1], number=k[2],
                                          status="excluded" if arch.get("esclusa") else "archive",
                                          outcome=arch.get("esito") or None, dispositif=(arch.get("dispositivo") or "")[:300] or None,
                                          objekti=arch.get("motivo") or arch.get("kolegji") or None)
                return
            trovate[k] = CaseCitation(raw=raw, court=court, year=k[1], number=k[2],
                                      status="quashed" if q else "unverified", quashed_by=q)
            return
        g = _cg.info(court, k[1], d.number) if _cg else None
        if g and g.get("quashed_by"):
            q = q or g["quashed_by"][0]
        trovate[k] = CaseCitation(
            raw=raw, court=court, year=k[1], number=k[2], status="quashed" if q else "verified",
            citation=d.citation, outcome=d.outcome or None,
            dispositif=(d.dispositif or "")[:300] or None,
            objekti=(d.objekti or "")[:200] or None,
            quashed_by=q, cited_by=int((g or {}).get("cited_by") or 0), unifying=bool((g or {}).get("unifying")))

    for m in _GJL.finditer(text):
        aggiungi("gjykata_elarte", m.group(1), m.group(2), m.group(0).strip())
    # v9.388 — «Vendimi nr. N, datë …» NON è per forza della Kushtetuese: 3 delle 5 «Kushtetuese non confermate»
    # erano 837/2013, 1143/2020, 1842/2026 — numeri che la Corte non raggiunge (≤ 89 decisioni finali l'anno): decisioni
    # di altri organi citate nei fatti. Si giudica solo con la Corte nominata vicino, un numero plausibile e un anno che
    # l'indice copre (fuori copertura: nessun esito, come per la Consulta).
    anni_gjk = {str(d.year)[:4] for d in getattr(index, "decisions", []) or [] if d.court_code == "kushtetuese"}
    for m in _KUSH.finditer(text):
        anno = m.group(2) or m.group(3)
        if not anno or int(m.group(1)) > 150 or (anni_gjk and anno not in anni_gjk):
            continue
        # il genitivo albanese viene DOPO: «vendimit nr. 39, datë 10.07.2019, të Gjykatës së Apelit Vlorë» è dell'Appello
        # (prima era «verificato» come Kushtetuese 10/2023, 39/2019…); con la Kushtetuese nominata lì accanto vale sempre
        dopo = text[m.end(): m.end() + 90]
        if _ALTRA_CORTE.search(dopo) and not _re.search(r"[Kk]ushtetues|\bGjK\b", dopo):
            continue
        aggiungi("kushtetuese", anno, m.group(1), m.group(0).strip())

    items = [asdict(c) for c in trovate.values()]
    ver = sum(1 for c in items if c["status"] in ("verified", "archive"))
    qua = sum(1 for c in items if c["status"] == "quashed")
    esc = sum(1 for c in items if c["status"] == "excluded")
    return {"items": items,
            "stats": {"verified": ver, "unverified": len(items) - ver - qua - esc, "quashed": qua, "excluded": esc,
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
    it = str(jurisdiction).upper() == "IT"
    # v9.339 — ANNULLATE dalla Kushtetuese: avviso più forte, prima degli «unverified»
    annullate = [c for c in (cases.get("items") or []) if c.get("status") == "quashed"]
    if annullate:
        righe = []
        for c in annullate[:6]:
            q = (c.get("quashed_by") or "||").split("|")
            righe.append(("`%s` — annullata dalla Corte costituzionale con la decisione nr. %s/%s"
                          if it else "`%s` — e shfuqizuar nga Gjykata Kushtetuese me vendimin nr. %s/%s") % (c["raw"], q[2] if len(q) > 2 else "?", q[1] if len(q) > 1 else "?"))
        md += (("\n\n> ⛔ **Sentenze ANNULLATE — non citarle come precedenti validi.** " if it else
                "\n\n> ⛔ **Vendime TË SHFUQIZUARA — mos i cito si precedentë të vlefshëm.** ")
               + "; ".join(righe) + "\n")
    if it:
        md = _note_cassazione(md, cases)
    # v9.388 — esistono nell'archivio ufficiale ma NON sono precedenti (mospranim, kthim i rekursit…)
    escluse = [c for c in (cases.get("items") or []) if c.get("status") == "excluded"]
    if escluse and _TESTA_ESCLUSE_SQ not in md and _TESTA_ESCLUSE_IT not in md:
        righe = "; ".join("`%s` — %s" % (c["raw"], c.get("objekti") or c.get("outcome") or "") for c in escluse[:6])
        md += "\n\n" + (_TESTA_ESCLUSE_IT if it else _TESTA_ESCLUSE_SQ) + " " + righe + "\n"
    da_dire = [c for c in (cases.get("items") or [])
               if c.get("status") == "unverified" and c.get("court") != "Cass"]
    if not da_dire:
        return md
    lista = ", ".join("`%s`" % c["raw"] for c in da_dire[:8])
    nota = _NOTA_IT if it else _NOTA_SQ
    return md + nota.format(lista=lista)


_TESTA_ESCLUSE_SQ = ("> ⚠️ **Vendime që ekzistojnë në arkivin zyrtar të Gjykatës së Lartë, por NUK janë precedent** (nuk vendosin "
                     "mbi themelin — mos i cito si autoritet):")
_TESTA_ESCLUSE_IT = ("> ⚠️ **Decisioni che esistono nell'archivio ufficiale della Gjykata e Lartë ma NON sono precedenti** (non "
                     "decidono il merito — non citarle come autorità):")


# v9.385 — CASSAZIONE: l'archivio ufficiale è COMPLETO dal 2009 (metadati), quindi il linguaggio è diverso da quello
# della Consulta/AL («la nostra base non contiene tutte le decisioni»): qui un numero che non c'è ha numero o anno da
# riscontrare, e gli estremi che non tornano (sezione, data, tipo) si correggono con quelli ufficiali.
_TESTA_CASS_CORR = "> ⚠️ **Cassazione — estremi da correggere** (riscontro sull'archivio ufficiale della Corte):"
_TESTA_CASS_NF = "> ⚠️ **Cassazione — non trovate nell'archivio ufficiale** (Italgiure, completo dal 2009):"


def _note_cassazione(md: str, cases: dict) -> str:
    try:
        from . import cassazione as _cass
    except Exception:  # noqa: BLE001
        return md
    items = [c for c in (cases.get("items") or []) if c.get("court") == "Cass"]
    corr = []
    for c in items:
        rec = c.get("record") or {}
        if c.get("status") == "mismatch":
            alt = "; ".join(c.get("alternative") or [])
            if c.get("motivo") == "sezione":
                corr.append("`%s` → la n. %s/%s non è della %s: %s" % (
                    c["raw"][:90], c["number"], c["year"],
                    ", ".join(_cass.sezione_label(x, "") for x in c.get("dichiarata") or []), alt or "—"))
            else:
                corr.append("`%s` → nel ramo indicato non c'è: %s" % (c["raw"][:90], alt or "—"))
        elif c.get("status") == "verified" and c.get("correzioni"):
            corr.append("`%s` → %s (%s)" % (c["raw"][:90], "; ".join(c["correzioni"]), _cass.descrivi(rec) if rec else ""))
    nf = [c for c in items if c.get("status") == "unverified"]
    if corr and _TESTA_CASS_CORR not in md:
        md += "\n\n" + _TESTA_CASS_CORR + " " + " · ".join(corr[:6]) + "\n"
    if nf and _TESTA_CASS_NF not in md:
        md += ("\n\n" + _TESTA_CASS_NF + " " + ", ".join("`%s`" % c["raw"][:90] for c in nf[:6])
               + ". Numero o anno da riscontrare prima di citarle in un atto.\n")
    return md
