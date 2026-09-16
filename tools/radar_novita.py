# -*- coding: utf-8 -*-
"""RADAR NOVITÀ legislative (16 set 2026): cosa è USCITO di nuovo che al corpus potrebbe mancare.

Il controllo di freschezza (freshness_check) vede modifiche e abrogazioni delle leggi che
ABBIAMO; questo vede le leggi NUOVE. Due fonti, entrambe verificate a mano:
  • Gazzetta Ufficiale, RSS Serie Generale (https://www.gazzettaufficiale.it/rss/SG, ~46 voci,
    titoli tipo «DECRETO LEGISLATIVO 9 settembre 2026, n.160» + link ELI); per gli atti
    normativi (legge, d.lgs., d.l., d.p.r., legge costituzionale) si apre la pagina ELI per
    l'OGGETTO («Adeguamento … regole armonizzate sull'intelligenza artificiale…»).
  • QBZ, ricerca REST (POST …/search/versions/1/search, AFTS): «ligj» degli ultimi giorni +
    «vendim» del Consiglio dei ministri «Akt bazë» con parole-chiave giuridiche (i VKM sono
    centinaia al mese: senza filtro è rumore).
Ogni atto visto una volta sola (stato in data/radar_state.json); «rilevante» = titolo/oggetto
con parole-chiave del nostro dominio. Il digest settimanale elenca i rilevanti (e conta gli
altri) — è un elenco DA VALUTARE, non ingerisce nulla da solo.

    python3 tools/radar_novita.py collect            # giornaliero (cron 07:10)
    python3 tools/radar_novita.py digest [--email]   # settimanale (cron lunedì 06:40)
"""
import json, os, re, subprocess, sys, time, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

APP = Path(os.environ.get("SA_APP", "/var/www/apps/super-avvocato"))
STATE = Path(os.environ.get("RADAR_STATE", str(APP / "data" / "radar_state.json")))
UA = "Mozilla/5.0"
ENV_AALA = "/var/www/apps/aala/.env.local"
FROM = "AALA Monitor <njoftim@aala.global>"
TO = "info@aala.global"
GU_RSS = "https://www.gazzettaufficiale.it/rss/SG"
QBZ_SEARCH = "https://qbz.gov.al/alfresco/api/-default-/public/search/versions/1/search"
GU_TIPI = re.compile(r"^(LEGGE COSTITUZIONALE|LEGGE|DECRETO LEGISLATIVO|DECRETO-LEGGE|DECRETO DEL PRESIDENTE DELLA REPUBBLICA)\b", re.I)
KW_IT = ("codice", "testo unico", "tribut", "imposta", "iva", "dogan", "immigra", "stranier", "cittadinanza", "lavoro",
         "licenziament", "penal", "civil", "procedur", "notar", "famigli", "divorzio", "locazion", "condomin", "privacy",
         "dati personali", "appalt", "edilizi", "urbanist", "societ", "fallimen", "crisi d", "bancar", "assicura", "consumator",
         "sanzion", "riscossion", "accertament", "succession", "donazion", "registro", "catast", "veicol", "strada",
         "circolazione", "protezione internazionale", "asilo", "arbitra", "mediazion", "intelligenza artificiale",
         "responsabilit", "giustizia", "processo", "magistrat", "avvocat", "pena", "reat", "contratt", "propriet")
KW_AL = ("kod", "tatim", "tvsh", "dogan", "të huaj", "te huaj", "shtetësi", "shtetesi", "punë", "pune", "penal", "civil",
         "procedur", "noter", "famil", "qira", "pron", "kadastr", "të dhëna", "te dhena", "prokurim", "ndërtim", "ndertim",
         "shoqëri", "shoqeri", "falimentim", "bank", "sigurim", "konsumator", "gjob", "kundërvajt", "kundervajt", "trashëgim",
         "trashegim", "dhurim", "automjet", "rrug", "azil", "arbitrazh", "ndërmjetës", "ndermjetes", "avokat", "gjykat",
         "prokuror", "polici", "armë", "arme", "migr", "vizë", "vize", "leje", "rregullore", "trafik", "korrupsion", "ligj")
