# -*- coding: utf-8 -*-
"""Codifica il corpus per la ricerca densa (roadmap v4, punti 4 e 5) → data/models/ (volume).

    docker exec super-avvocato python3 tools/build_dense.py            # AL + IT + precedenti
    docker exec super-avvocato python3 tools/build_dense.py --only al  # solo articoli albanesi
    DENSE_MODEL=… python3 tools/build_dense.py --download               # scarica il modello (cartella piatta)

Scrive `emb_<sq|it>_<modello>.npy` + `.keys.json` (chiave (code, number) per riga: la ricerca li
riallinea all'indice vivo per chiave, così un rebuild del BM25 non li invalida) e, per i precedenti,
`emb_dec_<modello>.npy` + `.keys.json` (court_code|year|number). Da rilanciare dopo ogni ingest
(articoli nuovi senza embedding restano trovabili solo da BM25: `dense.py` lo dice nel log).
Il modello si scarica una volta in una cartella PIATTA (`flat_<modello>/`, senza symlink: onnxruntime
1.30 rifiuta i dati esterni raggiunti via symlink della cache HF). Tempo misurato (MiniLM-L12,
4 thread): 20 articoli/s → AL 8 min, IT 20 min, precedenti 1-2 min.
"""
import argparse, json, os, sys, time
sys.path.insert(0, "/app")
from pathlib import Path


def _download(model: str, flat: Path) -> None:
    from huggingface_hub import snapshot_download
    from fastembed import TextEmbedding
    desc = next((m for m in TextEmbedding.list_supported_models() if m["model"] == model), None)
    hf = ((desc or {}).get("sources") or {}).get("hf") or model
    if not flat.exists() or not any(flat.rglob("*.onnx")):
        print(f"scarico {hf} → {flat}", flush=True)
        snapshot_download(hf, local_dir=str(flat), local_dir_use_symlinks=False)
    print("modello presente:", flat, flush=True)


def _capitolo(x) -> str:
    """Il titolo del capitolo (kreu + seksioni) senza «KREU V —»: dice il TEMA quando la rubrica è generica."""
    from src.parser import _CAP_PREFIX
    parti = [_CAP_PREFIX.sub("", c or "").strip() for c in (getattr(x, "kreu", ""), getattr(x, "seksioni", ""))]
    return " · ".join(p for p in parti if p)


def _testata(x) -> str:
    """v9.376 — testata del segmento: rubrica (se l'articolo ha un corpo) + titolo del capitolo."""
    cap = _capitolo(x)
    rub = (x.heading or "") if (x.body or "").strip() else ""
    return " — ".join(p for p in (rub.strip(), cap.lower() if cap.isupper() else cap) if p)


def _corpo(x) -> str:
    """Il testo da codificare: il corpo; se è vuoto (articoli senza rubrica, testo tutto nella «rubrica») la rubrica
    intera — prima se ne codificavano solo i primi 120 caratteri."""
    return (x.body or "").strip() or (x.heading or "")


