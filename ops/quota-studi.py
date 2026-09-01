#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avviso quando uno studio si mangia l'abbonamento condiviso.

**Perche' esiste.** I limiti del piano sono DI TUTTI. Quando un solo studio li
satura, si fermano anche gli altri — che non hanno fatto niente. La fascia
dentro il pannello serve solo se qualcuno lo sta guardando; questa email
arriva anche se non lo guarda nessuno.

**Non blocca niente**: dice soltanto chi consuma quanto. Se alzare il tetto,
parlare col cliente o vendergli un piano piu' grande lo decide una persona.

⚠️ **In Python e non in bash**: sull'host `sqlite3` non e' installato
(verificato, non supposto) e non vale la pena aggiungere un pacchetto per
una query.

⚠️ **Sola lettura, su una copia.** L'app scrive nel database di continuo: un
lettore che tiene un lock puo' far fallire una scrittura in mezzo a
un'analisi legale. `mode=ro` + `.backup` in un file temporaneo.

⚠️ **Avvisa sui CAMBI di fascia**, non ogni giorno. La stessa email ogni
mattina si smette di leggerla dopo tre giorni — e allora non e' piu' un
avviso.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta

DB = "/var/www/apps/super-avvocato/data/app.db"
STATO = "/var/lib/quota-studi"
ENV_AALA = "/var/www/apps/aala/.env.local"
FROM = "AALA Monitor <njoftim@aala.global>"
TO = "info@aala.global"
SOGLIA_AVVISO = 80          # %


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
    carico = json.dumps({
        "from": FROM, "to": [TO], "subject": oggetto, "html": corpo_html,
    }, ensure_ascii=False)
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "20", "-X", "POST",
             "https://api.resend.com/emails",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "--data-binary", "@-"],
            input=carico, capture_output=True, text=True, timeout=40,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{ora()} ⚠️ invio fallito: {exc}")
        return False
    # Resend risponde {"id": "..."} se ha preso in carico. Qualunque altra
    # cosa e' un invio NON avvenuto, e va scritto: un avviso che fallisce in
    # silenzio e' peggio di nessun avviso, perche' il silenzio dice «tutto ok».
    if '"id"' not in (r.stdout or ""):
        print(f"{ora()} ⚠️ risposta Resend inattesa, email NON partita: "
              f"{(r.stdout or r.stderr or '')[:300]}")
        return False
    return True


def leggi_studi() -> list[tuple]:
    """Consumo degli ULTIMI 7 GIORNI per gli studi che hanno un tetto.

    Settimana MOBILE, non di calendario: i limiti dell'abbonamento si
    consumano cosi', e un lunedi' non azzera niente. A settimane solari il
    consumo sembrerebbe crollare ogni lunedi' senza che sia successo nulla.
    """
    if not os.access(DB, os.R_OK):
        print(f"{ora()} ⚠️ database non leggibile: {DB}")
        sys.exit(1)
    fd, copia = tempfile.mkstemp(prefix="quota-studi-", suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        dst = sqlite3.connect(copia)
        with dst:
            src.backup(dst)
        src.close()
        da = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        righe = dst.execute("""
            SELECT u.username, u.weekly_cap_micro,
                   COALESCE(SUM(a.cost_micro_usd), 0), COUNT(a.id)
            FROM users u
            LEFT JOIN ai_audit_log a
              ON a.user_id = u.id AND a.timestamp >= ?
            WHERE u.weekly_cap_micro IS NOT NULL AND u.weekly_cap_micro > 0
            GROUP BY u.id
        """, (da,)).fetchall()
        dst.close()
        return righe
    finally:
        for p in (copia, copia + "-wal", copia + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass


def main() -> None:
    os.makedirs(STATO, exist_ok=True)
    righe = leggi_studi()
    if not righe:
        print(f"{ora()} nessuno studio con tetto impostato — niente da controllare")
        return

    pezzi, gravi = [], 0
    for nome, cap, speso, chiamate in righe:
        cap, speso = int(cap or 0), int(speso or 0)
        if cap <= 0:
            continue
        pct = 100.0 * speso / cap
        fascia = "oltre" if pct >= 100 else ("vicino" if pct >= SOGLIA_AVVISO else "sotto")

        # Si avvisa solo quando la fascia CAMBIA.
        sicuro = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(nome))
        f = os.path.join(STATO, sicuro)
        try:
            prima = open(f, encoding="utf-8").read().strip()
        except OSError:
            prima = "sotto"
        try:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(fascia)
        except OSError:
            pass
        if fascia == "sotto" or fascia == prima:
            continue

        s_usd, c_usd = speso / 1e6, cap / 1e6
        if fascia == "oltre":
            gravi += 1
            pezzi.append(f"<p>⛔ <b>{nome}</b> ha superato il tetto settimanale: "
                         f"<b>{pct:.0f}%</b> (${s_usd:.2f} su ${c_usd:.2f}), "
                         f"{chiamate} chiamate.</p>")
        else:
            pezzi.append(f"<p>⚠️ <b>{nome}</b> è al <b>{pct:.0f}%</b> del tetto "
                         f"settimanale (${s_usd:.2f} su ${c_usd:.2f}), "
                         f"{chiamate} chiamate.</p>")

    if not pezzi:
        print(f"{ora()} tutti gli studi sotto soglia (o nessun cambio di fascia)")
        return

    corpo = "".join(pezzi) + (
        '<hr><p style="color:#666;font-size:13px">I limiti dell\'abbonamento sono '
        "condivisi: quando uno studio li satura, si fermano tutti. Questo avviso "
        "non blocca nulla — serve a decidere se alzare il tetto, parlare col "
        "cliente o vendergli un piano più grande.</p>")
    oggetto = (f"⛔ Abbonamento a rischio: {gravi} studio/i oltre il tetto"
               if gravi else "⚠️ Uno studio si avvicina al tetto settimanale")
    print(f"{ora()} {'✅ avviso inviato' if manda(oggetto, corpo) else '❌ avviso NON inviato'} → {TO}")


if __name__ == "__main__":
    main()
