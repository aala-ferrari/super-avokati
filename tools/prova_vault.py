# -*- coding: utf-8 -*-
"""Prova viva del Vault del fascicolo (v9.400): carica due documenti di testo in un fascicolo, aspetta che siano letti,
poi «Pyet dokumentet / Interroga i documenti», l'ago e «chi ha detto cosa». Controlla la lingua della sessione e il
marcatore delle citazioni ([Doc N] in IT, [Dok N] in AL).
Uso (container di prova, canali spenti, copia del DB):  python3 tools/prova_vault.py IT   |   python3 tools/prova_vault.py AL"""
import atexit, json, os, re, sys, time, uuid, urllib.request, http.cookiejar

sys.path.insert(0, "/app")
SESS = (sys.argv[1] if len(sys.argv) > 1 else "IT").upper()
IT = SESS == "IT"
BASE = "http://127.0.0.1:5050"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, payload=None, method="POST", timeout=900, headers=None, raw=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def carica(cid, nome, testo):
    b = "----sa" + uuid.uuid4().hex
    corpo = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{nome}\"\r\n"
             f"Content-Type: text/plain\r\n\r\n").encode() + testo.encode("utf-8") + f"\r\n--{b}--\r\n".encode()
    return call(f"/api/cases/{cid}/documents", raw=corpo, headers={"Content-Type": f"multipart/form-data; boundary={b}"})


if IT:
    call("/api/login", {"username": "admin.it", "password": os.environ.get("AUDIT_IT_PASS", "AdminIT2026!"), "lang": "it"})
    call("/api/session/jurisdiction", {"jurisdiction": "IT"})
else:
    _ts = int(time.time())
    EMAIL, CODE = f"prova-vault-{_ts}@superavokati.test", f"Prova-{_ts}"
    atexit.register(lambda: __import__("src.storage", fromlist=["delete_user"]).delete_user(EMAIL))
    call("/api/provision-demo", {"email": EMAIL, "code": CODE, "hours": 6, "modules": ["avokat", "prokuror", "noter"]},
         headers={"X-Provision-Secret": os.environ.get("DEMO_PROVISION_SECRET", "")})
    call("/api/login", {"username": EMAIL, "password": CODE, "lang": "sq"})
CID = call("/api/cases", {"title": "Prova Vault v9.400" if IT else "Provë Vault v9.400"})["id"]
atexit.register(lambda: op.open(urllib.request.Request(BASE + f"/api/cases/{CID}", method="DELETE"), timeout=30).read())

if IT:
    D1 = ("CONTRATTO DI LAVORO SUBORDINATO. Tra Beta srl e il sig. Mario Rossi. Data di assunzione: 1 febbraio 2019. "
          "Mansione: magazziniere. Retribuzione: 1.600 euro lordi mensili. Il recesso deve essere comunicato per iscritto.")
    D2 = ("LETTERA DEL DATORE, 20 marzo 2026. Egregio sig. Rossi, prendiamo atto delle sue dimissioni presentate a voce il "
          "5 marzo 2026. Il rapporto è cessato il 3 marzo 2026. Distinti saluti, Beta srl.")
    Q = "Da quando è assunto il lavoratore e che cosa dice il datore sulla fine del rapporto?"
else:
    D1 = ("KONTRATË PUNE. Ndërmjet ALFA shpk dhe z. Ilir Hoxha. Data e fillimit: 1 shkurt 2019. Detyra: magazinier. "
          "Paga: 80.000 lekë bruto në muaj. Zgjidhja e kontratës njoftohet me shkrim.")
    D2 = ("LETËR E PUNËDHËNËSIT, 20 mars 2026. I nderuar z. Hoxha, marrim akt dorëheqjen tuaj të dhënë me gojë më 5 mars "
          "2026. Marrëdhënia e punës përfundoi më 3 mars 2026. Me respekt, ALFA shpk.")
    Q = "Që kur është i punësuar punëmarrësi dhe çfarë thotë punëdhënësi për mbarimin e marrëdhënies?"
carica(CID, "contratto.txt" if IT else "kontrata.txt", D1)
carica(CID, "lettera_datore.txt" if IT else "letra_punedhenesi.txt", D2)
for _ in range(60):
    docs = call(f"/api/cases/{CID}/documents", method="GET").get("documents") or []
    if docs and all((d.get("status") or "") in ("ready", "failed", "error") for d in docs):
        break
    time.sleep(5)
print("documenti:", [(d.get("filename"), d.get("status")) for d in docs])

AL_LANG = re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|dokumentet|punëdhënësi|punëmarrësi|gjilpëra|pse)\b", re.I)
IT_LANG = re.compile(r"\b(il|della|delle|nella|che|non|sono|documenti|datore|lavoratore|perché)\b", re.I)
esiti = []
for nome, path, payload, chiave in (("vault", f"/api/cases/{CID}/vault", {"question": Q}, "answer"),
                                    ("ago", f"/api/cases/{CID}/needle", {}, "markdown"),
                                    ("chi_ha_detto", f"/api/cases/{CID}/who-said", {}, "markdown")):
    t0 = time.time()
    try:
        r = call(path, payload)
        txt = r.get(chiave) or ""
        err = r.get("error")
    except Exception as exc:  # noqa: BLE001
        txt, err = "", str(exc)[:160]
    spie = (AL_LANG if IT else IT_LANG).findall(txt)
    tag_ok = bool(re.search(r"\[Doc \d+\]", txt)) if IT else bool(re.search(r"\[Dok \d+\]", txt))
    tag_bad = bool(re.search(r"\[Dok \d+\]", txt)) if IT else bool(re.search(r"\[Doc \d+\]", txt))
    ok = bool(txt.strip()) and not err and not spie and tag_ok and not tag_bad
    esiti.append(ok)
    print(f"  {nome:12s} {'OK ' if ok else 'NO '} altra_lingua={len(spie)} marcatore={'ok' if tag_ok else 'NO'}"
          f"{' (altra forma!)' if tag_bad else ''} chr={len(txt)} ({time.time()-t0:4.0f}s)"
          f"{'  ERR ' + str(err) if err else ''}  {' · '.join(sorted(set(spie))[:6])}", flush=True)
    os.makedirs("/tmp/prova_vault", exist_ok=True)
    open(f"/tmp/prova_vault/{SESS}_{nome}.txt", "w", encoding="utf-8").write(txt)
print(f"== {sum(esiti)}/{len(esiti)} ({SESS}) ==")
