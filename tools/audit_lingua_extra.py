# -*- coding: utf-8 -*-
"""LINGUA = SESSIONE sugli strumenti «di contorno» (v9.399).

Gli audit `audit_tools_it.py` / `audit_tools_al.py` coprono i 28 strumenti del cervello;
restano fuori quelli che scrivono per il CLIENTE o per lo studio e che avevano un prompt
solo albanese: lettere automatiche, notizia di stato al cliente, traduzione del gergo,
revisione contratto, agente proattivo, assistente d'udienza, prove d'udienza (giudice /
controparte / coach), mappa delle pretese, stima degli onorari, simulazione dell'accordo.

Per ogni strumento conta le parole dell'ALTRA lingua (e, in sessione IT, i riferimenti al
diritto albanese). Uso (dentro il container):
    python3 tools/audit_lingua_extra.py IT          # admin.it
    python3 tools/audit_lingua_extra.py AL          # account di prova con tutti i moduli
Uscita 1 se almeno uno strumento mescola le lingue. Gli output integrali vanno in
/tmp/audit_lingua/<sessione>_<strumento>.txt."""
import atexit, json, os, re, sys, time, urllib.request, http.cookiejar

sys.path.insert(0, "/app")
SESS = (sys.argv[1] if len(sys.argv) > 1 else "IT").upper()
SOLO = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
BASE = "http://127.0.0.1:5050"
OUT = "/tmp/audit_lingua"
os.makedirs(OUT, exist_ok=True)
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, payload=None, method="POST", timeout=900, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


if SESS == "IT":
    call("/api/login", {"username": "admin.it", "password": "AdminIT2026!", "lang": "it"})
    call("/api/session/jurisdiction", {"jurisdiction": "IT"})
    case = call("/api/cases", {"title": "Licenziamento del sig. Rossi — impugnazione (audit lingua)"})
else:
    _ts = int(time.time())
    EMAIL, CODE = f"audit-lingua-{_ts}@superavokati.test", f"Audit-{_ts}"
    atexit.register(lambda: __import__("src.storage", fromlist=["delete_user"]).delete_user(EMAIL))
    call("/api/provision-demo", {"email": EMAIL, "code": CODE, "hours": 6,
                                 "modules": ["avokat", "prokuror", "noter"]},
         headers={"X-Provision-Secret": os.environ.get("DEMO_PROVISION_SECRET", "")})
    call("/api/login", {"username": EMAIL, "password": CODE, "lang": "sq"})
    case = call("/api/cases", {"title": "Pushimi nga puna i z. Hoxha — padi (kontroll gjuhe)"})
CID = case["id"]
atexit.register(lambda: op.open(urllib.request.Request(BASE + f"/api/cases/{CID}", method="DELETE"),
                                timeout=30).read())
print(f"sessione {SESS} · fascicolo {CID[:8]} ({case.get('jurisdiction')})\n", flush=True)

IT = SESS == "IT"
try:
    call("/api/events", {"title": ("Udienza di discussione — Tribunale di Milano, sez. lavoro" if IT
                                   else "Seanca përgatitore — Gjykata e Tiranës"),
                         "kind": "seance", "starts_at": "2026-10-15T09:30:00", "case_id": CID})
except Exception as exc:  # noqa: BLE001
    print("evento non creato:", exc)

AL_LANG = re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|nenit|neni|rastin|gjykata|pala|provat|afati|"
                     r"kërkesë|vendim|shqip|mbështetur|pjesërisht|kontestuar|mungon|klienti|"
                     r"avokati|letër|pagesë)\b", re.I)
AL_LAW = re.compile(r"\bKodi\b|\bKodit\b|\bKPC\b|\bKPP\b|\bKC\b|shqiptar|Shqipëri|9887", re.I)
IT_LANG = re.compile(r"\b(il|della|delle|degli|dello|nella|nel|che|non|sono|essere|articolo|comma|"
                     r"sentenza|tribunale|avvocato|pertanto|quindi|anche|termine|ricorso|cliente|"
                     r"diritto|udienza|lettera)\b", re.I)
