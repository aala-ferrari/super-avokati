# -*- coding: utf-8 -*-
"""A/B della RICERCA DENSA (embedding) contro BM25 e in ibrido (RRF), sull'indice AL VERO — roadmap v4,
punto 4 (20 set 2026). Si misura PRIMA di accendere, come per lo stemming (v9.345).

    python3 tools/emb_ab.py --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    python3 tools/emb_ab.py --model BAAI/bge-m3 --limit 2000     # prova su un sottoinsieme

Metriche: recall@12 sui test del benchmark strato 1 (retrieval:al, 306 query nel linguaggio del
codice), posizione sulle 16 query difficili dello stemming (parole dell'avvocato), le query «per
tipo di caso» (divorci, grabitje…) e i tempi (codifica del corpus, latenza per query).
Gli embedding si salvano in EMB_DIR (volume) per non ricodificare. Modelli via fastembed (ONNX, CPU).
"""
import argparse, json, os, sys, time
sys.path.insert(0, "/app")
from pathlib import Path
import numpy as np

EMB_DIR = Path(os.environ.get("EMB_DIR", "/app/data/models"))
K = 12
HARD = [
    ("afati i parashkrimit", ("kodi_civil", "114")), ("sa është afati i parashkrimit të padisë", ("kodi_civil", "114")),
    ("parashkrimi i përgjithshëm dhjetë vjet", ("kodi_civil", "114")),
    ("makina bën zhurmë marmita", ("kodi_rrugor", "153")), ("zhurmë e tepërt nga automjeti gjoba", ("kodi_rrugor", "153")),
    ("kufizimi i zhurmave", ("kodi_rrugor", "153")),
    ("pushimi nga puna pa paralajmërim dëmshpërblimi", ("kodi_punes", "155")),
    ("shpërblimi për vjetërsi në punë", ("kodi_punes", "152")),
    ("anulimi i lejes së qëndrimit të huajt", ("ligji_te_huajt", "73")),
    ("zgjidhja e menjëhershme e pajustifikuar e kontratës", ("kodi_punes", "155")),
    ("kontrata e qirasë afati", ("kodi_civil", "801")), ("divorci me pëlqim reciprok", ("kodi_familjes", "125")),
    # «divorci»: il capitolo dello scioglimento (Kreu II 125-144 + Kreu III pasojat 145-162, verificato sul corpus 20 set)
    ("divorci", ("kodi_familjes", "125-162")), ("grabitje", ("kodi_penal", "139")), ("vjedhje me dhunë", ("kodi_penal", "139")),
    ("dhuna në familje urdhri i mbrojtjes", ("ligji_dhuna_familje_2026", "1")),
    ("trashëgimia ligjore fëmijët", ("kodi_civil", "361")), ("rapina", ("kodi_penal", "139")),
    # v9.362 — query «di coda»: la risposta sta nell'ULTIMO paragrafo, oltre i 128 token (misurato 21 set)
    ("përjashtohen nga përgjegjësia penale të afërmit që ndihmojnë autorin e krimit", ("kodi_penal", "302")),
    ("strehova vëllain tim që ishte i kërkuar nga policia", ("kodi_penal", "302")),
    ("plagosje e rëndë kundër bashkëshortit ose ish-bashkëjetuesit dënimi", ("kodi_penal", "88")),
    # v9.376 — domande da avvocato dove il TEMA sta nel titolo del capitolo (misurate con il BM25 il 23 set)
    ("dëmshpërblim nga burgimi i padrejtë", ("kodi_proc_penale", "268")), ("kompensimi për paraburgim të padrejtë", ("kodi_proc_penale", "268")),
    ("afati i kërkesës për kompensim të burgimit", ("kodi_proc_penale", "269")),
    ("rivendosja në afat e ankimit", ("kodi_proc_penale", "147")), ("sekuestro konservative sigurimi i padisë", ("kodi_proc_civile", "202-210")),
    ("zgjidhja e martesës me kërkesën e njërit bashkëshort", ("kodi_familjes", "125-144")),
    ("masat e sigurimit personal arrest në burg", ("kodi_proc_penale", "228-262")),
    ("kundërshtimi i veprimeve të përmbaruesit", ("kodi_proc_civile", "609-611")),
    ("pavlefshmëria absolute e veprimit juridik", ("kodi_civil", "92-99")),
    ("fitimi i pronësisë me parashkrim", ("kodi_civil", "168-169")),
    ("kontrabanda me mallra gjoba doganore", ("kodi_doganor", "262-282")),
    ("shpërblimi i dëmit jashtëkontraktor", ("kodi_civil", "608-646")),
    ("e drejta e trashëgimisë së fëmijëve jashtë martese", ("kodi_civil", "361-362")),
    ("zgjidhja e kontratës së punës me afat të pacaktuar", ("kodi_punes", "140-155")),
    ("përgjegjësia e prindërve për dëmin e shkaktuar nga i mituri", ("kodi_civil", "612-613")),
    # v9.376 — le leggi nuove (49/2012, 8577/2000, 152/2013)
    ("afati për të paditur aktin administrativ në gjykatë", ("ligji_gjykatat_administrative", "18")),
    ("kërkesa individuale në gjykatën kushtetuese afati katër muaj", ("ligji_gjykata_kushtetuese", "71/a")),
    ("largimi nga shërbimi civil i nëpunësit", ("ligji_nepunesi_civil", "59-64")),
]

