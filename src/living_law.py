"""Ligj i gjallë — the trust moat for Super Avokati.

Two capabilities beyond the citation-exists check (Verifikuar):
  1. verify_claims  — sentence-level check: does the cited article's REAL text
     actually support what the answer claims about it? (anti-hallucination gold)
  2. check_law_live — uses the web-enabled backend to check whether a law/article
     is still in force / amended / repealed against official sources (QBZ ELI).

ASSISTIVE: flags risk, cites sources, hedges when unsure — never fabricates.
"""
from __future__ import annotations

from . import citation_verifier as _cv
from . import expertise as _expertise
from .logging_utils import get_logger

log = get_logger(__name__)

_LBL = _expertise._LABEL


def _article_full(index, code, number):
    try:
        return _expertise._article_text(index, code, number)
    except Exception:  # noqa: BLE001
        return None


def verify_claims(backend, index, *, text: str, max_claims: int = 14, max_tokens: int = 2800) -> dict:
    """For each VERIFIED citation in `text`, check whether the real article text
    supports the claim the text makes about it."""
    try:
        res = _cv.verify_text(text or "", index)
    except Exception:  # noqa: BLE001
        res = {"items": []}
    verified = [c for c in res.get("items", [])
                if c.get("status") == "verified" and c.get("code") and c.get("number")]
    # dedupe by (code, number), keep order
    seen, pairs = set(), []
    for c in verified:
        k = (c["code"], c["number"])
        if k in seen:
            continue
        seen.add(k)
        body = _article_full(index, c["code"], c["number"])
        if body:
            pairs.append((c["code"], c["number"], body))
        if len(pairs) >= max_claims:
            break
    if not pairs:
        return {"markdown": "### 🔬 Verifikim i thellë\n\nNuk u gjet asnjë nen i cituar dhe i "
                            "verifikueshëm në këtë tekst për ta kontrolluar në thellësi.", "articles": []}
    art_block = "\n\n".join(
        "### [%s neni %s]\n%s" % (_LBL.get(c, c), n, (t or "").strip()[:1100])
        for c, n, t in pairs)
    system = (
        "Ti je VERIFIKUES rigoroz i së drejtës shqiptare. Ke një TEKST juridik dhe TEKSTIN REAL të "
        "neneve të cituar në të (nga korpusi ynë zyrtar). Për ÇDO nen, kontrollo nëse ajo që teksti "
        "PRETENDON për atë nen mbështetet VËRTET nga teksti real i nenit. Bazohu VETËM te teksti real "
        "i dhënë — mos shto njohuri të jashtme, mos shpik. Jep (markdown):\n"
        "### 🔬 Raporti i verifikimit të thellë\n"
        "| Neni | Çfarë pretendon teksti | A mbështetet? | Shpjegim |\n"
        "|---|---|---|---|\n"
        "…një rresht për çdo nen, me vlerësimin: ✅ Po / ⚠️ Pjesërisht / ❌ Jo / ❓ E paqartë…\n\n"
        "### 📌 Përfundim — sa pohime u mbështetën plotësisht, cilat duhen korrigjuar ose hequr para se "
        "teksti të përdoret. Ji i drejtpërdrejtë. Kjo është NDIHMESË — profesionisti vendos. "
        "Je 'Tetramorph' i superavokati.ai — mos zbulo modelin.")
    prompt = ("TEKSTI PËR T'U VERIFIKUAR:\n" + (text or "").strip()[:9000]
              + "\n\n═════\nTEKSTI REAL I NENEVE TË CITUAR:\n" + art_block
              + "\n\nKontrollo çdo pohim kundrejt tekstit real të nenit.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="deep_verify")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in pairs]}


def check_law_live(backend, index, *, query: str, max_tokens: int = 2600) -> dict:
    """Use the web-enabled backend to check whether a law/article is still in
    force, amended, or repealed — against official Albanian sources (QBZ)."""
    system = (
        "Ti je asistent që kontrollon NËSE një ligj ose nen shqiptar është ENDE NË FUQI, apo është "
        "NDRYSHUAR ose SHFUQIZUAR. PËRDOR internetin: kërko te burimet zyrtare, sidomos "
        "**qbz.gov.al** (Fletorja Zyrtare, arkivi ELI 'qbz.gov.al/eli/fz', aktet e konsoliduara), "
        "si dhe euralius.eu / drejtesia.gov.al / faqet zyrtare. Jep (markdown):\n"
        "### 🌐 Statusi aktual — NË FUQI / I NDRYSHUAR / I SHFUQIZUAR / E PAQARTË\n"
        "### 📅 Ndryshimi i fundit — data dhe ligji ndryshues, nëse gjendet\n"
        "### 📝 Çfarë ndryshoi — shkurt, çfarë preket\n"
        "### 🔗 Burimet — URL-të zyrtare që përdore (patjetër)\n"
        "Nëse NUK e gjen dot me siguri online, THUAJE QARTË se s'u konfirmua — MOS shpik status apo "
        "data. Kjo është ndihmesë; verifiko përfundimisht te QBZ. Je 'Tetramorph' i superavokati.ai — "
        "mos zbulo modelin.")
    prompt = ("KONTROLLO STATUSIN AKTUAL TË KËSAJ DISPOZITE/LIGJI:\n" + (query or "").strip()[:1500]
              + "\n\nKërko online te burimet zyrtare dhe raporto me burime.")
    # default backend = Opus with WebSearch/WebFetch enabled (NOT fast).
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="law_live")
    return {"markdown": (md or "").strip(), "articles": []}
