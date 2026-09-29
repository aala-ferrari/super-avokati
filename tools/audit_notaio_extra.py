# -*- coding: utf-8 -*-
"""LINGUA = SESSIONE e diritto della sessione sugli strumenti del NOTAIO mai provati (v9.400).

`audit_tools_it.py` / `audit_tools_al.py` coprono controllo atto, successione, bozza, procura, checklist, verifica della
proprietà e del soggetto, adempimenti e antiriciclaggio. Restano fuori: dichiarazioni, lista dei documenti, revoca della
procura, conflitti con gli atti precedenti, ispezione dell'atto, estrazione dei dati, spiegazione al cliente e le lettere.
Per ognuno conta le parole dell'ALTRA lingua e i riferimenti al diritto dell'altra giurisdizione, e salva l'uscita.
Uso (dentro un container di prova, canali spenti, copia del DB):
    python3 tools/audit_notaio_extra.py AL
    python3 tools/audit_notaio_extra.py IT
Gli output integrali vanno in /tmp/audit_notaio/<sessione>_<strumento>.txt. Uscita 1 se uno strumento mescola."""
import atexit, json, os, re, sys, time, urllib.request, http.cookiejar

sys.path.insert(0, "/app")
SESS = (sys.argv[1] if len(sys.argv) > 1 else "IT").upper()
SOLO = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None     # es. «IT lettera»
IT = SESS == "IT"
BASE = "http://127.0.0.1:5050"
OUT = "/tmp/audit_notaio"
os.makedirs(OUT, exist_ok=True)
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, payload=None, method="POST", timeout=1500, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers=h, method=method)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


if IT:
    call("/api/login", {"username": "admin.it", "password": os.environ.get("AUDIT_IT_PASS", "AdminIT2026!"), "lang": "it"})
    call("/api/session/jurisdiction", {"jurisdiction": "IT"})
else:
    _ts = int(time.time())
    EMAIL, CODE = f"audit-noter-{_ts}@superavokati.test", f"Audit-{_ts}"
    atexit.register(lambda: __import__("src.storage", fromlist=["delete_user"]).delete_user(EMAIL))
    call("/api/provision-demo", {"email": EMAIL, "code": CODE, "hours": 6, "modules": ["avokat", "prokuror", "noter"]},
         headers={"X-Provision-Secret": os.environ.get("DEMO_PROVISION_SECRET", "")})
    call("/api/login", {"username": EMAIL, "password": CODE, "lang": "sq"})
case = call("/api/cases", {"title": "Audit notaio v9.400" if IT else "Auditim noter v9.400"})
CID = case["id"]
atexit.register(lambda: op.open(urllib.request.Request(BASE + f"/api/cases/{CID}", method="DELETE"), timeout=30).read())

AL_LANG = re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|nenit|neni|rastin|gjykata|pala|provat|afati|"
                     r"kërkesë|vendim|shqip|mbështetur|pjesërisht|kontestuar|mungon|klienti|noteri|"
                     r"avokati|letër|pagesë|prokurë|deklaratë)\b", re.I)
AL_LAW = re.compile(r"\bKodi\b|\bKodit\b|\bKPC\b|\bKPP\b|\bKC\b|\bKF\b|shqiptar|Shqipëri|110/2018|111/2018|ASHK|QKB", re.I)
IT_LANG = re.compile(r"\b(il|della|delle|degli|dello|nella|nel|che|non|sono|essere|articolo|comma|"
                     r"sentenza|tribunale|avvocato|pertanto|quindi|anche|termine|ricorso|cliente|"
                     r"diritto|udienza|lettera|notaio|procura)\b", re.I)
IT_LAW = re.compile(r"\bc\.c\.|\bc\.p\.c\.|\bc\.p\.p\.|codice civile|codice del consumo|d\.lgs|legge notarile|"
                    r"\bGDPR\b.*2016/679|Statuto dei lavoratori|89/1913", re.I)

ATTO_IT = ("REPERTORIO N. 1234 — RACCOLTA N. 567. COMPRAVENDITA. L'anno 2026, il giorno 10 settembre, in Milano, davanti a me "
           "dott. Paolo Verdi, notaio in Milano, sono comparsi: il sig. Mario Rossi, nato a Milano il 3 aprile 1970, codice "
           "fiscale RSSMRA70D03F205X, venditore, e la sig.ra Anna Bianchi, nata a Roma il 12 maggio 1985, acquirente. Il "
           "venditore vende all'acquirente, che acquista, l'appartamento sito in Milano, via Roma 10, piano terzo, censito al "
           "catasto fabbricati foglio 12, particella 345, subalterno 6, per il prezzo di euro 250.000, pagato con bonifico. "
           "Il venditore garantisce che l'immobile è libero da ipoteche. L'acquirente dichiara di essere coniugata in regime "
           "di comunione legale. Letto, confermato e sottoscritto.")
ATTO_AL = ("NR. 1234 REP. — NR. 567 KOL. KONTRATË SHITJEJE. Sot, më 10.09.2026, në Tiranë, para meje, noterit Arben Deda, "
           "u paraqitën: z. Ilir Hoxha, lindur në Tiranë më 3.4.1970, me nr. personal J70403123A, shitës, dhe znj. Mira Dema, "
           "lindur në Durrës më 12.5.1985, blerëse. Shitësi i shet blerëses apartamentin në Tiranë, rruga e Kavajës nr. 10, "
           "kati 3, zona kadastrale 8150, nr. pasurie 12/45, për çmimin 90.000 euro, paguar me transfertë bankare. Shitësi "
           "garanton se pasuria është e lirë nga hipotekat. Blerësja deklaron se është e martuar. U lexua, u miratua dhe u nënshkrua.")

