# -*- coding: utf-8 -*-
"""CONTROLLO GENERALE in sessione IT — v2.

Rispetto alla v1: endpoint corretti (investigation-plan, second-opinion con
question+answer), act-check valutato per quello che e' (un verificatore di
citazioni, non un generatore di testo) e 4 strumenti in piu' che coprono le
vie rimaste scoperte (notaio bozza/procura/checklist, intake).

Per ogni strumento: quanto albanese, quanti riferimenti al diritto ITALIANO,
quanti al diritto ALBANESE (errore grave)."""
import json, os, re, sys, time, urllib.request, http.cookiejar

BASE = "http://127.0.0.1:5050"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(path, payload, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


post("/api/login", {"username": "admin.it", "password": "AdminIT2026!", "lang": "it"})
case = post("/api/cases", {"title": "Audit strumenti IT v2"})
CID = case["id"]
print(f"caso {CID[:8]} giurisdizione={case.get('jurisdiction')}\n", flush=True)

AL_LANG = re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|nenit|neni|rastin|"
                     r"gjykata|pala|provat|afati|kërkesë|vendim|shqip)\b", re.I)
AL_LAW = re.compile(r"\bKodi\b|\bKodit\b|\bKodin\b|shqiptar|Shqipëris|\bKPC\b|"
                    r"\bKPP\b|Kushtetuta e Republikës", re.I)
IT_LAW = re.compile(r"\bc\.c\.|\bc\.p\.c\.|\bc\.p\.p\.|\bC\.d\.S\.|codice civile|"
                    r"codice penale|art\.\s*\d|d\.lgs|legge\s+\d", re.I)

ANSWER_IT = ("Il credito derivante dal contratto di appalto e' liquido ed esigibile; "
             "si puo' quindi chiedere decreto ingiuntivo ex art. 633 c.p.c., con "
             "provvisoria esecuzione ex art. 642 c.p.c. se ricorrono i presupposti.")

# Visura ipotecaria realistica con la TRAPPOLA italiana speculare al caso Neni 195:
# un'ipoteca (condiziona, non blocca) + un pignoramento su una quota (blocca).
VISURA_IT = """AGENZIA DELLE ENTRATE - SERVIZIO DI PUBBLICITA' IMMOBILIARE DI MILANO 1
ISPEZIONE IPOTECARIA - ELENCO SINTETICO DELLE FORMALITA'
Immobile: Comune di Milano, Foglio 5, Particella 120, Subalterno 3 - Categoria A/2, vani 5,5, via Verdi 10, piano 2.
Intestatari (visura catastale): ROSSI MARIO, nato a Milano il 12/03/1970, C.F. RSSMRA70C12F205X - proprieta' per 1/2;
BIANCHI ANNA, nata a Monza il 05/07/1972, C.F. BNCNNA72L45F704Y - proprieta' per 1/2.
Atto di provenienza: compravendita Notaio Verdi rep. 4521 del 10/05/2015, TRASCRITTA il 15/05/2015 R.G. 30211 R.P. 20105 (a favore Rossi/Bianchi, contro Neri Giuseppe).

FORMALITA':
1) ISCRIZIONE del 20/05/2015 R.G. 30890 R.P. 5120 - IPOTECA VOLONTARIA derivante da concessione a garanzia di mutuo fondiario, notaio Verdi rep. 4522 del 10/05/2015; a favore INTESA SANPAOLO S.P.A. (C.F. 00799960158); contro ROSSI MARIO, BIANCHI ANNA; capitale euro 180.000, totale euro 360.000; durata 25 anni.
2) TRASCRIZIONE del 03/02/2026 R.G. 6021 R.P. 4110 - ATTO ESECUTIVO O CAUTELARE: VERBALE DI PIGNORAMENTO IMMOBILI, Tribunale di Milano, Ufficiale Giudiziario, rep. 1187 del 28/01/2026; a favore ALFA COSTRUZIONI S.R.L. (C.F. 05566778899); contro ROSSI MARIO per la quota di 1/2; importo precetto euro 42.500.

Planimetria catastale: presente, ultimo aggiornamento 2015. Nessuna annotazione di cancellazione.
Data ispezione: 14/09/2026."""

