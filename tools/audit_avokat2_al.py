# v9.645 — uso: bash tools/prova_pro.sh <nome> tools/audit_avokat2_al.py [immagine] [cartella_src]  (risposte in /tmp/pp_<nome>/out)
# Audit degli strumenti dell'AVVOCATO che lavoravano senza articoli del corpus (dati inventati): la mappa delle pretese
# («Harta e Pretendimeve»), il Red Team sul contratto («Kundërshtari»), la revisione del contratto — chiamati per la STESSA
# strada delle rotte (`web._harta_pretendimeve`, `web._red_team`, `web._rishikim_kontrate`) dentro un contesto di richiesta
# finto, con la giurisdizione della sessione per thread. Riga di sintesi: tempi, lunghezza, citazioni verificate/false,
# se il blocco del corpus c'era; in fondo il contesto e il costo di ogni chiamata dal registro (copia del DB).
# Prima della v9.645 le funzioni non esistono: lo script ripiega sui prompt nudi (la misura di prima).
import sys, time, json, threading, collections, sqlite3, os, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import web, brain
from src import citation_verifier as cv

web._ensure_loaded()
_TL = threading.local()
web._active_jurisdiction = lambda u: getattr(_TL, "giur", "AL")      # la sessione del thread
NUOVO = hasattr(web, "_harta_pretendimeve")

FAKTET_HARTA = (
    "Klienti ynë Gent Shembulli bleu më 10.3.2026, me kontratë noteriale, një apartament 86 m² në Tiranë nga shoqëria ndërtuese "
    "«Ndërtimi Shembull» sh.p.k. për 85.000 euro, të paguara me transfertë bankare. Në shtator 2026 zbuloi lagështirë të rëndë në "
    "muret e jashtme; raporti i një eksperti privat (25.9.2026) thotë se është defekt ndërtimi i izolimit të fasadës. Matja e "
    "ekspertit jep 78 m². Klienti i dërgoi shoqërisë dy mesazhe WhatsApp (28.9 dhe 5.10) pa përgjigje. Duam padi për ulje çmimi "
    "dhe dëmshpërblim.")
KONTRATA = (
    "KONTRATË QIRAJE\nE lidhur më 1.9.2026 në Tiranë midis «Prona Shembull» sh.p.k. (qiradhënësi) dhe Arben Prova (qiramarrësi).\n"
    "Neni 1. Qiradhënësi i jep me qira qiramarrësit apartamentin në rrugën «Shembulli» 5, Tiranë, për banim.\n"
    "Neni 2. Qiraja është 600 euro në muaj, e pagueshme deri më datën 5 të çdo muaji. Për çdo ditë vonesë qiramarrësi paguan "
    "penalitet 50 euro.\n"
    "Neni 3. Kontrata lidhet për 3 vjet. Qiramarrësi nuk mund ta zgjidhë kontratën para afatit; nëse largohet, paguan qiranë e "
    "gjithë periudhës së mbetur.\n"
    "Neni 4. Qiradhënësi mund ta zgjidhë kontratën në çdo kohë me njoftim 7 ditë.\n"
    "Neni 5. Depozita është 3.000 euro dhe nuk kthehet në asnjë rast.\n"
    "Neni 6. Qiradhënësi nuk përgjigjet për asnjë dëm që i vjen qiramarrësit nga gjendja e apartamentit.\n"
    "Neni 7. Çdo mosmarrëveshje zgjidhet nga arbitri i caktuar nga qiradhënësi.\n")
