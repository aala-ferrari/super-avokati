#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron settimanale: la legge in corpus è ancora quella vigente? (Super Avokati, 16 set 2026)

Gira sull'HOST (non dentro il container: niente da riavviare, il cervello non se ne accorge):
  1. lancia tools/freshness_check.py it al (Normattiva, EUR-Lex, QBZ) con i percorsi del volume;
  2. scrive il log datato in LOG_DIR e l'ultimo esito in data/freshness_last.json;
  3. manda un'email (Resend, stesso canale di quota-studi/uptime) SOLO se c'è qualcosa da fare:
       🔴 STALE/REPEALED → leggi da riscaricare o sostituite,
       🟡 UNKNOWN/ERROR ≥ SOGLIA_INCOMPLETO → il controllo non ha potuto leggere la fonte
          (EUR-Lex dietro AWS WAF: dopo una raffica risponde 202 vuoto per un po').
     Nessuna email = tutto OK (si legge il log). `--dry` = nessuna email, solo stampa.

Installazione (fatta il 16 set): /opt/freshness-cron.py + crontab «20 6 * * 1» (lunedì).
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

APP = Path("/var/www/apps/super-avvocato")
CHECK = APP / "tools" / "freshness_check.py"
LOG_DIR = Path("/var/log/superavokati")
LAST = APP / "data" / "freshness_last.json"
ENV_AALA = "/var/www/apps/aala/.env.local"          # RESEND_API_KEY (come quota-studi.py)
FROM = "AALA Monitor <njoftim@aala.global>"
TO = "info@aala.global"
SOGLIA_INCOMPLETO = 8


def ora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def chiave_resend() -> str:
    try:
        with open(ENV_AALA, encoding="utf-8") as f:
            for riga in f:
                if riga.startswith("RESEND_API_KEY="):
                    return riga.split("=", 1)[1].strip().strip('"').strip()
    except OSError:
        pass
    return ""


def manda(oggetto: str, corpo_html: str) -> bool:
    key = chiave_resend()
    if not key:
        print(f"{ora()} ⚠️ RESEND_API_KEY assente: nessun avviso puo' partire")
        return False
    carico = json.dumps({"from": FROM, "to": [TO], "subject": oggetto, "html": corpo_html}, ensure_ascii=False)
    try:
        r = subprocess.run(["curl", "-s", "-m", "20", "-X", "POST", "https://api.resend.com/emails",
                            "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
                            "--data-binary", "@-"], input=carico, capture_output=True, text=True, timeout=40)
    except Exception as exc:  # noqa: BLE001
        print(f"{ora()} ⚠️ invio fallito: {exc}")
        return False
    if '"id"' not in (r.stdout or ""):
        # un avviso che fallisce in silenzio è peggio di nessun avviso: lo si scrive
        print(f"{ora()} ⚠️ risposta Resend inattesa, email NON partita: {(r.stdout or r.stderr)[:200]}")
        return False
    print(f"{ora()} ✉️ email inviata a {TO}: {oggetto}")
    return True


def main() -> int:
    dry = "--dry" in sys.argv
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"freshness-{datetime.now():%Y%m%d}.log"
    env = dict(os.environ, IT_ACTS_DIR=str(APP / "data" / "processed" / "it_acts"),
               AL_SOURCES=str(APP / "tools" / "al_sources.json"), PYTHONUNBUFFERED="1")
    print(f"{ora()} avvio controllo freschezza → {log}")
    with open(log, "w", encoding="utf-8") as fh:
        p = subprocess.run([sys.executable, str(CHECK), "it", "al", "--json", str(LAST)],
                           cwd=str(APP / "tools"), env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=3600)
    try:
        rows = json.loads(LAST.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"{ora()} ⚠️ esito non leggibile ({exc}); exit del controllo {p.returncode}")
        if not dry:
            manda("🟡 Super Avokati — controllo leggi NON eseguito", f"<p>freshness_check non ha prodotto l'esito (exit {p.returncode}). Log: {log}</p>")
        return 2
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    bad = [r for r in rows if r["status"] in ("STALE", "REPEALED")]
    unk = [r for r in rows if r["status"] in ("UNKNOWN", "ERROR")]
    riep = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"{ora()} esito: {riep}")
    for r in bad + unk:
        print(f"   {r['status']:8s} {r['lang']}:{r['code']:30s} {r.get('note', '')[:100]}")
    # leggi da aggiornare / sostituite: l'avvocato non deve citare legge morta
    if bad:
        # v9.390 — il d.P.R. 309/1990 porta con sé le TABELLE delle sostanze (dizionario a parte): vanno rilette anche loro
        _extra = {"stupefacenti": " — rileggere anche le tabelle delle sostanze: <code>tools/ingest_tabelle_stupefacenti.py</code>",
                  # v9.392 — la 7975/1995 porta le LISTE delle sostanze in figure e lo schema dei gruppi: dopo l'ingest, riparazione
                  # dell'atto (capi, allegato, schema, rimando 61/2023) e rilettura delle figure
                  "ligji_lendet_narkotike": " — poi <code>tools/repair_lendet_narkotike.py --apply</code> e rileggere le liste delle "
                                            "sostanze: <code>tools/ingest_liste_narkotike_al.py</code>"}
        righe = "".join(f"<li><b>{r['lang']}:{r['code']}</b> — {r['status']}: {r.get('note', '')}{_extra.get(r['code'], '')}</li>" for r in bad)
        corpo = (f"<p>Controllo di freschezza del corpus ({ora()}): <b>{len(bad)} atti da aggiornare o sostituiti</b>.</p><ul>{righe}</ul>"
                 f"<p>Riepilogo: {riep}. Log: {log}<br>Rimedio: rilanciare l'ingest dell'atto (Normattiva: <code>tools/ingest_it_normattiva.py &lt;id&gt;</code>; "
                 f"EUR-Lex: <code>tools/ingest_eurlex.py &lt;id&gt;</code>; QBZ: aggiornare tools/al_sources.json e <code>tools/ingest_al_qbz.py probe/apply</code>), "
                 f"poi ricostruire l'indice e fare il deploy a server libero.</p>")
        if not dry:
            manda(f"🔴 Super Avokati — {len(bad)} leggi da aggiornare (controllo settimanale)", corpo)
    elif len(unk) >= SOGLIA_INCOMPLETO:
        righe = "".join(f"<li>{r['lang']}:{r['code']} — {r.get('note', '')}</li>" for r in unk[:30])
        corpo = (f"<p>Controllo di freschezza ({ora()}): nessuna legge da aggiornare tra quelle lette, ma <b>{len(unk)} atti non verificabili</b> "
                 f"(fonte non raggiungibile — EUR-Lex dietro WAF risponde pagine vuote dopo una raffica).</p><ul>{righe}</ul><p>Riepilogo: {riep}. Log: {log}. "
                 f"Rimedio: rilanciare tra qualche ora <code>python3 /opt/freshness-cron.py</code>.</p>")
        if not dry:
            manda(f"🟡 Super Avokati — controllo leggi incompleto ({len(unk)} non verificabili)", corpo)
    else:
        print(f"{ora()} tutto OK: nessuna email")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