TESTS = [
    ("Avvocato — risposta principale", "/api/ask",
     {"case_id": CID, "message": "Licenziamento disciplinare senza contestazione scritta preventiva, azienda con 40 dipendenti: quali tutele ha il lavoratore e quali termini?"},
     ["text", "action_plan", "evidence_map", "urgency_scan", "nullity_radar", "premortem", "missing_facts", "timeline"]),
    ("Procuratore — analisi", "/api/prosecutor/analyze",
     {"facts": "Un imprenditore ha emesso fatture per operazioni inesistenti per 200.000 euro; la Guardia di Finanza ha sequestrato la documentazione."},
     ["markdown"]),
    ("Procuratore — piano indagine", "/api/prosecutor/investigation-plan",
     {"facts": "Denuncia per truffa aggravata: la vittima ha versato 50.000 euro per un investimento inesistente."},
     ["markdown"]),
    ("Notaio — controllo atto", "/api/notary/check",
     {"text": "CONTRATTO DI COMPRAVENDITA. Il signor Mario Rossi vende a Luigi Bianchi l'immobile sito in Milano, via Roma 1, al prezzo di 200.000 euro. Le parti dichiarano che l'immobile e libero da ipoteche. Il pagamento avverra in contanti alla firma."},
     ["markdown"]),
    ("Notaio — successione", "/api/notary/succession",
     {"situation": "Il defunto lascia il coniuge e due figli; i genitori sono in vita; patrimonio: appartamento e conto corrente."},
     ["markdown"]),
    ("Notaio — bozza atto", "/api/notary/draft",
     {"deed_type": "shitje_pasurie", "details": "Vendita di appartamento a Milano, via Verdi 10, foglio 5 particella 120 sub 3, prezzo 250.000 euro, pagamento con bonifico alla stipula; venditore Mario Rossi, acquirente Luigi Bianchi."},
     ["markdown"]),
    ("Notaio — procura", "/api/notary/prokura",
     {"form": "e_posacme", "details": "Procura speciale per vendere un immobile sito in Roma per conto del mandante.", "duration": "12 mesi"},
     ["markdown"]),
    ("Notaio — checklist documenti", "/api/notary/checklist",
     # serve anche l'elenco dei documenti gia' raccolti (>= 20 caratteri)
     {"act": "compravendita immobiliare",
      "text": ("Documenti gia' raccolti dalle parti: visura catastale aggiornata "
               "dell'immobile, atto di provenienza (donazione del 2011), attestato "
               "di prestazione energetica, documenti di identita' e codici fiscali "
               "di venditore e acquirente, planimetria catastale.")},
     ["markdown", "completeness"]),
    ("Perizia (Modelli)", "/api/expertise/analyze",
     {"case_type": "aksident_rrugor", "facts": "Incidente stradale: il mio cliente e stato tamponato a un semaforo, ha riportato lesioni al collo e l'auto e danneggiata."},
     ["markdown"]),
    ("Avvocato del Diavolo", "/api/devil-consult",
     {"situation": "Il cliente ha firmato una fideiussione omnibus a favore della banca; ora la banca escute. Come lo difendiamo?"},
     ["markdown", "text"]),
    ("Secondo parere (Fable)", "/api/second-opinion",
     {"question": "Posso agire per decreto ingiuntivo sul credito da appalto?",
      "answer": ANSWER_IT},
     ["markdown"]),
    ("Intake — triage", "/api/intake/triage",
     {"story": "Ho comprato un'auto usata da un concessionario, dopo due settimane il motore si e' rotto e il venditore non risponde alle mie richieste di riparazione."},
     ["markdown", "text", "summary", "area", "questions"]),
    ("Motore scadenze", "/api/afati/compute",
     {"trigger": "vendim_civil", "event_date": "2026-08-01", "facts": "Sentenza di primo grado notificata al cliente."},
     ["markdown"]),
    # ── v3 (v9.312): gli strumenti nuovi del notaio (v9.301-9.306), mai misurati in IT ──
    ("Notaio — verifica proprietà (visura)", "/api/notary/verify-property",
     {"certificate": VISURA_IT,
      "transaction": ("Rossi e Bianchi vogliono vendere l'intero appartamento a un terzo acquirente: "
                      "il notaio può stipulare? Se no, come si cancellano le formalità?")},
     ["markdown"]),
    ("Notaio — adempimenti post-atto", "/api/notary/post-deed",
     {"act": ("Compravendita di appartamento a Milano, via Verdi 10, foglio 5 particella 120 sub 3, "
              "prezzo 250.000 euro, stipulata oggi davanti al notaio."),
      "act_date": "2026-09-14"},
     ["markdown"]),
    ("Notaio — verifica soggetto", "/api/notary/verify-subject",
     {"subject": ("Visura camerale: ROSSI COSTRUZIONI S.R.L., P.IVA 01234567890, sede legale Milano via Roma 1; "
                  "stato attivita': ATTIVA; amministratore unico: Mario Rossi (nato 1970), poteri di ordinaria e "
                  "straordinaria amministrazione; soci: Mario Rossi 60%, Luigi Bianchi 40%; capitale sociale "
                  "10.000 euro i.v.; nessuna procedura concorsuale in corso."),
      "context": "La societa' vende un capannone industriale a un terzo per 800.000 euro."},
     ["markdown"]),
    ("Notaio — antiriciclaggio", "/api/notary/aml-check",
     {"situation": ("Acquirente: persona politicamente esposta straniera; propone il pagamento di 300.000 euro "
                    "in contanti; l'immobile verrebbe intestato a una societa' con sede alle Isole Cayman.")},
     ["markdown"]),
    # la pipeline COMPLETA su un caso immobiliare: dottrina IT nel compose, domande di
    # chiarimento (non devono chiedere la natura delle formalità: è scritta), Giudice finale
    ("Avvocato — immobile con formalità (pipeline)", "/api/ask",
     {"case_id": CID,
      "message": ("Il mio cliente vuole comprare questo appartamento: il notaio può stipulare con queste "
                  "formalità? Se no, come si cancellano? Controlla la visura qui sotto.\n\n" + VISURA_IT)},
     ["text", "action_plan", "nullity_radar", "premortem", "missing_facts"]),
]

