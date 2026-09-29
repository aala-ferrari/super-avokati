# -*- coding: utf-8 -*-
"""LINGUA = SESSIONE e diritto della sessione sugli strumenti PRO del fascicolo mai provati in audit (v9.400):
Red Team (stress test dell'udienza), cronologia del fascicolo, bozza d'atto, duello avversariale, bussola strategica.
Hanno prompt albanesi con il solo vincolo di giurisdizione al collo di bottiglia: qui si misura se basta.

Uso (container di prova, canali spenti, copia del DB):
    python3 tools/audit_pro_extra.py AL
    python3 tools/audit_pro_extra.py IT
Conta le parole dell'altra lingua e i riferimenti al diritto dell'altra giurisdizione nei VALORI di testo (non nelle chiavi
né nei valori-codice come `type`/`severity`); gli output integrali in /tmp/audit_pro/<sessione>_<strumento>.txt."""
import atexit, json, os, re, sys, time, urllib.request, http.cookiejar

sys.path.insert(0, "/app")
SESS = (sys.argv[1] if len(sys.argv) > 1 else "IT").upper()
SOLO = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
IT = SESS == "IT"
BASE = "http://127.0.0.1:5050"
OUT = "/tmp/audit_pro"
os.makedirs(OUT, exist_ok=True)
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, payload=None, method="POST", timeout=1800, headers=None):
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
    EMAIL, CODE = f"audit-pro-{_ts}@superavokati.test", f"Audit-{_ts}"
    atexit.register(lambda: __import__("src.storage", fromlist=["delete_user"]).delete_user(EMAIL))
    call("/api/provision-demo", {"email": EMAIL, "code": CODE, "hours": 6, "modules": ["avokat", "prokuror", "noter"]},
         headers={"X-Provision-Secret": os.environ.get("DEMO_PROVISION_SECRET", "")})
    call("/api/login", {"username": EMAIL, "password": CODE, "lang": "sq"})
case = call("/api/cases", {"title": ("Licenziamento orale — Rossi c. Beta srl" if IT else
                                     "Pushim me gojë — Hoxha kundër ALFA shpk")})
CID = case["id"]
atexit.register(lambda: op.open(urllib.request.Request(BASE + f"/api/cases/{CID}", method="DELETE"), timeout=30).read())

AL_LANG = re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|nenit|neni|rastin|gjykata|pala|provat|afati|"
                     r"kërkesë|vendim|shqip|mbështetur|pjesërisht|kontestuar|mungon|klienti|"
                     r"avokati|letër|pagesë|punëdhënësi|punëmarrësi)\b", re.I)
AL_LAW = re.compile(r"\bKodi\b|\bKodit\b|\bKPC\b|\bKPP\b|\bKC\b|\bKP\b|shqiptar|Shqipëri", re.I)
# v9.402: le massime LATINE («non bis in idem», «a non domino»…) non sono italiano (falsi allarmi nelle sessioni AL)
_LATINO = re.compile(r"\b(?:ne|non)\s+bis\s+in\s+idem\b|\ba\s+non\s+domino\b|\bin\s+dubio\s+pro\s+reo\b|\bpacta\s+sunt\s+servanda\b|"
                     r"\bnon\s+liquet\b|\bnullum\s+crimen\b|\bnulla\s+poena\b|\b(?:non\s+)?reformatio\s+in\s+peius\b|\bex\s+(?:tunc|nunc)\b|"
                     r"\berga\s+omnes\b|\btempus\s+regit\s+actum\b|\bcondicio\s+sine\s+qua\s+non\b|\bsine\s+qua\s+non\b", re.I)
IT_LANG = re.compile(r"\b(il|della|delle|degli|dello|nella|nel|che|non|sono|essere|articolo|comma|"
                     r"sentenza|tribunale|avvocato|pertanto|quindi|anche|termine|ricorso|cliente|"
                     r"diritto|udienza|lettera|licenziamento|lavoratore)\b", re.I)