def _encode(texts: list[str], batch: int = 32):
    from src import dense
    t0 = time.time()
    E = dense.embed_passages(texts, batch_size=batch)
    if E is None:
        raise RuntimeError("modello non disponibile (fastembed/flat dir)")
    dt = time.time() - t0
    print(f"  codificati {len(texts)} testi in {dt:.0f}s ({len(texts)/max(dt,1e-6):.1f}/s)", flush=True)
    return E


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["al", "it", "dec"], default=None)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--incremental", action="store_true", help="v9.373: codifica SOLO gli articoli senza embedding e li accoda ai file esistenti")
    ap.add_argument("--rifai", default="", help="v9.376: file JSON con le chiavi [code, number] da RIcodificare (testo cambiato): "
                    "le loro righe si tolgono e si rifanno, il resto resta com'è")
    ap.add_argument("--kreu", action="store_true", help="v9.376: il titolo del CAPITOLO entra nel testo codificato, e gli articoli "
                    "senza corpo (testo tutto nella «rubrica») si codificano per intero invece dei primi 120 caratteri")
    ap.add_argument("--flat", action="store_true", help="un vettore per articolo (testo troncato a 128 token: comportamento v9.353)")
    ap.add_argument("--suffix", default=os.environ.get("EMB_SUFFIX", ""), help="suffisso dei file (es. _ck) per una codifica affiancata")
    a = ap.parse_args()
    import numpy as np
    from src import dense
    from src.retrieval import ArticleIndex, DecisionIndex
    flat = dense.flat_dir()
    _download(dense.MODEL, flat)
    if a.download:
        return 0
    todo = [a.only] if a.only else ["al", "it", "dec"]
    for what in todo:
        if what in ("al", "it"):
            lang = "sq" if what == "al" else "it"
            idx = ArticleIndex.load() if what == "al" else ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
            base = dense.EMB_DIR / f"emb_{lang}_{dense.tag()}{a.suffix}"
            _old_E, _old_keys = None, None
            _rif = {(k[0], str(k[1])) for k in json.loads(Path(a.rifai).read_text(encoding="utf-8"))} if a.rifai else set()
            if base.with_suffix(".npy").exists() and (a.incremental or _rif):
                _old_E = np.load(base.with_suffix(".npy"))
                _old_keys = json.loads(Path(str(base) + ".keys.json").read_text(encoding="utf-8"))
                if _rif:            # le righe degli articoli da rifare si tolgono (flat: una; segmenti: tutte)
                    _tieni = [i for i, k in enumerate(_old_keys) if (k[0], str(k[1])) not in _rif]
                    _old_E = _old_E[_tieni]; _old_keys = [_old_keys[i] for i in _tieni]
            elif base.with_suffix(".npy").exists() and not a.force:
                print(f"{what}: {base.name}.npy esiste (usa --force per rifare, --incremental per i soli nuovi)"); continue
            arts = idx.articles
            if _old_keys is not None:
                _have = {(k[0], k[1]) for k in _old_keys}
                arts = [x for x in arts if (x.code, str(x.number)) not in _have]
                if not arts:
                    print(f"{what}: nessun articolo nuovo"); continue
            if a.flat:
                if a.kreu:
                    texts = [((_testata(x) + ". " + _corpo(x)) if _testata(x) else _corpo(x))[:1500] for x in arts]
                else:
                    texts = [((x.heading or "") + ". " + (x.body or ""))[:1500] for x in arts]
                keys = [[x.code, str(x.number)] for x in arts]
            else:
                # v9.362 — SEGMENTI: ogni articolo → 1..N testi (rubrica + ~110 token), chiave [code, number, i]
                texts, keys = [], []
                for x in arts:
                    _segs = (dense.chunk_text(_testata(x), _corpo(x), rub_max=200) if a.kreu
                             else dense.chunk_text(x.heading or "", x.body or ""))
                    for i, seg in enumerate(_segs):
                        texts.append(seg); keys.append([x.code, str(x.number), i])
            print(f"{what}: {len(arts)} articoli → {len(texts)} {'testi' if a.flat else 'segmenti'}", flush=True)
            E = _encode(texts)
            if _old_E is not None:
                E = np.concatenate([_old_E, np.asarray(E, dtype=_old_E.dtype)], axis=0); keys = _old_keys + keys
            _tmp = base.with_name(base.name + ".tmp.npy")
            np.save(_tmp, E); os.replace(_tmp, base.with_suffix(".npy"))
            Path(str(base) + ".keys.json").write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")
            print(f"  → {base.name}.npy {E.shape}", flush=True)
        else:
            didx = DecisionIndex.load()
            base = dense.EMB_DIR / f"emb_dec_{dense.tag()}"
            if base.with_suffix(".npy").exists() and not a.force:
                print(f"dec: {base.name}.npy esiste (usa --force per rifare)"); continue
            decs = didx.decisions
            print(f"dec: {len(decs)} precedenti", flush=True)
            texts = [(f"{d.objekti or ''}. {d.dispositif or ''}. {(d.reasoning or '')[:1200]}")[:1800] for d in decs]
            E = _encode(texts)
            np.save(base.with_suffix(".npy"), E)
            Path(str(base) + ".keys.json").write_text(json.dumps([f"{d.court_code}|{d.year}|{d.number}" for d in decs], ensure_ascii=False), encoding="utf-8")
            print(f"  → {base.name}.npy {E.shape}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