CONTRATTO_IT = (
    "CONTRATTO DI LOCAZIONE AD USO ABITATIVO\nTra «Immobiliare Esempio» s.r.l. (locatore) e Mario Prova (conduttore), Milano, "
    "1.9.2026.\nArt. 1. Il locatore concede in locazione l'appartamento in via Esempio 5, Milano, ad uso abitativo.\n"
    "Art. 2. Il canone è di 900 euro mensili da pagare entro il giorno 5. Per ogni giorno di ritardo il conduttore paga una penale "
    "di 80 euro.\nArt. 3. La durata è di 4 anni. Il conduttore non può recedere prima della scadenza; se lascia l'immobile paga i "
    "canoni fino alla scadenza.\nArt. 4. Il locatore può risolvere il contratto in qualsiasi momento con preavviso di 7 giorni.\n"
    "Art. 5. Il deposito cauzionale è di 5.400 euro e non viene restituito in nessun caso.\n"
    "Art. 6. Il locatore non risponde di alcun danno derivante dallo stato dell'immobile.\n"
    "Art. 7. Ogni controversia è decisa da un arbitro nominato dal locatore.\n")


def harta():
    if NUOVO:
        return web._harta_pretendimeve(FAKTET_HARTA, {})
    return {"markdown": web._BRAIN.backend.complete(system=web._HARTA_SYSTEM, messages=[{"role": "user", "content": FAKTET_HARTA}],
                                                     max_tokens=3000, fast=False, callsite="audit_claim_chart")}


def red_team(testo):
    def f():
        if NUOVO:
            return web._red_team(testo, {})
        from src import adversary
        return adversary.attack(web._BRAIN.backend, text=testo)
    return f


def rishikim(testo):
    def f():
        if NUOVO:
            parsed, st = web._rishikim_kontrate(testo, {})
            return {"markdown": json.dumps(parsed, ensure_ascii=False, indent=1), "citations": {"stats": st}, "grounded": True}
        return {"markdown": web._BRAIN.backend.complete(system=web.CONTRACT_REVIEW_SYSTEM, messages=[{"role": "user", "content": testo}],
                                                         max_tokens=6000, fast=False, callsite="audit_contract_review")}
    return f


CASI = {
    "harta_apartament": ("AL", harta),
    "red_team_qira": ("AL", red_team(KONTRATA)),
    "rishikim_qira": ("AL", rishikim(KONTRATA)),
    "red_team_locazione_it": ("IT", red_team(CONTRATTO_IT)),
    "rishikim_locazione_it": ("IT", rishikim(CONTRATTO_IT)),
}
_solo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SOLO", "")
ordine = [n for n in CASI if not _solo or any(s in n for s in _solo.split(","))]


def corri(nome):
    giur, fn = CASI[nome]
    _TL.giur = giur
    brain.set_request_jurisdiction(giur)
    t0 = time.time()
    try:
        with web.app.test_request_context("/api/audit", method="POST"):
            from flask import request as _rq
            _rq.user = object()
            res, err = fn() or {}, None
    except Exception as e:  # noqa: BLE001
        res, err = {}, f"{type(e).__name__}: {e}"
    return nome, giur, time.time() - t0, res, err


t_inizio = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, giur, sec, res, err in ex.map(corri, ordine):
        md = res.get("markdown") or ""
        open(f"/out/{nome}.md", "w", encoding="utf-8").write(md)
        st = dict((res.get("citations") or {}).get("stats") or {})
        if not st and md and not nome.startswith("rishikim"):
            idx = web._INDEX_IT if giur == "IT" else web._INDEX
            st = dict(collections.Counter(it.get("status") for it in cv.verify_text(md, idx).get("items", [])))
        print(f"===== {nome} [{giur}] — {sec:.0f} s, {len(md)} chr, radicato={res.get('grounded')} {'ERRORE ' + err if err else ''}")
        print(f"   citazioni {st}")

try:
    con = sqlite3.connect(os.environ.get("APP_DB_PATH", "/tqa/app.db"))
    cols = {r[1] for r in con.execute("PRAGMA table_info(ai_audit_log)")}
    sel = [c for c in ("callsite", "model", "latency_ms", "context_tokens", "cost_micro_usd") if c in cols]
    print("\n-- registro delle chiamate (dopo l'inizio)")
    for r in con.execute(f"SELECT {', '.join(sel)} FROM ai_audit_log WHERE timestamp >= ? ORDER BY id", (t_inizio,)):
        print("  ", dict(zip(sel, r)))
except Exception as e:  # noqa: BLE001
    print("registro non letto:", e)
