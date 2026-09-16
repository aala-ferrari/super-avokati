# -*- coding: utf-8 -*-
"""Controllo di FRESCHEZZA del corpus: la legge che abbiamo è ancora quella vigente?

Per ogni atto confronta ciò che sta nel corpus con la fonte ufficiale, con UNA-DUE richieste
per atto, senza scaricare testi:
  • IT / Normattiva: la pagina-atto dice «ultimo aggiornamento all'atto: GG/MM/AAAA» → se è
    posteriore alla data in cui abbiamo scaricato l'atto (mtime del JSON) → STALE.
  • IT / EUR-Lex: la pagina ALL elenca le versioni consolidate «0…-AAAAMMGG» → se ce n'è una
    più recente di quella nel nostro `urn` → STALE.
  • AL / QBZ (REST Alfresco aperta): cartelle `cons-AAAA-MM-GG` dell'atto → se ce n'è una
    più recente della nostra (con PDF > 10 KB) → STALE; associazioni `qbz:actRepeals`
    (abrogato da) → REPEALED; `qbz:actChanges` con data posteriore alla nostra consolidata →
    STALE (modifica pubblicata, consolidato non ancora rifatto).
Gli atti già «morti» nel corpus (≥50% abrogati, o superati e marcati) si saltano: sono
tenuti apposta per dire «superato» a chi li cita.

    python3 tools/freshness_check.py [it|al] [--json out.json] [--limit N]
Esce 1 se c'è almeno uno STALE/REPEALED (per il cron/avviso).
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date, datetime
from pathlib import Path

for p in ("/app", "/app/tools", "/tmp"):
    sys.path.insert(0, p)

IT_ACTS = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
AL_SRC = Path(os.environ.get("AL_SOURCES", "/app/tools/al_sources.json"))
# UA: QBZ e gli altri accettano un UA da browser; EUR-Lex (AWS WAF) al contrario risponde
# 202-sfida (corpo vuoto) all'UA lungo di Chrome e la pagina vera all'UA corto «Mozilla/5.0»
# (misurato il 16 set 2026: 202/0 byte contro 200/15 MB sullo stesso URL, a 20 s di distanza).
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
UA_EURLEX = "Mozilla/5.0"
QBZ = "https://qbz.gov.al/alfresco/api/-default-/public/alfresco/versions/1"
ONLY: set[str] = set()             # --only codice,codice: ricontrolla solo questi atti
SKIP_AL = {"ligji_konsumatoret"}   # senza consolidato QBZ (testo in corpus da altra fonte)
try:  # le leggi superate e marcate abrogate (ingest_al_qbz.SUPERSEDED) non vanno controllate
    from ingest_al_qbz import SUPERSEDED as _SUP
    SKIP_AL |= set(_SUP)
except Exception:  # noqa: BLE001
    SKIP_AL |= {"ligji_te_dhenat", "ligji_policia", "ligji_dhuna_familje"}


def _get(url: str, timeout: int = 60) -> str:
    # EUR-Lex sta dietro AWS WAF: a urllib risponde 202 con una pagina-sfida JavaScript
    # (impronta TLS), a curl la pagina vera. Per EUR-Lex si passa da curl (host e container
    # lo hanno), con urllib di riserva.
    if "eur-lex.europa.eu" in url:
        import shutil, subprocess
        if shutil.which("curl"):
            # il WAF passa a «sfida» per l'IP dopo una raffica di richieste (misurato: da 200/15 MB
            # a 202/0 byte in pochi minuti): 3 tentativi con pausa crescente, poi si risponde
            # vuoto e il chiamante segna UNKNOWN (mai un OK finto)
            for pause in (0, 30, 90):
                if pause:
                    time.sleep(pause)
                p = subprocess.run(["curl", "-sL", "-A", UA_EURLEX, "--max-time", str(max(timeout, 120)), url],
                                   capture_output=True)
                if p.returncode == 0 and len(p.stdout) > 20_000 and b"challenge-container" not in p.stdout[:4000]:
                    return p.stdout.decode("utf-8", "replace")
            return ""
    ua = UA_EURLEX if "eur-lex.europa.eu" in url else UA
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "it,sq"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _head_pdf(url: str) -> bool:
    """HEAD via curl (stesso motivo del WAF): True se l'ultima risposta è 200 e PDF."""
    import shutil, subprocess
    if not shutil.which("curl"):
        return False
    p = subprocess.run(["curl", "-sIL", "-A", UA_EURLEX, "--max-time", "60", url], capture_output=True)
    head = p.stdout.decode("latin1")
    blocks = [b for b in re.split(r"\r?\n\r?\n", head) if b.strip()]
    last = blocks[-1] if blocks else ""
    return bool(re.match(r"HTTP/\S+\s+200", last)) and "application/pdf" in last.lower()