TESTS = [
    ("dichiarazione", lambda: call("/api/notary/declaration", {
        "decl_type": "pelqim_udhetimi_minor",
        "details": ("Consenso del padre, Mario Rossi, all'espatrio del figlio minore Luca (nato il 3 aprile 2015, passaporto "
                    "YA1234567) per un viaggio in Grecia dal 1 al 15 luglio 2026 con la madre Anna Bianchi." if IT else
                    "Pëlqimi i babait, Ilir Hoxha, për udhëtimin e djalit të mitur Arbër (lindur më 3.4.2015, pasaporta "
                    "BA1234567) në Greqi nga 1 deri më 15 korrik 2026 me nënën Mira Dema.")}),
     lambda r: r.get("markdown", "")),
    ("lista_documenti", lambda: call("/api/notary/documents", {
        "act": ("compravendita di un appartamento a Milano; il venditore è coniugato in comunione legale" if IT else
                "shitje apartamenti në Tiranë; shitësi është i martuar")}),
     lambda r: r.get("markdown", "")),
    ("revoca_procura", lambda: call("/api/notary/revocation", {
        "details": ("Revoca della procura speciale rilasciata il 10 marzo 2025 dal sig. Mario Rossi al sig. Luigi Bianchi "
                    "per vendere l'appartamento di via Roma 10 a Milano; il procuratore non ha ancora venduto." if IT else
                    "Revokim i prokurës së posaçme të dhënë më 10.3.2025 nga z. Ilir Hoxha te z. Gent Leka për shitjen e "
                    "apartamentit në rrugën e Kavajës nr. 10, Tiranë; i përfaqësuari nuk e ka shitur ende.")}),
     lambda r: r.get("markdown", "")),
    ("conflitti", lambda: call("/api/notary/conflicts", {
        "case_id": CID,
        "new_act": ("Vendita a terzi dell'appartamento di via Roma 10 a Milano già promesso in vendita con preliminare "
                    "trascritto del 5 maggio 2026 ad Anna Bianchi." if IT else
                    "Shitja te një i tretë e apartamentit në rrugën e Kavajës nr. 10, Tiranë, i premtuar më parë me "
                    "kontratë premtimi të regjistruar më 5.5.2026 te Mira Dema.")}),
     lambda r: r.get("markdown", "")),
    ("ispezione_atto", lambda: call("/api/notary/inspect", {"text": ATTO_IT if IT else ATTO_AL, "case_id": CID}),
     lambda r: r.get("markdown", "")),
    ("estrazione_dati", lambda: call("/api/notary/extract", {"text": ATTO_IT if IT else ATTO_AL, "case_id": CID}),
     lambda r: r.get("markdown", "") or json.dumps(r.get("data") or r, ensure_ascii=False)),
    ("spiegazione_cliente", lambda: call("/api/notary/client", {"text": ATTO_IT if IT else ATTO_AL}),
     lambda r: r.get("markdown", "")),
]


def _prima_lettera():
    try:
        kinds = call("/api/letters/kinds", method="GET").get("kinds") or []
        claim = [k for k in kinds if (k.get("family") or "").upper() == "CLAIM"]
        for k in claim:                               # un tipo coerente coi fatti (canone/affitto non pagato)
            if re.search(r"pagament|pagesa|canon|qira|diffida|mora|borxh|credit", (k.get("key", "") + " " + k.get("label", "")), re.I):
                return k.get("key")
        for k in claim:
            return k.get("key")
        return kinds[0].get("key") if kinds else None
    except Exception:  # noqa: BLE001
        return None


TESTS.append(("lettera", lambda: call("/api/letters/draft", {
    "kind": _prima_lettera() or "", "case_id": CID,
    "facts": ("Il conduttore Luca Verdi non paga il canone di locazione di 1.200 euro da tre mesi (luglio-settembre 2026) "
              "per l'appartamento di via Roma 10 a Milano; il contratto è registrato." if IT else
              "Qiramarrësi Gent Leka nuk e paguan qiranë prej 300 euro prej tre muajsh (korrik-shtator 2026) për "
              "apartamentin në rrugën e Kavajës nr. 10, Tiranë; kontrata është e noterizuar.")}),
    lambda r: r.get("markdown", "")))

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
    spie = (AL_LANG if IT else IT_LANG).findall(txt)
    legge = (AL_LAW if IT else IT_LAW).findall(txt)
    ok = bool(txt.strip()) and not err and not spie and not legge
    esiti.append(ok)
    campioni = " · ".join(sorted({s if isinstance(s, str) else s[0] for s in spie + legge})[:8])
    print(f"  {nome:20s} {'OK ' if ok else 'NO '} altra_lingua={len(spie):3d} legge_estera={len(legge):2d} "
          f"chr={len(txt):5d} ({dt:4.0f}s){'  ERR ' + str(err) if err else ''}  {campioni}", flush=True)

print(f"\n== {sum(esiti)}/{len(esiti)} strumenti del notaio nella lingua e nel diritto della sessione ({SESS}) ==")
sys.exit(0 if all(esiti) else 1)
