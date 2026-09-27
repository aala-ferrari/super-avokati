# -*- coding: utf-8 -*-
"""CONTROLLO GENERALE in sessione AL (v9.395, collaudo prima del lancio) — il gemello di `audit_tools_it.py`.

Gli stessi strumenti chiamati in sessione albanese con input albanesi (un account di prova usa-e-getta, cancellato
all'uscita). Per ogni strumento: quante parole ITALIANE (lingua = sessione: in AL non deve comparirne nessuna), quanti
riferimenti al diritto ITALIANO (errore grave: diritto straniero come base), quanti al diritto ALBANESE (atteso).

    docker exec super-avvocato python3 -u tools/audit_tools_al.py [filtro | -esclusione]
"""
import atexit, json, os, re, sys, time, urllib.request, http.cookiejar

sys.path.insert(0, "/app")
BASE = "http://127.0.0.1:5050"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(path, payload, timeout=900, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers=h)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


_ts = int(time.time())
EMAIL, CODE = f"audit-al-{_ts}@superavokati.test", f"Audit-{_ts}"
atexit.register(lambda: __import__("src.storage", fromlist=["delete_user"]).delete_user(EMAIL))
post("/api/provision-demo", {"email": EMAIL, "code": CODE, "hours": 6},
     headers={"X-Provision-Secret": os.environ.get("DEMO_PROVISION_SECRET", "")})
post("/api/login", {"username": EMAIL, "password": CODE, "lang": "sq"})
case = post("/api/cases", {"title": "Kontroll i veglave AL"})
CID = case["id"]
print(f"rasti {CID[:8]} juridiksioni={case.get('jurisdiction')}\n", flush=True)

# parole italiane che in un testo albanese non hanno ragione di esserci (mai termini tecnici condivisi come «euro»)
IT_LANG = re.compile(r"\b(il|della|delle|degli|dello|nella|nel|che|non|sono|essere|articolo|comma|sentenza|tribunale|"
                     r"avvocato|pertanto|quindi|anche|termine|ricorso|cliente|diritto)\b", re.I)
IT_LAW = re.compile(r"\bc\.c\.|\bc\.p\.c\.|\bc\.p\.p\.|\bC\.d\.S\.|codice civile|codice penale|d\.lgs|\bd\.P\.R\.", re.I)
AL_LAW = re.compile(r"\bneni\b|\bnenit\b|\bKodi\b|\bKodit\b|\bligji\b|\bligjit\b", re.I)

KARTELA_AL = """REPUBLIKA E SHQIPËRISË — AGJENCIA SHTETËRORE E KADASTRËS — DREJTORIA VENDORE TIRANË
KARTELA E PASURISË — Zona kadastrale 8150, Nr. pasurie 12/45, Lloji: apartament, Sipërfaqja 85 m2, Kati 3.
RUBRIKA A (Pasuria): apartament 3+1, rruga e Kavajës nr. 10, Tiranë.
RUBRIKA B (Pronarët): Arben Hoxha, pjesa 1/2; Mira Hoxha, pjesa 1/2. Akti i fitimit: kontratë shitjeje nr. 4521 rep., datë 10.05.2015, regjistruar më 15.05.2015.
RUBRIKA C (Hipotekat): D-1 Hipotekë vullnetare në favor të Bankës Kombëtare Tregtare, regjistruar më 20.05.2015 nr. 5521, shuma 60.000 euro.
RUBRIKA D (Kufizimet): D-2 Sekuestro konservative e vendosur nga Gjykata e Rrethit Gjyqësor Tiranë, vendimi nr. 1234, datë 03.02.2026, mbi pjesën 1/2 të Arben Hoxhës, për një detyrim prej 42.500 euro.
Data e lëshimit: 14.09.2026."""

