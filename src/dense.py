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
# v9.362 — SEGMENTI: MiniLM legge 128 token e il 61 % AL / 62 % IT dei nene sono più lunghi (misurato 21 set:
# il 3° paragrafo del 302 — l'esclusione dei familiari — cominciava al token 206 e non era MAI stato
# codificato). Ogni articolo diventa 1..N segmenti da ~CHUNK_TOKENS token con sovrapposizione, ognuno
# preceduto dalla rubrica; alla ricerca l'articolo prende il MASSIMO dei suoi segmenti. `EMB_SUFFIX`
# permette di tenere due codifiche affiancate per la misura A/B (es. «_ck»).
CHUNK_TOKENS = int(os.environ.get("DENSE_CHUNK_TOKENS", "110"))
CHUNK_OVERLAP = int(os.environ.get("DENSE_CHUNK_OVERLAP", "25"))
CHUNK_MAX = int(os.environ.get("DENSE_CHUNK_MAX", "40"))
EMB_SUFFIX = os.environ.get("EMB_SUFFIX", "")
_TOK = None
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


def _tokenizer():
    """Un tokenizer SEPARATO (senza troncatura) solo per contare e spezzare: quello del modello resta
    com'è (tronca a 128, come deve). None se manca → si ripiega sui caratteri (~4 per token)."""
    global _TOK
    if _TOK is not None:
        return _TOK or None
    try:
        from tokenizers import Tokenizer
        f = flat_dir() / "tokenizer.json"
        t = Tokenizer.from_file(str(f)); t.no_truncation(); _TOK = t
    except Exception:  # noqa: BLE001
        _TOK = False
    return _TOK or None


def n_token(text: str) -> int:
    t = _tokenizer()
    return len(t.encode(text or "").ids) if t else max(1, len(text or "") // 4)


def chunk_text(heading: str, body: str, max_tokens: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP, max_chunks: int = CHUNK_MAX) -> list[str]:
    """Segmenti di ~max_tokens token (sovrapposizione `overlap`), ognuno preceduto dalla rubrica.
    Si spezza su parole, mai a metà parola; un articolo corto = 1 segmento (identico a prima)."""
    rub = " ".join((heading or "").split())[:120]
    words = (body or "").split()
    if not words:
        return [rub] if rub else []
    t = _tokenizer()
    if t is None:
        per = 4
        wl = [max(1, len(w) // per + 1) for w in words]
    else:
        enc = t.encode_batch(words)
        wl = [max(1, len(e.ids)) for e in enc]
    rub_t = n_token(rub) if rub else 0
    budget = max(24, max_tokens - rub_t - 2)
    out, i = [], 0
    while i < len(words) and len(out) < max_chunks:
        j, tot = i, 0
        while j < len(words) and tot + wl[j] <= budget:
            tot += wl[j]; j += 1
        if j == i:
            j = i + 1
        seg = " ".join(words[i:j])
        out.append((rub + ". " + seg) if rub else seg)
        if j >= len(words):
            break
        # sovrapposizione: torna indietro di ~overlap token
        back, k = 0, j
        while k > i + 1 and back < overlap:
            k -= 1; back += wl[k]
        i = max(k, i + 1)
    return out


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
        base = EMB_DIR / f"emb_{lang}_{tag()}{EMB_SUFFIX}"
        f, fk = base.with_suffix(".npy"), Path(str(base) + ".keys.json")
        if not f.exists() or not fk.exists():
            return None
        try:
            E = np.load(f, mmap_mode="r")
            keys = json.loads(fk.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("dense: embedding %s illeggibili: %s", f.name, exc); return None
        pos = {(a.code, str(a.number)): i for i, a in enumerate(index.articles)}
        rows = [pos.get((k[0], str(k[1])), -1) for k in keys]      # chiavi [code, number] o [code, number, segmento]
        mancanti = sum(1 for r in rows if r < 0)
        coperti = len({r for r in rows if r >= 0})
        nuovi = len(index.articles) - coperti
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
        visti: set = set()
        for i in order:
            r = self.rows[i]
            if r < 0 or r in visti:
                continue
            visti.add(r)                     # più segmenti per articolo: vale il MASSIMO (il primo in ordine)
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
                log.info("dense: indice %s pronto (%d embedding, %d articoli%s)", lang, len(_INDICI[k].rows),
                         len({r for r in _INDICI[k].rows if r >= 0}), f", suffisso {EMB_SUFFIX}" if EMB_SUFFIX else "")
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


# ── precedenti (roadmap v4, punto 5): il caso più simile per SENSO, non per parole ──
_DEC: dict = {}


class DenseDecisions:
    """Embedding dei precedenti (objekti + dispositivo + ragionamento), allineati ai casi del retriever
    per chiave court_code|year|number. Le Kushtetuese hanno tutte lo stesso «objekti» («shfuqizimi i
    vendimit…»): per parole vincono sempre loro; per senso emergono i casi di merito simili."""

    def __init__(self, E, rows: list[int]):
        self.E, self.rows = E, rows

    @classmethod
    def carica(cls, cases):
        import numpy as np
        base = EMB_DIR / f"emb_dec_{tag()}"
        f, fk = base.with_suffix(".npy"), Path(str(base) + ".keys.json")
        if not f.exists() or not fk.exists():
            return None
        try:
            E = np.asarray(np.load(f, mmap_mode="r")); keys = json.loads(fk.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("dense: embedding precedenti illeggibili: %s", exc); return None
        pos = {}
        for i, c in enumerate(cases):
            # il pickle dà year=0 ai casi senza data (CEDU, alcune GjL), il retriever None: stessa chiave
            pos[f"{c.court_code}|{c.year or 0}|{c.case_number}"] = i
        rows = [pos.get(k, -1) for k in keys]
        mancanti = sum(1 for r in rows if r < 0)
        if mancanti:
            log.warning("dense: %d precedenti con embedding non trovati nel retriever (chiavi diverse o corpus cambiato)", mancanti)
        if mancanti > len(rows) * 0.2:
            return None
        return cls(E, rows)

    def search(self, query: str, depth: int = DEPTH) -> list[tuple[int, float]]:
        """[(indice del caso nel retriever, coseno)] in ordine decrescente."""
        import numpy as np
        v = embed_query(query)
        if v is None:
            return []
        s = self.E @ v
        out = []
        for i in np.argsort(-s):
            if self.rows[i] >= 0:
                out.append((self.rows[i], float(s[i])))
                if len(out) >= depth:
                    break
        return out


def precedenti(retriever):
    if not ENABLED:
        return None
    k = id(retriever)
    if k in _DEC:
        return _DEC[k]
    with _LOCK:
        if k not in _DEC:
            try:
                _DEC[k] = DenseDecisions.carica(getattr(retriever, "cases", []) or [])
            except Exception as exc:  # noqa: BLE001
                log.warning("dense: precedenti non caricati (%s)", exc); _DEC[k] = None
            if _DEC[k] is not None:
                log.info("dense: precedenti pronti (%d embedding)", len(_DEC[k].rows))
    return _DEC[k]