def _qbz(path: str, **params) -> dict:
    url = f"{QBZ}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return json.loads(_get(url))


def _d(s: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8], fmt).date()
        except ValueError:
            pass
    return None


# ── IT ────────────────────────────────────────────────────────────────────────
def check_it(limit: int | None) -> list[dict]:
    out: list[dict] = []
    files = sorted(IT_ACTS.glob("*.json"))
    if ONLY:
        files = [f for f in files if f.stem in ONLY]
    if limit:
        files = files[:limit]
    nm = None
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        arts = d.get("articles") or []
        rep = sum(1 for a in arts if a.get("repealed") is True)
        # data di scarico: campo «fetched» scritto dall'ingest (dal 16 set 2026); prima il mtime
        # del file — ma il mtime cambia a ogni ricalcolo (repealed, riparazioni) e mentirebbe
        row = {"lang": "it", "code": f.stem,
               "ingested": d.get("fetched") or date.fromtimestamp(f.stat().st_mtime).isoformat(),
               "status": "OK", "note": ""}
        if arts and rep >= len(arts) / 2:
            row["status"] = "DEAD"; row["note"] = f"{rep}/{len(arts)} abrogati: tenuto per dire «superato»"
            out.append(row); continue
        urn = d.get("urn") or ""
        try:
            if urn.startswith("eurlex:"):
                ours = urn.split(":", 1)[1]                       # 02015R2446-20260701 | 02016E/TXT-20250315
                m = re.match(r"^0(.+?)-(\d{8})$", ours)
                if not m:
                    # testo originale (nessun consolidato al momento dell'ingest): se ora EUR-Lex
                    # ne ha uno, lo segnala come da valutare (spesso solo rettifiche)
                    base = ours.split("/")[0] if "/" not in ours else ours
                    page = _get(f"https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=CELEX:{base}")
                    vers = sorted(set(re.findall(r"0" + re.escape(base[1:]) + r"-(\d{8})", page)), reverse=True)
                    row["ours"] = "originale"; row["source"] = vers[0] if vers else "-"
                    if vers:
                        row["status"] = "INFO"; row["note"] = f"testo originale in corpus; EUR-Lex ha un consolidato {vers[0]} (spesso rettifiche)"
                    time.sleep(6.0)   # EUR-Lex: con richieste fitte il WAF passa a «sfida» (202 vuoto)
                else:
                    base = ("1" if "/TXT" in m.group(1) else "3") + m.group(1)
                    page = _get(f"https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=CELEX:{base}")
                    vers = sorted(set(re.findall(r"0" + re.escape(m.group(1)) + r"-(\d{8})", page)), reverse=True)
                    row["source"] = vers[0] if vers else "-"; row["ours"] = m.group(2)
                    if not vers:
                        # un «OK» silenzioso è il difetto peggiore: se la pagina ALL non elenca
                        # versioni (throttling, pagina diversa) lo si dice
                        row["status"] = "UNKNOWN"; row["note"] = "EUR-Lex: nessuna versione letta dalla pagina ALL (throttling?) — riprovare"
                    elif vers[0] > m.group(2):
                        # scaricabile? Per i testi grandi (Reg. 2015/2447) EUR-Lex serve l'HTML-guscio
                        # e il PDF del consolidato nuovo puo' non esistere ancora (404): si segnala
                        # come INFO, non come STALE che nessuno puo' sanare
                        newest = "0" + m.group(1) + "-" + vers[0]
                        ok_pdf = _head_pdf(f"https://eur-lex.europa.eu/legal-content/IT/TXT/PDF/?uri=CELEX:{newest}")
                        if ok_pdf:
                            row["status"] = "STALE"; row["note"] = f"EUR-Lex consolidato {vers[0]} > nostro {m.group(2)} (PDF disponibile: rilanciare ingest_eurlex)"
                        else:
                            row["status"] = "INFO"; row["note"] = f"EUR-Lex consolidato {vers[0]} > nostro {m.group(2)}, ma senza PDF scaricabile (HTML-guscio): riprovare"
                time.sleep(6.0)   # EUR-Lex: con richieste fitte il WAF passa a «sfida» (202 vuoto)
            elif urn.startswith("coe:"):
                row["note"] = "CEDU: testo stabile (CoE)"
            elif urn:
                from normattiva_lib import Normattiva
                nm = nm or Normattiva(delay=0.4)
                html = nm.open_act(urn)
                m = re.search(r"ultimo aggiornamento all.atto:?\s*(\d{2}/\d{2}/\d{4})", html, re.I)
                if not m:
                    m = re.search(r"Ultimo aggiornamento all.{0,6}atto pubblicato il (\d{2}/\d{2}/\d{4})", html, re.I)
                upd = _d(m.group(1)) if m else None
                row["source"] = upd.isoformat() if upd else "-"
                if upd and upd > date.fromisoformat(row["ingested"]):
                    row["status"] = "STALE"; row["note"] = f"Normattiva: ultimo aggiornamento {upd} > scaricato {row['ingested']}"
                elif not upd:
                    # atti mai modificati (L. 219/2017, L. 175/1998): la pagina non ha la riga
                    row["note"] = "Normattiva: nessun aggiornamento pubblicato"
                if re.search(r"PROVVEDIMENTO ABROGATO", html):
                    row["status"] = "REPEALED"; row["note"] = "Normattiva: PROVVEDIMENTO ABROGATO"
            else:
                row["status"] = "UNKNOWN"; row["note"] = "senza urn"
        except Exception as exc:  # noqa: BLE001
            row["status"] = "ERROR"; row["note"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        out.append(row)
        print(f"  {row['status']:8s} {row['code']:32s} {row.get('source', '-'):>12}  {row['note'][:90]}", flush=True)
    return out


# ── AL ────────────────────────────────────────────────────────────────────────
_QBZ_URL = re.compile(r"webdav/Aktet/(?P<kind>ligj|vendim)/(?P<inst>[^/]+)/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<num>[^/]+)/(?P<ver>base|cons-\d{4}-\d{2}-\d{2})/")


def check_al(limit: int | None) -> list[dict]:
    out: list[dict] = []
    laws = [l for l in json.loads(AL_SRC.read_text(encoding="utf-8"))["laws"] if "code" in l]
    if ONLY:
        laws = [l for l in laws if l["code"] in ONLY]
    if limit:
        laws = laws[:limit]
    for law in laws:
        code = law["code"]
        row = {"lang": "al", "code": code, "status": "OK", "note": ""}
        if code in SKIP_AL:
            row["status"] = "DEAD"; row["note"] = "superata/marcata (tenuta apposta)"; out.append(row); continue
        m = _QBZ_URL.search(law["url"])
        if not m:
            row["status"] = "UNKNOWN"; row["note"] = "URL non QBZ"; out.append(row); continue
        g = m.groupdict()
        rel = f"Aktet/{g['kind']}/{g['inst']}/{g['y']}/{g['m']}/{g['d']}/{g['num']}"
        ours = g["ver"]
        our_date = _d(ours[5:]) if ours.startswith("cons-") else date(int(g["y"]), int(g["m"]), int(g["d"]))
        row["ours"] = ours
        try:
            folders = [e["entry"]["name"] for e in _qbz("nodes/-root-/children", relativePath=rel, maxItems=200)["list"]["entries"]]
            cons = sorted(n for n in folders if re.match(r"^cons-\d{4}-\d{2}-\d{2}$", n))
            newest = cons[-1] if cons else "base"
            row["source"] = newest
            if newest != ours and newest > ours:
                kids = _qbz("nodes/-root-/children", relativePath=f"{rel}/{newest}", include="properties")["list"]["entries"]
                pdfs = [k["entry"] for k in kids if k["entry"]["name"].lower().endswith(".pdf")]
                size = max((p.get("content", {}).get("sizeInBytes", 0) for p in pdfs), default=0)
                if size > 10_000:
                    row["status"] = "STALE"; row["note"] = f"QBZ ha {newest} ({size // 1024} KB) > nostro {ours}"
                else:
                    row["note"] = f"QBZ {newest} senza PDF utile (docx?) — nostro {ours}"
            base = _qbz("nodes/-root-/children", relativePath=f"{rel}/base", include="properties")["list"]["entries"]
            node = next((e["entry"] for e in base if e["entry"].get("nodeType") == "qbz:act"), None)
            if node:
                reps = _qbz(f"nodes/{node['id']}/sources", where="(assocType='qbz:actRepeals')", include="properties")["list"]["entries"]
                if reps:
                    # «actRepeals» copre anche abrogazioni PARZIALI (Kodi Rrugor ← ligji 12/2010 abroga
                    # alcuni articoli, ma il codice vive: consolidato 2026). Abrogazione vera solo se
                    # la data dell'atto abrogante è posteriore all'ultimo consolidato dell'atto.
                    rep_dates = sorted((r["entry"].get("properties", {}).get("qbz:actDate") or "")[:10] for r in reps)
                    p = reps[-1]["entry"].get("properties", {})
                    newest_date = _d(newest[5:]) if newest.startswith("cons-") else None
                    rep_date = _d(rep_dates[-1]) if rep_dates and rep_dates[-1] else None
                    if rep_date and (not newest_date or rep_date > newest_date):
                        row["status"] = "REPEALED"
                        row["note"] = f"QBZ: shfuqizuar nga {p.get('qbz:actNumber')} ({rep_date}); " + row["note"]
                    else:
                        row["note"] = f"abrogazione parziale ({p.get('qbz:actNumber')}, {rep_date}) prima del consolidato; " + row["note"]
                chg = _qbz(f"nodes/{node['id']}/sources", where="(assocType='qbz:actChanges')", include="properties", maxItems=100)["list"]["entries"]
                dates = sorted((c["entry"].get("properties", {}).get("qbz:actDate") or "")[:10] for c in chg)
                last = _d(dates[-1]) if dates and dates[-1] else None
                row["last_change"] = last.isoformat() if last else "-"
                if last and our_date and last > our_date and row["status"] == "OK":
                    row["status"] = "STALE"; row["note"] = f"QBZ: modifica del {last} posteriore al nostro {ours}"
            time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            row["status"] = "ERROR"; row["note"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        out.append(row)
        print(f"  {row['status']:8s} {code:30s} {row.get('ours', '-'):>15} → {row.get('source', '-'):>15}  ultima modifica {row.get('last_change', '-'):>10}  {row['note'][:70]}", flush=True)
    return out


if __name__ == "__main__":
    langs = [a for a in sys.argv[1:] if a in ("it", "al")] or ["it", "al"]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    if "--only" in sys.argv:
        ONLY.update(c.strip() for c in sys.argv[sys.argv.index("--only") + 1].split(",") if c.strip())
    rows: list[dict] = []
    for lg in langs:
        print(f"\n=== {lg.upper()} ===")
        rows += check_it(limit) if lg == "it" else check_al(limit)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\n=== RIEPILOGO:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), "===")
    bad = [r for r in rows if r["status"] in ("STALE", "REPEALED")]
    for r in bad:
        print(f"  ! {r['lang']}:{r['code']}: {r['status']} — {r['note']}")
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if bad else 0)