HARD_IT = [
    ("rapina", ("codice_penale", "628")), ("divorzio", ("divorzio", "1")), ("licenziamento senza giusta causa", ("licenziamenti_individuali", "3")),
    ("prescrizione ordinaria", ("codice_civile", "2946")), ("auto targa straniera residente in italia", ("codice_strada", "93-bis")),
    ("clausole vessatorie consumatore", ("codice_consumo", "33")), ("guida in stato di ebbrezza", ("codice_strada", "186")),
    ("sfratto per morosità", ("codice_procedura_civile", "658")), ("cittadinanza per matrimonio", ("cittadinanza", "5")),
    ("permesso di soggiorno rinnovo", ("tu_immigrazione", "5")),
    # v9.383 — domande in cui la RUBRICA è generica e il tema lo dice solo il CAPITOLO (Titolo/Capo/Sezione)
    ("riparazione per ingiusta detenzione", ("codice_procedura_penale", "314")),
    ("prescrizione presuntiva di un anno", ("codice_civile", "2955")),
    ("ricorso nel rito del lavoro forma della domanda", ("codice_procedura_civile", "414")),
    ("opposizione a decreto ingiuntivo", ("codice_procedura_civile", "645")),
    ("ricorso per cassazione penale motivi", ("codice_procedura_penale", "606")),
    ("opposizione al decreto penale di condanna", ("codice_procedura_penale", "461")),
    ("opposizione alla convalida di sfratto", ("codice_procedura_civile", "665")),
    ("pignoramento presso terzi dichiarazione del terzo", ("codice_procedura_civile", "547")),
    ("ipoteca giudiziale sentenza di condanna", ("codice_civile", "2818")),
    ("comunione legale dei beni tra coniugi oggetto", ("codice_civile", "177")),
    ("eredità giacente nomina del curatore", ("codice_civile", "528")),
    ("rinuncia all'eredità", ("codice_civile", "519")),
    ("collazione delle donazioni tra coeredi", ("codice_civile", "737")),
    ("misure cautelari personali condizioni di applicabilità", ("codice_procedura_penale", "273")),
    ("termini per impugnare la sentenza penale", ("codice_procedura_penale", "585")),
    # v9.384 — diritto UE e CEDU: il tema lo dice il capitolo (Bruxelles I-bis non ha rubriche; CDU 250 «Ambito di applicazione»)
    ("ammissione temporanea di merci e veicoli", ("codice_doganale_ue", "250")),
    ("ammissione temporanea auto uso privato residente fuori dall'Unione", ("reg_ue_2015_2446", "215")),
    ("competenza giurisdizionale nei contratti conclusi dai consumatori", ("bruxelles_i_bis", "17")),
    ("competenza esclusiva diritti reali su immobili", ("bruxelles_i_bis", "24")),
    ("proroga di competenza clausola di scelta del foro", ("bruxelles_i_bis", "25")),
    ("riconoscimento della decisione di un altro Stato membro", ("bruxelles_i_bis", "36")),
    ("legge applicabile ai contratti conclusi dai consumatori", ("roma_i", "6")),
    ("legge applicabile al contratto in mancanza di scelta", ("roma_i", "4")),
    ("rinvio pregiudiziale alla Corte di giustizia", ("tfue", "267")),
    ("legge applicabile alla successione ultima residenza abituale", ("successioni_ue", "21")),
    ("competenza sulla responsabilità genitoriale residenza abituale del minore", ("bruxelles_ii_ter", "7")),
    ("diritto a un equo processo in tempo ragionevole", ("cedu", "6")),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--lang", default="al", choices=["al", "it"])
    ap.add_argument("--it-index", default="/app/data/index/bm25_it.pkl", help="v9.383: indice BM25 italiano da misurare (di prova)")
    ap.add_argument("--suffix", default="", help="codifica di produzione da misurare (es. _ck = segmenti)")
    ap.add_argument("--suffix2", default="", help="SECONDA codifica da fondere con la prima (es. --suffix _flat2 --suffix2 _ck)")
    ap.add_argument("--fuse", default="rrf3", choices=["rrf3", "max", "avg", "maxlog", "top2"],
                    help="rrf3 = tre liste RRF; max = massimo dei due coseni; avg = media articolo-intero/segmenti; maxlog = segmenti scontati di 0,02·ln(n segmenti); top2 = media dei 2 segmenti migliori, poi max con l'articolo intero")
    a = ap.parse_args()
    from fastembed import TextEmbedding
    from src.retrieval import ArticleIndex
    idx = ArticleIndex.load() if a.lang == "al" else ArticleIndex.load(Path(a.it_index))
    arts = idx.articles if not a.limit else idx.articles[: a.limit]
    live = [i for i, x in enumerate(arts) if not x.repealed]
    tag = a.model.replace("/", "__")
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    f = EMB_DIR / f"emb_{a.lang}_{tag}_{len(arts)}.npy"
    t0 = time.time()
    # onnxruntime 1.30 rifiuta i dati esterni (model.onnx_data) raggiunti via symlink della cache HF
    # («External data path escapes model directory», visto con multilingual-e5-large): si scarica il
    # modello in una cartella PIATTA (senza symlink) e la si passa a fastembed come percorso esplicito.
    from huggingface_hub import snapshot_download
    desc = next((m for m in TextEmbedding.list_supported_models() if m["model"] == a.model), None)
    hf = ((desc or {}).get("sources") or {}).get("hf") or a.model
    flat = EMB_DIR / ("flat_" + tag)
    if not flat.exists() or not any(flat.rglob("*.onnx")):
        snapshot_download(hf, local_dir=str(flat), local_dir_use_symlinks=False)
    model = TextEmbedding(model_name=a.model, cache_dir=str(EMB_DIR), threads=a.threads, specific_model_path=str(flat))
    print(f"modello pronto in {time.time()-t0:.0f}s: {a.model}", flush=True)
    # riusa gli embedding di produzione (tools/build_dense.py) se esistono per questo modello
    prod = EMB_DIR / f"emb_{'sq' if a.lang == 'al' else 'it'}_{tag}{a.suffix}"
    ROWS = None          # v9.362: con i segmenti E ha più righe per articolo; ROWS[i] = indice dell'articolo
    if (a.suffix or not f.exists()) and prod.with_suffix(".npy").exists() and Path(str(prod) + ".keys.json").exists() and not a.limit:
        keys = json.loads(Path(str(prod) + ".keys.json").read_text(encoding="utf-8"))
        Ep = np.load(prod.with_suffix(".npy"))
        apos = {(x.code, str(x.number)): i for i, x in enumerate(arts)}
        ROWS = np.array([apos.get((k[0], str(k[1])), -1) for k in keys])
        if (ROWS >= 0).sum() == 0:
            E = None; ROWS = None
        else:
            E = Ep; print(f"embedding di produzione riusati: {prod.name}.npy → {E.shape} ({len(set(ROWS[ROWS>=0]))} articoli)", flush=True)
    else:
        E = None
    if E is not None:
        pass
    elif f.exists():
        E = np.load(f); print(f"embedding caricati da {f.name}: {E.shape}", flush=True)
    else:
        docs = [((x.heading or "") + ". " + (x.body or ""))[:1500] for x in arts]
        t0 = time.time()
        E = np.asarray(list(model.passage_embed(docs, batch_size=32) if hasattr(model, "passage_embed") else model.embed(docs, batch_size=32)), dtype=np.float32)
        dt = time.time() - t0
        E /= (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
        np.save(f, E)
        print(f"codificati {len(docs)} articoli in {dt:.0f}s ({len(docs)/dt:.1f} art/s) → {f.name} {E.shape}", flush=True)
    E2 = ROWS2 = None
    if a.suffix2:
        prod2 = EMB_DIR / f"emb_{'sq' if a.lang == 'al' else 'it'}_{tag}{a.suffix2}"
        keys2 = json.loads(Path(str(prod2) + ".keys.json").read_text(encoding="utf-8"))
        E2 = np.load(prod2.with_suffix(".npy"))
        apos2 = {(x.code, str(x.number)): i for i, x in enumerate(arts)}
        ROWS2 = np.array([apos2.get((k[0], str(k[1])), -1) for k in keys2])
        print(f"seconda codifica: {prod2.name}.npy → {E2.shape}", flush=True)
    live_mask = np.zeros(len(arts), dtype=bool); live_mask[live] = True

    def q_emb(q):
        v = np.asarray(list(model.query_embed([q]) if hasattr(model, "query_embed") else model.embed([q])), dtype=np.float32)[0]
        return v / (np.linalg.norm(v) + 1e-9)

    def _scores(Emat, rows, v):
        s = Emat @ v
        if rows is not None:                       # segmenti → massimo per articolo
            sa = np.full(len(arts), -9.0, dtype=np.float32)
            ok = rows >= 0
            np.maximum.at(sa, rows[ok], s[ok])
            s = sa
        s = s.copy(); s[~live_mask] = -9
        return s

    NSEG = None
    if E2 is not None and ROWS2 is not None:
        NSEG = np.bincount(ROWS2[ROWS2 >= 0], minlength=len(arts)).astype(np.float32)

    def _top2(Emat, rows, v):
        """media dei due segmenti migliori per articolo (un solo segmento → il suo coseno)."""
        s = Emat @ v
        best = np.full(len(arts), -9.0, dtype=np.float32); second = np.full(len(arts), -9.0, dtype=np.float32)
        order = np.argsort(-s)
        for i in order:
            r = rows[i]
            if r < 0: continue
            if best[r] <= -9.0: best[r] = s[i]
            elif second[r] <= -9.0: second[r] = s[i]
        out = np.where(second > -9.0, (best + second) / 2.0, best)
        out[~live_mask] = -9
        return out

    def dense(q, k=K, depth=50):
        v = q_emb(q); s = _scores(E, ROWS, v)
        if E2 is not None and a.fuse != "rrf3":
            s2 = _scores(E2, ROWS2, v)
            if a.fuse == "max":
                s = np.maximum(s, s2)
            elif a.fuse == "avg":
                s = (s + s2) / 2.0
            elif a.fuse == "maxlog":
                s = np.maximum(s, s2 - 0.02 * np.log(np.maximum(NSEG, 1.0)))
            elif a.fuse == "top2":
                s = np.maximum(s, _top2(E2, ROWS2, v))
        order = np.argsort(-s)[:depth]
        return [(arts[i], float(s[i])) for i in order][:k], order

    def dense2(q, k=K, depth=50):
        v = q_emb(q); s = _scores(E2, ROWS2, v)
        order = np.argsort(-s)[:depth]
        return [(arts[i], float(s[i])) for i in order][:k], order

    def bm25(q, depth=50):
        return idx.search(q, top_k=depth)

    def hybrid(q, k=K, depth=50, kk=60):
        b = bm25(q, depth); d, _ = dense(q, depth, depth)
        sc = {}
        for r, (art, _) in enumerate(b, 1):
            sc[(art.code, str(art.number))] = sc.get((art.code, str(art.number)), 0) + 1 / (kk + r)
        for r, (art, _) in enumerate(d, 1):
            sc[(art.code, str(art.number))] = sc.get((art.code, str(art.number)), 0) + 1 / (kk + r)
        if E2 is not None and a.fuse == "rrf3":     # terza lista: la seconda codifica (RRF a tre)
            d2, _ = dense2(q, depth, depth)
            for r, (art, _) in enumerate(d2, 1):
                sc[(art.code, str(art.number))] = sc.get((art.code, str(art.number)), 0) + 1 / (kk + r)
        by = {(x.code, str(x.number)): x for x in arts}
        return sorted(((by[kkey], s) for kkey, s in sc.items() if kkey in by), key=lambda t: -t[1])[:k]

    tests = [json.loads(l) for l in open("/app/data/benchmark/layer1_auto.jsonl", encoding="utf-8") if l.strip()]
    tests = [t for t in tests if t["kind"] == "retrieval" and t["lang"] == a.lang]
    if a.limit:
        keys = {(x.code, str(x.number)) for x in arts}
        tests = [t for t in tests if all(tuple(e) in keys for e in t["expect"])]

    def rec(fn):
        hit = 0; t0 = time.time()
        for t in tests:
            got = {(x.code, str(x.number)) for x, _ in fn(t["query"])}
            hit += all(tuple(e) in got for e in t["expect"])
        return hit, (time.time() - t0) / max(1, len(tests)) * 1000

    rb, lb = rec(lambda q: bm25(q)[:K]); rd, ld = rec(lambda q: dense(q)[0]); rh, lh = rec(hybrid)
    print(f"\nstrato 1 retrieval:al ({len(tests)} test, recall@{K}): BM25 {rb}  dense {rd}  ibrido {rh}   | latenza ms/query: {lb:.0f} / {ld:.0f} / {lh:.0f}")

    def _match(x, key):
        if x.code != key[0]:
            return False
        if "-" in key[1] and key[1].replace("-", "").isdigit():
            lo, hi = (int(v) for v in key[1].split("-"))
            base = str(x.number).split("/")[0]
            return base.isdigit() and lo <= int(base) <= hi
        return str(x.number) == key[1]

    def pos(fn, q, key, depth=200):
        for i, (x, _) in enumerate(fn(q, depth), 1):
            if _match(x, key):
                return i
        return None
    print("\nquery difficili (posizione: BM25 → dense → ibrido; None = oltre 200):")
    wins = 0
    lista = HARD if a.lang == "al" else HARD_IT
    posiz = {"bm25": [], "dense": [], "ibrido": []}
    for q, key in lista:
        pb = pos(lambda q, d: bm25(q, d), q, key); pd = pos(lambda q, d: dense(q, d, d)[0], q, key); ph = pos(lambda q, d: hybrid(q, d, d), q, key)
        posiz["bm25"].append(pb); posiz["dense"].append(pd); posiz["ibrido"].append(ph)
        m = "  "
        if ph is not None and (pb is None or ph < pb): m = "▲"; wins += 1
        elif pb is not None and (ph is None or ph > pb): m = "▼"
        print(f"  {m} {q:55s} {str(key):32s} {pb} → {pd} → {ph}")
    print(f"ibrido meglio di BM25 su {wins}/{len(lista)} query difficili")
    for nome, ps in posiz.items():        # v9.383: il riassunto che serve per decidere (primo posto, primi 3, primi 12, MRR)
        print(f"  {nome:7s}: 1° {sum(1 for p in ps if p == 1):2d} · primi 3 {sum(1 for p in ps if p and p <= 3):2d} · "
              f"primi 12 {sum(1 for p in ps if p and p <= 12):2d} · MRR {sum(1 / p for p in ps if p) / max(1, len(ps)):.3f}  (su {len(ps)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