TESTS = [
    ("Avokat — përgjigja kryesore", "/api/ask",
     {"case_id": CID, "message": ("Punëdhënësi e pushoi klientin tim pa asnjë njoftim me shkrim pas 6 vitesh punë, duke pretenduar "
                                  "një shkelje disiplinore që nuk i është komunikuar kurrë. Çfarë të drejtash ka dhe brenda çfarë "
                                  "afati duhet të paditë?")},
     ["text", "action_plan", "evidence_map", "urgency_scan", "nullity_radar", "premortem", "missing_facts", "timeline"]),
    ("Prokuror — analiza", "/api/prosecutor/analyze",
     {"facts": "Një biznesmen ka lëshuar fatura fiktive për 20 milionë lekë; policia ka sekuestruar dokumentacionin kontabël."},
     ["markdown"]),
    ("Prokuror — plani i hetimit", "/api/prosecutor/investigation-plan",
     {"facts": "Kallëzim për mashtrim: viktima ka paguar 5.000 euro për një investim që nuk ka ekzistuar kurrë."},
     ["markdown"]),
    # v9.397 — të gjitha veglat e prokurorit (më parë vetëm analiza dhe plani: 2 nga 11)
    ("Prokuror — aktakuza", "/api/prosecutor/indictment",
     {"facts": "Vjedhje në banesë në Tiranë më 3 mars 2026: gjurmët e gishtave të të pandehurit në dritaren e thyer, stolitë u gjetën në makinën e tij, dy dëshmitarë e panë duke dalë nga pallati."},
     ["markdown"]),
    ("Prokuror — veprim hetimor", "/api/prosecutor/investigative-act",
     {"kind": "pergjim", "facts": "Grup i organizuar për trafik kokaine në lagje; dy bashkëpunëtorë tregojnë se porositë kalojnë nga celulari i drejtuesit, i identifikuar."},
     ["markdown"]),
    ("Prokuror — masë sigurimi", "/api/prosecutor/coercive-measure",
     {"facts": "I pandehuri u kap në flagrancë duke shitur 50 gram kokainë; ka një dënim të mëparshëm për të njëjtën vepër; u përpoq të ikte."},
     ["markdown"]),
    ("Prokuror — mosfillim/pushim", "/api/prosecutor/dismissal",
     {"facts": "Kallëzim për shpërdorim: shuma e kontestuar ishte paradhënie e rënë dakord për shpenzime të dokumentuara dhe pjesa e mbetur u kthye para kallëzimit."},
     ["markdown"]),
    ("Prokuror — stres-test", "/api/prosecutor/stress-test",
     {"text": "KËRKESË PËR GJYKIM. Prokuroria kërkon dërgimin në gjyq të Arben Hoxhës për veprën penale të vjedhjes, sepse më 3 mars 2026 mori telefonin celular të të dëmtuarit. Provat: deklarata e të dëmtuarit."},
     ["markdown"]),
    ("Prokuror — kallëzimi i qytetarit", "/api/prosecutor/complaint",
     {"facts": "Mbrëmë më vodhën makinën e parkuar poshtë pallatit në Durrës; kam pamjet e një kamere të pallatit."},
     ["markdown"]),
    ("Prokuror — të drejtat e viktimës", "/api/prosecutor/victim-rights",
     {"facts": "Më sulmoi ish-partneri dhe bëra kallëzim: çfarë mund të bëj gjatë procedimit?"},
     ["markdown"]),
    ("Prokuror — ankim ndaj pushimit", "/api/prosecutor/dismissal-appeal",
     {"facts": "Më njoftuan vendimin e mosfillimit për kallëzimin tim për mashtrim: prokurori thotë se është çështje civile, por kam bisedat ku shitësi pranon se nuk e ka pasur kurrë mallin."},
     ["markdown"]),
    ("Prokuror — ankesë për vonesë", "/api/prosecutor/delay",
     {"facts": "Bëra kallëzim për një mashtrim online në mars 2025 dhe që atëherë nuk kam marrë asnjë lajm."},
     ["markdown"]),
    ("Noter — kontrolli i aktit", "/api/notary/check",
     {"text": ("KONTRATË SHITJEJE. Z. Arben Hoxha i shet z. Ilir Dema apartamentin në Tiranë, rruga e Kavajës nr. 10, me çmim "
               "80.000 euro. Palët deklarojnë se pasuria është e lirë nga hipoteka. Pagesa bëhet në para në dorë në momentin e "
               "nënshkrimit.")},
     ["markdown"]),
    ("Noter — trashëgimia", "/api/notary/succession",
     {"situation": "I ndjeri lë bashkëshorten dhe dy fëmijë; prindërit janë gjallë; pasuria: një apartament dhe një llogari bankare."},
     ["markdown"]),
    ("Noter — drafti i aktit", "/api/notary/draft",
     {"deed_type": "shitje_pasurie",
      "details": ("Shitje apartamenti në Tiranë, zona kadastrale 8150, nr. pasurie 12/45, çmimi 90.000 euro, pagesa me "
                  "transfertë bankare në momentin e nënshkrimit; shitës Arben Hoxha, blerës Ilir Dema.")},
     ["markdown"]),
    ("Noter — prokura", "/api/notary/prokura",
     {"form": "e_posacme", "details": "Prokurë e posaçme për shitjen e një apartamenti në Durrës në emër të dhënësit të prokurës.",
      "duration": "12 muaj"},
     ["markdown"]),
    ("Noter — lista e dokumenteve", "/api/notary/checklist",
     {"act": "shitje pasurie e paluajtshme",
      "text": ("Dokumentet e mbledhura nga palët: certifikata e pronësisë nga ASHK, akti i fitimit të pronësisë (kontratë dhurimi "
               "e vitit 2011), kartat e identitetit të shitësit dhe të blerësit, planimetria e apartamentit.")},
     ["markdown", "completeness"]),
    ("Ekspertizë (Modele)", "/api/expertise/analyze",
     {"case_type": "aksident_rrugor",
      "facts": "Aksident rrugor: klienti im u përplas nga pas te semafori, ka dëmtime në qafë dhe makina është dëmtuar."},
     ["markdown"]),
    ("Avokati i djallit", "/api/devil-consult",
     {"situation": ("Klienti ka nënshkruar një garanci personale për kredinë e shoqërisë së tij; tani banka kërkon ekzekutimin "
                    "ndaj pasurisë së tij personale. Si e mbrojmë?")},
     ["markdown", "text"]),
    ("Mendim i dytë", "/api/second-opinion",
     {"question": "A mund të kërkoj urdhër ekzekutimi për detyrimin nga kontrata e sipërmarrjes?",
      "answer": ("Detyrimi nga kontrata e sipërmarrjes është i likuidueshëm dhe i kërkueshëm; mund të kërkohet lëshimi i urdhrit "
                 "të ekzekutimit sipas neneve 510 e vijues të Kodit të Procedurës Civile.")},
     ["markdown"]),
    ("Pika e parë — triazhi", "/api/intake/triage",
     {"story": "Bleva një makinë të përdorur nga një tregtar, pas dy javësh motori u prish dhe shitësi nuk më përgjigjet më."},
     ["markdown", "text", "summary", "area", "questions"]),
    ("Motori i afateve", "/api/afati/compute",
     {"trigger": "vendim_civil", "event_date": "2026-08-01", "facts": "Vendimi i shkallës së parë iu njoftua klientit sot."},
     ["markdown"]),
    ("Noter — verifikimi i pronës (kartela)", "/api/notary/verify-property",
     {"certificate": KARTELA_AL,
      "transaction": "Arben dhe Mira Hoxha duan t'ia shesin të gjithë apartamentin një blerësi të tretë: a mund ta lidhë noteri aktin?"},
     ["markdown"]),
    ("Noter — detyrimet pas aktit", "/api/notary/post-deed",
     {"act": "Kontratë shitjeje e apartamentit në Tiranë, zona kadastrale 8150, nr. pasurie 12/45, çmimi 90.000 euro, nënshkruar sot.",
      "act_date": "2026-09-14"},
     ["markdown"]),
    ("Noter — verifikimi i subjektit", "/api/notary/verify-subject",
     {"subject": ("Ekstrakt QKB: ALFA SHPK, NIPT L12345678A, selia Tiranë; statusi: Aktiv; administrator: Arben Hoxha; ortakë: "
                  "Arben Hoxha 60%, Ilir Dema 40%; kapitali 100.000 lekë; asnjë procedurë falimentimi."),
      "context": "Shoqëria shet një magazinë për 500.000 euro."},
     ["markdown"]),
    ("Noter — kundër pastrimit të parave", "/api/notary/aml-check",
     {"situation": ("Blerësi është person i ekspozuar politikisht i huaj; propozon pagesën e 300.000 eurove në para në dorë; "
                    "pasuria do të regjistrohet në emër të një shoqërie me seli në Ishujt Kajman.")},
     ["markdown"]),
]

