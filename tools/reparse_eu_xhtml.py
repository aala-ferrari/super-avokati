#!/usr/bin/env python3
"""v9.384 — GLI ATTI UE RILETTI DAL TESTO STRUTTURATO DELL'UFFICIO DELLE PUBBLICAZIONI (CELLAR), articolo per articolo.

Perché: tre regolamenti erano stati letti dal PDF (EUR-Lex non serve l'HTML dei testi molto grandi) — Reg. delegato
2015/2446, Reg. di esecuzione 2015/2447 (le regole attuative del codice doganale: l'ammissione temporanea!) e il Reg.
1896/2006 — e dal PDF alcuni articoli escono col testo di un ALTRO articolo (2446 art. 4 con la rubrica e il testo
dell'art. «Uso speciale della dichiarazione doganale in formato cartaceo»; art. 163 con pezzi di una tabella di un
allegato), le rubriche su due righe si spezzano (art. 214). E nei consolidati «Roma I» la rubrica non è in
`stitle-article-norm` ma nel blocco `eli-title`: l'ingest la lasciava nel testo.

Il testo CELLAR (stessa versione: il CELEX nel campo `urn` dell'atto; `tools/eu_gerarchia.py fetch` lo mette in
/root/eu_ger_cache) ha la struttura esplicita:
    <div class="eli-subdivision" id="art_4">
      <p class="title-article-norm">Articolo 4</p>
      <div class="eli-title"><p class="norm">Presentazione delle indicazioni per la registrazione EORI</p>
                             <p class="norm">(Articolo 6, paragrafo 4, del codice)</p></div>
      <p class="norm">Le autorità doganali possono …</p>
Rubrica = primo paragrafo di `eli-title` (o `stitle-article-norm`); la base giuridica «(Articolo …)» resta in testa al
testo, come nel corpus. Il blocco dell'articolo si delimita PER INDICI (dall'inizio del suo `eli-subdivision` al
successivo, o al titolo di capo/allegato), mai con un regex non-greedy (la lezione di Normattiva).

    python3 tools/reparse_eu_xhtml.py report [--only a,b]   # confronto col corpus, nulla scritto
    python3 tools/reparse_eu_xhtml.py apply --only a,b      # sostituisce gli articoli (backup del JSON accanto)
"""
import json, os, re, sys, time, difflib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eu_gerarchia as E  # noqa: E402
import ingest_eurlex as IE  # noqa: E402

ACTS = E.G.ACTS
_ART_P = re.compile(r'<p[^>]*class="(?:title-article-norm|oj-ti-art|ti-art)"[^>]*>(.*?)</p>', re.S)
_STOP = re.compile(r'<p[^>]*class="(?:title-division-1|oj-ti-section-1|ti-section-1|title-annex-1|oj-ti-annex|title-doc-first)"')
_ELI_TITLE = re.compile(r'<div[^>]*class="eli-title"[^>]*>(.*?)</div>', re.S)
_STITLE = re.compile(r'<p[^>]*class="(?:stitle-article-norm|oj-sti-art|sti-art)"[^>]*>(.*?)</p>', re.S)
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_MARK = re.compile(r"[▼►][A-Z]\d*|◄|▲")


def parse_xhtml(x: str) -> list[dict]:
    """Articoli del testo principale (ci si ferma al primo riavvio della numerazione: protocolli, allegati)."""
    x = _MARK.sub("", x)
    hits = []
    last = 0
    for m in _ART_P.finditer(x):
        t = E._pulito(m.group(1))
        a = E._ART.match(t)
        if not a:
            continue
        n = int(a.group(1))
        if n < last:
            break
        last = n
        hits.append((m.start(), m.end(), a.group(1) + ("-" + a.group(2).lower() if a.group(2) else "")))
    arts = []
    for i, (s0, s1, num) in enumerate(hits):
        fine = hits[i + 1][0] if i + 1 < len(hits) else len(x)
        blocco = x[s1:fine]
        cut = _STOP.search(blocco)
        if cut:
            blocco = blocco[:cut.start()]
        heading, base = "", ""
        st = _STITLE.search(blocco)
        et = _ELI_TITLE.search(blocco)
        if st and (not et or st.start() < et.start()):
            heading = E._pulito(st.group(1))
            blocco = blocco[:st.start()] + blocco[st.end():]
        elif et:
            ps = [E._pulito(p) for p in _P.findall(et.group(1))]
            ps = [p for p in ps if p]
            if ps:
                heading = ps[0]
                base = "\n".join(ps[1:])            # «(Articolo 6, paragrafo 4, del codice)»: la base giuridica, nel testo
            blocco = blocco[:et.start()] + blocco[et.end():]
        body = IE._text(blocco)
        if base:
            body = (base + "\n" + body).strip()
        arts.append(IE._mk(num.split("-")[0], num.split("-")[1] if "-" in num else "", heading, body))
    return IE._dedup(arts)