# filtro opzionale: `python3 audit_tools_it.py notaio` esegue solo i test col nome;
# `python3 audit_tools_it.py -notaio` esegue tutto TRANNE quelli (esclusione).
ONLY = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
if ONLY.startswith("-") and ONLY[1:]:
    TESTS = [t for t in TESTS if ONLY[1:] not in t[0].lower()]
elif ONLY:
    TESTS = [t for t in TESTS if ONLY in t[0].lower()]

# gli output integrali si salvano qui: i numeri dicono «quanto», il testo dice «cosa»
OUT_DIR = "/tmp/audit_it"
os.makedirs(OUT_DIR, exist_ok=True)

rows = []
for name, path, payload, keys in TESTS:
    t0 = time.time()
    try:
        d = post(path, payload)
        blob = ""
        for k in keys:
            v = d.get(k)
            if isinstance(v, str):
                blob += "\n" + v
            elif v:
                blob += "\n" + json.dumps(v, ensure_ascii=False)
        if not blob.strip():
            rows.append((name, "VUOTO", 0, 0, 0, time.time() - t0, str(d)[:130]))
            print(f"  {name:34s} VUOTO  ({str(d)[:80]})", flush=True)
            continue
        try:
            with open(os.path.join(OUT_DIR, re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".txt"),
                      "w", encoding="utf-8") as _fh:
                _fh.write(blob)
        except Exception:  # noqa: BLE001 - il salvataggio non deve fermare l'audit
            pass
        al_hits = AL_LANG.findall(blob)
        al_l = len(al_hits)
        al_w = len(AL_LAW.findall(blob))
        it_w = len(IT_LAW.findall(blob))
        verdict = "OK" if (al_l <= 3 and al_w == 0) else ("DIRITTO AL!" if al_w else "ALBANESE")
        rows.append((name, verdict, al_l, al_w, it_w, time.time() - t0, blob[:150]))
        # QUALI token albanesi (con 12 caratteri di contesto): «ogni lettera» conta
        _tok = ""
        if al_l:
            _ctx = []
            for _m in list(AL_LANG.finditer(blob))[:4]:
                _ctx.append(blob[max(0, _m.start() - 12):_m.end() + 12].replace("\n", " "))
            _tok = "  «" + "» · «".join(_ctx) + "»"
        print(f"  {name:34s} {verdict:12s} albanese={al_l:>4} dirittoAL={al_w:>2} dirittoIT={it_w:>3}  ({time.time()-t0:.0f}s){_tok}", flush=True)
    except Exception as e:
        rows.append((name, "ERRORE", 0, 0, 0, time.time() - t0, str(e)[:150]))
        print(f"  {name:34s} ERRORE: {type(e).__name__}: {str(e)[:90]}", flush=True)

# ── verificatore di citazioni: non genera testo, si valuta diversamente ──
print("", flush=True)
try:
    d = post("/api/act-check", {"text": "Con il presente atto si chiede la risoluzione "
             "del contratto ex art. 1453 c.c. e il risarcimento ex art. 1223 c.c., "
             "oltre agli interessi ex art. 1224 c.c."})
    ok = (d.get("verified", 0) >= 3 and not d.get("fake") and not d.get("repealed"))
    rows.append(("Verifica citazioni (act-check)", "OK" if ok else "PROBLEMA",
                 0, 0, d.get("verified", 0), 0, json.dumps(d, ensure_ascii=False)[:130]))
    print(f"  {'Verifica citazioni (act-check)':34s} {'OK' if ok else 'PROBLEMA':12s} "
          f"articoli IT verificati={d.get('verified')}/{d.get('total')} inesistenti={len(d.get('fake') or [])}", flush=True)
except Exception as e:
    rows.append(("Verifica citazioni (act-check)", "ERRORE", 0, 0, 0, 0, str(e)[:130]))
    print(f"  Verifica citazioni (act-check)     ERRORE: {e}", flush=True)

print("\n" + "=" * 78)
print("RIEPILOGO")
print("=" * 78)
bad = [r for r in rows if r[1] != "OK"]
for name, verdict, al_l, al_w, it_w, dt, sample in rows:
    print(f"  {verdict:12s} {name}")
    if verdict != "OK":
        print(f"               campione: {sample[:130]}")
print(f"\n{len(rows)-len(bad)}/{len(rows)} strumenti corretti")
