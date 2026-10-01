"""v9.444 — MISURA del Vault («Pyet dokumentet / Chiedi ai documenti») su un FASCICOLO LUNGO: la risposta sta in fondo (pagina
55 di 60, gli atti più recenti stanno lì). Prima il Vault leggeva i primi 9.000 caratteri per documento e rispondeva «non si trova
nei documenti» con sicurezza. DB di PROVA (`APP_DB_PATH` su una COPIA); due domande al modello per sessione.

    docker run --rm … -e APP_DB_PATH=/tqa/app.db … super-avvocato:vX python3 tools/eval_vault.py
"""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import storage, brain, vault  # noqa: E402
from src.backends import build_backend  # noqa: E402

storage.init_db()

PAGINE = []
for i in range(1, 61):
    corpo = ("Il difensore richiama le deduzioni istruttorie già formulate e si oppone all'ammissione dei capitoli avversari. " * 12)
    if i == 55:
        corpo += ("\nIl Giudice dispone consulenza tecnica d'ufficio e nomina CTU l'ing. Marco Bellini, fissando per il giuramento "
                  "l'udienza del 9 dicembre 2026; il consulente depositerà la relazione entro novanta giorni.")
    PAGINE.append(f"── Pagina {i}/60 ──\n{corpo}")
TESTO = "\n\n".join(PAGINE)
DOMANDE = [("Chi è stato nominato consulente tecnico d'ufficio e quando giura?", ("bellini", "9 dicembre")),
           ("Quale udienza viene citata nella prima pagina?", None)]


def main() -> int:
    u = storage.create_user(f"prova.vault.{uuid.uuid4().hex[:6]}", "x", profession="avokat")
    try:
        brain.set_request_user(u.id)
        brain.set_request_jurisdiction("IT")
        c = storage.create_case(u.id, "Rossi contro Alfa", jurisdiction="IT")
        d = storage.create_document(case_id=c.id, filename="fascicolo_rossi.pdf", ext=".pdf", mimetype="application/pdf",
                                    size_bytes=len(TESTO), storage_path="/tmp/non-serve.pdf")
        storage.update_document_analysis(d.id, extracted_text=TESTO, doc_type="Fascicolo", summary=None, key_facts=[])
        try:
            ctx, used, _n = vault.build_context(c.id, DOMANDE[0][0])
        except TypeError:                          # codice di prima della v9.444 (senza la domanda)
            ctx, used, _n = vault.build_context(c.id)
        print(f"contesto: {len(ctx)} caratteri; la pagina 55 c'è: {'Bellini' in ctx}")
        cervello = SimpleNamespace(backend=build_backend())
        q, attese = DOMANDE[0]
        r = vault.ask(cervello, c.id, q)
        a = (r.get("answer") or "").lower()
        ok = all(x in a for x in attese)
        print(f"{'✓' if ok else '✗'} {q}\n   → {a[:300]}")
        print(f"\nTOTALE: {int(ok)}/1")
    finally:
        try:
            storage.delete_user(u.username)
        except Exception as exc:  # noqa: BLE001
            print("pulizia:", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
