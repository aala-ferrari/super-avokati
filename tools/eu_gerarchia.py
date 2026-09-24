#!/usr/bin/env python3
"""v9.384 — I CAPITOLI DEI REGOLAMENTI UE, DEI TRATTATI E DELLA CEDU (Parte / Titolo / Capo / Sezione / Sottosezione).

Normattiva non ha il diritto UE: i 22 atti UE del corpus vengono da EUR-Lex (`tools/ingest_eurlex.py`) e la CEDU dal PDF
della Corte. EUR-Lex dal server risponde spesso con la sfida anti-robot (AWS WAF, 202 + JavaScript), anche a curl; lo
stesso testo, nella STESSA versione (il CELEX nel campo `urn` dell'atto), lo dà l'archivio dell'Ufficio delle
pubblicazioni UE (CELLAR, `publications.europa.eu/resource/celex/<CELEX>`, Accept: application/xhtml+xml,
Accept-Language: ita), che non ha la sfida. Il markup è quello di EUR-Lex:
    consolidati   <p class="title-division-1">CAPO II</p><p class="title-division-2">COMPETENZA</p> … <p class="title-article-norm">Articolo 4</p>
    GU recente    oj-ti-section-1 / oj-ti-section-2 / oj-ti-art
    GU vecchia    ti-section-1 / ti-section-2 / ti-art          (la Carta dei diritti)
Le intestazioni si leggono con la stessa macchina dell'albero di Normattiva (`it_gerarchia.applica_righe`: pila dei
livelli, stesso tipo+stile si sostituisce). Ci si ferma al primo RIAVVIO della numerazione (protocolli e allegati dei
trattati, come l'ingest). CEDU: i tre «TITOLO …» sono rimasti incollati in coda agli artt. 1, 18 e 51 del corpus → la
mappa si ricava da lì (e `build_it_index` li toglie dal testo).

    python3 tools/eu_gerarchia.py fetch [--only id,…]      # sull'host: scarica da CELLAR in /root/eu_ger_cache
    python3 tools/eu_gerarchia.py probe [id]               # legge la cache, stampa copertura, nulla scritto
    python3 tools/eu_gerarchia.py run                      # scrive data/processed/it_gerarchia/<id>.json
"""
import html as _html, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import it_gerarchia as G  # noqa: E402

CACHE = Path(os.environ.get("EU_GER_CACHE", "/root/eu_ger_cache"))
CELLAR = "http://publications.europa.eu/resource/celex/"

_EL = re.compile(r'<p[^>]*class="(title-division-1|title-division-2|oj-ti-section-1|oj-ti-section-2|ti-section-1|ti-section-2|'
                 r'title-article-norm|oj-ti-art|ti-art)"[^>]*>(.*?)</p>', re.S)
_ART = re.compile(r"^\s*Articolo\s+(\d+)\s*((?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)?)\s*$", re.I)
_MARK = re.compile(r"\s*(▼[A-Z]\d*|►[A-Z]\d*|◄|▲)\s*")
_CEDU_TIT = re.compile(r"(?<=[.;:])\s+(TITOLO\s+[IVXLC]+)\s+([A-ZÀ-Ü’'«»,\- ]+?)\s*$")


def _celex(atto: dict) -> str:
    return (atto.get("urn") or "").split(":", 1)[1] if (atto.get("urn") or "").startswith("eurlex:") else ""


def _file(celex: str) -> Path:
    return CACHE / (celex.replace("/", "_") + ".xhtml")


def _pulito(s: str) -> str:
    t = _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    t = _MARK.sub(" ", t)
    return " ".join(t.split())


def atti_ue() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(G.ACTS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if _celex(d) or f.stem == "cedu":
            out.append((f.stem, d))
    return out


def fetch(celex: str) -> tuple[bool, str]:
    """Scarica da CELLAR con curl (stesso User-Agent semplice che funziona); mai sovrascrive un file buono."""
    f = _file(celex)
    if f.exists() and f.stat().st_size > 10_000:
        return True, "in cache"
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".part")
    for attesa in (0, 20, 60):
        time.sleep(attesa)
        r = subprocess.run(["curl", "-s", "-L", "-m", "300", "-A", "Mozilla/5.0", "-H", "Accept: application/xhtml+xml",
                            "-H", "Accept-Language: ita", "-w", "%{http_code}", "-o", str(tmp),
                            CELLAR + celex.replace("/", "%2F")], capture_output=True, text=True)
        code = (r.stdout or "").strip()[-3:]
        if code == "200" and tmp.exists() and tmp.stat().st_size > 10_000:
            testo = tmp.read_text(encoding="utf-8", errors="replace")
            if "awsWaf" in testo or "challenge-container" in testo:
                continue
            tmp.replace(f)
            return True, f"{f.stat().st_size // 1024} KB"
    return False, f"HTTP {code}"