IT_LAW = re.compile(r"\bc\.c\.|\bc\.p\.c\.|\bc\.p\.p\.|codice civile|codice del consumo|d\.lgs|"
                    r"\bGDPR\b.*2016/679|Statuto dei lavoratori", re.I)

CONTRACT_IT = """CONTRATTO DI LOCAZIONE AD USO COMMERCIALE
Tra ALFA S.R.L. (locatore) e il sig. Mario Rossi, titolare della ditta individuale Rossi Bar (conduttore).
Art. 1 - Oggetto: il locatore concede in locazione il locale sito in Milano, via Roma 12, per uso bar.
Art. 2 - Durata: sei anni dal 1° novembre 2026, rinnovabile.
Art. 3 - Canone: euro 2.500 mensili, da pagare entro il giorno 5 di ogni mese.
Art. 4 - Penale: in caso di ritardo nel pagamento anche di un solo giorno il conduttore pagherà una penale di euro 500 al giorno.
Art. 5 - Responsabilità: il locatore non risponde di alcun danno, anche se causato da suo dolo o colpa grave.
Art. 6 - Recesso: il locatore può recedere in qualsiasi momento senza preavviso.
Art. 7 - Dati personali: il conduttore autorizza il locatore a cedere i propri dati a terzi per finalità commerciali.
Art. 8 - Foro: per ogni controversia è competente in via esclusiva il Tribunale di Palermo.
Milano, 20 settembre 2026. Firme."""
CONTRACT_AL = """KONTRATË QIRAJE PËR QËLLIME TREGTARE
Ndërmjet ALFA SH.P.K. (qiradhënës) dhe z. Arben Hoxha, person fizik tregtar «Bar Hoxha» (qiramarrës).
Neni 1 - Objekti: qiradhënësi i jep me qira ambientin në Tiranë, rruga e Durrësit 12, për bar.
Neni 2 - Afati: gjashtë vjet nga 1 nëntori 2026.
Neni 3 - Qiraja: 2.500 euro në muaj, e paguar deri më 5 të çdo muaji.
Neni 4 - Kamatëvonesa: për çdo ditë vonesë qiramarrësi paguan 500 euro në ditë.
Neni 5 - Përgjegjësia: qiradhënësi nuk përgjigjet për asnjë dëm, edhe kur shkaktohet me dashje.
Neni 6 - Zgjidhja: qiradhënësi mund ta zgjidhë kontratën në çdo kohë pa njoftim.
Neni 7 - Të dhënat personale: qiramarrësi lejon qiradhënësin t'ua japë të dhënat e tij palëve të treta për qëllime tregtare.
Neni 8 - Gjykata: për çdo mosmarrëveshje është kompetente vetëm Gjykata e Shkodrës.
Tiranë, 20 shtator 2026. Nënshkrimet."""

JARGON_IT = ("Il ricorso ex art. 414 c.p.c. è stato depositato e notificato; il giudice del lavoro ha fissato "
             "l'udienza di discussione ex art. 420 c.p.c., nella quale si procederà al tentativo di conciliazione "
             "e all'interrogatorio libero delle parti; la controparte dovrà costituirsi almeno dieci giorni prima "
             "con memoria difensiva, a pena di decadenza dalle eccezioni non rilevabili d'ufficio.")
JARGON_AL = ("Padia sipas nenit 154 të Kodit të Procedurës Civile u depozitua dhe iu njoftua palës së paditur; "
             "gjykata caktoi seancën përgatitore, ku do të tentohet pajtimi i palëve dhe do të vendoset për "
             "kërkesat për prova; e paditura duhet të paraqesë përgjigjen ndaj padisë brenda afatit, përndryshe "
             "humbet të drejtën e prapësimeve procedurale.")