# VKM «amministrativi» (un singolo bene, un incarico, un fondo): non sono norme che un avvocato cita
_QBZ_RUMORE = re.compile(r"shpronësim|shpronesim|vënies në dispozicion|venies ne dispozicion|pasuri(?:ve|së|se)? të paluajtshme "
                         r"shtetërore|investimit strategjik|kalimin (?:në|ne) përgjegjësi|dhënie licenc|emërim|lirim|"
                         r"miratimin e listës|përdorimin e fondit|perdorimin e fondit|financimin|ndihmë financiare|"
                         r"buxhet|programit|marrëveshjes së huas|marreveshjes se huas|granti|kredi", re.I)


def _get(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it,sq"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        p = subprocess.run(["curl", "-sL", "-A", UA, "--max-time", str(timeout), url], capture_output=True)
        return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else ""


def _load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"items": {}, "last_collect": "", "last_digest": ""}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def _rilevante(testo: str, kws: tuple) -> bool:
    t = testo.lower()
    return any(k in t for k in kws)


# ── Gazzetta Ufficiale ────────────────────────────────────────────────────────
def gu_oggetto(link: str) -> str:
    h = _get(link)
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    txt = re.sub(r"<[^>]+>", "\n", txt).replace("&nbsp;", " ")
    txt = re.sub(r"[ \t]+", " ", txt); txt = re.sub(r"\n\s*\n+", "\n", txt)
    m = re.search(r"n\.\s*\d+\s*\n(.*?)\(\d{2}[A-Z]\d{5}\)", txt, re.S)
    if not m:
        m = re.search(r"(?:LEGGE|DECRETO)[^\n]*\n[^\n]*\n(.*?)\(\d{2}[A-Z]\d{5}\)", txt, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:400] if m else ""