def albero_ue(pagina: str) -> tuple[dict, dict]:
    """({("0", numero): (pjesa, kreu, seksioni)}, statistiche) dall'XHTML CELLAR/EUR-Lex."""
    pila: list = []
    out: dict = {}
    visti: dict = {}
    blocco: list[str] = []
    n_blocchi = n_intest = 0
    ultimo = 0
    fermato = ""
    for m in _EL.finditer(pagina):
        cls, testo = m.group(1), _pulito(m.group(2))
        if not testo:
            continue
        if cls in ("title-article-norm", "oj-ti-art", "ti-art"):
            a = _ART.match(testo)
            if not a:
                continue
            n = int(a.group(1))
            if n < ultimo:                     # la numerazione riparte: protocolli, allegati, dichiarazioni
                fermato = f"riavvio a «{testo}» dopo l'art. {ultimo}"
                break
            ultimo = n
            if blocco:
                n_blocchi += 1
                pila = G.applica_righe(pila, blocco, n_blocchi)
                blocco = []
            for x in pila:
                x["art"] = True
            num = a.group(1) + ("-" + a.group(2).lower() if a.group(2) else "")
            visti.setdefault(num, 0)
            visti[num] += 1
            out[("0", num)] = G._voce_da_pila(pila)
        else:
            n_intest += cls.endswith("-1")
            blocco.append(testo)
    ambigui = [n for n, c in visti.items() if c > 1]
    for n in ambigui:
        out.pop(("0", n), None)
    return out, {"intestazioni": n_intest, "blocchi": n_blocchi, "articoli": sum(visti.values()), "ambigui": len(ambigui),
                 "fermato": fermato}


def albero_cedu(atto: dict) -> tuple[dict, dict]:
    """CEDU: «… della presente Convenzione. TITOLO I DIRITTI E LIBERTÀ» in coda all'art. 1 = gli articoli DOPO stanno lì."""
    pila: list = []
    out: dict = {}
    n = 0
    for a in atto.get("articles") or []:
        out[("0", str(a["number"]))] = G._voce_da_pila(pila)
        m = _CEDU_TIT.search(a.get("body") or "")
        if m:
            n += 1
            pila = G.applica_righe([], [m.group(1), m.group(2).strip()], n)
            for x in pila:
                x["art"] = True
    return out, {"intestazioni": n, "blocchi": n, "articoli": len(out), "ambigui": 0, "fermato": ""}


def _elabora(cid: str, atto: dict):
    if cid == "cedu":
        return albero_cedu(atto)
    f = _file(_celex(atto))
    if not f.exists():
        return None, {"errore": "non in cache (fetch)"}
    return albero_ue(f.read_text(encoding="utf-8", errors="replace"))


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    solo = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else set()
    if cmd == "probe" and len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        solo = {sys.argv[2]}
    atti = [(c, d) for c, d in atti_ue() if not solo or c in solo]
    if cmd == "fetch":
        for cid, atto in atti:
            if cid == "cedu":
                continue
            ok, info = fetch(_celex(atto))
            print(f"{cid:28s} {_celex(atto):28s} {'✓' if ok else '✗'} {info}", flush=True)
            time.sleep(3)
        return 0
    tot_ok = tot = 0
    for cid, atto in atti:
        mappa, st = _elabora(cid, atto)
        if mappa is None:
            print(f"{cid:28s} ✗ {st.get('errore')}"); continue
        mancanti: list = []
        ok, n = G.copertura(atto, mappa, mancanti)
        tot_ok += ok; tot += n
        print(f"{cid:28s} intestazioni {st['intestazioni']:4d} · articoli {st['articoli']:4d} · ambigui {st['ambigui']} · "
              f"coperti {ok}/{n}" + (f" · senza: {', '.join(mancanti[:6])}" if mancanti else "") +
              (f" · {st['fermato']}" if st.get("fermato") else ""), flush=True)
        if cmd == "run":
            G.salva(cid, atto.get("urn") or "", mappa, st)
    print(f"\ntotale: {tot_ok}/{tot} articoli UE/CEDU con la voce dell'albero")
    return 0


if __name__ == "__main__":
    sys.exit(main())
