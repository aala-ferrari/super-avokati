# -*- coding: utf-8 -*-
"""War Room — il DOSSIER CANONICO a oggetti tipizzati (spec «Legal War Room»).

Modulo NUOVO e ADDITIVO: non tocca i percorsi esistenti (veloce/simple/complex).
È la FONDAZIONE della modalità massima per i casi più difficili — ogni fonte
diventa un oggetto con ID univoco, qualità indipendente dalla confidence del
modello, e stato di verifica. Il senior cita per ID: [LAW-001], [CASE-014],
[UPDATE-002]. Così la provenienza e la verifica-per-ID diventano possibili.

Principio sacro (già nostro): il corpus è la verità VERIFICATA; il web è
PARTIAL «da verificare»; una fonte SECONDARY non vale come PRIMARY_OFFICIAL.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# Qualità della fonte, indipendente dalla confidence del modello (spec sez. 14).
QUALITY = ("PRIMARY_OFFICIAL", "AUTHORITATIVE_DATABASE", "INSTITUTIONAL",
           "SECONDARY", "UNVERIFIED")
# Stato di verifica (spec sez. 15).
VERIF = ("VERIFIED", "PARTIAL", "SOURCE_NOT_RETRIEVED", "UNVERIFIED")


@dataclass
class DossierItem:
    """Un elemento del dossier canonico, con ID univoco e provenienza."""
    id: str            # LAW-001 / CASE-014 / WEB-003 / UPDATE-002
    tip: str           # STATUTE / CASE_LAW / WEB / UPDATE
    titulli: str
    burimi: str        # "korpus" / "arkiv" / URL
    cilesia: str       # qualità della fonte (QUALITY)
    teksti: str        # testo esatto / passaggio
    verifikimi: str    # verifica (VERIF)
    mbeshtet: str = "NEUTRAL"   # CLIENT / OPPONENT / NEUTRAL
    data: str = ""
    agjenti: str = ""
    ts: float = field(default_factory=time.time)


def cilesia_nga_url(url: str) -> str:
    """Qualità della fonte dal dominio — deterministica, difendibile."""
    u = (url or "").lower().strip()
    if not u:
        return "UNVERIFIED"
    if any(d in u for d in (".gov.al", ".gov.it", "qbz.gov.al", "gazzettaufficiale.it",
                            "normattiva.it", "giustizia.it", "arkiva.gov.al",
                            "dogana.gov.al", "tatime.gov.al", "financa.gov.al")):
        return "PRIMARY_OFFICIAL"
    if any(d in u for d in ("giurcost", "cortecostituzionale", "italgiure",
                            "cassazione", "gjykata", "giustizia-amministrativa",
                            "eur-lex", "hudoc")):
        return "AUTHORITATIVE_DATABASE"
    return "SECONDARY"


def _case_titull(c) -> str:
    parts = [getattr(c, "court_name", "") or getattr(c, "court_code", ""),
             getattr(c, "case_number", "")]
    d = getattr(c, "decision_date", None)
    if d:
        parts.append(str(d))
    return " ".join(p for p in parts if p).strip() or "Vendim"


def build_canonical(retrieved, dosja, precedents, lang="sq") -> list[DossierItem]:
    """Assembla il dossier CANONICO con ID univoci, dai pezzi che abbiamo già:

    - i nene RECUPERATI dal corpus  → LAW-xxx, PRIMARY_OFFICIAL, VERIFIED;
    - i precedenti dell'archivio    → CASE-xxx, AUTHORITATIVE_DATABASE, VERIFIED;
    - le fonti web dei raccoglitori → WEB-xxx, qualità dal dominio, PARTIAL;
    - la Fletorja Zyrtare/Agent D   → UPDATE-xxx, PARTIAL.

    Dedup per URL. Nessuna fonte «ricordata ma non recuperata» entra qui.
    """
    items: list[DossierItem] = []
    seen_url: set[str] = set()

    nl = 0
    for a, _ in (retrieved or []):
        nl += 1
        body = (getattr(a, "body", "") or "").replace("\n", " ")[:2000]
        num = getattr(a, "number", "") or ""
        titull = ("%s %s" % (num, getattr(a, "title_sq", None) or getattr(a, "code", ""))).strip()
        items.append(DossierItem(
            id="LAW-%03d" % nl, tip="STATUTE", titulli=titull, burimi="korpus",
            cilesia="PRIMARY_OFFICIAL", teksti=body, verifikimi="VERIFIED", agjenti="A"))

    nc = 0
    for c, _ in (precedents or []):
        nc += 1
        teksti = (getattr(c, "excerpt", "") or getattr(c, "summary", "") or "").replace("\n", " ")[:1200]
        items.append(DossierItem(
            id="CASE-%03d" % nc, tip="CASE_LAW", titulli=_case_titull(c), burimi="arkiv",
            cilesia="AUTHORITATIVE_DATABASE", teksti=teksti, verifikimi="VERIFIED", agjenti="B"))

    web = (dosja or {}).get("web") or {}
    nw = 0
    for x in ((web.get("akte_nenligjore") or []) + (web.get("burime") or [])):
        if not isinstance(x, dict):
            continue
        url = (x.get("url") or "").strip()
        if url and url in seen_url:
            continue
        if url:
            seen_url.add(url)
        nw += 1
        items.append(DossierItem(
            id="WEB-%03d" % nw, tip="WEB", titulli=(x.get("titulli") or "")[:160],
            burimi=url, cilesia=cilesia_nga_url(url), teksti=(x.get("citim") or "")[:600],
            verifikimi="PARTIAL", data=(x.get("data") or ""), agjenti="B"))

    nu = 0
    for f in ((dosja or {}).get("fletorja") or []):
        if not isinstance(f, dict):
            continue
        url = (f.get("url") or "").strip()
        nu += 1
        items.append(DossierItem(
            id="UPDATE-%03d" % nu, tip="UPDATE",
            titulli=(f.get("neni") or f.get("ligji") or "")[:160], burimi=url,
            cilesia=cilesia_nga_url(url), teksti=(f.get("citim") or "")[:500],
            verifikimi="PARTIAL", data=(f.get("fletorja") or f.get("data") or ""), agjenti="D"))

    return items


_KREU = {
    "sq": ("━━━ DOSJA KANONIKE (çdo burim me ID — cito me [LAW-x], [CASE-x], [UPDATE-x]; "
           "korpusi = I VËRTETUAR, web = «për verifikim»; cilësia e burimit e shënuar) ━━━"),
    "it": ("━━━ DOSSIER CANONICO (ogni fonte con ID — cita con [LAW-x], [CASE-x], [UPDATE-x]; "
           "corpus = VERIFICATO, web = «da verificare»; qualità della fonte indicata) ━━━"),
}


def format_canonical(items: list[DossierItem], lang="sq") -> str:
    """Il dossier canonico per il senior, per ID + qualità + verifica. Vuoto
    se non c'è nulla da dare."""
    if not items:
        return ""
    rr = ["", _KREU.get(lang, _KREU["sq"])]
    for it in items:
        q = it.cilesia.replace("_", " ").lower()
        burim = it.burimi if it.burimi in ("korpus", "arkiv") else (it.burimi[:70] or "—")
        rr.append("  [%s] %s — %s · %s · %s%s" % (
            it.id, it.titulli, q, it.verifikimi.lower(), burim,
            (" (%s)" % it.data) if it.data else ""))
        if it.teksti:
            rr.append("     «%s»" % it.teksti[:400])
    rr.append("")
    return "\n".join(rr)


def statistika(items: list[DossierItem]) -> dict:
    """Conteggi per tipo e qualità — per il gate DOSSIER_READY e la diagnostica."""
    out = {"total": len(items)}
    for it in items:
        out[it.tip] = out.get(it.tip, 0) + 1
    out["primary"] = sum(1 for it in items if it.cilesia == "PRIMARY_OFFICIAL")
    return out
