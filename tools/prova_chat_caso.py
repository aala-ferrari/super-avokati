# -*- coding: utf-8 -*-
"""PROVA VIVA sul percorso della CHAT (job + stream SSE, come il browser): la
stessa domanda in sessione IT (admin.it) e in sessione AL (account demo).

Misura quello che il titolare vede: verdetto IN TESTA, web usato (fonti), niente
«accesso negato», nessuna parola dell'altra lingua, pannelli corretti, lunghezza,
tempo. Salva il testo finale in /tmp/audit_it/chat_<lang>.txt.

    python3 tools/prova_chat_caso.py it
    python3 tools/prova_chat_caso.py al
"""
import json, os, re, sys, time, urllib.request, http.cookiejar

BASE = "http://127.0.0.1:5050"
LANG = (sys.argv[1] if len(sys.argv) > 1 else "it").strip().lower()
# PROVA_Q="…" sostituisce la domanda (per provare il corpus nuovo con casi mirati, 16 set 2026);
# PROVA_TAG="nome" cambia il file di uscita (/tmp/audit_it/chat_<lang>_<tag>.txt)
_Q_ENV = os.environ.get("PROVA_Q", "").strip()
_TAG = os.environ.get("PROVA_TAG", "").strip()
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(path, payload, headers=None, timeout=120):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers=h)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


Q_IT = ("ho un cliente che e' amministratore in una societa albanese shpk srl, la auto e targata "
        "albanese, nel nome della shpk, il amministratore ha la procura per girare sia al estero sia "
        "in albania dal notaio, ma la societa ha anche come mansione nel statuto sia servizi di vendita "
        "auto, auto a noleggio, servizi legali e siti web. il amministratore e stato residente in italia, "
        "adesso da un po di tempo vive in albania da piu di 6 mesi consecutivi, ma ha ancora permesso di "
        "soggiorno valido in italia 9 anni. puo andare in italia con la auto della societa con la procura? "
        "o essendo residente o magari domiciliato o visto che ha permesso di soggiorno italiano, possono "
        "fare divieto e blocco auto? come funziona, come fare in questi casi?")
Q_AL = ("Kam një klient që është administrator i një shoqërie shqiptare sh.p.k.; makina është me targa "
        "shqiptare, në emër të sh.p.k.-së; administratori ka prokurë nga noteri për ta drejtuar si jashtë "
        "shtetit ashtu edhe në Shqipëri; shoqëria ka në statut edhe shërbime shitjeje automjetesh, makina me "
        "qira, shërbime ligjore dhe faqe interneti. Administratori ka qenë rezident në Itali; tani prej ca "
        "kohësh jeton në Shqipëri, mbi 6 muaj rresht, por ka ende leje qëndrimi të vlefshme në Itali (9 vjet). "
        "A mund të shkojë në Itali me makinën e shoqërisë me prokurën? Apo, duke qenë rezident, ndoshta i "
        "domiciluar, ose meqë ka leje qëndrimi italiane, mund t'ia ndalojnë dhe bllokojnë makinën? Si "
        "funksionon, si veprohet në këto raste?")

if LANG == "it":
    print(post("/api/login", {"username": "admin.it", "password": "AdminIT2026!", "lang": "it"}), flush=True)
    juris, question = "IT", Q_IT
else:
    secret = os.environ.get("DEMO_PROVISION_SECRET", "")
    ts = int(time.time())
    email, code = f"prova-chat-{ts}@superavokati.test", f"Prova-{ts}-chat"
    print("provision:", post("/api/provision-demo", {"email": email, "code": code, "hours": 6},
                             headers={"X-Provision-Secret": secret}), flush=True)
    print(post("/api/login", {"username": email, "password": code, "lang": "sq"}), flush=True)
    juris, question = "AL", Q_AL

case = post("/api/cases", {"title": "Prova chat — auto shpk (%s)" % juris, "jurisdiction": juris})
cid = case["id"]
print(f"caso {cid[:8]} giurisdizione={case.get('jurisdiction')}", flush=True)

t0 = time.time()
if _Q_ENV:
    question = _Q_ENV
start = post("/api/ask/start", {"case_id": cid, "message": question, "deep": os.environ.get("PROVA_DEEP", "") == "1"})   # PROVA_DEEP=1 = Gjyqtari Suprem
job = start.get("job_id")
print("job:", job, flush=True)

final_text, n_delta, n_status, n_err, done = "", 0, 0, 0, False
req = urllib.request.Request(f"{BASE}/api/ask/events?job={job}&from=0")
with op.open(req, timeout=3600) as r:
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[5:].strip())
        except Exception:  # noqa: BLE001
            continue
        t = evt.get("type")
        if t == "delta":
            n_delta += 1
        elif t == "status":
            n_status += 1
            # come il client (app.js): text_it SOLO in sessione IT, altrimenti text (sq)
            _st = (evt.get("text_it") if LANG == "it" else None) or evt.get("text") or evt.get("text_it") or ""
            print(f"   [{int(time.time()-t0):4d}s] status: {_st[:90]}", flush=True)
        elif t == "final":
            final_text = evt.get("text") or ""
        elif t == "error":
            n_err += 1
            print("   ERROR:", str(evt)[:200], flush=True)
        elif t == "done":
            done = True
            break
dt = time.time() - t0

os.makedirs("/tmp/audit_it", exist_ok=True)
out = f"/tmp/audit_it/chat_{LANG}{('_' + _TAG) if _TAG else ''}.txt"
with open(out, "w", encoding="utf-8") as fh:
    fh.write(final_text)

AL_LANG = re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|nenit|neni|rastin|gjykata|pala|provat|afati|kërkesë|vendim|shqip|përgjigje|pyetje)\b", re.I)
IT_LANG = re.compile(r"\b(art\.|c\.c\.|c\.p\.c\.|C\.d\.S\.|comma|articolo|sentenza|tribunale|avvocato|verdetto|risposta)\b")
head = final_text[:160].replace("\n", " ")
print("\n" + "=" * 78)
print(f"RISULTATO {juris}: {dt:.0f}s · delta={n_delta} status={n_status} error={n_err} done={done} · {len(final_text)} caratteri → {out}")
print("=" * 78)
print("inizio           :", repr(head))
if juris == "IT":
    print("verdetto in testa:", final_text.lstrip().startswith("### ⚖️ Verdetto finale"))
    print("analisi completa :", "Analisi completa" in final_text)
    print("albanese (token) :", len(AL_LANG.findall(final_text)), [m.group(0) for m in AL_LANG.finditer(final_text)][:6])
else:
    print("verdetto in testa:", final_text.lstrip().startswith("### ⚖️ Vendimi përfundimtar"))
    print("analiza e plotë  :", "Analiza e plotë" in final_text)
    print("italiano (token) :", len(IT_LANG.findall(final_text)), [m.group(0) for m in IT_LANG.finditer(final_text)][:6])
print("fonti web (http) :", final_text.count("http"))
print("«accesso negato» :", len(re.findall(r"negat[oa]|non (?:è|sono) disponibil|nuk (?:është|janë) të disponuesh|u refuzua", final_text, re.I)))
print("pannelli corretti:", ("Pannelli da correggere" in final_text) or ("Panele për t'u korrigjuar" in final_text))
print("per precisione   :", ("Per precisione" in final_text) or ("Për saktësi" in final_text))
print("DONE")
