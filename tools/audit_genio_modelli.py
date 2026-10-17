# v9.648 — uso: bash tools/prova_pro.sh <nome> tools/audit_genio_modelli.py [immagine] [cartella_src]  (risultati in /tmp/pp_<nome>/out)
# MISURA DELLE COMBINAZIONI DI MODELLI del «Genio Legale» col cervello vero (dati inventati), per la STESSA strada della rotta
# (`web._genio_prepare` → il generatore nel thread del lavoro, come `audit_genio.py`), una combinazione alla volta (mai due Geni
# insieme) nello stesso processo: `genio._kw_lente` legge l'env a ogni chiamata. Per ogni combinazione e caso: tempo, lenti in
# errore, citazioni verificate/inesistenti/senza codice (la verifica del server su ogni lente), le norme decisive del caso trovate,
# contesto e costo dal registro. SELEZIONE = le combinazioni da misurare (si cambia con sed prima di lanciare).
import sys, os, time, json, threading, collections, sqlite3, re
sys.path.insert(0, "/app")
from src import web, brain, storage

web._ensure_loaded()
_TL = threading.local()
web._active_jurisdiction = lambda u: getattr(_TL, "giur", "AL")

SELEZIONE = ["predefinito"]
CASI_SCELTI = ["pushim_al", "licenziamento_it"]

_TROVA = ("DECISION_TREE", "BRUTAL_TRUTH", "VOICE")          # le lenti che non devono «trovare» norme
COMBO = {
    "opus5max": {"GENIO_MODEL": "opus"},   # dalla v9.648 il Genio senza env è «misto_opus55»: Opus 5 max va chiesto
    "predefinito": {},                       # la combinazione di GENIO_PREDEFINITO (genio.py)
    "fable51max": {"GENIO_MODEL": "fable", "GENIO_EFFORT": "max"},
    "fable51high": {"GENIO_MODEL": "fable", "GENIO_EFFORT": "high"},
    "opus55high": {"GENIO_MODEL": "opus55", "GENIO_EFFORT": "high"},
    "opus55max": {"GENIO_MODEL": "opus55", "GENIO_EFFORT": "max"},
    "sonnet55high": {"GENIO_MODEL": "sonnet", "GENIO_EFFORT": "high"},
    # le tre lenti che trovano le norme sul senior, le tre di stima e di stile su Sonnet 5.5
    "misto": {"GENIO_MODEL": "opus",
              **{f"GENIO_MODEL_{k}": "sonnet" for k in _TROVA}, **{f"GENIO_EFFORT_{k}": "high" for k in _TROVA}},
    "misto_fable": {"GENIO_MODEL": "fable", "GENIO_EFFORT": "max",
                    **{f"GENIO_MODEL_{k}": "sonnet" for k in _TROVA}, **{f"GENIO_EFFORT_{k}": "high" for k in _TROVA}},
    "misto_opus55": {"GENIO_MODEL": "opus55", "GENIO_EFFORT": "high",
                     **{f"GENIO_MODEL_{k}": "sonnet" for k in _TROVA}, **{f"GENIO_EFFORT_{k}": "high" for k in _TROVA}},
}

CASI = {
    "apartament_al": ("AL", "Apartamenti me lagështirë — Gent Shembulli", (
        "Klienti ynë Gent Shembulli bleu më 10.3.2026, me kontratë noteriale, një apartament 86 m² në Tiranë nga shoqëria ndërtuese "
        "«Ndërtimi Shembull» sh.p.k. për 85.000 euro, të paguara me transfertë bankare. Në shtator 2026 zbuloi lagështirë të rëndë në "
        "muret e jashtme; raporti i një eksperti privat (25.9.2026) thotë se është defekt ndërtimi i izolimit të fasadës. Matja e "
        "ekspertit jep 78 m². Klienti i dërgoi shoqërisë dy mesazhe WhatsApp (28.9 dhe 5.10) pa përgjigje. Duam padi për ulje çmimi "
        "dhe dëmshpërblim. Si e fitojmë?"),
        # le norme decisive: i vizi dell'IMMOBILE (5 anni, non i 10 giorni del KC 717 che sta sotto i mobili), la superficie minore
        # (752, 755: due anni), il venditore che sapeva (718)
        {"KC 756": r"\b756\b", "KC 752": r"\b752\b", "KC 755": r"\b755\b", "KC 718": r"\b718\b"}),
    "pushim_al": ("AL", "Pushimi me gojë — Luan Shembulli", (
        "Klienti ynë Luan Shembulli punoi si shofer te «Transport Shembull» sh.p.k. nga 1.3.2019 me kontratë me afat të pacaktuar, "
        "pagë 80.000 lekë. Më 2.10.2026 administratori i tha me gojë «mos eja më nesër», pa asnjë letër e pa takim paraprak; nuk i ka "
        "paguar pagën e shtatorit. Shoqëria pretendon se punëtori braktisi punën më 3.10.2026. Si e fitojmë?"),
        # la risoluzione immediata ingiustificata (155), il termine della causa (146: 180 giorni), il premio di anzianità (145),
        # il preavviso (143)
        {"KP 155": r"\b155\b", "KP 146": r"\b146\b", "KP 145": r"\b145\b", "KP 143": r"\b143\b"}),
    "licenziamento_it": ("IT", "Licenziamento orale — Mario Prova", (
        "Il nostro cliente Mario Prova, autista assunto a tempo indeterminato nel 2019 da «Trasporti Esempio» s.r.l. (40 dipendenti), "
        "è stato licenziato oralmente il 2.10.2026 («non venire più domani»), senza lettera. La retribuzione di settembre non è stata "
        "pagata. La società sostiene che il lavoratore si è dimesso. Vogliamo la nullità del licenziamento orale, la reintegrazione e "
        "le retribuzioni. Come vinciamo?"),
        {"L. 604/1966 art. 2": r"(?:art\.?\s*2\b[^.\n]{0,40}604|604[^.\n]{0,25}art\.?\s*2\b)",
         "d.lgs. 23/2015 art. 2": r"(?:art\.?\s*2\b[^.\n]{0,40}23/2015|23/2015[^.\n]{0,25}art\.?\s*2\b)",
         "dimissioni telematiche": r"dimission\w*[^.\n]{0,80}telematic|telematic\w*[^.\n]{0,80}dimission",
         "c.p.c. 441-bis / rito": r"441[- ]bis|414\s*c\.p\.c"}),
}