ARG_IT = ("Signor giudice, il licenziamento del mio assistito è nullo perché è stato intimato oralmente, senza la "
          "forma scritta richiesta dall'art. 2 della legge 604/1966; chiediamo la reintegrazione e il risarcimento.")
ARG_AL = ("I nderuar gjyqtar, pushimi nga puna i klientit tim është i pavlefshëm sepse u bë me gojë, pa formën e "
          "shkruar që kërkon Kodi i Punës; kërkojmë rikthimin në punë dhe shpërblimin e dëmit.")

TESTS = [
    ("lettera_cliente", lambda: call(f"/api/cases/{CID}/letters", {
        "kind": "client_followup", "recipient": "Mario Rossi" if IT else "Arben Hoxha",
        "context": ("Aggiornalo: udienza fissata il 15 ottobre, serve la copia della lettera di licenziamento."
                    if IT else "Informoje: seanca është më 15 tetor, na duhet kopja e njoftimit të pushimit.")}),
     lambda r: r.get("body_md", "") + "\n" + r.get("kind_label", "")),
    ("lettera_pagamento", lambda: call(f"/api/cases/{CID}/letters", {
        "kind": "payment_reminder", "recipient": "Mario Rossi" if IT else "Arben Hoxha",
        "context": ("Fattura n. 12/2026 di euro 1.200, scaduta il 30 settembre." if IT
                    else "Fatura nr. 12/2026 prej 1.200 euro, e skaduar më 30 shtator.")}),
     lambda r: r.get("body_md", "") + "\n" + r.get("kind_label", "")),
    ("gergo_cliente", lambda: call(f"/api/cases/{CID}/translate-jargon",
                                   {"source_text": JARGON_IT if IT else JARGON_AL}),
     lambda r: r.get("plain_sq", "")),
    ("stato_cliente", lambda: call(f"/api/cases/{CID}/auto-status", {}),
     lambda r: r.get("body_sq", "")),
    ("revisione_contratto", lambda: call(f"/api/cases/{CID}/contract-review", {
        "contract_text": CONTRACT_IT if IT else CONTRACT_AL, "contract_label": "Locazione" if IT else "Qira"}),
     lambda r: json.dumps(r.get("result", {}), ensure_ascii=False)),
    ("agente", lambda: call(f"/api/cases/{CID}/agent/scan", {}),
     lambda r: json.dumps(r.get("suggestions", []), ensure_ascii=False)),
    ("udienza_rapida", lambda: call(f"/api/cases/{CID}/hearing/quick", {
        "question": ("Il giudice mi chiede se il licenziamento orale è impugnabile oltre i 60 giorni: cosa rispondo?"
                     if IT else "Gjyqtari më pyet nëse pushimi me gojë ankimohet pas 30 ditëve: çfarë i them?")}),
     lambda r: (r.get("reply") or {}).get("body_sq", "")),
    ("prova_giudice", lambda: call("/api/rehearsal", {"mode": "judge", "user_text": ARG_IT if IT else ARG_AL,
                                                      "case_id": CID}),
     lambda r: r.get("reply", "")),
    ("prova_controparte", lambda: call("/api/rehearsal", {"mode": "opposing", "user_text": ARG_IT if IT else ARG_AL,
                                                          "case_id": CID}),
     lambda r: r.get("reply", "")),
    ("prova_coach", lambda: call("/api/rehearsal", {"mode": "coach", "user_text": ARG_IT if IT else ARG_AL,
                                                    "case_id": CID}),
     lambda r: r.get("reply", "")),
    ("mappa_pretese", lambda: call("/api/claim-chart", {"facts": ARG_IT if IT else ARG_AL, "case_id": CID}),
     lambda r: r.get("markdown", "")),
    # (la stima degli onorari /fee-estimate non ha un pannello nell'interfaccia: fuori dalla misura)
    ("simulazione_accordo", lambda: call(f"/api/cases/{CID}/settlement-simulation", {
        "description": ARG_IT if IT else ARG_AL, "valore_in_causa_eur": 30000, "plaintiff": True, "samples": 2000}),
     lambda r: json.dumps({k: r.get(k) for k in ("scenarios", "recommendation")}, ensure_ascii=False)),
]

