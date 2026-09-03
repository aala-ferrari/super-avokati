#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[2️⃣] Digest javor — l'email del lunedì che raggiunge l'avvocato.

Il «Brifing i ditës» esiste gia' DENTRO l'app: lo vedi solo se apri. Questa
e' la versione che ti raggiunge — il pattern «renewal-watcher» della suite
Apache di Anthropic, scritto da noi sul canale gia' rodato (Resend, come il
monitor e quota-studi).

Per ogni utente attivo con un indirizzo email: le scadenze dei prossimi 7
giorni, gli impegni scaduti e non chiusi, i fascicoli fermi da 30+ giorni.
**Se non c'e' nulla da dire, l'email NON parte**: un digest vuoto ogni
lunedi' insegna a ignorare anche quello pieno.

⚠️ Sola lettura su una COPIA del db (stesso schema di quota-studi.py): l'app
scrive di continuo e un lettore col lock puo' far fallire una scrittura in
mezzo a un'analisi.

Uso:
  digest-javor.py                    # invio vero a tutti gli aventi diritto
  digest-javor.py --prova EMAIL      # genera il digest di admin e lo manda
                                     # SOLO a EMAIL (collaudo senza disturbare)
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta

DB = "/var/www/apps/super-avvocato/data/app.db"
ENV_AALA = "/var/www/apps/aala/.env.local"
FROM = "Super Avokati <njoftim@aala.global>"


def ora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def chiave_resend() -> str:
    try:
        with open(ENV_AALA, encoding="utf-8") as f:
            for r in f:
                if r.startswith("RESEND_API_KEY="):
                    return r.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def manda(a: str, oggetto: str, html: str) -> bool:
    key = chiave_resend()
    if not key:
        print(f"{ora()} ⚠️ RESEND_API_KEY assente")
        return False
    carico = json.dumps({"from": FROM, "to": [a], "subject": oggetto,
                         "html": html}, ensure_ascii=False)
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "20", "-X", "POST",
             "https://api.resend.com/emails",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "--data-binary", "@-"],
            input=carico, capture_output=True, text=True, timeout=40)
    except Exception as exc:  # noqa: BLE001
        print(f"{ora()} ⚠️ invio fallito ({a}): {exc}")
        return False
    if '"id"' not in (r.stdout or ""):
        print(f"{ora()} ⚠️ Resend inatteso ({a}): {(r.stdout or '')[:200]}")
        return False
    return True


def copia_db() -> sqlite3.Connection:
    fd, tmp = tempfile.mkstemp(prefix="digest-", suffix=".db")
    os.close(fd)
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close()
    dst.row_factory = sqlite3.Row
    # il file temporaneo si toglie a fine processo
    import atexit
    atexit.register(lambda: [os.unlink(p) for p in (tmp,)
                             if os.path.exists(p)])
    return dst


# ── i testi, nelle due lingue ─────────────────────────────────────────
T = {
    "sq": {
        "subj": "📅 Java jote — Super Avokati",
        "hi": "Përshëndetje {u} — ja java që të pret:",
        "afate": "⏰ 7 ditët e ardhshme",
        "skaduar": "🔴 Të skaduara e të pambyllura: <b>{n}</b> — hapi kalendarin dhe mbylli ose rishtyji.",
        "ferma": "😴 Fashikuj pa lëvizje prej 30+ ditësh",
        "asgje_afate": "(asnjë afat — javë e qetë)",
        "foot": "Ky përmbledhje niset çdo të hënë. Detajet i gjen te kalendari dhe fashikujt në superavokati.ai.",
    },
    "it": {
        "subj": "📅 La tua settimana — Super Avokati",
        "hi": "Ciao {u} — ecco la settimana che ti aspetta:",
        "afate": "⏰ Prossimi 7 giorni",
        "skaduar": "🔴 Scaduti e non chiusi: <b>{n}</b> — apri il calendario e chiudili o rimandali.",
        "ferma": "😴 Fascicoli fermi da 30+ giorni",
        "asgje_afate": "(nessuna scadenza — settimana tranquilla)",
        "foot": "Questo riepilogo parte ogni lunedì. I dettagli sono nel calendario e nei fascicoli su superavokati.ai.",
    },
}


def lingua_di(jur: str | None) -> str:
    j = (jur or "").upper()
    return "it" if ("IT" in j and "AL" not in j) else "sq"


def digest_per(c, u) -> tuple[str, str] | None:
    """(oggetto, html) per un utente — None se non c'e' nulla da dire."""
    adesso = datetime.now(UTC)
    a7 = (adesso + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    oggi = adesso.strftime("%Y-%m-%dT%H:%M:%SZ")
    t = T[lingua_di(u["jurisdictions"])]

    prossimi = c.execute(
        "SELECT title, starts_at FROM events WHERE user_id=? AND done=0 "
        "AND starts_at >= ? AND starts_at <= ? ORDER BY starts_at LIMIT 8",
        (u["id"], oggi, a7)).fetchall()
    scaduti = c.execute(
        "SELECT COUNT(*) FROM events WHERE user_id=? AND done=0 "
        "AND starts_at < ?", (u["id"], oggi)).fetchone()[0]
    trenta = (adesso - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fermi = c.execute(
        "SELECT title FROM cases WHERE user_id=? AND updated_at < ? "
        "ORDER BY updated_at LIMIT 3", (u["id"], trenta)).fetchall()

    if not prossimi and not scaduti and not fermi:
        return None

    p = [f"<p>{t['hi'].format(u=u['username'])}</p>",
         f"<h3>{t['afate']}</h3>"]
    if prossimi:
        p.append("<ul>")
        for e in prossimi:
            data = (e["starts_at"] or "")[:16].replace("T", " · ")
            p.append(f"<li><b>{data}</b> — {e['title']}</li>")
        p.append("</ul>")
    else:
        p.append(f"<p>{t['asgje_afate']}</p>")
    if scaduti:
        p.append(f"<p>{t['skaduar'].format(n=scaduti)}</p>")
    if fermi:
        p.append(f"<h3>{t['ferma']}</h3><ul>")
        for f in fermi:
            p.append(f"<li>{(f['title'] or '')[:60]}</li>")
        p.append("</ul>")
    p.append(f"<hr><p style='color:#888;font-size:12px'>{t['foot']}</p>")
    return t["subj"], "".join(p)


def main() -> None:
    prova = None
    if "--prova" in sys.argv:
        prova = sys.argv[sys.argv.index("--prova") + 1]
    c = copia_db()
    utenti = c.execute(
        "SELECT id, username, reminder_email, jurisdictions, suspended "
        "FROM users WHERE COALESCE(suspended,0)=0").fetchall()
    inviati = saltati = 0
    for u in utenti:
        if prova and u["username"] != "admin":
            continue
        dest = prova or (u["reminder_email"] or "").strip() \
            or (u["username"] if "@" in (u["username"] or "") else "")
        if not dest:
            saltati += 1
            continue
        d = digest_per(c, u)
        if d is None:
            continue                      # niente da dire → niente email
        ok = manda(dest, d[0], d[1])
        print(f"{ora()} {'✅' if ok else '❌'} {u['username']} → {dest}")
        inviati += 1 if ok else 0
    print(f"{ora()} digest: {inviati} inviati · {saltati} senza indirizzo")


if __name__ == "__main__":
    main()
