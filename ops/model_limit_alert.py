# -*- coding: utf-8 -*-
"""Avviso email quando un modello entra in PAUSA per limite di quota (v9.344, 17 set 2026).

Il backend (`src/backends.py`) scrive `data/model_limit.json` sul volume ogni volta che la CLI
risponde «You've reached your Fable limit» e passa a Opus max. Questo cron sull'host (che ha la
chiave Resend, il container no) legge gli eventi nuovi e manda UNA email per evento, così il
titolare lo sa prima che lo scopra un avvocato. Stato in `/var/log/superavokati/model_limit_notified.json`.

    */10 * * * * /usr/bin/python3 /opt/model-limit-alert.py >> /var/log/superavokati/model_limit_alert.log 2>&1
"""
import json, subprocess, sys, time
from pathlib import Path

EVENTI = Path("/var/www/apps/super-avvocato/data/model_limit.json")
STATO = Path("/var/log/superavokati/model_limit_notified.json")
ENV_AALA = "/var/www/apps/aala/.env.local"
FROM = "AALA Monitor <njoftim@aala.global>"
TO = "info@aala.global"


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
        print("RESEND_API_KEY assente"); return False
    carico = json.dumps({"from": FROM, "to": [TO], "subject": oggetto, "html": corpo_html}, ensure_ascii=False)
    r = subprocess.run(["curl", "-s", "-m", "20", "-X", "POST", "https://api.resend.com/emails",
                        "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json", "--data-binary", "@-"],
                       input=carico, capture_output=True, text=True, timeout=40)
    return '"id"' in (r.stdout or "")


def main() -> int:
    if not EVENTI.exists():
        return 0
    try:
        eventi = (json.loads(EVENTI.read_text(encoding="utf-8")) or {}).get("eventi") or []
    except Exception as exc:  # noqa: BLE001
        print("model_limit.json illeggibile:", exc); return 0
    try:
        stato = json.loads(STATO.read_text(encoding="utf-8")) if STATO.exists() else {}
    except Exception:  # noqa: BLE001
        stato = {}
    ultimo = stato.get("ultimo_ts") or ""
    nuovi = [e for e in eventi if (e.get("ts") or "") > ultimo]
    if not nuovi:
        return 0
    righe = "".join(f"<li>{e.get('ts')} — <b>{e.get('model')}</b>: {e.get('msg')} (pausa {int(e.get('pausa_s') or 0) // 60} min, ripiego su Opus max)</li>" for e in nuovi[-10:])
    ok = manda(f"⚠️ Super Avokati — {nuovi[-1].get('model')} in pausa per limite di quota ({len(nuovi)} evento/i)",
               f"<p>Il modello ha raggiunto il limite della sottoscrizione. Il cervello ha continuato con <b>Opus effort max</b> "
               f"(regola del 17 set 2026): nessuna risposta interrotta, ma il diavolo/Giudice/⚡ girano sul modello di riserva "
               f"finché la quota non torna.</p><ul>{righe}</ul><p>Dettagli: <code>data/model_limit.json</code>, registro AI "
               f"(error_class ModelLimit).</p>")
    print(time.strftime("%Y-%m-%d %H:%M"), "eventi nuovi:", len(nuovi), "email:", ok)
    if ok:
        STATO.parent.mkdir(parents=True, exist_ok=True)
        STATO.write_text(json.dumps({"ultimo_ts": nuovi[-1].get("ts")}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