ONLY = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
if ONLY.startswith("-") and ONLY[1:]:
    TESTS = [t for t in TESTS if ONLY[1:] not in t[0].lower()]
elif ONLY:
    TESTS = [t for t in TESTS if ONLY in t[0].lower()]
OUT_DIR = "/tmp/audit_al"
os.makedirs(OUT_DIR, exist_ok=True)

rows = []
for name, path, payload, keys in TESTS:
    t0 = time.time()
    try:
        d = post(path, payload, timeout=2400 if path == "/api/ask" else 900)
        blob = ""
        for k in keys:
            v = d.get(k)
            if isinstance(v, str):
                blob += "\n" + v
            elif v:
                blob += "\n" + json.dumps(v, ensure_ascii=False)
        if not blob.strip():
            rows.append((name, "BOSH"))
            print(f"  {name:38s} BOSH   ({str(d)[:80]})", flush=True)
            continue
        with open(os.path.join(OUT_DIR, re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(blob)
        it_l, it_w, al_w = len(IT_LANG.findall(blob)), len(IT_LAW.findall(blob)), len(AL_LAW.findall(blob))
        verdict = "OK" if (it_l <= 2 and it_w == 0) else ("DIRITTO IT!" if it_w else "ITALIANO")
        rows.append((name, verdict))
        _tok = ""
        if it_l:
            _tok = "  «" + "» · «".join(blob[max(0, m.start() - 14):m.end() + 14].replace("\n", " ")
                                        for m in list(IT_LANG.finditer(blob))[:4]) + "»"
        print(f"  {name:38s} {verdict:12s} italiano={it_l:>3} dirittoIT={it_w:>2} dirittoAL={al_w:>3}  ({time.time()-t0:.0f}s){_tok}", flush=True)
    except Exception as e:  # noqa: BLE001
        rows.append((name, "GABIM"))
        print(f"  {name:38s} GABIM: {type(e).__name__}: {str(e)[:90]}", flush=True)

print("", flush=True)
try:
    d = post("/api/act-check", {"text": ("Kërkojmë zgjidhjen e kontratës sipas nenit 698 të Kodit Civil dhe shpërblimin e dëmit "
                                         "sipas nenit 450 të Kodit Civil, si dhe kamatëvonesën sipas nenit 486 të Kodit Civil.")})
    ok = d.get("verified", 0) >= 3 and not d.get("fake") and not d.get("repealed")
    rows.append(("Verifikimi i citimeve (act-check)", "OK" if ok else "PROBLEM"))
    print(f"  {'Verifikimi i citimeve (act-check)':38s} {'OK' if ok else 'PROBLEM':12s} nene të verifikuara={d.get('verified')}/{d.get('total')}", flush=True)
except Exception as e:  # noqa: BLE001
    rows.append(("Verifikimi i citimeve (act-check)", "GABIM"))
    print(f"  act-check GABIM: {e}", flush=True)
n_ok = sum(1 for _, v in rows if v == "OK")
print(f"\n== {n_ok}/{len(rows)} OK ==", flush=True)