def corri(combo: str, nome: str, utente) -> dict:
    for k in list(os.environ):
        if k.startswith("GENIO_MODEL") or k.startswith("GENIO_EFFORT"):
            del os.environ[k]
    os.environ.update(COMBO[combo])
    giur, titolo, fatti, attese = CASI[nome]
    _TL.giur = giur
    brain.set_request_jurisdiction(giur)
    caso = storage.create_case(utente.id, f"{titolo} [{combo}]", jurisdiction=giur)
    storage.add_message(caso.id, "user", fatti)
    t_avvio = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    t0 = time.time()
    lenti: dict = {}
    err = None
    blocco = ""
    try:
        with web.app.test_request_context("/api/audit", method="POST"):
            from flask import request as _rq
            _rq.user = utente
            _rq.firm = None
            gen, brief_id, e = web._genio_prepare(caso.id, "Analizë e thellë: si e fitojmë?" if giur == "AL"
                                                  else "Analisi approfondita: come vinciamo?")
            if e is not None:
                raise RuntimeError(f"genio_prepare: {e}")

        def _gira():
            brain.set_request_jurisdiction(giur)
            for frame in gen():
                try:
                    evt = json.loads(frame.split("data: ", 1)[1])
                except Exception:  # noqa: BLE001
                    continue
                if evt.get("type") == "perspective":
                    lenti[evt["result"]["key"]] = evt["result"]
        th = threading.Thread(target=_gira)
        th.start()
        th.join()
        blocco = (storage.get_genio_brief(brief_id) or {}).get("case_block") or ""
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    sec = time.time() - t0
    testo = "\n".join((r.get("raw") or "") + " " + json.dumps(r.get("parsed") or {}, ensure_ascii=False) for r in lenti.values())
    trovate = {k: bool(re.search(rx, testo, re.I)) for k, rx in attese.items()}
    # la lingua della sessione: parole albanesi in un fascicolo italiano (e viceversa) nei testi del modello
    _estr = ((" të ", " dhe ", " është ", " për ", "neni ", "Kodi ") if giur == "IT" else (" il ", " della ", " che ", " art. ", " c.c."))
    estraneo = sum(testo.count(w) for w in _estr)
    cit = collections.Counter()
    for r in lenti.values():
        for k, v in (r.get("citations") or {}).items():
            cit[k] += int(v or 0)
    per_lente = {k: (r.get("kind"), int((r.get("ms") or 0) / 1000), len(r.get("raw") or "")) for k, r in sorted(lenti.items())}
    for k, r in lenti.items():
        open(f"/out/{combo}__{nome}__{k.replace(':', '_')}.txt", "w", encoding="utf-8").write(
            (r.get("raw") or "") + "\n\n=== parsed (verificato) ===\n" + json.dumps(r.get("parsed") or {}, ensure_ascii=False, indent=1))
    reg = []
    try:
        con = sqlite3.connect(os.environ.get("APP_DB_PATH", "/tqa/app.db"))
        for r in con.execute("SELECT callsite, model, latency_ms, context_tokens, cost_micro_usd, error_class FROM ai_audit_log "
                             "WHERE timestamp >= ? AND callsite LIKE 'genio:%' ORDER BY id", (t_avvio,)):
            reg.append(r)
    except Exception as e2:  # noqa: BLE001
        reg = [("registro non letto", str(e2))]
    tok = sum(int(r[3] or 0) for r in reg if len(r) > 3)
    costo = sum(int(r[4] or 0) for r in reg if len(r) > 4) / 1e6
    modelli = sorted({str(r[1]) for r in reg if len(r) > 1})
    errori = sum(1 for r in lenti.values() if r.get("kind") == "error")
    print(f"===== {combo} · {nome} [{giur}] — {sec:.0f} s · lenti in errore {errori} · nene nel blocco "
          f"{'sì' if ('NENET E KORPUSIT' in blocco or 'ARTICOLI DEL CORPUS' in blocco) else 'NO'} · modelli {modelli} "
          f"{('ERRORE ' + err) if err else ''}", flush=True)
    print(f"   norme decisive {sum(trovate.values())}/{len(trovate)} {trovate} · lingua estranea {estraneo}", flush=True)
    print(f"   citazioni (verifica del server) {dict(cit)} · contesto {tok:,} token · costo {costo:.2f} $", flush=True)
    print(f"   lenti {per_lente}", flush=True)
    return {"combo": combo, "caso": nome, "sec": int(sec), "errori": errori, "trovate": sum(trovate.values()),
            "attese": len(trovate), "cit": dict(cit), "tok": tok, "costo": round(costo, 2)}


utente = storage.create_user(f"audit.genio.modelli.{int(time.time())}@superavokati.test", "x", profession="avokat")
riep = []
for combo in SELEZIONE:
    for nome in CASI_SCELTI:
        riep.append(corri(combo, nome, utente))
print("\nRIEPILOGO")
for r in riep:
    print("  ", json.dumps(r, ensure_ascii=False))
