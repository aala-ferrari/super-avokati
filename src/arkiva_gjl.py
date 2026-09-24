# -*- coding: utf-8 -*-
"""v9.388 — L'ARCHIVIO UFFICIALE DELLA GJYKATA E LARTË dietro al verificatore delle sentenze albanesi.

Perché (misurato il 24 set sulle risposte albanesi salvate): delle 6 sentenze della Gjykata e Lartë citate e date «të
pakonfirmuara», **5 ESISTONO** nell'archivio ufficiale già scaricato (`data/raw/jurisprudence/gjykata_elarte/<anno>/
00-<anno>-<n>.doc|docx|pdf`, 7.763 file) — sono decisioni che il corpus dei precedenti esclude per regola: 00-2021-756
è un «Mospranimin e rekursit», 00-2022-4428 un «Kthimin e rekursit» del relatore. Il cervello le aveva citate come
precedenti: all'avvocato va detto non «non la trovo» ma **«esiste, ed è un'inammissibilità: non vale per il merito»**.

Qui: l'indice dei file (una scansione della cartella, ricaricata quando cambia) e la classificazione dal DISPOSITIVO
(dopo l'ultimo «PËR KËTO ARSYE» maiuscolo — la stessa regola di `tools/reparse_vendime.py`, che resta la fonte per le
esclusioni del corpus: mospranim, kthim i rekursit, errata, decisioni procedurali). Solo in positivo: un numero che
l'archivio non ha resta «da verificare» come prima (l'archivio online dal 2023 è parziale). Mai solleva.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .config import PROCESSED_DATA_PATH, RAW_DATA_PATH
from .logging_utils import get_logger

log = get_logger(__name__)

DIR = Path(os.environ.get("GJL_ARCHIVE_DIR", str(RAW_DATA_PATH / "jurisprudence" / "gjykata_elarte")))
CACHE = PROCESSED_DATA_PATH.parent / "cache" / "gjl_arkiva.json"
_lock = threading.Lock()
_stato: dict = {"mtime": None, "indice": {}, "cache": None}

# le esclusioni del corpus, dal primo verbo del dispositivo (stesse forme di tools/reparse_vendime.py GJL_VERBS,
# refusi compresi: «Mopranimin», «Mospranimine», «Mopsranimin», «Mosparanimin», «Deklarimin si të papranueshme»)
_ESCLUSIONI = [
    ("mospranim", re.compile(r"\bmo(?:sp|ps|s|p)?a?ranimin?e?\b|\bdeklarimin?\s+si\s+t[ëe]\s+papranueshm", re.I),
     "mospranim i rekursit — nuk vendos mbi themelin"),
    ("kthim i rekursit", re.compile(r"\bkthimin?\s+e\s+(?:rekursi\w*|kërkesës)", re.I),
     "kthim i rekursit nga relatori — nuk është vendim i Kolegjit mbi themelin"),
    ("errata", re.compile(r"\bndreqjen?\b|\bsakt[ëe]simin?\b|\bkorrigjimin?\b", re.I),
     "ndreqje/saktësim i një vendimi të mëparshëm"),
    ("procedural", re.compile(r"^\s*(?:[IVX0-9]+\s*[.\-)]\s*)?(?:Kalimin\b|T[ëe]\s+caktoj|T[ëe]\s+shtroj|Nisjen\s+e\s+procedur)", re.I),
     "vendim procedural — nuk vendos mbi themelin"),
]
_MERITO = re.compile(r"\bprishjen?\b|l[ëe]ne?[nr]?\s+n[ëe]\s+fuqi|l[ëe]nien?\s+n[ëe]\s+fuqi|\bndryshimin?\b|\bpushimin?\b|"
                     r"\bpranimin?\b|\brr[ëe]zimin?\b", re.I)
_KOLEGJI = re.compile(r"Kolegji\s+(Administrativ|Civil|Penal|t[ëe]\s+Bashkuara|i\s+Bashkuar\w*)", re.I)


def _indice() -> dict:
    """{(anno, numero): Path} — la cartella si riscandisce solo se cambia."""
    with _lock:
        try:
            mt = max((p.stat().st_mtime for p in DIR.iterdir() if p.is_dir()), default=0.0)
        except OSError:
            return {}
        if _stato["mtime"] == mt:
            return _stato["indice"]
        ind: dict = {}
        for p in DIR.glob("*/00-*"):
            m = re.match(r"^00-(\d{4})-(\d{1,5})\.(?:doc|docx|pdf)$", p.name, re.I)
            if m:
                ind[(m.group(1), str(int(m.group(2))))] = p
        _stato["indice"], _stato["mtime"] = ind, mt
        return ind


def _cache() -> dict:
    if _stato["cache"] is None:
        try:
            _stato["cache"] = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _stato["cache"] = {}
    return _stato["cache"]


def _salva_cache() -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_stato["cache"], ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CACHE)
    except Exception:  # noqa: BLE001
        log.debug("arkiva_gjl: cache non scrivibile", exc_info=True)


def _testo(p: Path) -> str:
    try:
        head = p.open("rb").read(8)
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            r = subprocess.run(["antiword", "-m", "UTF-8.txt", "-w", "0", str(p)], capture_output=True, timeout=30)
            return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
        if head.startswith(b"PK"):
            from docx import Document
            return "\n".join(x.text for x in Document(str(p)).paragraphs)
        if head.startswith(b"%PDF"):
            import pdfplumber
            with pdfplumber.open(str(p)) as pdf:
                pagine = pdf.pages
                scelte = list(pagine[:1]) + list(pagine[-3:]) if len(pagine) > 4 else list(pagine)
                return "\n".join((pg.extract_text() or "") for pg in scelte)
    except Exception:  # noqa: BLE001
        log.debug("arkiva_gjl: testo non leggibile %s", p, exc_info=True)
    return ""


def classifica(testo: str) -> dict:
    """{esito, esclusa, motivo, dispositivo, kolegji} dal testo della decisione (dispositivo dopo l'ULTIMO «PËR KËTO
    ARSYE» maiuscolo; un «për këto arsye» minuscolo nel ragionamento non è il dispositivo)."""
    t = testo or ""
    i = t.rfind("PËR KËTO ARSYE")
    if i < 0:
        i = t.rfind("PER KETO ARSYE")
    disp = t[i:] if i >= 0 else t[-1500:]
    m = re.search(r"V\s*E\s*N\s*D\s*O\s*S\s*[IËEA]\s*(?:N)?\s*:?", disp)
    corpo = re.sub(r"\s+", " ", disp[m.end():] if m else disp).strip()
    kol = _KOLEGJI.search(t)
    out = {"esito": "", "esclusa": False, "motivo": "", "dispositivo": corpo[:300],
           "kolegji": ("Kolegji " + kol.group(1)) if kol else ""}
    testa = corpo[:400]
    primo = (10 ** 9, None)
    for lab, rx, motivo in _ESCLUSIONI:
        mm = rx.search(testa)
        if mm and mm.start() < primo[0]:
            primo = (mm.start(), (lab, motivo))
    mm = _MERITO.search(testa)
    if primo[1] and (not mm or primo[0] <= mm.start()):
        out.update(esito=primo[1][0], esclusa=True, motivo=primo[1][1])
    elif mm:
        out.update(esito="merito")
    return out


def info(anno, numero) -> dict | None:
    """La decisione 00-<anno>-<numero> nell'archivio ufficiale: None se l'archivio non l'ha (resta «da verificare»)."""
    try:
        k = (str(anno)[:4], str(int(str(numero))))
    except Exception:  # noqa: BLE001
        return None
    p = _indice().get(k)
    if p is None:
        return None
    ck = f"{k[0]}-{k[1]}"
    c = _cache()
    if ck in c:
        return c[ck]
    t0 = time.time()
    r = classifica(_testo(p))
    r["file"] = p.name
    c[ck] = r
    _salva_cache()
    log.info("arkiva_gjl: 00-%s-%s → %s (%.1fs)", k[0], k[1], r.get("esito") or "?", time.time() - t0)
    return r