_SKIP_K = {"id", "case_id", "kind", "level", "status", "name", "created_at", "updated_at", "url", "source_url",
           "court_code", "code", "severity", "verdict", "decl_type", "outcome", "resolved_by", "tip", "number"}


def _valori(x):
    """Tutti i valori di testo di una risposta JSON (non le chiavi, non id/url/token)."""
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            if k in _SKIP_K or k in ("citations", "stats"):
                continue
            out += _valori(v)
    elif isinstance(x, list):
        for v in x:
            out += _valori(v)
    elif isinstance(x, str):
        out.append(x)
    return out


def _primo(path, chiave):
    try:
        d = call(path, method="GET")
        v = d.get(chiave) if isinstance(d, dict) else d
        if isinstance(v, dict):
            return next(iter(v))
        if isinstance(v, list) and v:
            return v[0].get("key") or v[0].get("id") or v[0].get("kind") if isinstance(v[0], dict) else v[0]
    except Exception as exc:  # noqa: BLE001
        print("elenco non letto:", path, exc)
    return None


FATTI_IT = ("Il mio cliente, Mario Rossi, ha prestato 20.000 euro al cognato nel marzo 2014 con bonifico "
            "e una scrittura privata; non ha mai sollecitato il pagamento. Il credito è prescritto?")
FATTI_AL = ("Klienti im, Arben Hoxha, i dha hua kunatit 20.000 euro në mars 2014 me transfertë bankare dhe "
            "një marrëveshje me shkrim; nuk ia ka kërkuar kurrë kthimin. A është parashkruar kërkesa?")
VISURA_IT = ("VISURA CAMERALE — ALFA S.R.L., C.F. 05566778899, sede in Milano, via Roma 1. Capitale sociale euro "
             "10.000 i.v. Soci: Mario Rossi 60%, Anna Bianchi 40%. Amministratore unico: Mario Rossi (dal 12/03/2020). "
             "Stato: attiva. Oggetto: commercio all'ingrosso di bevande.")
EKSTRAKT_AL = ("EKSTRAKT I THJESHTË — ALFA SH.P.K., NIPT L12345678A, selia Tiranë, rruga e Durrësit 1. Kapitali "
               "1.000.000 lekë. Ortakë: Arben Hoxha 60%, Mira Hoxha 40%. Administrator: Arben Hoxha (nga 12.03.2020). "
               "Statusi: Aktiv. Objekti: tregti me shumicë pijesh.")
ATTO_IT = ("ATTO DI COMPRAVENDITA. Il sig. Mario Rossi vende alla sig.ra Anna Bianchi l'appartamento in Milano, "
           "via Verdi 10, foglio 5, particella 120, sub. 3, per il prezzo di euro 250.000, pagato con bonifico.")
AKT_AL = ("KONTRATË SHITJEJE. Z. Arben Hoxha i shet znj. Mira Leka apartamentin në Tiranë, rruga e Kavajës 10, "
          "zona kadastrale 8150, nr. pasurie 12/45, për çmimin 120.000 euro, të paguar me transfertë bankare.")

