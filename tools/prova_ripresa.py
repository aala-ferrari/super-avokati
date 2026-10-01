"""v9.441 — prova della RIPRESA DEI LAVORI dopo un riavvio: documento rimasto «pending», documento il cui file non c'è più,
analisi delle scadenze rimasta «in_corso». Elaborazione e scadenziario SIMULATI (nessun modello). DB di PROVA."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage  # noqa: E402

storage.init_db()
from src import web  # noqa: E402

ESITI: list = []
RILETTI: list = []
LANCIATI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def finto_avvia(doc, case_id, uid, juris, path, fname):
    RILETTI.append((doc.id, juris))
    storage.update_document_analysis(doc.id, extracted_text="testo", doc_type=None, summary=None, key_facts=[])


web.avvia_elaborazione_documento = finto_avvia
web._scad_lancia = lambda cid, uid, juris, ids, avvisa: LANCIATI.append((cid, uid, juris, tuple(ids), avvisa)) or len(ids)
web._BRAIN = web._BRAIN or object()

u = storage.create_user(f"prova.rip.{uuid.uuid4().hex[:6]}", "x", profession="avokat")
try:
    c = storage.create_case(u.id, "Rossi contro Alfa", jurisdiction="IT")
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    f.write(b"%PDF-1.4"); f.close()
    d1 = storage.create_document(case_id=c.id, filename="verbale.pdf", ext=".pdf", mimetype="application/pdf",
                                 size_bytes=8, storage_path=f.name)
    d2 = storage.create_document(case_id=c.id, filename="sparito.pdf", ext=".pdf", mimetype="application/pdf",
                                 size_bytes=8, storage_path="/tmp/non-esiste-" + uuid.uuid4().hex)
    d3 = storage.create_document(case_id=c.id, filename="decreto.pdf", ext=".pdf", mimetype="application/pdf",
                                 size_bytes=8, storage_path=f.name)
    storage.update_document_analysis(d3.id, extracted_text="decreto", doc_type=None, summary=None, key_facts=[])
    storage.segna_analisi_scadenze(d3.id, c.id, u.id, "in_corso")
    storage.segna_analisi_scadenze(d1.id, c.id, u.id, "in_corso")
    esito = web._riprendi_lavori_interrotti(attesa_s=0)
    ok("il documento rimasto «in lettura» si rilegge, nella giurisdizione del fascicolo", (d1.id, "IT") in RILETTI, str(RILETTI))
    g2 = storage.get_document(d2.id, c.id)
    ok("il documento senza più il file passa in errore con il motivo", g2.status == "error" and "ricarica" in (g2.error or ""),
       str((g2.status, g2.error)))
    ok("l'analisi delle scadenze interrotta riparte (con l'avviso)", any(d3.id in x[3] and x[4] for x in LANCIATI), str(LANCIATI))
    ok("… ma non per il documento riletto (riparte da solo)", not any(d1.id in x[3] for x in LANCIATI))
    ok("l'esito conta i lavori ripresi", esito == {"documenti": 1, "analisi": 1, "persi": 1}, str(esito))
    os.environ["RIPRESA_LAVORI"] = "0"
    ok("RIPRESA_LAVORI=0 spegne", web._riprendi_lavori_interrotti(attesa_s=0) == {"documenti": 0, "analisi": 0, "persi": 0})
finally:
    try:
        os.unlink(f.name)
    except Exception:  # noqa: BLE001
        pass
    try:
        storage.delete_user(u.username)
    except Exception as exc:  # noqa: BLE001
        print("pulizia:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
