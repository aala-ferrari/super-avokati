# -*- coding: utf-8 -*-
"""PROVA VIVA del diavolo radicato (v9.355): sessione AL (account demo usa-e-getta) → fascicolo →
una domanda semplice (percorso breve, ~1-3 min) → 🔮 /api/second-opinion con case_id → poi
«Këshillë strategjike» /api/devil-consult sugli stessi fatti. Misura ciò che conta: radicato
(`grounded`), passato dal cancello (0 fantasmi nella spilla), salvato nel filo (messaggio kind
«devil» in coda al fascicolo), tempo, lingua.

    docker exec super-avvocato python3 tools/prova_djalli.py           # dentro il container (env + 5050)
    PROVA_Q="…" docker exec … python3 tools/prova_djalli.py            # domanda diversa
"""
import json, os, re, sys, time, urllib.request, http.cookiejar

BASE = "http://127.0.0.1:5050"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(path, payload, headers=None, timeout=120):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers=h)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(path, timeout=60):
    with op.open(urllib.request.Request(BASE + path), timeout=timeout) as r:
        return json.loads(r.read().decode())


Q = os.environ.get("PROVA_Q", "").strip() or (
    "Klienti im u pushua nga puna pa paralajmërim pas 4 vjetësh punë, me pretendimin se erdhi vonë tri herë "
    "brenda një muaji. Nuk ka marrë asnjë paralajmërim me shkrim më parë. Çfarë të drejtash ka dhe sa është afati për padi?")

secret = os.environ.get("DEMO_PROVISION_SECRET", "")
ts = int(time.time())
email, code = f"prova-djalli-{ts}@superavokati.test", f"Prova-{ts}-djalli"
# v9.369: l'account di prova si cancella SEMPRE all'uscita (anche su errore): ne erano rimasti 19 e il digest ci scriveva
__import__('atexit').register(lambda _e=email: (__import__('sys').path.insert(0, '/app'), __import__('src.storage', fromlist=['delete_user']).delete_user(_e)))
print("provision:", post("/api/provision-demo", {"email": email, "code": code, "hours": 6},
                         headers={"X-Provision-Secret": secret}), flush=True)
print("login:", post("/api/login", {"username": email, "password": code, "lang": "sq"}).get("ok"), flush=True)
case = post("/api/cases", {"title": "Prova djalli (AL)", "jurisdiction": "AL"})
cid = case["id"]
print(f"caso {cid[:8]}", flush=True)

t0 = time.time()
job = post("/api/ask/start", {"case_id": cid, "message": Q}).get("job_id")
final_text, done = "", False
with op.open(urllib.request.Request(f"{BASE}/api/ask/events?job={job}&from=0"), timeout=3600) as r:
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[5:].strip())
        except Exception:  # noqa: BLE001
            continue
        if evt.get("type") == "status":
            print(f"   [{int(time.time()-t0):4d}s] {(evt.get('text') or '')[:80]}", flush=True)
        elif evt.get("type") == "final":
            final_text = evt.get("text") or ""
        elif evt.get("type") == "done":
            done = True
            break
print(f"risposta: {time.time()-t0:.0f}s · {len(final_text)} chr · done={done}", flush=True)
print("   inizio:", repr(final_text[:140].replace("\n", " ")), flush=True)

IT_LANG = re.compile(r"\b(art\.|c\.c\.|c\.p\.c\.|comma|articolo|sentenza|tribunale|avvocato|verdetto|risposta)\b")


def esito(nome, d, dt):
    st = (d.get("citations") or {}).get("stats") or {}
    md = d.get("markdown") or ""
    print("\n" + "=" * 78)
    print(f"{nome}: {dt:.0f}s · {len(md)} chr · grounded={d.get('grounded')} · saved={d.get('saved')}")
    print("   spilla:", {k: st.get(k) for k in ("total", "verified", "fake", "repealed", "needs_code", "foreign_verified", "foreign_unverified") if st.get(k) is not None})
    print("   barrati (cancello):", md.count("~~"), "· «citim i hequr»:", md.count("citim i hequr"), "· [⚠ verifikim dështoi]:", md.count("verifikim dështoi"))
    print("   italiano (token):", len(IT_LANG.findall(md)))
    print("   nene citati:", sorted(set(re.findall(r"[Nn]enit?\s+(\d+[/a-z]*)", md)))[:20])
    print("   inizio:", repr(md[:200].replace("\n", " ")))
    return md


t1 = time.time()
so = post("/api/second-opinion", {"question": Q, "answer": final_text, "case_id": cid}, timeout=1800)
md_so = esito("🔮 SECOND-OPINION (con fascicolo)", so, time.time() - t1)

msgs = get(f"/api/cases/{cid}").get("messages") or []
last = msgs[-1] if msgs else {}
print("   ultimo messaggio del filo: role=%s kind=%s inizio=%r" % (last.get("role"), last.get("kind"), (last.get("content") or "")[:90]))
ok_fill = last.get("kind") == "devil" and last.get("role") == "assistant" and (last.get("content") or "").startswith("### ⚔️")

t2 = time.time()
dc = post("/api/devil-consult", {"situation": Q, "case_id": cid}, timeout=1800)
md_dc = esito("😈 DEVIL-CONSULT (fatti + fascicolo)", dc, time.time() - t2)

print("\nVERDETTO PROVA: grounded=%s/%s · cancello: fantasmi residui=%s/%s · salvato nel filo=%s" % (
    so.get("grounded"), dc.get("grounded"),
    ((so.get("citations") or {}).get("stats") or {}).get("fake"), ((dc.get("citations") or {}).get("stats") or {}).get("fake"),
    ok_fill))
os.makedirs("/tmp/audit_it", exist_ok=True)
with open("/tmp/audit_it/djalli.txt", "w", encoding="utf-8") as fh:
    fh.write("### RISPOSTA\n" + final_text + "\n\n### SECOND-OPINION\n" + md_so + "\n\n### DEVIL-CONSULT\n" + md_dc)
print("testi in /tmp/audit_it/djalli.txt · DONE")
