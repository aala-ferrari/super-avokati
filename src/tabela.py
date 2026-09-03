"""Tabela e Dosjes — la logica pura, senza Flask e senza cervello.

Vive separata da web.py per una ragione sola: le guardie golden la PROVANO
eseguendola (la lezione di casa: su questo codice la lettura statica mente).
"""
from __future__ import annotations

import json
import re

MAX_DOKUMENTE = 30       # righe: oltre, la tabella non si legge piu'
MAX_PYETJE = 8           # colonne: oltre, ogni cella diventa un francobollo
TEKST_MAX = 14_000       # caratteri di documento per chiamata (Sonnet, veloce)

SISTEMI = (
    "Je nje nxjerres faktesh nga NJE dokument i vetem.\n"
    "RREGULLA TE PANEGOCIUESHME:\n"
    "1. Pergjigju VETEM nga teksti i dhene. Asgje nga jashte.\n"
    "2. Nese dokumenti nuk e permban pergjigjen: found=false, answer=\"—\".\n"
    "   MOS hamendeso kurre — nje qelize bosh vlen, nje e shpikur demton.\n"
    "3. quote = citim TEKSTUAL nga dokumenti (max 200 karaktere) qe e\n"
    "   mbeshtet pergjigjen; bosh kur found=false.\n"
    "4. Pergjigju ne gjuhen e PYETJES.\n"
    "5. Kthe VETEM JSON: nje liste me nje objekt per pyetje, ne te njejtin\n"
    "   rend: [{\"answer\": \"...\", \"quote\": \"...\", \"found\": true}]"
)


def pastro_pyetjet(grezze) -> list[str]:
    """Pulisce e limita le domande: una per riga, niente vuote, max colonne."""
    if not isinstance(grezze, list):
        return []
    viste, fuori = set(), []
    for q in grezze:
        q = str(q or "").strip()
        if not q or q.lower() in viste:
            continue
        viste.add(q.lower())
        fuori.append(q[:300])
        if len(fuori) >= MAX_PYETJE:
            break
    return fuori


def pergatit_prompt(filename, doc_type, summary, text, pyetjet) -> str:
    kreu = ["DOKUMENTI: " + str(filename or "?")]
    if doc_type:
        kreu.append(f"Lloji: {doc_type}")
    if summary:
        kreu.append(f"Permbledhja: {summary}")
    kreu.append("")
    kreu.append("TEKSTI I DOKUMENTIT:")
    kreu.append((text or "").strip()[:TEKST_MAX])
    kreu.append("")
    kreu.append(f"PYETJET ({len(pyetjet)}):")
    for i, q in enumerate(pyetjet, 1):
        kreu.append(f"{i}. {q}")
    kreu.append("")
    kreu.append("Kthe VETEM listen JSON, nje objekt per pyetje, ne rend.")
    return "\n".join(kreu)


def parse_qeliza(raw: str, n: int) -> list[dict]:
    """Dal testo del modello alla riga di celle, con tolleranza.

    Accetta: lista nuda, lista dentro recinti ```, oggetto {"answers": [...]}
    o prosa attorno alla lista. Normalizza SEMPRE a `n` celle: il modello a
    volte ne salta una, e una tabella sfasata di una colonna e' peggio di
    una cella vuota.
    """
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    dati = None
    try:
        dati = json.loads(s)
    except Exception:
        m = re.search(r"\[.*\]", s, re.DOTALL)
        if m:
            try:
                dati = json.loads(m.group(0))
            except Exception:
                pass
    if isinstance(dati, dict):
        dati = dati.get("answers") or dati.get("cells") or dati.get("items")
    if not isinstance(dati, list):
        raise ValueError("pergjigje pa liste JSON")

    celle = []
    for x in dati[:n]:
        if not isinstance(x, dict):
            x = {"answer": str(x)}
        celle.append({
            "answer": str(x.get("answer") or "—")[:600],
            "quote": str(x.get("quote") or "")[:240],
            "found": bool(x.get("found", bool(str(x.get("answer") or "").strip("— ")))),
        })
    while len(celle) < n:
        celle.append({"answer": "—", "quote": "", "found": False})
    return celle
