# -*- coding: utf-8 -*-
"""v9.634 — MISURA DELLA REVISIONE DEI DOCUMENTI (titolare, 12 ott: «doveva solo revisionare il documento e rispondere»).

Per ogni caso in tools/golden_cases/rishikim/*.json: un account di prova, un fascicolo nella giurisdizione del caso, il documento
caricato (.docx o .txt) dal percorso vero del caricamento, la domanda dell'avvocato dal percorso vero della chat (start + events,
come il browser), poi il controllo:
  - le CINQUE sezioni della revisione (verdetto, errori giuridici, dati mancanti, errori di lingua, testo corretto);
  - niente sala di guerra (piano d'azione, radar, allarmi, precedenti contrari);
  - le norme attese VERIFICATE sul corpus (tutte quelle di «norme_tutte», almeno una di «norme_una_di»);
  - i difetti del documento trovati (le espressioni di «parole»);
  - nessuna parola dell'altra lingua.
Gira DENTRO un container di prova col server acceso (COPIA del DB, canali spenti): tools/misura_rishikim.sh. Testi in
/tmp/misura_rishikim/<caso>.txt. Esce 1 se un caso non passa.

    python3 tools/eval_rishikim.py [id_caso ...]
"""
import atexit, glob, http.cookiejar, io, json, os, re, sys, time, urllib.request, uuid

sys.path.insert(0, "/app")
BASE = os.environ.get("BASE", "http://127.0.0.1:5050")
CARTELLA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_cases", "rishikim")
USCITA = "/tmp/misura_rishikim"

SEZIONI = {
    "AL": [r"Verdikti", r"Gabimet ligjore", r"Të dhëna që mungojnë|mospërputhje", r"Gabime gjuhësore|gjuhësore", r"Teksti i korrigjuar"],
    "IT": [r"Verdetto", r"Errori giuridici", r"Dati mancanti|incongruenze", r"Errori di lingua|di traduzione", r"Testo corretto"],
}
SALA_DI_GUERRA = {
    "AL": r"Plani i veprimit|PLANI I VEPRIMIT|Radari i pavlefshm|ALARM I NGRITUR|Precedent[eë]t e kund[eë]rt|Leva t[eë] fshehura",
    "IT": r"Piano d'azione|PIANO D'AZIONE|Radar di nullità|ALLARME|Precedenti contrari|Leve nascoste",
}
ALTRA_LINGUA = {
    "AL": re.compile(r"\b(della|degli|delle|sentenza|tribunale|articolo|comma|quindi|perché|questo|questa)\b", re.I),
    "IT": re.compile(r"[ëç]|\b(nuk|është|janë|duhet|sipas|nenit|gjykata|kërkesë|vendim|përgjigje)\b", re.I),
}
PANNELLI_GUERRA = ("nullity", "urgency", "action_plan", "premortem", "evidence", "leverage", "opponent", "timeline", "strategic")

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(path, payload, headers=None, timeout=120):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers=h)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def get(path, timeout=60):
    with op.open(urllib.request.Request(BASE + path), timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def carica(cid, nome, dati):
    confine = "----sa" + uuid.uuid4().hex
    corpo = (f"--{confine}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{nome}\"\r\n"
             f"Content-Type: application/octet-stream\r\n\r\n").encode() + dati + f"\r\n--{confine}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/cases/{cid}/documents", data=corpo,
                                 headers={"Content-Type": f"multipart/form-data; boundary={confine}"})
    with op.open(req, timeout=120) as r:
        return json.loads(r.read().decode() or "{}")


def file_del_caso(caso):
    testo = caso["testo"]
    if caso.get("formato") == "docx":
        import docx                                     # python-docx è nell'immagine (lettori e atti esportati)
        d = docx.Document()
        for riga in testo.split("\n"):
            d.add_paragraph(riga)
        buf = io.BytesIO()
        d.save(buf)
        return buf.getvalue()
    return testo.encode("utf-8")


def segui(cid, domanda, lingua):
    start = post("/api/ask/start", {"case_id": cid, "message": domanda})
    job = start.get("job_id")
    finale, tipi, fasi, errori = "", {}, set(), []
    req = urllib.request.Request(f"{BASE}/api/ask/events?job={job}&from=0")
    with op.open(req, timeout=3600) as r:
        for raw in r:
            riga = raw.decode("utf-8", "replace").strip()
            if not riga.startswith("data:"):
                continue
            try:
                ev = json.loads(riga[5:].strip())
            except Exception:  # noqa: BLE001
                continue
            t = ev.get("type") or "?"
            tipi[t] = tipi.get(t, 0) + 1
            for k in ("stage", "name", "phase", "panel"):
                if isinstance(ev.get(k), str):
                    fasi.add(ev[k])
            if t == "final":
                finale = ev.get("text") or finale
            elif t == "error":
                errori.append(str(ev)[:200])
            elif t == "done":
                break
    return finale, tipi, sorted(fasi), errori


def norme_verificate(testo, lingua):
    from pathlib import Path
    from src.retrieval import ArticleIndex
    from src import citation_verifier as cv
    idx = ArticleIndex.load(Path("/app/data/index/bm25.pkl" if lingua == "AL" else "/app/data/index/bm25_it.pkl"))
    ris = cv.verify_text(testo, idx)
    out = set()
    for d in ris.get("items") or []:                     # asdict(Citation): code, number, status…
        if d.get("status") == "verified" and d.get("code") and d.get("number"):
            num = str(d["number"])
            out.add((d["code"], num))
            out.add((d["code"], num.split("/")[0]))     # «72/2», «803/2» valgono anche per l'articolo
    return out


