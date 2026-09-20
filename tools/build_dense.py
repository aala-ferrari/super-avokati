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
            base = dense.EMB_DIR / f"emb_{lang}_{dense.tag()}"
            if base.with_suffix(".npy").exists() and not a.force:
                print(f"{what}: {base.name}.npy esiste (usa --force per rifare)"); continue
            arts = idx.articles
            print(f"{what}: {len(arts)} articoli", flush=True)
            E = _encode([((x.heading or "") + ". " + (x.body or ""))[:1500] for x in arts])
            np.save(base.with_suffix(".npy"), E)
            Path(str(base) + ".keys.json").write_text(json.dumps([[x.code, str(x.number)] for x in arts], ensure_ascii=False), encoding="utf-8")
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