def _norm(t: str) -> str:
    t = re.sub(r"[▼►][A-Z]\d*|◄|▲", " ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def confronta(cid: str, atto: dict) -> dict | None:
    f = E._file(E._celex(atto))
    if not f.exists():
        return None
    nuovi = {a["number"]: a for a in parse_xhtml(f.read_text(encoding="utf-8", errors="replace"))}
    vecchi = {a["number"]: a for a in atto["articles"] if not str(a["number"]).startswith("allegato")}
    solo_v = [n for n in vecchi if n not in nuovi]
    solo_n = [n for n in nuovi if n not in vecchi]
    rub, testo = [], []
    for n, v in vecchi.items():
        if n not in nuovi:
            continue
        w = nuovi[n]
        if _norm(v["heading"]) != _norm(w["heading"]):
            rub.append(n)
        r = difflib.SequenceMatcher(None, _norm(v["body"])[:4000], _norm(w["body"])[:4000], autojunk=False).ratio()
        if r < 0.97:
            testo.append((round(r, 2), n))
    return {"vecchi": len(vecchi), "nuovi": len(nuovi), "solo_vecchi": solo_v, "solo_nuovi": solo_n,
            "rubriche_diverse": rub, "testi_diversi": sorted(testo), "articoli": nuovi}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    solo = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else set()
    for cid, atto in E.atti_ue():
        if cid == "cedu" or (solo and cid not in solo):
            continue
        c = confronta(cid, atto)
        if c is None:
            print(f"{cid:26s} ✗ non in cache"); continue
        print(f"{cid:26s} corpus {c['vecchi']:4d} · CELLAR {c['nuovi']:4d} · solo corpus {c['solo_vecchi'][:6]} · solo CELLAR "
              f"{c['solo_nuovi'][:6]} · rubriche diverse {len(c['rubriche_diverse'])} · testi diversi (<0,97) {len(c['testi_diversi'])}",
              flush=True)
        if "-v" in sys.argv:
            by_v = {a["number"]: a for a in atto["articles"]}
            for r, n in c["testi_diversi"][:5]:
                print(f"     {n} ({r}) corpus: {_norm(by_v[n]['heading'] + ' | ' + by_v[n]['body'])[:120]}")
                print(f"     {' ' * len(n)}        CELLAR: {_norm(c['articoli'][n]['heading'] + ' | ' + c['articoli'][n]['body'])[:120]}")
            for n in c["rubriche_diverse"][:4]:
                print(f"     rubrica {n}: «{by_v[n]['heading'][:60]}» → «{c['articoli'][n]['heading'][:60]}»")
        if cmd == "apply":
            f = ACTS / f"{cid}.json"
            bak = f.with_name(f"{f.name}.bak-xhtml-{time.strftime('%Y%m%d-%H%M')}")
            bak.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            d = json.loads(f.read_text(encoding="utf-8"))
            allegati = [a for a in d["articles"] if str(a["number"]).startswith("allegato")]
            nuovi = list(c["articoli"].values())
            d["articles"] = nuovi + allegati
            d["source"] = "xhtml-cellar"
            d["fetched"] = time.strftime("%Y-%m-%d")
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            try:
                os.chown(f, 1000, 1000)
            except Exception:  # noqa: BLE001
                pass
            print(f"   ✓ {cid}: {len(nuovi)} articoli dal testo CELLAR (+{len(allegati)} allegati invariati), backup {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
