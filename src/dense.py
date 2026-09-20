# -*- coding: utf-8 -*-
"""RICERCA DENSA (embedding) accanto a BM25 — roadmap v4, punto 4 (20 set 2026).

Perché: BM25 cerca parole. «divorci» → legge sugli appalti, «grabitje» → Codice della strada; il
Kodi i Familjes dice «zgjidhja e martesës», il Kodi Penal «vjedhja me dhunë». Oggi lo compensa il
triage (una chiamata al modello, 25 s, non deterministica). Qui: un modello multilingue piccolo
(fastembed/ONNX, CPU, albanese e italiano) codifica ogni articolo UNA volta (`tools/build_dense.py`
→ `data/models/emb_<lang>_<modello>.npy` + `.keys.json`); a ogni query si codifica solo la domanda
(~40-100 ms) e si fonde con BM25 per rango (RRF: 1/(60+rango), somma dei due). MISURATO prima di
accendere (`tools/emb_ab.py`, MiniLM-L12 multilingue): strato 1 AL recall@12 BM25 304/306 → ibrido
306/306; 11 su 18 query difficili meglio («zhurmë e tepërt… gjoba» 110→2, «vjedhje me dhunë» 8→1,
«divorci me pëlqim reciprok» 4→1), 1 peggio (155: 1→6, resta nei 12).

Regole: additivo e fail-silent (senza file/modello/fastembed → solo BM25, un avviso nel log una
volta); la COPERTURA resta un segnale BM25 (la similarità è sempre > 0: non dice «nessuna parola in
comune»); un articolo portato SOLO dal senso si dichiara al cervello («⚑ GJETUR NGA KUPTIMI»,
stessa onestà delle ancore) su una COPIA, mai sull'oggetto dell'indice; `DENSE_ENABLED=0` lo spegne.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .config import INDEX_PATH
from .logging_utils import get_logger

log = get_logger(__name__)

ENABLED = os.environ.get("DENSE_ENABLED", "1") == "1"
MODEL = os.environ.get("DENSE_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMB_DIR = Path(os.environ.get("EMB_DIR", str(INDEX_PATH.parent / "models")))
DEPTH = int(os.environ.get("DENSE_DEPTH", "50"))
RRF_K = 60
_LOCK = threading.Lock()
_MODEL = None
_MODEL_FAILED = False
_INDICI: dict = {}


def tag(model: str = MODEL) -> str:
    return model.replace("/", "__")


def flat_dir(model: str = MODEL) -> Path:
    return EMB_DIR / ("flat_" + tag(model))


def _carica_modello():
    """Il codificatore delle QUERY (ONNX, CPU), una volta per processo. None se non disponibile."""
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None or _MODEL_FAILED:
        return _MODEL
    with _LOCK:
        if _MODEL is not None or _MODEL_FAILED:
            return _MODEL
        try:
            from fastembed import TextEmbedding
            fd = flat_dir()
            if not any(fd.rglob("*.onnx")):
                raise FileNotFoundError(f"modello non presente in {fd}")
            _MODEL = TextEmbedding(model_name=MODEL, cache_dir=str(EMB_DIR), threads=2, specific_model_path=str(fd))
            log.info("dense: modello pronto (%s)", MODEL)
        except Exception as exc:  # noqa: BLE001
            _MODEL_FAILED = True
            log.warning("dense: ricerca semantica spenta (%s)", str(exc)[:160])
    return _MODEL


def embed_query(text: str):
    m = _carica_modello()
    if m is None:
        return None
    import numpy as np
    v = np.asarray(list(m.query_embed([text]) if hasattr(m, "query_embed") else m.embed([text])), dtype=np.float32)[0]
    return v / (np.linalg.norm(v) + 1e-9)


def embed_passages(texts: list[str], batch_size: int = 32):
    m = _carica_modello()
    if m is None:
        return None
    import numpy as np
    E = np.asarray(list(m.passage_embed(texts, batch_size=batch_size) if hasattr(m, "passage_embed") else m.embed(texts, batch_size=batch_size)), dtype=np.float32)
    return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


class DenseIndex:
    """Embedding degli articoli di UN ArticleIndex, allineati per chiave (code, number)."""

    def __init__(self, E, rows: list[int], articles):
        self.E = E                  # (n_emb, dim)
        self.rows = rows            # posizione dell'articolo nell'ArticleIndex per ogni riga di E (-1 = sparito)
        self.articles = articles

    @classmethod
    def carica(cls, index, lang: str):
        """Legge emb_<lang>_<tag>.npy + .keys.json e li allinea all'indice vivo. None se manca o non combacia."""
        import numpy as np
        base = EMB_DIR / f"emb_{lang}_{tag()}"
        f, fk = base.with_suffix(".npy"), Path(str(base) + ".keys.json")
        if not f.exists() or not fk.exists():
            return None
        try:
            E = np.load(f, mmap_mode="r")
            keys = json.loads(fk.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("dense: embedding %s illeggibili: %s", f.name, exc); return None
        pos = {(a.code, str(a.number)): i for i, a in enumerate(index.articles)}
        rows = [pos.get((k[0], str(k[1])), -1) for k in keys]
        mancanti = sum(1 for r in rows if r < 0)
        nuovi = len(index.articles) - (len(rows) - mancanti)
        if mancanti or nuovi:
            log.warning("dense: embedding %s non allineati all'indice (%d spariti, %d articoli nuovi senza embedding): rilanciare tools/build_dense.py",
                        f.name, mancanti, nuovi)
            if nuovi > len(index.articles) * 0.05:
                return None         # troppo disallineato: meglio solo BM25 che un indice a metà
        return cls(np.asarray(E), rows, index.articles)

    def search(self, query: str, depth: int = DEPTH, include_repealed: bool = False, restrict_codes=None):
        import numpy as np
        v = embed_query(query)
        if v is None:
            return []
        s = self.E @ v
        order = np.argsort(-s)
        out = []
        restrict = set(restrict_codes) if restrict_codes else None
        for i in order:
            r = self.rows[i]
            if r < 0:
                continue
            a = self.articles[r]
            if not include_repealed and a.repealed:
                continue
            if restrict and a.code not in restrict:
                continue
            out.append((a, float(s[i])))
            if len(out) >= depth:
                break
        return out


def indice(index, lang: str):
    """DenseIndex per questo ArticleIndex (cache per identità dell'indice); None se spento/assente."""
    if not ENABLED:
        return None
    k = id(index)
    if k in _INDICI:
        return _INDICI[k]
    with _LOCK:
        if k not in _INDICI:
            try:
                _INDICI[k] = DenseIndex.carica(index, lang)
            except Exception as exc:  # noqa: BLE001
                log.warning("dense: caricamento fallito (%s)", exc); _INDICI[k] = None
            if _INDICI[k] is not None:
                log.info("dense: indice %s pronto (%d embedding)", lang, len(_INDICI[k].rows))
    return _INDICI[k]


def fondi(bm25_results, dense_results, kk: int = RRF_K) -> dict:
    """Reciprocal Rank Fusion: {(code, number): (fused, bm25_score, dense_score)}."""
    out: dict = {}
    for r, (a, s) in enumerate(bm25_results, 1):
        key = (a.code, a.number)
        f, b, d = out.get(key, (0.0, 0.0, 0.0))
        out[key] = (f + 1.0 / (kk + r), max(b, float(s)), d)
    for r, (a, s) in enumerate(dense_results, 1):
        key = (a.code, a.number)
        f, b, d = out.get(key, (0.0, 0.0, 0.0))
        out[key] = (f + 1.0 / (kk + r), b, max(d, float(s)))
    return out
