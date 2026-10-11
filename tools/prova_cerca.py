"""v9.623 — prova della RICERCA NEI FASCICOLI (e, dal v9.624, dell'ARCHIVIO dei fascicoli) su un database di PROVA (client di test di Flask, nessuna richiesta vera). Si lancia
come tools/prova_link_scadenze.py (container usa-e-getta, `APP_DB_PATH` su una COPIA)."""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402

storage.init_db()
from src import web  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    cond = bool(cond)
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


suf = uuid.uuid4().hex[:6]
u1 = storage.create_user(f"prova.cerca.{suf}@esempio.it", "x")
u2 = storage.create_user(f"prova.cerca2.{suf}@esempio.it", "x")
try:
    storage.set_user_jurisdictions(u1.id, ["AL", "IT"])
    kola = storage.create_case(u1.id, "Kola — pushim", jurisdiction="AL")
    rossi = storage.create_case(u1.id, "Rossi — licenziamento", jurisdiction="IT")
    altro = storage.create_case(u2.id, "Di un altro studio", jurisdiction="AL")
    storage.add_message(kola.id, "user", "Klienti u pushua pa paralajmërim pas 9 vitesh: brenda sa ditësh bëjmë padi?")
    storage.add_message(kola.id, "assistant", "Padia ngrihet brenda 180 ditëve (neni 146 i Kodit të Punës).", kind="answer")
    storage.add_message(kola.id, "assistant", "gabim gjatë paralajmërimit", kind="error")
    storage.add_message(rossi.id, "user", "Licenziato senza preavviso dopo 9 anni: entro quando impugniamo?")
    storage.add_message(altro.id, "user", "Edhe këtu flitet për paralajmërim, por është rast i një tjetri.")
    doc = storage.create_document(case_id=kola.id, filename="Vendimi_GjRr_Tirane.pdf", ext=".pdf",
                                  mimetype="application/pdf", size_bytes=10, storage_path="/tmp/nessuno.pdf")
    storage.update_document_analysis(doc.id, extracted_text="REPUBLIKA E SHQIPËRISË — Gjykata e Rrethit Gjyqësor Tiranë. "
                                     "Vendim nr. 4417 i datës 12.03.2026 për mosmarrëveshjen e punës.",
                                     doc_type="vendim", summary="Vendim i gjykatës së shkallës së parë", key_facts=[])
    app = web.app
    app.config["TESTING"] = True
    cl = app.test_client()
    with cl.session_transaction() as s:
        s["user_id"] = u1.id
        s["jurisdiction"] = "AL"

    def cerca(client, q):
        r = client.get("/api/cases/search", query_string={"q": q})
        return r.status_code, (r.get_json(silent=True) or {})

    st, d = cerca(cl, "paralajmerim")
    ids = [x["case_id"] for x in d.get("results", [])]
    ok("senza la ë trova la domanda col «paralajmërim»", st == 200 and ids == [kola.id]
       and any("paralajmërim" in h["brano"] for h in d["results"][0]["hits"]), repr(d)[:300])
    ok("gli errori del cervello e i fascicoli di un altro avvocato restano fuori",
       all(h.get("role") != "assistant" or "gabim" not in h["brano"] for h in d["results"][0]["hits"]) and altro.id not in ids)
    st, d = cerca(cl, "KODIT TE PUNES")
    ok("maiuscole e diacritici non contano, trova la risposta", st == 200 and d.get("results")
       and d["results"][0]["hits"][0]["role"] == "assistant", repr(d)[:300])
    st, d = cerca(cl, "4417")
    hit = (d.get("results") or [{}])[0].get("hits", [{}])[0] if d.get("results") else {}
    ok("trova nel testo letto di un documento caricato, col nome del file", hit.get("tipo") == "documento"
       and hit.get("filename") == "Vendimi_GjRr_Tirane.pdf" and "4417" in hit.get("brano", ""), repr(d)[:300])
    st, d = cerca(cl, "preavviso")
    ok("in sessione albanese il fascicolo italiano non esiste", st == 200 and d.get("results") == [], repr(d)[:200])
    with cl.session_transaction() as s:
        s["jurisdiction"] = "IT"
    st, d = cerca(cl, "preavviso")
    ok("in sessione italiana sì", st == 200 and [x["case_id"] for x in d.get("results", [])] == [rossi.id], repr(d)[:200])
    st, d = cerca(cl, "ab")
    ok("meno di 3 lettere → nessuna ricerca", st == 200 and d.get("results") == [])
    st, d = cerca(cl, "100%_")
    ok("i caratteri speciali non diventano jolly", st == 200 and d.get("results") == [], repr(d)[:200])
    ok("senza sessione → 401", app.test_client().get("/api/cases/search?q=paralajmerim").status_code == 401)

    # v9.624 — archiviare un fascicolo chiuso
    with cl.session_transaction() as s:
        s["jurisdiction"] = "AL"
    r = cl.patch(f"/api/cases/{kola.id}/archive", json={"archived": True})
    elenco = {c["id"]: c for c in (cl.get("/api/cases").get_json() or {}).get("cases", [])}
    ok("archiviato: resta nell'elenco col segno «archiviato»", r.status_code == 200 and elenco.get(kola.id, {}).get("archived") is True,
       f"{r.status_code} {elenco.get(kola.id)}")
    st, d = cerca(cl, "paralajmerim")
    ok("un fascicolo archiviato si trova ancora con la ricerca, segnato", st == 200 and d.get("results")
       and d["results"][0].get("archived") is True, repr(d)[:200])
    ok("aperto, dice di essere archiviato", (cl.get(f"/api/cases/{kola.id}").get_json() or {}).get("archived_at"))
    cl2 = app.test_client()
    with cl2.session_transaction() as s:
        s["user_id"] = u2.id
        s["jurisdiction"] = "AL"
    ok("un altro avvocato non archivia il fascicolo altrui → 404",
       cl2.patch(f"/api/cases/{kola.id}/archive", json={"archived": False}).status_code == 404)
    r = cl.patch(f"/api/cases/{kola.id}/archive", json={"archived": False})
    elenco = {c["id"]: c for c in (cl.get("/api/cases").get_json() or {}).get("cases", [])}
    ok("riportato tra gli attivi", r.status_code == 200 and elenco.get(kola.id, {}).get("archived") is False
       and (cl.get(f"/api/cases/{kola.id}").get_json() or {}).get("archived_at") is None)
    html = cl.get("/").get_data(as_text=True)
    ok("la casella di ricerca sta sopra l'elenco dei fascicoli",
       'id="case-search"' in html and html.find('id="case-search"') < html.find('id="case-list"'))
finally:
    for u in (u1, u2):
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
