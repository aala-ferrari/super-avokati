"""v9.625 — prova di «SCARICA I MIEI DATI» (tutti i fascicoli della sessione in un .zip) su un database di PROVA (client di test di
Flask, nessuna richiesta vera). Si lancia come tools/prova_link_scadenze.py (container usa-e-getta, `APP_DB_PATH` su una COPIA)."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

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
u1 = storage.create_user(f"prova.export.{suf}@esempio.it", "x")
u2 = storage.create_user(f"prova.export2.{suf}@esempio.it", "x")
cartella = Path(tempfile.mkdtemp())
try:
    storage.set_user_jurisdictions(u1.id, ["AL", "IT"])
    kola = storage.create_case(u1.id, "Kola — pushim pa paralajmërim", jurisdiction="AL")
    rossi = storage.create_case(u1.id, "Rossi — licenziamento", jurisdiction="IT")
    altro = storage.create_case(u2.id, "Di un altro avvocato", jurisdiction="AL")
    storage.add_message(kola.id, "user", "Klienti u pushua pa paralajmërim: brenda sa ditësh bëjmë padi?")
    storage.add_message(kola.id, "assistant", "Padia ngrihet brenda 180 ditëve (neni 146 i Kodit të Punës).", kind="answer")
    storage.add_message(rossi.id, "user", "Licenziato senza preavviso: entro quando impugniamo?")
    storage.add_message(altro.id, "user", "Un fascicolo che non deve uscire.")
    contenuto = b"%PDF-1.4 prova del documento originale \x00\x01\x02"
    f = cartella / "orig.pdf"
    f.write_bytes(contenuto)
    doc = storage.create_document(case_id=kola.id, filename="Vendimi i shkallës së parë.pdf", ext=".pdf",
                                  mimetype="application/pdf", size_bytes=len(contenuto), storage_path=str(f))
    storage.create_document(case_id=kola.id, filename="sparito.pdf", ext=".pdf", mimetype="application/pdf",
                            size_bytes=1, storage_path=str(cartella / "non-esiste.pdf"))
    storage.save_research(kola.id, None, u1.id, source="answer", title="Afati i padisë", content="180 ditë nga njoftimi.")
    app = web.app
    app.config["TESTING"] = True
    cl = app.test_client()
    with cl.session_transaction() as s:
        s["user_id"] = u1.id
        s["jurisdiction"] = "AL"
    r = cl.get("/api/me/export")
    ok("risponde con un .zip", r.status_code == 200 and r.mimetype == "application/zip"
       and "attachment" in (r.headers.get("Content-Disposition") or ""), f"{r.status_code} {r.mimetype}")
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    nomi = zf.namelist()
    radice = nomi[0].split("/")[0] if nomi else ""
    def trova(fine):
        return [n for n in nomi if n.endswith(fine)]
    ok("dentro: la conversazione leggibile e completa del fascicolo", trova("/rasti.md") and trova("/rasti.json"), repr(nomi)[:400])
    md = zf.read(trova("/rasti.md")[0]).decode("utf-8") if trova("/rasti.md") else ""
    ok("la conversazione in albanese, con la domanda e la risposta", "# Kola" in md and "🧑 Avokati" in md and "180 ditëve" in md)
    js = json.loads(zf.read(trova("/rasti.json")[0])) if trova("/rasti.json") else {}
    ok("il .json ha tutti i messaggi", len(js.get("messages", [])) == 2 and js.get("case", {}).get("id") == kola.id)
    pdf = [n for n in nomi if "/dokumente/" in n]
    ok("il documento caricato, originale e col suo nome", len(pdf) == 1 and pdf[0].endswith("Vendimi i shkallës së parë.pdf")
       and zf.read(pdf[0]) == contenuto, repr(pdf))
    ok("la ricerca salvata", [n for n in nomi if "/kerkime/" in n and n.endswith("Afati i padisë.md")])
    ok("l'agenda e la nota «leggimi» in albanese", trova("/agjenda.json") and trova("/LEXOMË.txt")
       and "raste: 1" in zf.read(trova("/LEXOMË.txt")[0]).decode("utf-8"), repr(nomi)[:300])
    ok("fuori il fascicolo italiano (altra sessione) e quello di un altro avvocato",
       not [n for n in nomi if "Rossi" in n or "altro avvocato" in n], repr(nomi)[:300])
    ok("tutto dentro una cartella con la data", radice.startswith("super-avokati-") and all(n.startswith(radice + "/") for n in nomi))
    with storage.db() as conn:
        n_log = conn.execute("SELECT COUNT(*) AS n FROM case_access_log WHERE case_id = ? AND action = 'export'",
                             (kola.id,)).fetchone()["n"]
    ok("l'esportazione finisce nel registro degli accessi", n_log == 1, str(n_log))
    with cl.session_transaction() as s:
        s["jurisdiction"] = "IT"
    r = cl.get("/api/me/export")
    nomi_it = zipfile.ZipFile(io.BytesIO(r.data)).namelist() if r.status_code == 200 else []
    ok("in sessione italiana: il fascicolo italiano, coi nomi in italiano",
       r.status_code == 200 and any(n.endswith("/fascicolo.md") and "Rossi" in n for n in nomi_it)
       and any(n.endswith("/LEGGIMI.txt") for n in nomi_it) and not any("Kola" in n for n in nomi_it), repr(nomi_it)[:300])
    st = [cl.get("/api/me/export").status_code for _ in range(2)]
    ok("al massimo 3 esportazioni l'ora", st == [200, 429], repr(st))
    ok("senza sessione → 401", app.test_client().get("/api/me/export").status_code == 401)
    with cl.session_transaction() as s:
        s["jurisdiction"] = "AL"
    r = cl.get(f"/api/cases/{kola.id}/export?format=md")
    ok("l'esportazione del singolo fascicolo è rimasta uguale", r.status_code == 200 and r.data.decode("utf-8") == md,
       r.data.decode("utf-8")[:120])
    r = cl.get(f"/api/cases/{kola.id}/export")
    ok("e quella completa .json", r.status_code == 200 and json.loads(r.data) == js)
finally:
    for u in (u1, u2):
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
