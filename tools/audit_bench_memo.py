# v9.647 — uso: bash tools/prova_pro.sh <nome> tools/audit_bench_memo.py [immagine] [cartella_src]  (risposte in /tmp/pp_<nome>/out)
# Audit del «Memo e gjyqtarit / Memo del giudice» col cervello vero (dati inventati), per la STESSA strada della rotta
# (`web._memo_gjyqtari` dalla v9.647; prima `bench_memo.generate_bench_memo` con la ricerca BM25 nuda): due casi in sessione AL,
# uno in sessione IT. Per ogni memo: tempi, articoli dati, precedenti (e di quale archivio), le citazioni del JSON verificate,
# la lingua dei valori; il JSON intero in /out.
import sys, time, json, threading, collections, os, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import web, brain, bench_memo
from src import citation_verifier as cv

web._ensure_loaded()
_TL = threading.local()
web._active_jurisdiction = lambda u: getattr(_TL, "giur", "AL")
NUOVO = hasattr(web, "_memo_gjyqtari")

CASI = {
    "pushim_al": ("AL", "gjykata_shkalle1", (
        "Klienti ynë Luan Shembulli (paditës) punoi si shofer te «Transport Shembull» sh.p.k. nga 1.3.2019 me kontratë me afat të "
        "pacaktuar, pagë 80.000 lekë. Më 2.10.2026 administratori i tha me gojë «mos eja më nesër», pa asnjë letër e pa takim "
        "paraprak; nuk i ka paguar pagën e shtatorit. Kërkojmë konstatimin e zgjidhjes së pajustifikuar, dëmshpërblimin dhe pagat. "
        "Shoqëria pretendon se punëtori braktisi punën më 3.10.2026."), (
        "Punëmarrësi nuk u paraqit në punë nga 3.10.2026 dhe nuk njoftoi brenda 7 ditëve: marrëdhënia u zgjidh për braktisje.")),
    "apartament_al": ("AL", "gjykata_apelit", (
        "Klienti ynë Gent Shembulli bleu më 10.3.2026 me kontratë noteriale një apartament 86 m² nga «Ndërtimi Shembull» sh.p.k. "
        "për 85.000 euro. Në shtator 2026 zbuloi lagështirë nga defekt i izolimit të fasadës; ekspertiza jep 78 m². Gjykata e "
        "shkallës së parë e rrëzoi padinë për ulje çmimi sepse të metat nuk u denoncuan brenda 10 ditëve (neni 717 KC). Bëjmë apel."),
        ""),
    "licenziamento_it": ("IT", "gjykata_shkalle1", (
        "Il nostro cliente Mario Prova, autista assunto a tempo indeterminato nel 2019 da «Trasporti Esempio» s.r.l. (40 dipendenti), "
        "è stato licenziato oralmente il 2.10.2026 («non venire più domani»), senza lettera. Chiediamo la nullità del licenziamento "
        "orale, la reintegrazione e le retribuzioni di settembre non pagate. La società sostiene che il lavoratore si è dimesso."),
        "Il lavoratore ha abbandonato il posto di lavoro e non si è più presentato: si tratta di dimissioni per fatti concludenti."),
}
_solo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SOLO", "")
ordine = [n for n in CASI if not _solo or any(s in n for s in _solo.split(","))]


def corri(nome):
    giur, corte, descr, opp = CASI[nome]
    _TL.giur = giur
    brain.set_request_jurisdiction(giur)
    t0 = time.time()
    try:
        with web.app.test_request_context("/api/audit", method="POST"):
            from flask import request as _rq
            _rq.user = object()
            if NUOVO:
                memo = web._memo_gjyqtari(descr, "", opp, corte, case_id=None)
            else:
                inp = bench_memo.BenchMemoInput(case_description=descr, documents_summary="", opponent_filing=opp, court_code=corte)
                memo = bench_memo.generate_bench_memo(inp, backend=web._BRAIN.backend, article_index=web._req_index(),
                                                      decision_index=None, case_id=None)
            err = None
    except Exception as e:  # noqa: BLE001
        memo, err = {}, f"{type(e).__name__}: {e}"
    return nome, giur, time.time() - t0, memo, err


with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, giur, sec, memo, err in ex.map(corri, ordine):
        open(f"/out/{nome}.json", "w", encoding="utf-8").write(json.dumps(memo, ensure_ascii=False, indent=1))
        idx = web._INDEX_IT if giur == "IT" else web._INDEX
        testo = json.dumps({k: v for k, v in memo.items() if not k.startswith("_") and k not in ("precedents_used", "articles_used")},
                           ensure_ascii=False)
        st = collections.Counter(it.get("status") for it in cv.verify_text(testo, idx).get("items", []))
        precs = memo.get("precedents_used") or []
        alb = sum(testo.count(w) for w in (" të ", " dhe ", " është ", "i lartë", "i mesëm")) if giur == "IT" else 0
        print(f"===== {nome} [{giur}] — {sec:.0f} s {'ERRORE ' + err if err else ''} parse={memo.get('_parse_error')}")
        print(f"   articoli dati: {len(memo.get('articles_used') or [])} · precedenti {len(precs)}: "
              f"{[p.get('court_code') for p in precs][:6]}")
        print(f"   citazioni nel memo {dict(st)} · albanese(IT)={alb} · raccomandazione: {str(memo.get('recommendation'))[:120]}")
        print(f"   applicable_law: {[l.get('reference') for l in (memo.get('applicable_law') or [])][:10]}")
