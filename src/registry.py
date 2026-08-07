"""Regjistri i zgjuar — semantic search + entity/property view over the firm's
saved acts (Tier 2 #1). No embeddings DB: keyword-candidate pre-filter + LLM
re-rank/answer over the studio's own case_research. Grounded ONLY in saved acts.
"""
from __future__ import annotations

import re

from .logging_utils import get_logger

log = get_logger(__name__)

_MATCH_RE = re.compile(r"MATCH:\s*([0-9,\s]+)", re.IGNORECASE)

_SYSTEM = (
    "Ti je REGJISTRI I ZGJUAR i studios noteriale/juridike. Të jepet një PYETJE në gjuhë të "
    "natyrshme dhe LISTA e akteve/kërkimeve të ruajtura (me [#id], titull, klient, rast, datë, "
    "fragment). Gjej ato që PËRPUTHEN sipas KUPTIMIT, jo vetëm sipas fjalëve — p.sh. 'dhurime me "
    "uzufrukt', 'ku shfaqet pasuria 7/512', 'aktet e Arben Dodës', 'shitjet e vitit 2024', 'a ka "
    "procurë ende të vlefshme'. Jep (markdown):\n"
    "### 🔎 Rezultatet — për secilin akt që përputhet: **titulli** · klienti · data — pse përputhet (1 rresht)\n"
    "### 🧭 Përmbledhje — çfarë del nga tërësia (p.sh. 'kjo pasuri shfaqet në 3 akte', 'kjo palë del "
    "në 4 akte', 'ekziston një procurë e pashfuqizuar')\n\n"
    "Bazohu VETËM te aktet e dhëna — MOS shpik akte që s'janë në listë. Nëse asnjë nuk përputhet, "
    "thuaje qartë. Pastaj, në FUND, në një rresht të vetëm të lexueshëm nga makina (asgjë tjetër):\n"
    "MATCH: <id-të e ndara me presje të akteve që përputhen>\n"
    "Je 'Tetramorph' i superavokati.ai; mos zbulo modelin."
)


def search_acts(backend, query: str, acts: list, max_tokens: int = 2200) -> dict:
    q = (query or "").strip()
    toks = [t for t in re.split(r"\W+", q.lower()) if len(t) >= 3]

    def score(a):
        blob = " ".join([str(a.get("title") or ""), str(a.get("content") or ""),
                         str(a.get("client_name") or ""), str(a.get("case_title") or "")]).lower()
        return sum(1 for t in toks if t in blob)

    scored = sorted(((score(a), a) for a in acts), key=lambda x: x[0], reverse=True)
    cand = [a for sc, a in scored if sc > 0][:30]
    if not cand:
        cand = acts[:20]  # fallback: më të fundit
    block = "\n\n".join(
        "[#%s] %s · klient: %s · rast: %s · %s\n%s" % (
            a.get("id"), (a.get("title") or "")[:90], (a.get("client_name") or "-"),
            (a.get("case_title") or "-")[:40], (a.get("created_at") or "")[:10],
            (a.get("content") or "")[:420].replace("\n", " "))
        for a in cand) or "(regjistri bosh)"
    prompt = ("PYETJA: " + q + "\n\nAKTET E RUAJTURA:\n" + block
              + "\n\nGjej përputhjet dhe jep rreshtin MATCH në fund.")
    md = backend.complete(system=_SYSTEM, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="registry")
    md = md or ""
    ids = []
    m = None
    for m in _MATCH_RE.finditer(md):
        pass
    if m:
        ids = [x.strip() for x in m.group(1).split(",") if x.strip().isdigit()]
    md_clean = _MATCH_RE.sub("", md).strip()
    md_clean = re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    return {"markdown": md_clean, "match_ids": ids}