def valuta(caso, finale, tipi, fasi, errori, secondi):
    lingua = caso["giurisdizione"]
    sez = [bool(re.search(p, finale, re.I)) for p in SEZIONI[lingua]]
    guerra = re.findall(SALA_DI_GUERRA[lingua], finale)
    pannelli = [f for f in fasi if any(p in f for p in PANNELLI_GUERRA)]
    verif = norme_verificate(finale, lingua) if finale else set()
    tutte = [tuple(x) for x in caso.get("norme_tutte", [])]
    una_di = [tuple(x) for x in caso.get("norme_una_di", [])]
    manca_tutte = [f"{c} {n}" for c, n in tutte if (c, n) not in verif]
    ok_una = (not una_di) or any(x in verif for x in una_di)
    parole = [(p, bool(re.search(p, finale, re.I))) for p in caso.get("parole", [])]
    altra = ALTRA_LINGUA[lingua].findall(finale)
    esito = {
        "caso": caso["id"], "secondi": int(secondi), "caratteri": len(finale), "errori": errori[:3],
        "sezioni": f"{sum(sez)}/5", "sala_di_guerra_nel_testo": guerra[:4], "pannelli_di_guerra": pannelli,
        "norme_mancanti": manca_tutte, "una_di_ok": ok_una,
        "una_di_trovate": [f"{c} {n}" for c, n in una_di if (c, n) in verif],
        "parole": {p[:40]: ok for p, ok in parole}, "altra_lingua": len(altra), "esempi_altra_lingua": altra[:5],
        "tipi_eventi": tipi,
    }
    esito["passa"] = bool(finale and sum(sez) >= 4 and not guerra and not pannelli and not manca_tutte and ok_una
                          and all(ok for _, ok in parole) and len(altra) <= 2 and not errori)
    return esito


def main():
    scelti = set(sys.argv[1:])
    casi = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(CARTELLA, "*.json")))]
    casi = [c for c in casi if not scelti or c["id"] in scelti]
    os.makedirs(USCITA, exist_ok=True)
    from src import storage
    secret = os.environ.get("DEMO_PROVISION_SECRET", "")
    ts = int(time.time())
    email, code = f"misura-rishikim-{ts}@superavokati.test", f"Prova-{ts}-rk"
    atexit.register(lambda: storage.delete_user(email))
    print("provision:", post("/api/provision-demo", {"email": email, "code": code, "hours": 6,
                                                     "modules": ["avokat", "noter", "prokuror"]},
                             headers={"X-Provision-Secret": secret}), flush=True)
    u = storage.get_user_by_username(email)
    storage.set_user_jurisdictions(u.id, ["AL", "IT"])
    print(post("/api/login", {"username": email, "password": code, "lang": "sq"}), flush=True)
    try:
        post("/api/legal/accept", {})
    except Exception:  # noqa: BLE001
        pass
    esiti = []
    for caso in casi:
        lingua = caso["giurisdizione"]
        print(f"\n=== {caso['id']} ({lingua}) — {caso.get('nota', '')}", flush=True)
        post("/api/session/jurisdiction", {"jurisdiction": lingua})
        cid = post("/api/cases", {"title": f"Misura revisione — {caso['id']}", "jurisdiction": lingua})["id"]
        print("caricato:", (carica(cid, caso["nome_file"], file_del_caso(caso)).get("document") or {}).get("status"), flush=True)
        stato = None
        for _ in range(90):
            ds = get(f"/api/cases/{cid}/documents").get("documents") or []
            stato = ds[-1].get("status") if ds else None
            if stato and stato != "pending":
                break
            time.sleep(4)
        print("documento:", stato, flush=True)
        t0 = time.time()
        finale, tipi, fasi, errori = segui(cid, caso["domanda"], lingua)
        dt = time.time() - t0
        open(os.path.join(USCITA, caso["id"] + ".txt"), "w", encoding="utf-8").write(finale)
        e = valuta(caso, finale, tipi, fasi, errori, dt)
        e["documento"] = stato
        esiti.append(e)
        print(json.dumps(e, ensure_ascii=False, indent=1), flush=True)
    passati = sum(1 for e in esiti if e["passa"])
    print(f"\n== Revisione dei documenti: {passati}/{len(esiti)} casi passati ==")
    for e in esiti:
        print(f"{'✓' if e['passa'] else '✗'} {e['caso']:26s} {e['secondi']:5d}s sezioni {e['sezioni']} · norme mancanti "
              f"{e['norme_mancanti'] or '-'} · una_di {e['una_di_trovate'] or '-'} · difetti "
              f"{sum(e['parole'].values())}/{len(e['parole'])} · sala di guerra {len(e['sala_di_guerra_nel_testo']) + len(e['pannelli_di_guerra'])}"
              f" · altra lingua {e['altra_lingua']}")
    json.dump(esiti, open(os.path.join(USCITA, "esiti.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if passati == len(esiti) else 1


if __name__ == "__main__":
    sys.exit(main())
