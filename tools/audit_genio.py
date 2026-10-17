# v9.648 — uso: bash tools/prova_pro.sh <nome> tools/audit_genio.py [immagine] [cartella_src]  (risultati in /tmp/pp_<nome>/out)
# Misura del «Genio Legale» col cervello vero (dati inventati), per la STESSA strada della rotta (`web._genio_prepare` → il generatore
# che gira nel thread del lavoro): un utente e un fascicolo di prova creati nella COPIA del DB, i fatti come primo messaggio del
# fascicolo (come li scrive l'avvocato in chat), il Genio lanciato sopra. Per ogni lente: tempo, esito, lunghezza, citazioni
# verificate/inesistenti/senza codice sul testo del modello, lingua; in fondo contesto e costo di ogni chiamata dal registro.
# SOLO=al|it per un caso solo. Sulla copia del DB: niente resta in produzione.
import sys, os, time, json, threading, collections, sqlite3
sys.path.insert(0, "/app")
from src import web, brain, storage
from src import citation_verifier as cv

web._ensure_loaded()
_TL = threading.local()
web._active_jurisdiction = lambda u: getattr(_TL, "giur", "AL")

CASI = {
    "apartament_al": ("AL", "Apartamenti me lagështirë — Gent Shembulli", (
        "Klienti ynë Gent Shembulli bleu më 10.3.2026, me kontratë noteriale, një apartament 86 m² në Tiranë nga shoqëria ndërtuese "
        "«Ndërtimi Shembull» sh.p.k. për 85.000 euro, të paguara me transfertë bankare. Në shtator 2026 zbuloi lagështirë të rëndë në "
        "muret e jashtme; raporti i një eksperti privat (25.9.2026) thotë se është defekt ndërtimi i izolimit të fasadës. Matja e "
        "ekspertit jep 78 m². Klienti i dërgoi shoqërisë dy mesazhe WhatsApp (28.9 dhe 5.10) pa përgjigje. Duam padi për ulje çmimi "
        "dhe dëmshpërblim. Si e fitojmë?")),
    "licenziamento_it": ("IT", "Licenziamento orale — Mario Prova", (
        "Il nostro cliente Mario Prova, autista assunto a tempo indeterminato nel 2019 da «Trasporti Esempio» s.r.l. (40 dipendenti), "
        "è stato licenziato oralmente il 2.10.2026 («non venire più domani»), senza lettera. La retribuzione di settembre non è stata "
        "pagata. La società sostiene che il lavoratore si è dimesso. Vogliamo la nullità del licenziamento orale, la reintegrazione e "
        "le retribuzioni. Come vinciamo?")),
}
_solo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SOLO", "")
ordine = [n for n in CASI if not _solo or any(s in n for s in _solo.split(","))]

_ALB = (" të ", " dhe ", " është ", " për ", " nga ", " në ", "neni ", "Kodi ")
_ITA = (" il ", " della ", " che ", " per ", " non ", " art. ", " c.c.", " c.p.c.")

utente = storage.create_user(f"audit.genio.{int(time.time())}@superavokati.test", "x", profession="avokat")
t_inizio = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
riepilogo = []
for nome in ordine:
    giur, titolo, fatti = CASI[nome]
    _TL.giur = giur
    brain.set_request_jurisdiction(giur)
    caso = storage.create_case(utente.id, titolo, jurisdiction=giur)
    storage.add_message(caso.id, "user", fatti)
    t0 = time.time()
    lenti = {}
    err = None
    try:
        with web.app.test_request_context("/api/audit", method="POST"):
            from flask import request as _rq
            _rq.user = utente
            _rq.firm = None
            gen, brief_id, e = web._genio_prepare(caso.id, "Analizë e thellë: si e fitojmë?" if giur == "AL"
                                                  else "Analisi approfondita: come vinciamo?")
            if e is not None:
                raise RuntimeError(f"genio_prepare: {e}")
            blocco = (storage.get_genio_brief(brief_id) or {}).get("case_block") or ""
            open(f"/out/{nome}__case_block.txt", "w", encoding="utf-8").write(blocco)
        # come in produzione: il generatore gira FUORI dalla richiesta (thread del lavoro)
        risultato = {}

        def _corri():
            brain.set_request_jurisdiction(giur)
            for frame in gen():
                try:
                    evt = json.loads(frame.split("data: ", 1)[1])
                except Exception:  # noqa: BLE001
                    continue
                if evt.get("type") == "perspective":
                    r = evt["result"]
                    lenti[r["key"]] = r
                elif evt.get("type") == "done":
                    risultato["status"] = evt.get("status")
        th = threading.Thread(target=_corri)
        th.start()
        th.join()
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    sec = time.time() - t0
    idx = web._INDEX_IT if giur == "IT" else web._INDEX
    print(f"===== {nome} [{giur}] — {sec:.0f} s {('ERRORE ' + err) if err else ''} blocco del caso {len(blocco)} chr, "
          f"articoli del corpus nel blocco: {'sì' if ('NENET E KORPUSIT' in blocco or 'ARTICOLI DEL CORPUS' in blocco) else 'no'}")
    tot = collections.Counter()
    for k, r in sorted(lenti.items()):
        raw = r.get("raw") or ""
        open(f"/out/{nome}__{k.replace(':', '_')}.txt", "w", encoding="utf-8").write(raw)
        st = collections.Counter(it.get("status") for it in cv.verify_text(raw, idx).get("items", [])) if raw else collections.Counter()
        tot.update(st)
        estraneo = sum(raw.count(w) for w in (_ALB if giur == "IT" else _ITA))
        cit = (r.get("citations") or {})
        print(f"   {k:16s} {r.get('kind'):5s} {int((r.get('ms') or 0) / 1000):5d} s {len(raw):6d} chr  citazioni {dict(st)}"
              f"  lingua/diritto estraneo={estraneo}  {('verifica del server ' + json.dumps(cit, ensure_ascii=False)) if cit else ''}"
              f"  {(r.get('error') or '')[:90]}")
    print(f"   TOTALE citazioni {dict(tot)}")
    riepilogo.append((nome, int(sec), dict(tot), sum(1 for r in lenti.values() if r.get("kind") == "error")))

try:
    con = sqlite3.connect(os.environ.get("APP_DB_PATH", "/tqa/app.db"))
    cols = {r[1] for r in con.execute("PRAGMA table_info(ai_audit_log)")}
    sel = [c for c in ("callsite", "model", "latency_ms", "context_tokens", "cost_micro_usd", "error_class") if c in cols]
    print("\n-- registro delle chiamate (dopo l'inizio)")
    for r in con.execute(f"SELECT {', '.join(sel)} FROM ai_audit_log WHERE timestamp >= ? ORDER BY id", (t_inizio,)):
        print("  ", dict(zip(sel, r)))
except Exception as e:  # noqa: BLE001
    print("registro non letto:", e)
print("\nRIEPILOGO", riepilogo)