TESTS += [
    ("prescrizione", lambda: call("/api/deadlines/prescription", {"facts": FATTI_IT if IT else FATTI_AL}),
     lambda r: "\n".join(_valori(r))),
    ("lettere_atti", lambda: call("/api/letters/draft", {
        "kind": _primo("/api/letters/kinds", "kinds") or "", "facts": FATTI_IT if IT else FATTI_AL, "case_id": CID}),
     lambda r: "\n".join(_valori(r))),
    ("controparte", lambda: call("/api/adversary", {"text": CONTRACT_IT if IT else CONTRACT_AL}),
     lambda r: "\n".join(_valori(r))),
    ("redazione", lambda: call("/api/fable-draft", {"kind": "contract", "brief": (
        "Contratto di comodato d'uso gratuito di un appartamento a Milano fra padre e figlio, durata 4 anni."
        if IT else "Kontratë huapërdorjeje falas e një apartamenti në Tiranë mes babait dhe djalit, për 4 vjet.")}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_dichiarazione", lambda: call("/api/notary/declaration", {
        "decl_type": _primo("/api/notary/declaration-types", "types") or "",
        "details": ("Mario Rossi dichiara di essere celibe e di risiedere a Milano, via Roma 1." if IT
                    else "Arben Hoxha deklaron se është beqar dhe banon në Tiranë, rruga e Durrësit 1.")}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_revoca", lambda: call("/api/notary/revocation", {"details": (
        "Mario Rossi revoca la procura generale conferita ad Anna Bianchi con atto del notaio Verdi, rep. 4521 del 10/05/2024."
        if IT else "Arben Hoxha revokon prokurën e përgjithshme që i dha Mira Lekës me aktin e noterit Dervishi, nr. 4521 rep., datë 10.05.2024.")}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_conflitti", lambda: call("/api/notary/conflicts", {"case_id": CID, "new_act": ATTO_IT if IT else AKT_AL}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_e_se", lambda: call("/api/notary/whatif", {"act": ATTO_IT if IT else AKT_AL, "change": (
        "E se il prezzo venisse pagato in contanti?" if IT else "Po sikur çmimi të paguhet me para në dorë?")}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_ispettore", lambda: call("/api/notary/inspect", {"case_id": CID, "text": ATTO_IT if IT else AKT_AL}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_estrazione", lambda: call("/api/notary/extract", {"case_id": CID, "text": ATTO_IT if IT else AKT_AL}),
     lambda r: "\n".join(_valori(r))),
    ("notaio_cliente", lambda: call("/api/notary/client", {
        "kind": _primo("/api/notary/client-kinds", "kinds") or "", "text": ATTO_IT if IT else AKT_AL}),
     lambda r: "\n".join(_valori(r))),
    ("bench_memo", lambda: call(f"/api/cases/{CID}/bench-memo", {"description": ARG_IT if IT else ARG_AL}),
     lambda r: "\n".join(_valori(r))),
    ("corporate", lambda: call(f"/api/cases/{CID}/corporate/extract", {
        "doc_name": "visura.txt" if IT else "ekstrakt.txt", "doc_text": VISURA_IT if IT else EKSTRAKT_AL,
        "doc_type": "visura camerale" if IT else "ekstrakt QKB"}),
     lambda r: "\n".join(_valori(r))),
]

esiti = []
for nome, fare, testo in TESTS:
    if SOLO and nome not in SOLO:
        continue
    t0 = time.time()
    try:
        r = fare()
        txt = testo(r) or ""
        err = r.get("error") if isinstance(r, dict) else None
    except Exception as exc:  # noqa: BLE001
        txt, err = "", str(exc)[:160]
    dt = time.time() - t0
    open(f"{OUT}/{SESS}_{nome}.txt", "w", encoding="utf-8").write(txt)
    if IT:
        spie = AL_LANG.findall(txt)
        legge_estera = AL_LAW.findall(txt)
    else:
        spie = IT_LANG.findall(txt)
        legge_estera = IT_LAW.findall(txt)
    ok = bool(txt.strip()) and not err and len(spie) == 0 and len(legge_estera) == 0
    esiti.append(ok)
    campioni = " · ".join(sorted(set(s if isinstance(s, str) else s[0] for s in spie))[:8])
    print(f"  {nome:22s} {'OK ' if ok else 'NO '} altra_lingua={len(spie):3d} legge_estera={len(legge_estera):2d} "
          f"chr={len(txt):5d} ({dt:4.0f}s){'  ERR ' + str(err) if err else ''}  {campioni}", flush=True)

print(f"\n== {sum(esiti)}/{len(esiti)} strumenti nella lingua della sessione ({SESS}) ==")
sys.exit(0 if all(esiti) else 1)