IT_LAW = re.compile(r"\bc\.c\.|\bc\.p\.c\.|\bc\.p\.p\.|codice civile|d\.lgs|Statuto dei lavoratori|604/1966", re.I)

_SKIP_K = {"id", "case_id", "kind", "level", "status", "name", "created_at", "updated_at", "url", "source_url", "code",
           "severity", "verdict", "type", "date_confidence", "timing", "urgency", "bucket", "applies_to",
           "citizen_applicable", "outcome", "loop_id", "act_type", "number", "article", "date", "time", "from", "to",
           "source_doc", "citations", "stats", "model", "round"}


def _valori(x):
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            if k in _SKIP_K:
                continue
            out += _valori(v)
    elif isinstance(x, list):
        for v in x:
            out += _valori(v)
    elif isinstance(x, str):
        out.append(x)
    return out


FATTI = ("Il lavoratore Mario Rossi, assunto nel 2019 da Beta srl, è stato licenziato a voce il 3 marzo 2026 dal "
         "titolare, senza lettera né motivazione; il 10 marzo ha inviato una PEC di contestazione; il datore sostiene "
         "che si sia dimesso. Vogliamo chiedere l'inefficacia del licenziamento e il risarcimento." if IT else
         "Punëmarrësi Ilir Hoxha, i punësuar nga ALFA shpk në 2019, u pushua me gojë më 3.3.2026 nga administratori, "
         "pa njoftim me shkrim dhe pa arsye; më 10.3.2026 dërgoi kundërshtim me shkrim; punëdhënësi pretendon se ai "
         "dha dorëheqjen. Kërkojmë pavlefshmërinë e pushimit dhe dëmshpërblimin.")


def _duello():
    r = call(f"/api/cases/{CID}/adversarial", {"hypothesis": FATTI, "max_rounds": 2})
    lid = r.get("loop_id") or r.get("id")
    if lid and not (r.get("rounds") or r.get("summary")):
        for _ in range(120):
            time.sleep(10)
            g = call(f"/api/adversarial/{lid}", method="GET")
            if (g.get("status") or "") in ("done", "completed", "failed", "error") or g.get("summary"):
                return g
        return {"error": "timeout del duello"}
    return r


TESTS = [
    ("stress_test", lambda: call(f"/api/cases/{CID}/stress-test", {"hypothesis": FATTI}), lambda r: "\n".join(_valori(r))),
    ("cronologia", lambda: call(f"/api/cases/{CID}/timeline", {"summary": FATTI}), lambda r: "\n".join(_valori(r))),
    ("bozza_atto", lambda: call("/api/draft-act", {"act_type": "padi", "case_id": CID,
                                                   "brief": FATTI + (" Redigi il ricorso." if IT else " Harto padinë.")}),
     lambda r: "\n".join(_valori(r))),
    ("duello", _duello, lambda r: "\n".join(_valori(r))),
    ("bussola", lambda: call(f"/api/cases/{CID}/strategy", {"objective": ("Ottenere il risarcimento più alto nel minor "
                                                                          "tempo possibile" if IT else
                                                                          "Dëmshpërblimi më i lartë në kohën më të shkurtër")}),
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
    spie = (AL_LANG if IT else IT_LANG).findall(txt if IT else _LATINO.sub(" ", txt))
    legge = (AL_LAW if IT else IT_LAW).findall(txt)
    ok = bool(txt.strip()) and not err and not spie and not legge
    esiti.append(ok)
    campioni = " · ".join(sorted({s if isinstance(s, str) else s[0] for s in spie + legge})[:8])
    print(f"  {nome:14s} {'OK ' if ok else 'NO '} altra_lingua={len(spie):3d} legge_estera={len(legge):2d} "
          f"chr={len(txt):5d} ({dt:4.0f}s){'  ERR ' + str(err) if err else ''}  {campioni}", flush=True)

print(f"\n== {sum(esiti)}/{len(esiti)} strumenti PRO nella lingua e nel diritto della sessione ({SESS}) ==")
sys.exit(0 if all(esiti) else 1)
