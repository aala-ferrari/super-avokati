# v9.646 — uso: bash tools/prova_pro.sh <nome> tools/audit_redattore.py [immagine] [cartella_src]  (risposte in /tmp/pp_<nome>/out)
# Audit di «Redakto me Tetramorph» (il redattore dell'avvocato, Fable) con dati inventati: un contratto e un atto in sessione AL,
# un contratto in sessione IT — per la STESSA strada della rotta (`web._redakto`, dalla v9.646; prima `fable_drafter.draft`
# senza articoli). Riga di sintesi: tempi, lunghezza, citazioni verificate/false/senza codice, se il blocco del corpus c'era;
# in fondo il contesto e il costo di ogni chiamata dal registro (copia del DB).
import sys, time, threading, collections, sqlite3, os, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import web, brain, fable_drafter
from src import citation_verifier as cv

web._ensure_loaded()
_TL = threading.local()
web._active_jurisdiction = lambda u: getattr(_TL, "giur", "AL")
NUOVO = hasattr(web, "_redakto")

CASI = {
    "kontrate_qira_al": ("AL", "contract", (
        "Harto një kontratë qiraje banimi për apartamentin 2+1 në rrugën «Shembulli» 12, Tiranë (pasuria nr. [___], zona "
        "kadastrale [___]). Qiradhënës: Arben Prova (person fizik, pronar). Qiramarrës: Gent Shembulli. Afati 2 vjet nga "
        "1.11.2026, qiraja 450 euro në muaj e pagueshme deri më datën 5, depozitë sa një muaj qira që kthehet në mbarim pa "
        "dëme. Klienti ynë është qiradhënësi: duam mbrojtje për mospagimin e qirasë, dëmtimet, nënqiranë dhe largimin "
        "para afatit.")),
    "padi_paga_al": ("AL", "act", (
        "Harto padinë e klientit tonë Luan Shembulli kundër «Transport Shembull» sh.p.k. (Tiranë). Ai punoi si shofer nga "
        "1.3.2019 me kontratë me afat të pacaktuar, pagë 80.000 lekë. Më 2.10.2026 administratori i tha me gojë «mos eja më "
        "nesër», pa asnjë letër dhe pa paralajmërim; nuk i ka paguar pagën e shtatorit 2026. Prova: kontrata, listëpagesat e "
        "bankës deri në gusht, mesazhi WhatsApp. Kërkojmë: konstatimin e zgjidhjes së pajustifikuar, dëmshpërblimin, pagën "
        "e shtatorit dhe pagën e periudhës së njoftimit.")),
    "locazione_it": ("IT", "contract", (
        "Redigi un contratto di locazione ad uso abitativo (canone libero, 4+4) per l'appartamento in via Esempio 12, Milano "
        "(foglio [___], particella [___]). Locatore: Mario Prova (persona fisica, proprietario). Conduttore: Luca Esempio. "
        "Decorrenza 1.11.2026, canone 1.100 euro mensili entro il giorno 5, deposito cauzionale di due mensilità. Il nostro "
        "cliente è il locatore: vogliamo tutele per la morosità, i danni, la sublocazione e il recesso anticipato.")),
}
_solo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SOLO", "")
ordine = [n for n in CASI if not _solo or any(s in n for s in _solo.split(","))]


def corri(nome):
    giur, kind, brief = CASI[nome]
    _TL.giur = giur
    brain.set_request_jurisdiction(giur)
    t0 = time.time()
    try:
        with web.app.test_request_context("/api/audit", method="POST"):
            from flask import request as _rq
            _rq.user = object()
            if NUOVO:
                res = web._redakto(kind, brief, "", {})
            else:
                res = fable_drafter.draft(web._BRAIN.backend, kind=kind, brief=brief)
            err = None
    except Exception as e:  # noqa: BLE001
        res, err = {}, f"{type(e).__name__}: {e}"
    return nome, giur, time.time() - t0, res, err


t_inizio = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, giur, sec, res, err in ex.map(corri, ordine):
        md = res.get("markdown") or ""
        open(f"/out/{nome}.md", "w", encoding="utf-8").write(md)
        st = dict((res.get("citations") or {}).get("stats") or {})
        if not st and md:
            idx = web._INDEX_IT if giur == "IT" else web._INDEX
            st = dict(collections.Counter(it.get("status") for it in cv.verify_text(md, idx).get("items", [])))
        st = {k: v for k, v in st.items() if v}
        alb = sum(md.count(w) for w in (" të ", " dhe ", " është ")) if giur == "IT" else 0
        print(f"===== {nome} [{giur}] — {sec:.0f} s, {len(md)} chr, radicato={res.get('grounded')} albanese={alb} "
              f"{'ERRORE ' + err if err else ''}")
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
