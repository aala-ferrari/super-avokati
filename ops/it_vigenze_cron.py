#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron notturno: una data di VIGENZA del corpus italiano è arrivata? (Super Avokati v9.405, 29 set 2026)

Dal v9.405 il corpus italiano ha il testo in vigore OGGI e, per ogni articolo che cambia (o si abroga, o entra in vigore) più
avanti, la versione futura con la sua data (`tools/riallinea_vigenti_it.py`). L'indice (`build_it_index.py`) usa il testo giusto
per la data del BUILD e scrive le date ancora da venire in `it_corrispondenze.json` (`_vigenze`). Quando una di quelle date
arriva (il 1° gennaio 2027: i sette testi unici fiscali si applicano e i vecchi atti sono abrogati) l'indice va ricostruito:
fino ad allora verificatore e blocco degli articoli si reggono sulla rete (`corrispondenze_tu.vigenza_scaduta`), ma il BM25 e il
testo dato al modello restano quelli di prima.

Gira sull'HOST ogni notte:
  1. legge `_vigenze` dal volume; se nessuna data è arrivata, esce in silenzio;
  2. altrimenti ricostruisce l'indice DENTRO il container vivo (`tools/build_it_index.py`) e lo fa ricaricare con il riavvio
     guardato (`ops/restart_when_idle.sh`: mai durante l'analisi di un avvocato);
  3. controlla che nella mappa nuova non restino date passate e manda un'email (Resend, stesso canale della freschezza).
`--dry` = nessuna azione, solo stampa.

Installazione: /opt/it-vigenze-cron.py + crontab «25 0 * * *».
"""
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

APP = Path("/var/www/apps/super-avvocato")
MAPPA = APP / "data" / "processed" / "it_corrispondenze.json"
RESTART = APP / "ops" / "restart_when_idle.sh"
ENV_AALA = "/var/www/apps/aala/.env.local"
FROM = "AALA Monitor <njoftim@aala.global>"
TO = "info@aala.global"


def ora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def scadute(mappa: dict, oggi: str) -> list[str]:
    out = []
    for code, arts in ((mappa.get("_vigenze") or {}).items()):
        for num, v in (arts or {}).items():
            d = (v or {}).get("non_in_vigore_dal") or (v or {}).get("dal") or ""
            if d and d <= oggi:
                out.append(f"{code} art. {num} ({d})")
    return out


def chiave_resend() -> str:
    try:
        with open(ENV_AALA, encoding="utf-8") as f:
            for riga in f:
                if riga.startswith("RESEND_API_KEY="):
                    return riga.split("=", 1)[1].strip().strip('"').strip()
    except OSError:
        pass
    return ""


def manda(oggetto: str, corpo_html: str) -> None:
    key = chiave_resend()
    if not key:
        print(f"{ora()} ⚠️ RESEND_API_KEY assente: nessun avviso")
        return
    carico = json.dumps({"from": FROM, "to": [TO], "subject": oggetto, "html": corpo_html}, ensure_ascii=False)
    r = subprocess.run(["curl", "-s", "-m", "20", "-X", "POST", "https://api.resend.com/emails",
                        "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
                        "--data-binary", "@-"], input=carico, capture_output=True, text=True, timeout=40)
    if '"id"' not in (r.stdout or ""):
        print(f"{ora()} ⚠️ email NON partita: {(r.stdout or r.stderr)[:200]}")


def main() -> int:
    dry = "--dry" in sys.argv
    oggi = date.today().isoformat()
    try:
        mappa = json.loads(MAPPA.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"{ora()} ⚠️ mappa illeggibile: {exc}")
        return 1
    arrivate = scadute(mappa, oggi)
    if not arrivate:
        return 0
    print(f"{ora()} date di vigenza arrivate: {len(arrivate)} articoli — {', '.join(arrivate[:8])}"
          + (" …" if len(arrivate) > 8 else ""))
    if dry:
        print(f"{ora()} (a secco: niente ricostruzione)")
        return 0
    b = subprocess.run(["docker", "exec", "super-avvocato", "python3", "tools/build_it_index.py"],
                       capture_output=True, text=True, timeout=3600)
    print((b.stdout or "")[-1500:])
    if b.returncode != 0:
        print(f"{ora()} ⚠️ build_it_index FALLITO: {(b.stderr or '')[-800:]}")
        manda("⚠️ Super Avokati — indice italiano NON ricostruito",
              f"<p>Data di vigenza arrivata per {len(arrivate)} articoli ma <b>build_it_index è fallito</b>.</p>"
              f"<pre>{(b.stderr or '')[-1500:]}</pre>")
        return 1
    r = subprocess.run(["bash", str(RESTART)], capture_output=True, text=True, timeout=4 * 3600)
    print((r.stdout or "")[-800:])
    try:
        resto = scadute(json.loads(MAPPA.read_text(encoding="utf-8")), oggi)
    except Exception:  # noqa: BLE001
        resto = ["(mappa illeggibile dopo il build)"]
    esito = "✅" if not resto else "⚠️"
    manda(f"{esito} Super Avokati — indice italiano aggiornato alla vigenza del {oggi}",
          f"<p>Sono entrati in vigore i testi nuovi di <b>{len(arrivate)}</b> articoli: l'indice italiano è stato "
          f"ricostruito e ricaricato (riavvio guardato).</p><p>{'<br>'.join(arrivate[:40])}</p>"
          + (f"<p>⚠️ Restano date passate nella mappa: {', '.join(resto[:10])}</p>" if resto else ""))
    return 0 if not resto else 1


if __name__ == "__main__":
    sys.exit(main())