def collect_gu(st: dict) -> int:
    xml = _get(GU_RSS)
    if not xml.strip().startswith("<"):
        print("  GU: RSS non letto"); return 0
    root = ET.fromstring(xml)
    new = 0
    for it in root.findall(".//item"):
        title = re.sub(r"\s+", " ", it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not GU_TIPI.match(title):
            continue
        m = re.search(r"/eli/id/(\d{4}/\d{2}/\d{2}/[A-Z0-9]+)", link)
        key = "gu:" + (m.group(1) if m else link)
        if key in st["items"]:
            continue
        ogg = gu_oggetto(link) if link else ""
        time.sleep(0.5)
        st["items"][key] = {"lang": "it", "tipo": title, "oggetto": ogg, "link": link,
                            "data": (it.findtext("pubDate") or "")[:16], "visto": date.today().isoformat(),
                            "rilevante": _rilevante(title + " " + ogg, KW_IT), "riportato": False}
        new += 1
        print(f"  GU {'★' if st['items'][key]['rilevante'] else ' '} {title[:60]} — {ogg[:80]}")
    return new


# ── QBZ ──────────────────────────────────────────────────────────────────────
def collect_qbz(st: dict, giorni: int) -> int:
    since = (date.today() - timedelta(days=giorni)).isoformat()
    q = {"query": {"language": "afts", "query": f'TYPE:"qbz:act" AND qbz:actDate:["{since}T00:00:00" TO NOW]'},
         "include": ["properties"], "paging": {"maxItems": 400},
         "sort": [{"type": "FIELD", "field": "qbz:actDate", "ascending": False}]}
    req = urllib.request.Request(QBZ_SEARCH, data=json.dumps(q).encode(), headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    new = 0
    for e in d.get("list", {}).get("entries", []):
        p = e["entry"].get("properties", {})
        tipo = (p.get("qbz:actActType") or "").rsplit("/", 1)[-1]
        num, dt = p.get("qbz:actNumber") or "", (p.get("qbz:actDate") or "")[:10]
        title = re.sub(r"\s+", " ", p.get("qbz:actTitle") or "").strip()
        base = (p.get("qbz:actType") or "") == "Akt bazë"
        if tipo == "ligj":
            keep = True
        elif tipo == "vendim" and base:
            keep = _rilevante(title, KW_AL) and not _QBZ_RUMORE.search(title)
        else:
            continue
        if not keep:
            continue
        key = f"qbz:{tipo}:{num}:{dt}"
        if key in st["items"]:
            continue
        st["items"][key] = {"lang": "al", "tipo": f"{tipo} nr. {num}, {dt}", "oggetto": title,
                            "link": p.get("qbz:url") or "", "data": dt, "visto": date.today().isoformat(),
                            "rilevante": tipo == "ligj" or _rilevante(title, KW_AL), "riportato": False}
        new += 1
        print(f"  QBZ {'★' if st['items'][key]['rilevante'] else ' '} {tipo} {num} {dt} — {title[:80]}")
    return new


# ── digest + email ───────────────────────────────────────────────────────────
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
        print("⚠️ RESEND_API_KEY assente: nessuna email"); return False
    carico = json.dumps({"from": FROM, "to": [TO], "subject": oggetto, "html": corpo_html}, ensure_ascii=False)
    r = subprocess.run(["curl", "-s", "-m", "20", "-X", "POST", "https://api.resend.com/emails",
                        "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json", "--data-binary", "@-"],
                       input=carico, capture_output=True, text=True, timeout=40)
    ok = '"id"' in (r.stdout or "")
    print("✉️ email inviata" if ok else f"⚠️ email NON partita: {(r.stdout or r.stderr)[:200]}")
    return ok


def digest(st: dict, email: bool) -> int:
    da_riportare = [(k, v) for k, v in st["items"].items() if not v.get("riportato")]
    ril = [kv for kv in da_riportare if kv[1]["rilevante"]]
    altri = len(da_riportare) - len(ril)
    print(f"digest: {len(ril)} atti rilevanti, {altri} altri (dal {st.get('last_digest') or 'inizio'})")
    righe_txt, righe_html = [], []
    for k, v in sorted(ril, key=lambda kv: (kv[1]["lang"], kv[1]["data"]), reverse=True):
        riga = f"[{v['lang'].upper()}] {v['tipo']} — {v['oggetto'][:220]} {v['link']}"
        righe_txt.append(riga); print("  ★ " + riga[:200])
        righe_html.append(f"<li><b>[{v['lang'].upper()}] {v['tipo']}</b> — {v['oggetto'][:300]} <a href=\"{v['link']}\">link</a></li>")
    if email and ril:
        corpo = (f"<p>Radar novità legislative ({date.today()}): <b>{len(ril)} atti nuovi nel nostro dominio</b> "
                 f"({altri} altri atti normativi non pertinenti). Da valutare: se uno serve al corpus, aggiungerlo "
                 f"(Normattiva: tools/ingest_it_normattiva.py; QBZ: tools/al_sources.json + tools/ingest_al_qbz.py).</p><ul>"
                 + "".join(righe_html) + "</ul>")
        manda(f"📡 Super Avokati — {len(ril)} novità legislative da valutare (IT/AL)", corpo)
    if email:  # senza --email è un'anteprima: non consuma le voci
        for k, _ in da_riportare:
            st["items"][k]["riportato"] = True
        st["last_digest"] = date.today().isoformat()
    # tieni lo stato snello: via le voci più vecchie di 180 giorni
    cutoff = (date.today() - timedelta(days=180)).isoformat()
    st["items"] = {k: v for k, v in st["items"].items() if v.get("visto", "") >= cutoff}
    return len(ril)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "collect"
    st = _load()
    if mode == "collect":
        giorni = 8 if not st.get("last_collect") else max(2, (date.today() - date.fromisoformat(st["last_collect"])).days + 1)
        print(f"{datetime.now():%Y-%m-%d %H:%M} raccolta (QBZ: ultimi {giorni} giorni)")
        n_gu = collect_gu(st)
        n_qbz = collect_qbz(st, giorni)
        st["last_collect"] = date.today().isoformat()
        _save(st)
        print(f"nuovi: GU {n_gu}, QBZ {n_qbz}; in stato {len(st['items'])}")
    elif mode == "digest":
        n = digest(st, "--email" in sys.argv)
        _save(st)
        sys.exit(0)
    else:
        print(__doc__); sys.exit(2)
